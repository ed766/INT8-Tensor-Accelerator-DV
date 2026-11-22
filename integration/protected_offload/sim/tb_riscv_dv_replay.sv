`timescale 1ns/1ps
module tb_riscv_dv_replay;
  logic clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic [31:0] rom [0:4095];
  logic valid, trap, intr;
  logic [31:0] pc, insn, value;
  logic [4:0] rd;
  logic [3:0] rmask, wmask;
  logic [31:0] terminal;
  string image;
  wire in_rom = dut.pc_q[31:14] == 0;
  rv32_core #(.ENABLE_M(1), .ENABLE_TRAPS(1)) dut (
    .clk, .rst_n, .instr_valid(in_rom), .instr(rom[dut.pc_q[13:2]]),
    .irq_ext(1'b0), .irq_timer(1'b0), .prdata('0), .pready(1'b0), .pslverr(1'b0),
    .rvfi_valid(valid), .rvfi_trap(trap), .rvfi_intr(intr), .rvfi_pc_rdata(pc),
    .rvfi_insn(insn), .rvfi_rd_addr(rd), .rvfi_rd_wdata(value),
    .rvfi_mem_rmask(rmask), .rvfi_mem_wmask(wmask)
  );

  initial begin
    if (!$value$plusargs("IMAGE=%s", image) || !$value$plusargs("TERMINAL=%h", terminal))
      $fatal(1, "Replay image and terminal PC are required");
    $readmemh(image, rom);
    repeat (3) @(negedge clk);
    rst_n = 1;
    repeat (100000) begin
      @(negedge clk);
      if (!in_rom) $fatal(1, "Instruction fetch outside ROM");
      if (valid) begin
        if (trap || intr || rmask != 0 || wmask != 0)
          $fatal(1, "Unexpected trap, interrupt, or memory access at %08x", pc);
        $display("REPLAY,%08x,%08x,%0d,%08x", pc, insn, rd, rd == 0 ? 32'b0 : value);
        if (pc == terminal) $finish;
      end
    end
    $fatal(1, "Replay did not reach terminal");
  end
endmodule
