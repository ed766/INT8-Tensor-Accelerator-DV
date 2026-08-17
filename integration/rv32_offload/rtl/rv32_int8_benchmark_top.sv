`timescale 1ns/1ps

module rv32_int8_benchmark_top #(
  parameter int ROM_WORDS = 4096,
  parameter int DATA_MEM_WORDS = 4096
) (
  input logic clk, input logic rst_n,
  output logic firmware_done, output logic [31:0] firmware_result,
  output logic commit_valid, output logic [31:0] commit_pc,
  output logic [31:0] commit_instr, output logic halted,
  output logic [31:0] benchmark_stats [0:15]
);
  logic instr_valid,instr_ready; logic[31:0]instr,commit_next_pc;
  logic[31:0]paddr,pwdata,prdata;logic psel,penable,pwrite,pready,pslverr;
  logic axil_sel,mail_sel;logic[31:0]axil_prdata,mail_prdata;
  logic axil_pready,axil_pslverr,mail_pready,mail_pslverr;
  logic[7:0]awaddr,araddr;logic awvalid,awready,wvalid,wready,bvalid,bready;
  logic[31:0]wdata,rdata;logic[3:0]wstrb;logic[1:0]bresp,rresp;logic arvalid,arready,rvalid,rready;
  logic[31:0]axis_in_data,axis_out_data;logic[7:0]axis_in_tag,axis_out_tag;
  logic axis_in_valid,axis_in_ready,axis_out_valid,axis_out_ready,irq_error;

  assign axil_sel = psel && (paddr >= 32'h4000_0000) && (paddr <= 32'h4000_0044);
  assign mail_sel = psel && (paddr >= 32'h4000_0100) && (paddr <= 32'h4000_01f4);
  assign prdata = axil_sel ? axil_prdata : mail_prdata;
  assign pready = axil_sel ? axil_pready : (mail_sel ? mail_pready : (psel && penable));
  assign pslverr = axil_sel ? axil_pslverr : (mail_sel ? mail_pslverr : (psel && penable));

  rv32_core #(.MMIO_BASE(32'h4000_0000),.MMIO_END(32'h4000_01ff),
    .DATA_MEM_WORDS(DATA_MEM_WORDS),.MAILBOX_ALIAS_BASE(32'h0000_8000),
    .ENABLE_TRAPS(1'b0),.EBREAK_TEST_HALT(1'b1)) cpu (
    .clk,.rst_n,.instr_valid,.instr_ready,.instr,.irq_ext(1'b0),.irq_timer(1'b0),
    .paddr,.psel,.penable,.pwrite,.pwdata,.prdata,.pready,.pslverr,
    .commit_valid,.commit_instr,.commit_pc,.commit_next_pc,.halted,
    .wb_valid(),.wb_rd(),.wb_data(),.mem_valid(),.mem_write(),.mem_addr(),
    .mem_wdata(),.mem_rdata(),.branch_taken(),.illegal_instr(),.bus_error(),.retire(),
    .rvfi_valid(),.rvfi_order(),.rvfi_insn(),.rvfi_trap(),.rvfi_intr(),
    .rvfi_pc_rdata(),.rvfi_pc_wdata(),.rvfi_rs1_addr(),.rvfi_rs2_addr(),
    .rvfi_rs1_rdata(),.rvfi_rs2_rdata(),.rvfi_rd_addr(),.rvfi_rd_wdata(),
    .rvfi_mem_addr(),.rvfi_mem_rmask(),.rvfi_mem_wmask(),.rvfi_mem_rdata(),
    .rvfi_mem_wdata(),.rvfi_mstatus(),.rvfi_mie(),.rvfi_mtvec(),.rvfi_mscratch(),
    .rvfi_mscratch_state(),.rvfi_mepc(),.rvfi_mcause(),.rvfi_mtval()
  );
  rv32_rom_feeder #(.ROM_WORDS(ROM_WORDS),.DEFAULT_HEX("build/rv32_benchmark/smoke.hex")) rom (
    .clk,.rst_n,.instr_ready,.instr_valid,.instr,.commit_valid,.commit_next_pc,.halted);

  apb_to_axil_bridge bridge (
    .clk,.rst_n,.paddr,.psel(axil_sel),.penable,.pwrite,.pwdata,
    .prdata(axil_prdata),.pready(axil_pready),.pslverr(axil_pslverr),
    .m_awaddr(awaddr),.m_awvalid(awvalid),.m_awready(awready),
    .m_wdata(wdata),.m_wstrb(wstrb),.m_wvalid(wvalid),.m_wready(wready),
    .m_bresp(bresp),.m_bvalid(bvalid),.m_bready(bready),
    .m_araddr(araddr),.m_arvalid(arvalid),.m_arready(arready),
    .m_rdata(rdata),.m_rresp(rresp),.m_rvalid(rvalid),.m_rready(rready));

  apb_axis_mailbox stream_mailbox (
    .clk,.rst_n,.paddr,.psel(mail_sel),.penable,.pwrite,.pwdata,
    .prdata(mail_prdata),.pready(mail_pready),.pslverr(mail_pslverr),
    .s_axis_tdata(axis_in_data),.s_axis_tuser(axis_in_tag),
    .s_axis_tvalid(axis_in_valid),.s_axis_tready(axis_in_ready),
    .m_axis_tdata(axis_out_data),.m_axis_tuser(axis_out_tag),
    .m_axis_tvalid(axis_out_valid),.m_axis_tready(axis_out_ready),.commit_valid,
    .firmware_done,.firmware_result,.benchmark_stats);

  int8_accel_axi_wrapper accelerator (
    .clk,.rst_n,.s_axil_awaddr(awaddr),.s_axil_awvalid(awvalid),.s_axil_awready(awready),
    .s_axil_wdata(wdata),.s_axil_wstrb(wstrb),.s_axil_wvalid(wvalid),.s_axil_wready(wready),
    .s_axil_bresp(bresp),.s_axil_bvalid(bvalid),.s_axil_bready(bready),
    .s_axil_araddr(araddr),.s_axil_arvalid(arvalid),.s_axil_arready(arready),
    .s_axil_rdata(rdata),.s_axil_rresp(rresp),.s_axil_rvalid(rvalid),.s_axil_rready(rready),
    .s_axis_tdata(axis_in_data),.s_axis_tuser(axis_in_tag),
`ifdef RV32_BENCH_MUT_DROP_CHUNK
    .s_axis_tvalid(1'b0),.s_axis_tready(axis_in_ready),
`else
    .s_axis_tvalid(axis_in_valid),.s_axis_tready(axis_in_ready),
`endif
    .m_axis_tdata(axis_out_data),.m_axis_tuser(axis_out_tag),
    .m_axis_tvalid(axis_out_valid),.m_axis_tready(axis_out_ready),.irq_error);

`ifndef SYNTHESIS
  a_done_after_results: assert property (@(posedge clk) disable iff(!rst_n)
    firmware_done |-> (accelerator.perf_completed != 0));
  a_done_command_accounting: assert property (@(posedge clk) disable iff(!rst_n)
    firmware_done |-> (accelerator.perf_accepted == accelerator.perf_completed));
`endif
endmodule
