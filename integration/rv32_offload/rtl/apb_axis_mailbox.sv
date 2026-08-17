`timescale 1ns/1ps

module apb_axis_mailbox (
  input logic clk, input logic rst_n,
  input logic [31:0] paddr, input logic psel, input logic penable,
  input logic pwrite, input logic [31:0] pwdata,
  output logic [31:0] prdata, output logic pready, output logic pslverr,
  output logic [31:0] s_axis_tdata, output logic [7:0] s_axis_tuser,
  output logic s_axis_tvalid, input logic s_axis_tready,
  input logic [31:0] m_axis_tdata, input logic [7:0] m_axis_tuser,
  input logic m_axis_tvalid, output logic m_axis_tready,
  input logic commit_valid,
  output logic firmware_done, output logic [31:0] firmware_result,
  output logic [31:0] benchmark_stats [0:15]
);
  logic [31:0] input_data;
  logic [7:0] input_tag;
  logic access;
  integer output_stall_percent;
  logic [31:0] cycle_count;
  logic [31:0] retire_count;
  logic [31:0] scalar_cycle_start, scalar_retire_start;
  logic [31:0] accel_cycle_start, accel_retire_start;
  logic [31:0] config_start, stream_start, poll_start, output_start;
  logic [31:0] calibration_start;
  logic calibration_valid;
  logic output_stall_block;
  initial begin
    output_stall_percent = 0;
    void'($value$plusargs("OUT_STALL_PERCENT=%d", output_stall_percent));
  end
  assign output_stall_block = (output_stall_percent > 0) &&
                              ((cycle_count % 100) < output_stall_percent);
  assign access = psel && penable;
  assign s_axis_tdata = input_data;
  assign s_axis_tuser = input_tag;
  assign s_axis_tvalid = access && pwrite && paddr[11:0] == 12'h108;
  assign m_axis_tready = access && pwrite && paddr[11:0] == 12'h12c && !output_stall_block;

  always_comb begin
    prdata = 0; pready = 0; pslverr = 0;
    if (access) begin
      unique case (paddr[11:0])
        12'h100: pready = 1;
        12'h104: pready = 1;
        12'h108: pready = pwrite && s_axis_tready;
        12'h10c: begin prdata = {31'd0,s_axis_tready}; pready = !pwrite; end
        12'h120: begin prdata = m_axis_tdata; pready = !pwrite; end
        12'h124: begin prdata = {24'd0,m_axis_tuser}; pready = !pwrite; end
        12'h128: begin prdata = {31'd0,m_axis_tvalid}; pready = !pwrite; end
        12'h12c: pready = pwrite && m_axis_tvalid && !output_stall_block;
        12'h174: begin prdata = benchmark_stats[4]; pready = 1; end
        12'h180,12'h184,12'h188,12'h18c,12'h190,12'h194,
        12'h198,12'h19c,12'h1a0,12'h1a4,12'h1a8,12'h1ac,
        12'h1c0,12'h1c4,12'h1c8,12'h1cc,12'h1d0,12'h1d4,
        12'h1d8,12'h1dc,12'h1e0,12'h1e4,12'h1e8,12'h1ec,
        12'h1f0,12'h1f4: pready = pwrite;
        default: begin pready = 1; pslverr = 1; end
      endcase
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      input_data <= 0; input_tag <= 0; firmware_done <= 0; firmware_result <= 0;
      for (int i=0;i<16;i++) benchmark_stats[i] <= 0;
      cycle_count <= 0;
      retire_count <= 0; scalar_cycle_start <= 0; scalar_retire_start <= 0;
      accel_cycle_start <= 0; accel_retire_start <= 0;
      config_start <= 0; stream_start <= 0; poll_start <= 0; output_start <= 0;
      calibration_start <= 0; calibration_valid <= 0;
    end else if (access && pready && pwrite) begin
      cycle_count <= cycle_count + 1'b1;
      if (commit_valid) retire_count <= retire_count + 1'b1;
      case (paddr[11:0])
        12'h100: input_data <= pwdata;
        12'h104: input_tag <= pwdata[7:0];
        12'h1f0: firmware_result <= pwdata;
        12'h1f4: firmware_done <= pwdata[0];
        12'h174: begin
          if (calibration_valid) benchmark_stats[4] <= cycle_count-calibration_start;
          calibration_start <= cycle_count; calibration_valid <= 1;
        end
        12'h180: begin scalar_cycle_start <= cycle_count; scalar_retire_start <= retire_count; end
        12'h184: begin benchmark_stats[0] <= cycle_count-scalar_cycle_start; benchmark_stats[2] <= retire_count-scalar_retire_start; end
        12'h188: begin accel_cycle_start <= cycle_count; accel_retire_start <= retire_count; end
        12'h18c: begin benchmark_stats[1] <= cycle_count-accel_cycle_start; benchmark_stats[3] <= retire_count-accel_retire_start; end
        12'h190: config_start <= cycle_count;
        12'h194: benchmark_stats[12] <= benchmark_stats[12] + cycle_count-config_start;
        12'h198: stream_start <= cycle_count;
        12'h19c: benchmark_stats[13] <= benchmark_stats[13] + cycle_count-stream_start;
        12'h1a0: poll_start <= cycle_count;
        12'h1a4: benchmark_stats[14] <= benchmark_stats[14] + cycle_count-poll_start;
        12'h1a8: output_start <= cycle_count;
        12'h1ac: benchmark_stats[15] <= benchmark_stats[15] + cycle_count-output_start;
        12'h1c0: benchmark_stats[0] <= pwdata;
        12'h1c4: benchmark_stats[1] <= pwdata;
        12'h1c8: benchmark_stats[2] <= pwdata;
        12'h1cc: benchmark_stats[3] <= pwdata;
        12'h1d0: benchmark_stats[4] <= pwdata;
        12'h1d4: benchmark_stats[5] <= pwdata;
        12'h1d8: benchmark_stats[6] <= pwdata;
        12'h1dc: benchmark_stats[7] <= pwdata;
        12'h1e0: benchmark_stats[8] <= pwdata;
        12'h1e4: benchmark_stats[9] <= pwdata;
        12'h1e8: benchmark_stats[10] <= pwdata;
        12'h1ec: benchmark_stats[11] <= pwdata;
        default: begin end
      endcase
    end else begin
      cycle_count <= cycle_count + 1'b1;
      if (commit_valid) retire_count <= retire_count + 1'b1;
    end
  end

`ifndef SYNTHESIS
  a_input_stable_wait: assert property (@(posedge clk) disable iff (!rst_n)
    s_axis_tvalid && !s_axis_tready |=> s_axis_tvalid && $stable({s_axis_tdata,s_axis_tuser}));
  a_output_stable_until_pop: assert property (@(posedge clk) disable iff (!rst_n)
    m_axis_tvalid && !m_axis_tready |=> m_axis_tvalid && $stable({m_axis_tdata,m_axis_tuser}));
`endif
endmodule
