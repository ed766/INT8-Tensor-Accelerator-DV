`timescale 1ns/1ps

module int8_accel_axi_wrapper #(
  parameter int LANES = 4,
  parameter int OUTPUTS = 4,
  parameter int MAX_K = 64,
  parameter int FIFO_DEPTH = 4,
  parameter int TAG_W = 8
) (
  input logic clk, input logic rst_n,
  input logic [7:0] s_axil_awaddr, input logic s_axil_awvalid, output logic s_axil_awready,
  input logic [31:0] s_axil_wdata, input logic [3:0] s_axil_wstrb,
  input logic s_axil_wvalid, output logic s_axil_wready,
  output logic [1:0] s_axil_bresp, output logic s_axil_bvalid, input logic s_axil_bready,
  input logic [7:0] s_axil_araddr, input logic s_axil_arvalid, output logic s_axil_arready,
  output logic [31:0] s_axil_rdata, output logic [1:0] s_axil_rresp,
  output logic s_axil_rvalid, input logic s_axil_rready,
  input logic [LANES*8-1:0] s_axis_tdata, input logic [TAG_W-1:0] s_axis_tuser,
  input logic s_axis_tvalid, output logic s_axis_tready,
  output logic [OUTPUTS*8-1:0] m_axis_tdata, output logic [TAG_W-1:0] m_axis_tuser,
  output logic m_axis_tvalid, input logic m_axis_tready,
  output logic irq_error
);
  localparam logic [1:0] OKAY = 2'b00, SLVERR = 2'b10;
  logic aw_pending, w_pending, write_exec;
  logic [7:0] awaddr_q;
  logic [31:0] wdata_q;
  logic [3:0] wstrb_q;
  logic [11:0] cfg_select;
  logic cfg_valid, cfg_ready, cfg_bank;
  logic [2:0] cfg_kind;
  logic [$clog2(OUTPUTS)-1:0] cfg_output;
  logic [$clog2(MAX_K)-1:0] cfg_index;
  logic [31:0] cfg_data;
  logic cmd_valid, cmd_ready, cmd_bank, cmd_error;
  logic [$clog2(MAX_K+1)-1:0] cmd_k;
  logic [TAG_W-1:0] cmd_tag;
  logic [31:0] perf_accepted, perf_completed, perf_input_chunks;
  logic [31:0] perf_output_stalls, perf_bank_swaps;
  logic monitor_clear;
  logic [31:0] mon_accepted, mon_completed, mon_chunks;
  logic [31:0] mon_cmd_stalls, mon_input_stalls, mon_output_stalls;
  logic [31:0] mon_max_outstanding, mon_last_latency, mon_active_cycles;
  logic mon_protocol_error;
  logic duplicate_command_pending;
  logic duplicate_command_injected;
  logic configuration_committed;
  logic in_ready, out_valid;
  logic [OUTPUTS*8-1:0] out_data;
  logic [TAG_W-1:0] out_tag;

  assign s_axil_awready = !aw_pending && !s_axil_bvalid && !write_exec;
  assign s_axil_wready = !w_pending && !s_axil_bvalid && !write_exec;
  assign s_axil_arready = !s_axil_rvalid;
  assign s_axis_tready = in_ready;
  assign m_axis_tvalid = out_valid;
  assign m_axis_tdata = out_data;
  assign m_axis_tuser = out_tag;

  int8_tensor_accel #(.LANES(LANES), .OUTPUTS(OUTPUTS), .MAX_K(MAX_K),
      .FIFO_DEPTH(FIFO_DEPTH), .TAG_W(TAG_W)) accelerator (
    .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_kind, .cfg_bank, .cfg_output,
    .cfg_index, .cfg_data, .cmd_valid, .cmd_ready, .cmd_bank, .cmd_k, .cmd_tag,
    .cmd_error, .in_valid(s_axis_tvalid), .in_ready, .in_data(s_axis_tdata),
    .in_tag(s_axis_tuser), .out_valid, .out_ready(m_axis_tready), .out_data, .out_tag,
    .perf_accepted, .perf_completed, .perf_input_chunks, .perf_output_stalls,
    .perf_bank_swaps
  );

  int8_accel_health_monitor monitor (
    .clk, .rst_n, .clear(monitor_clear), .cmd_valid, .cmd_ready,
    .in_valid(s_axis_tvalid), .in_ready,
    .out_valid, .out_ready(m_axis_tready), .out_tag,
    .accepted_commands(mon_accepted), .completed_commands(mon_completed),
    .accepted_chunks(mon_chunks), .command_stall_cycles(mon_cmd_stalls),
    .input_stall_cycles(mon_input_stalls), .output_stall_cycles(mon_output_stalls),
    .max_outstanding(mon_max_outstanding), .last_command_latency(mon_last_latency),
    .active_compute_cycles(mon_active_cycles), .protocol_error(mon_protocol_error)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      aw_pending <= 0; w_pending <= 0; write_exec <= 0; awaddr_q <= 0;
      wdata_q <= 0; wstrb_q <= 0; s_axil_bvalid <= 0; s_axil_bresp <= OKAY;
      s_axil_rvalid <= 0; s_axil_rdata <= 0; s_axil_rresp <= OKAY;
      cfg_select <= 0; cfg_valid <= 0; cfg_kind <= 0; cfg_bank <= 0;
      cfg_output <= 0; cfg_index <= 0; cfg_data <= 0;
      cmd_valid <= 0; cmd_bank <= 0; cmd_k <= 0; cmd_tag <= 0; irq_error <= 0;
      monitor_clear <= 0;
      duplicate_command_pending <= 0;
      duplicate_command_injected <= 0;
      configuration_committed <= 0;
    end else begin
      monitor_clear <= 0;
      if (s_axil_awvalid && s_axil_awready) begin aw_pending <= 1; awaddr_q <= s_axil_awaddr; end
      if (s_axil_wvalid && s_axil_wready) begin w_pending <= 1; wdata_q <= s_axil_wdata; wstrb_q <= s_axil_wstrb; end
      if (s_axil_bvalid && s_axil_bready) s_axil_bvalid <= 0;
      if (s_axil_rvalid && s_axil_rready) s_axil_rvalid <= 0;
      if (cmd_error) irq_error <= 1;
`ifdef RV32_BENCH_MUT_DUP_COMMAND
      if (duplicate_command_pending && !cmd_valid && cmd_ready) begin
        cmd_valid <= 1;
        duplicate_command_pending <= 0;
        duplicate_command_injected <= 1;
      end
`endif

      if (aw_pending && w_pending && !write_exec && !s_axil_bvalid) begin
        aw_pending <= 0; w_pending <= 0;
        if (awaddr_q[1:0] != 0 || wstrb_q != 4'hf) begin
          s_axil_bresp <= SLVERR; s_axil_bvalid <= 1; irq_error <= 1;
        end else case (awaddr_q)
          8'h00: begin cfg_select <= wdata_q[11:0]; s_axil_bresp <= OKAY; s_axil_bvalid <= 1; end
          8'h04: begin
            cfg_kind <= cfg_select[2:0]; cfg_bank <= cfg_select[3];
            cfg_output <= cfg_select[5:4]; cfg_index <= cfg_select[11:6];
            cfg_data <= wdata_q; cfg_valid <= 1; write_exec <= 1;
          end
          8'h08: begin
            cmd_bank <= wdata_q[0]; cmd_k <= wdata_q[7:1]; cmd_tag <= wdata_q[15:8];
            cmd_valid <= 1; write_exec <= 1;
          end
          8'h28: begin irq_error <= irq_error & ~wdata_q[0]; s_axil_bresp <= OKAY; s_axil_bvalid <= 1; end
          8'h44: begin monitor_clear <= wdata_q[0]; s_axil_bresp <= OKAY; s_axil_bvalid <= 1; end
          default: begin s_axil_bresp <= SLVERR; s_axil_bvalid <= 1; irq_error <= 1; end
        endcase
      end
      if (cfg_valid && cfg_ready) begin
        cfg_valid <= 0; write_exec <= 0; s_axil_bresp <= OKAY; s_axil_bvalid <= 1;
        configuration_committed <= 1;
      end
      if (cmd_valid && cmd_ready) begin
        cmd_valid <= 0; write_exec <= 0; s_axil_bresp <= OKAY; s_axil_bvalid <= 1;
`ifdef RV32_BENCH_MUT_DUP_COMMAND
        if (!duplicate_command_injected) duplicate_command_pending <= 1;
`endif
      end

      if (s_axil_arvalid && s_axil_arready) begin
        s_axil_rvalid <= 1; s_axil_rresp <= OKAY;
        if (s_axil_araddr[1:0] != 0) begin s_axil_rdata <= 0; s_axil_rresp <= SLVERR; end
        else case (s_axil_araddr)
          8'h00: s_axil_rdata <= {20'd0, cfg_select};
          8'h0c: s_axil_rdata <= {28'd0, irq_error, out_valid, cmd_ready, cfg_ready};
          8'h10: s_axil_rdata <= perf_accepted;
          8'h14: s_axil_rdata <= perf_completed;
          8'h18: s_axil_rdata <= perf_input_chunks;
          8'h1c: s_axil_rdata <= perf_output_stalls;
          8'h20: s_axil_rdata <= perf_bank_swaps;
          8'h24: s_axil_rdata <= {31'd0, irq_error};
          8'h2c: s_axil_rdata <= mon_last_latency;
          8'h30: s_axil_rdata <= mon_active_cycles;
          8'h34: s_axil_rdata <= mon_input_stalls;
          8'h38: s_axil_rdata <= mon_output_stalls;
          8'h3c: s_axil_rdata <= mon_cmd_stalls;
          8'h40: s_axil_rdata <= mon_max_outstanding;
          8'h44: s_axil_rdata <= {31'd0, mon_protocol_error};
          default: begin s_axil_rdata <= 0; s_axil_rresp <= SLVERR; end
        endcase
      end
    end
  end

`ifndef SYNTHESIS
  a_bresp_stable: assert property (@(posedge clk) disable iff (!rst_n)
    s_axil_bvalid && !s_axil_bready |=> s_axil_bvalid && $stable(s_axil_bresp));
  a_rpayload_stable: assert property (@(posedge clk) disable iff (!rst_n)
    s_axil_rvalid && !s_axil_rready |=> s_axil_rvalid && $stable({s_axil_rdata, s_axil_rresp}));
  a_axis_input_stable: assert property (@(posedge clk) disable iff (!rst_n)
    s_axis_tvalid && !s_axis_tready |=> s_axis_tvalid && $stable({s_axis_tdata, s_axis_tuser}));
  a_axis_output_stable: assert property (@(posedge clk) disable iff (!rst_n)
    m_axis_tvalid && !m_axis_tready |=> m_axis_tvalid && $stable({m_axis_tdata, m_axis_tuser}));
  a_command_after_configuration: assert property (@(posedge clk) disable iff (!rst_n)
    cmd_valid && cmd_ready |-> configuration_committed);
`endif
endmodule
