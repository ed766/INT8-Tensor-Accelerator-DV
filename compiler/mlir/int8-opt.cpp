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
// Lifetimes use completion of blocking runtime calls as their boundaries.
// A consumer and producer in the same call cannot alias.
struct BufferLifetime {
  unsigned firstWrite;
  unsigned lastRead;
};

unsigned allocateSlot(BufferLifetime value, SmallVectorImpl<unsigned> &lastReads,
                      bool dedicated) {
  if (!dedicated) {
    for (unsigned slot = 0; slot < lastReads.size(); ++slot) {
      if (lastReads[slot] < value.firstWrite) {
        lastReads[slot] = value.lastRead;
        return slot;
      }
    }
  }
  lastReads.push_back(value.lastRead);
  return lastReads.size() - 1;
}

// Both head results are synchronously exported to host-owned storage.
LogicalResult verifyFanout(func::FuncOp schedule) {
  if (schedule->getAttrOfType<IntegerAttr>("int8.layers").getInt() != 3)
    return schedule.emitError("fan-out requires a trunk and two heads");
  auto slot = schedule->getAttrOfType<IntegerAttr>("int8.head2_slot");
  if (!slot || (slot.getInt() != 1 && slot.getInt() != 2))
    return schedule.emitError("head output must use a non-trunk arena slot");
  StringRef order[] = {"dma_layer1", "dma_head1", "publish_head1",
                       "dma_head2", "publish_head2"};
  unsigned next = 0;
  for (Operation &op : schedule.front().without_terminator()) {
    auto call = dyn_cast<func::CallOp>(op);
    if (call && call.getCallee() == "reuse_trunk")
      return op.emitError("premature reuse: the second head still needs the trunk");
    if (!call || call.getNumOperands() || call.getNumResults() ||
        next == 5 || call.getCallee() != order[next])
      return op.emitError("invalid fan-out ownership transition");
    ++next;
  }
  if (next != 5)
    return schedule.emitError("missing fan-out completion or publish");
  return success();
}

// Each DMA ABI call returns after firmware consumes its completion. A
// staged value stays live from the CPU copy through that consuming call.
LogicalResult verifySchedule(func::FuncOp schedule) {
  if (!schedule || !llvm::hasSingleElement(schedule.getBody()))
    return failure();
  auto layers = schedule->getAttrOfType<IntegerAttr>("int8.layers");
  if (!layers || (layers.getInt() != 2 && layers.getInt() != 3))
    return schedule.emitError("expected a two- or three-layer runtime schedule");
  if (auto tile = schedule->getAttrOfType<IntegerAttr>("int8.tile_vectors")) {
    auto batch = schedule->getAttrOfType<IntegerAttr>("int8.batch");
    if (!batch || (batch.getInt() != 4 && batch.getInt() != 8 && batch.getInt() != 16) ||
        (tile.getInt() != 4 && tile.getInt() != batch.getInt()) ||
        batch.getInt() % tile.getInt() != 0)
      return schedule.emitError("invalid batch tile");
  }
  if (schedule->hasAttr("int8.head2_slot"))
    return verifyFanout(schedule);
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
  LowerModel(bool enableChaining, bool dedicated)
      : enableChaining(enableChaining), dedicated(dedicated) {}
  bool enableChaining;
  bool dedicated;

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
    bool fanout = signature.getNumResults() == 2;
    SmallVector<Type> results(fanout ? 2 : 1, output);
    if (model.getFunctionType() != builder.getFunctionType({input}, results) ||
        !quantization || quantization.getValue() != "signed-i8-nearest-away-saturate-v1")
      return reject("unsupported model shape or quantization contract");

    Block &block = model.front();
    auto first = dyn_cast<func::CallOp>(block.front());
    auto last = dyn_cast<func::ReturnOp>(block.back());
    if (!first || first.getCallee() != "linear_relu" ||
        first.getNumOperands() != 1 || first.getOperand(0) != block.getArgument(0) ||
        first.getNumResults() != 1 || first.getResult(0).getType() != output ||
        !last || last.getNumOperands() != results.size())
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
               call.getOperand(0) == (fanout ? hidden : second.getResult(0)) &&
               call.getNumResults() == 1 && call.getResult(0).getType() == output)
        third = call;
      else if (call.getCallee() == "observe_hidden" && call.getOperand(0) == hidden && !cpuConsumer && !second &&
               call.getNumResults() == 0)
        cpuConsumer = true;
      else
        return reject("unsupported consumer or schedule");
    }
    if (!second || (fanout
        ? (!third || cpuConsumer || last.getOperand(0) != second.getResult(0) ||
           last.getOperand(1) != third.getResult(0))
        : last.getOperand(0) != (third ? third : second).getResult(0)))
      return reject("expected model to return the final layer");

    bool chain = enableChaining && hidden.hasOneUse();
    auto location = model.getLoc();
    builder.setInsertionPointToEnd(module.getBody());
    auto abiType = builder.getFunctionType({}, {});
    auto schedule = builder.create<func::FuncOp>(location, "run_schedule", abiType);
    schedule->setAttr("int8.layers", builder.getI32IntegerAttr(third ? 3 : 2));
    schedule->setAttr("int8.batch", builder.getI32IntegerAttr(samples));
    schedule->setAttr("int8.input_width", builder.getI32IntegerAttr(width));
    builder.setInsertionPointToStart(schedule.addEntryBlock());
    auto emit = [&](StringRef name) {
      builder.create<func::CallOp>(location, name, TypeRange{}, ValueRange{});
    };
    emit("dma_layer1");
    if (fanout) {
      // Trunk is live across both heads. Head one's slot becomes free only
      // after publish_head1 copies it out of the arena.
      SmallVector<unsigned> lastReads;
      allocateSlot({0, 3}, lastReads, dedicated); // trunk, read by both DMA heads
      allocateSlot({1, 2}, lastReads, dedicated); // first head, read by publish_head1
      unsigned head2 = allocateSlot({3, 4}, lastReads, dedicated);
      schedule->setAttr("int8.head2_slot", builder.getI32IntegerAttr(head2));
      emit("dma_head1");
      emit("publish_head1");
      emit("dma_head2");
      emit("publish_head2");
    } else {
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
    }
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
// This pass keeps each layer's ownership boundary intact. The runtime
// splits its blocking DMA call into contiguous slices of the same buffers.
struct TileBatch : PassWrapper<TileBatch, OperationPass<ModuleOp>> {
  TileBatch(StringRef policy, bool contended)
      : policy(policy.str()), contended(contended) {}

  void runOnOperation() override {
    auto schedule = getOperation().lookupSymbol<func::FuncOp>("run_schedule");
    auto batch = schedule->getAttrOfType<IntegerAttr>("int8.batch").getInt();
    auto width = schedule->getAttrOfType<IntegerAttr>("int8.input_width").getInt();
    // Prefer fewer descriptors unless contention and descriptor work favor
    // publishing completions at smaller intervals.
    int64_t tile = batch;
    if (policy == "four" || (policy == "auto" && contended && batch * (width / 4) > 64))
      tile = 4;
    schedule->setAttr("int8.tile_vectors", IntegerAttr::get(
        IntegerType::get(&getContext(), 32), tile));
    if (failed(verifySchedule(schedule)))
      signalPassFailure();
  }

  std::string policy;
  bool contended;
};
} // namespace

int main(int argc, char **argv) {
  llvm::cl::opt<std::string> input(llvm::cl::Positional, llvm::cl::Required);
  llvm::cl::opt<bool> staged("force-staging", llvm::cl::desc("Disable DMA chaining"));
  llvm::cl::opt<std::string> header("emit-header", llvm::cl::desc("Write firmware schedule"));
  llvm::cl::opt<bool> verifyOnly("verify-schedule", llvm::cl::desc("Verify lowered buffer lifetimes"));
  llvm::cl::opt<std::string> tile("batch-tiling", llvm::cl::init("full"),
                                 llvm::cl::desc("full, four, or auto"));
  llvm::cl::opt<bool> contended("axi-contention");
  llvm::cl::opt<bool> dedicated("dedicated-scratch");
  llvm::cl::ParseCommandLineOptions(argc, argv);
  DialectRegistry registry;
  registry.insert<func::FuncDialect>();
  MLIRContext context(registry);
  auto module = parseSourceFile<ModuleOp>(input.getValue(), &context);
  if (!module)
    return 1;
  if (verifyOnly)
    return failed(verifySchedule(module->lookupSymbol<func::FuncOp>("run_schedule")));
  if (tile != "full" && tile != "four" && tile != "auto") {
    llvm::errs() << "unknown batch tiling policy\n";
    return 1;
  }
  PassManager manager(&context);
  manager.addPass(std::make_unique<LowerModel>(!staged, dedicated));
  manager.addPass(std::make_unique<TileBatch>(tile.getValue(), contended));
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
    file << "#ifdef MLIR_SCHEDULE_CONFIG\n#define MLIR_TILE_VECTORS "
         << schedule->getAttrOfType<IntegerAttr>("int8.tile_vectors").getInt()
         << "\n";
    if (auto slot = schedule->getAttrOfType<IntegerAttr>("int8.head2_slot"))
      file << "#define MLIR_HEAD2_SLOT " << slot.getInt() << "\n";
    file << "#else\n";
    bool three = schedule->getAttrOfType<IntegerAttr>("int8.layers").getInt() == 3;
    for (auto call : schedule.getOps<func::CallOp>())
      file << (three ? "if (ok) ok = " : "ok &= ") << call.getCallee() << "();\n";
    file << "#endif\n";
  }
}
