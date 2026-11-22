#include "mlir/Dialect/Func/IR/FuncOps.h"
#include "mlir/IR/BuiltinOps.h"
#include "mlir/Parser/Parser.h"
#include "mlir/Pass/Pass.h"
#include "mlir/Pass/PassManager.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/FileSystem.h"

using namespace mlir;

namespace {
struct LowerModel : PassWrapper<LowerModel, OperationPass<ModuleOp>> {
  explicit LowerModel(bool enableChaining) : enableChaining(enableChaining) {}
  bool enableChaining;

  void runOnOperation() override {
    ModuleOp module = getOperation();
    auto model = module.lookupSymbol<func::FuncOp>("model");
    auto reject = [&](StringRef reason) {
      module.emitError(reason);
      signalPassFailure();
    };
    if (!model || !llvm::hasSingleElement(model.getBody()))
      return reject("expected one model block");

    OpBuilder builder(module.getContext());
    auto signature = model.getFunctionType();
    auto input = signature.getNumInputs() == 1
                     ? dyn_cast<RankedTensorType>(signature.getInput(0))
                     : RankedTensorType{};
    if (!input || input.getRank() != 2 || !input.getElementType().isInteger(8))
      return reject("unsupported model shape");
    int64_t samples = input.getDimSize(0);
    int64_t width = input.getDimSize(1);
    if ((samples != 4 && samples != 8 && samples != 16) ||
        (width != 4 && width != 8 && width != 16 && width != 32 && width != 64))
      return reject("unsupported model shape");
    auto output = RankedTensorType::get({samples, 4}, builder.getI8Type());
    auto quantization = model->getAttrOfType<StringAttr>("int8.quantization");
    if (model.getFunctionType() != builder.getFunctionType({input}, {output}) ||
        !quantization || quantization.getValue() != "signed-i8-nearest-away-saturate-v1")
      return reject("unsupported model shape or quantization contract");

    Block &block = model.front();
    auto first = dyn_cast<func::CallOp>(block.front());
    auto last = dyn_cast<func::ReturnOp>(block.back());
    if (!first || first.getCallee() != "linear_relu" ||
        first.getNumOperands() != 1 || first.getOperand(0) != block.getArgument(0) ||
        first.getNumResults() != 1 || first.getResult(0).getType() != output ||
        !last || last.getNumOperands() != 1)
      return reject("expected Linear/ReLU followed by Linear");
    auto hidden = first.getResult(0);
    func::CallOp second;
    bool cpuConsumer = false;
    for (Operation &op : block) {
      if (&op == first.getOperation() || &op == last.getOperation())
        continue;
      auto call = dyn_cast<func::CallOp>(op);
      if (!call || call.getNumOperands() != 1 || call.getOperand(0) != hidden)
        return reject("unsupported operation or intermediate use");
      if (call.getCallee() == "linear" && !second &&
          call.getNumResults() == 1 && call.getResult(0).getType() == output)
        second = call;
      else if (call.getCallee() == "observe_hidden" && !cpuConsumer && !second &&
               call.getNumResults() == 0)
        cpuConsumer = true;
      else
        return reject("unsupported consumer or schedule");
    }
    if (!second || last.getOperand(0) != second.getResult(0))
      return reject("expected model to return the second layer");

    bool chain = enableChaining && hidden.hasOneUse();
    auto location = model.getLoc();
    builder.setInsertionPointToEnd(module.getBody());
    auto abiType = builder.getFunctionType({}, {});
    auto schedule = builder.create<func::FuncOp>(location, "run_schedule", abiType);
    builder.setInsertionPointToStart(schedule.addEntryBlock());
    auto emit = [&](StringRef name) {
      builder.create<func::CallOp>(location, name, TypeRange{}, ValueRange{});
    };
    emit("dma_layer1");
    if (chain) {
      emit("dma_layer2_hidden");
    } else {
      emit("invalidate_hidden");
      if (cpuConsumer)
        emit("observe_hidden");
      emit("stage_hidden");
      emit("clean_staged");
      emit("dma_layer2_staged");
    }
    emit("invalidate_output");
    builder.create<func::ReturnOp>(location);

    // Only the model and its known external declarations are part of the ABI.
    for (auto function : llvm::make_early_inc_range(module.getOps<func::FuncOp>())) {
      if (function == schedule)
        continue;
      if (function != model &&
          (!function.isExternal() ||
           (function.getName() != "linear_relu" && function.getName() != "linear" &&
            function.getName() != "observe_hidden")))
        return reject("unexpected module function");
      function.erase();
    }
    OpBuilder declarations(module.getBodyRegion());
    declarations.setInsertionPointToStart(module.getBody());
    for (auto call : schedule.getOps<func::CallOp>())
      declarations.create<func::FuncOp>(location, call.getCallee(), abiType).setPrivate();
  }
};
} // namespace

int main(int argc, char **argv) {
  llvm::cl::opt<std::string> input(llvm::cl::Positional, llvm::cl::Required);
  llvm::cl::opt<bool> staged("force-staging", llvm::cl::desc("Disable DMA chaining"));
  llvm::cl::opt<std::string> header("emit-header", llvm::cl::desc("Write firmware schedule"));
  llvm::cl::ParseCommandLineOptions(argc, argv);
  DialectRegistry registry;
  registry.insert<func::FuncDialect>();
  MLIRContext context(registry);
  auto module = parseSourceFile<ModuleOp>(input.getValue(), &context);
  if (!module)
    return 1;
  PassManager manager(&context);
  manager.addPass(std::make_unique<LowerModel>(!staged));
  if (failed(manager.run(*module)))
    return 1;
  module->print(llvm::outs());
  if (!header.empty()) {
    std::error_code error;
    llvm::raw_fd_ostream file(header.getValue(), error, llvm::sys::fs::OF_Text);
    if (error) {
      llvm::errs() << error.message() << '\n';
      return 1;
    }
    file << "/* Generated from MLIR. */\n";
    for (auto call : module->lookupSymbol<func::FuncOp>("run_schedule").getOps<func::CallOp>())
      file << "ok &= " << call.getCallee() << "();\n";
  }
}
