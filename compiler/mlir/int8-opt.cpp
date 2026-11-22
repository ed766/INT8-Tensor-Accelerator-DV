#include "mlir/Dialect/Func/IR/FuncOps.h"
#include "mlir/IR/BuiltinOps.h"
#include "mlir/Parser/Parser.h"
#include "mlir/Pass/Pass.h"
#include "mlir/Pass/PassManager.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/ADT/StringSwitch.h"
#include "llvm/Support/FileSystem.h"

using namespace mlir;

namespace {
// Each DMA ABI call returns after firmware consumes its completion. A
// staged value stays live from the CPU copy through that consuming call.
LogicalResult verifySchedule(func::FuncOp schedule) {
  if (!schedule || !llvm::hasSingleElement(schedule.getBody()))
    return failure();
  auto layers = schedule->getAttrOfType<IntegerAttr>("int8.layers");
  if (!layers || (layers.getInt() != 2 && layers.getInt() != 3))
    return schedule.emitError("expected a two- or three-layer runtime schedule");
  unsigned completed = 0;
  unsigned staged = 0;
  bool cpuVisible = false, clean = false, terminal = false;
  for (Operation &op : schedule.front().without_terminator()) {
    auto call = dyn_cast<func::CallOp>(op);
    if (!call || call.getNumOperands() || call.getNumResults())
      return op.emitError("expected a zero-argument runtime call");
    StringRef name = call.getCallee();
    if (terminal)
      return call.emitError("operation after output invalidation");
    if (name == "stage_hidden" || name == "stage_middle") {
      if (staged)
        return call.emitError("premature reuse of live staging buffer");
      unsigned producer = name == "stage_hidden" ? 1 : 2;
      if (!cpuVisible || completed != producer)
        return call.emitError("CPU copy requires completed and invalidated DMA output");
      staged = producer;
      clean = false;
    } else if (name == "clean_staged") {
      if (!staged || clean)
        return call.emitError("clean requires a dirty staging buffer");
      clean = true;
    } else if (name == "invalidate_hidden" || name == "invalidate_middle") {
      if (staged || completed != (name == "invalidate_hidden" ? 1u : 2u))
        return call.emitError("invalidation requires the completed producer");
      cpuVisible = true;
    } else if (name == "observe_hidden") {
      if (!cpuVisible || completed != 1)
        return call.emitError("CPU observer requires a coherent hidden buffer");
    } else if (name == "invalidate_output") {
      if (completed != layers.getInt() || staged)
        return call.emitError("output invalidation requires final completion");
      terminal = true;
    } else {
      unsigned layer = llvm::StringSwitch<unsigned>(name)
                           .Case("dma_layer1", 1)
                           .Cases("dma_layer2_hidden", "dma_layer2_staged", 2)
                           .Cases("dma_layer2_to_middle", "dma_layer2_staged_to_middle", 2)
                           .Cases("dma_layer3_middle", "dma_layer3_staged", 3)
                           .Default(0);
      bool usesStaged = name.contains("_staged");
      if (layer == 2 && (name.ends_with("_middle") != (layers.getInt() == 3)))
        return call.emitError("layer-two output buffer disagrees with the graph");
      if (layer != completed + 1 || layer > layers.getInt() ||
          (usesStaged ? (!clean || staged != completed) : staged != 0))
        return call.emitError("DMA input is out of order or unavailable");
      completed = layer;
      staged = 0;
      clean = cpuVisible = false;
    }
  }
  if (!terminal)
    return schedule.emitError("missing final output invalidation");
  return success();
}

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
    func::CallOp third;
    bool cpuConsumer = false;
    for (Operation &op : block) {
      if (&op == first.getOperation() || &op == last.getOperation())
        continue;
      auto call = dyn_cast<func::CallOp>(op);
      if (!call || call.getNumOperands() != 1)
        return reject("unsupported operation or intermediate use");
      if (call.getCallee() == "linear" && !second && call.getOperand(0) == hidden &&
          call.getNumResults() == 1 && call.getResult(0).getType() == output)
        second = call;
      else if (call.getCallee() == "linear" && second && !third &&
               call.getOperand(0) == second.getResult(0) &&
               call.getNumResults() == 1 && call.getResult(0).getType() == output)
        third = call;
      else if (call.getCallee() == "observe_hidden" && call.getOperand(0) == hidden && !cpuConsumer && !second &&
               call.getNumResults() == 0)
        cpuConsumer = true;
      else
        return reject("unsupported consumer or schedule");
    }
    if (!second || last.getOperand(0) != (third ? third : second).getResult(0))
      return reject("expected model to return the final layer");

    bool chain = enableChaining && hidden.hasOneUse();
    auto location = model.getLoc();
    builder.setInsertionPointToEnd(module.getBody());
    auto abiType = builder.getFunctionType({}, {});
    auto schedule = builder.create<func::FuncOp>(location, "run_schedule", abiType);
    schedule->setAttr("int8.layers", builder.getI32IntegerAttr(third ? 3 : 2));
    builder.setInsertionPointToStart(schedule.addEntryBlock());
    auto emit = [&](StringRef name) {
      builder.create<func::CallOp>(location, name, TypeRange{}, ValueRange{});
    };
    emit("dma_layer1");
    if (chain) {
      emit(third ? "dma_layer2_to_middle" : "dma_layer2_hidden");
    } else {
      emit("invalidate_hidden");
      if (cpuConsumer)
        emit("observe_hidden");
      emit("stage_hidden");
      emit("clean_staged");
      emit(third ? "dma_layer2_staged_to_middle" : "dma_layer2_staged");
    }
    if (third) {
      bool chainMiddle = enableChaining && second.getResult(0).hasOneUse();
      if (!chainMiddle) {
        emit("invalidate_middle");
        emit("stage_middle");
        emit("clean_staged");
      }
      emit(chainMiddle ? "dma_layer3_middle" : "dma_layer3_staged");
    }
    emit("invalidate_output");
    builder.create<func::ReturnOp>(location);
    if (failed(verifySchedule(schedule)))
      return signalPassFailure();

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
    for (auto call : schedule.getOps<func::CallOp>()) {
      if (!module.lookupSymbol(call.getCallee()))
        declarations.create<func::FuncOp>(location, call.getCallee(), abiType).setPrivate();
    }
  }
};
} // namespace

int main(int argc, char **argv) {
  llvm::cl::opt<std::string> input(llvm::cl::Positional, llvm::cl::Required);
  llvm::cl::opt<bool> staged("force-staging", llvm::cl::desc("Disable DMA chaining"));
  llvm::cl::opt<std::string> header("emit-header", llvm::cl::desc("Write firmware schedule"));
  llvm::cl::opt<bool> verifyOnly("verify-schedule", llvm::cl::desc("Verify lowered buffer lifetimes"));
  llvm::cl::ParseCommandLineOptions(argc, argv);
  DialectRegistry registry;
  registry.insert<func::FuncDialect>();
  MLIRContext context(registry);
  auto module = parseSourceFile<ModuleOp>(input.getValue(), &context);
  if (!module)
    return 1;
  if (verifyOnly)
    return failed(verifySchedule(module->lookupSymbol<func::FuncOp>("run_schedule")));
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
    auto schedule = module->lookupSymbol<func::FuncOp>("run_schedule");
    bool three = schedule->getAttrOfType<IntegerAttr>("int8.layers").getInt() == 3;
    for (auto call : schedule.getOps<func::CallOp>())
      file << (three ? "if (ok) ok = " : "ok &= ") << call.getCallee() << "();\n";
  }
}
