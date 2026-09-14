`timescale 1ns/1ps

module tb_rv32_protected_offload;
  localparam logic [31:0] PHYS_BASE = 32'h1000_0000;
  localparam int INPUT_WORD = (32'h1000_1000 - PHYS_BASE) / 4;
  localparam int OUTPUT_WORD = (32'h1000_4000 - PHYS_BASE) / 4;

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  logic firmware_done;
  logic [31:0] firmware_result;
  logic commit_valid;
  logic [31:0] commit_pc;
  logic [31:0] commit_instr;
  logic irq;
  logic [31:0] cycles;
  int workflow;
  int k;
  int batch;
  int commits;
  int timeout_cycles;
  int waited_cycles;

  always #5 clk = ~clk;

  rv32_protected_offload_top dut (.*);

  function automatic int workflow_k(input int selected);
    case (selected)
      0: workflow_k = 4;
      1: workflow_k = 8;
      2: workflow_k = 16;
      3: workflow_k = 32;
      4: workflow_k = 64;
      5: workflow_k = 16;
      6: workflow_k = 32;
      default: workflow_k = 8;
    endcase
  endfunction

  function automatic int workflow_batch(input int selected);
    case (selected)
      0: workflow_batch = 1;
      1: workflow_batch = 2;
      2: workflow_batch = 4;
      3: workflow_batch = 8;
      4: workflow_batch = 1;
      5: workflow_batch = 16;
      6: workflow_batch = 2;
      default: workflow_batch = 4;
    endcase
  endfunction

  always_ff @(posedge clk) begin
    if (!rst_n) commits <= 0;
    else if (commit_valid) commits <= commits + 1;
  end

  initial begin
    if (!$value$plusargs("WORKFLOW=%d", workflow)) workflow = 0;
    if (!$value$plusargs("TIMEOUT_CYCLES=%d", timeout_cycles)) timeout_cycles = 300_000;
    k = workflow_k(workflow);
    batch = workflow_batch(workflow);
    for (int index = 0; index < 8192; index++) dut.memory[index] = '0;
    for (int vector_index = 0; vector_index < batch; vector_index++) begin
      for (int word_index = 0; word_index < (k / 4); word_index++) begin
        dut.memory[INPUT_WORD + vector_index * 16 + word_index] = 32'h0101_0101;
      end
    end

    repeat (5) @(posedge clk);
    rst_n = 1'b1;
    waited_cycles = 0;
    while (!firmware_done && waited_cycles < timeout_cycles) begin
      @(posedge clk);
      waited_cycles++;
    end
    if (!firmware_done)
      $fatal(1, "firmware timeout workflow=%0d pc=%08x instr=%08x", workflow, commit_pc, commit_instr);

    if (firmware_result !== (32'h600d_0000 | workflow))
      $fatal(1, "firmware result mismatch got=%08x workflow=%0d", firmware_result, workflow);
    if (dut.perf_tlb_misses < 2 || dut.perf_walk_reads < 4 || dut.perf_faults != 0)
      $fatal(1, "IOMMU activity mismatch hits=%0d misses=%0d walks=%0d faults=%0d",
             dut.perf_tlb_hits, dut.perf_tlb_misses, dut.perf_walk_reads, dut.perf_faults);
    for (int vector_index = 0; vector_index < batch; vector_index++) begin
      if (dut.memory[OUTPUT_WORD + vector_index] !== {4{8'(k)}})
        $fatal(1, "output mismatch vector=%0d got=%08x expected=%08x",
               vector_index, dut.memory[OUTPUT_WORD + vector_index], {4{8'(k)}});
    end
    $display("PROTECTED_FIRMWARE_EXEC|status=PASS|workflow=%0d|k=%0d|batch=%0d|cycles=%0d|commits=%0d|tlb_hits=%0d|tlb_misses=%0d|walks=%0d|result=%08x",
             workflow, k, batch, cycles, commits, dut.perf_tlb_hits,
             dut.perf_tlb_misses, dut.perf_walk_reads, firmware_result);
    $finish;
  end
endmodule
