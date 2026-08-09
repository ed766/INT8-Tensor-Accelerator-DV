`timescale 1ns/1ps

module tb_streaming_throughput;
  logic clk = 1'b0;
  logic rst_n = 1'b0;
  logic cfg_valid;
  logic cfg_ready;
  logic [1:0] cfg_kind;
  logic [1:0] cfg_output;
  logic [1:0] cfg_lane;
  logic [31:0] cfg_data;
  logic in_valid;
  logic in_ready;
  logic [31:0] in_data;
  logic [7:0] in_tag;
  logic out_valid;
  logic out_ready;
  logic [31:0] out_data;
  logic [7:0] out_tag;
  logic [31:0] perf_accepted;
  logic [31:0] perf_completed;
  logic [31:0] perf_output_stalls;

  always #5 clk <= ~clk;
  int8_tensor_accel dut (.*);

  task automatic configure(input logic [1:0] kind, input logic [1:0] output_sel,
                           input logic [1:0] lane_sel, input logic [31:0] value);
    begin
      @(negedge clk);
      cfg_valid = 1'b1;
      cfg_kind = kind;
      cfg_output = output_sel;
      cfg_lane = lane_sel;
      cfg_data = value;
      @(posedge clk);
      if (!cfg_ready) $fatal(1, "configuration unexpectedly blocked");
      @(negedge clk);
      cfg_valid = 1'b0;
    end
  endtask

  integer output_index;
  integer lane_index;
  integer vector_index;
  logic [31:0] expected_word;
  initial begin
    cfg_valid = 0; cfg_kind = 0; cfg_output = 0; cfg_lane = 0; cfg_data = 0;
    in_valid = 0; in_data = 0; in_tag = 0; out_ready = 0;
    repeat (4) @(posedge clk);
    rst_n = 1;
    for (output_index = 0; output_index < 4; output_index++) begin
      for (lane_index = 0; lane_index < 4; lane_index++)
        configure(2'd0, output_index[1:0], lane_index[1:0], output_index == lane_index ? 32'd1 : 32'd0);
      configure(2'd1, output_index[1:0], 2'd0, 32'd0);
      configure(2'd2, output_index[1:0], 2'd0, 32'd1);
      configure(2'd3, output_index[1:0], 2'd0, 32'd0);
    end
    out_ready = 1'b1;
    @(negedge clk);
    for (vector_index = 0; vector_index < 16; vector_index++) begin
      in_valid = 1'b1;
      in_tag = vector_index[7:0];
      in_data = {4{vector_index[7:0]}};
      @(posedge clk);
      if (!in_ready) $fatal(1, "streaming input was not accepted");
      @(negedge clk);
      expected_word = {4{vector_index[7:0]}};
      if (!out_valid || out_tag !== vector_index[7:0] || out_data !== expected_word)
        $fatal(1, "stream mismatch index=%0d tag=%0d data=%08x", vector_index, out_tag, out_data);
    end
    in_valid = 1'b0;
    @(posedge clk);
    @(negedge clk);
    if (perf_accepted != 16 || perf_completed != 16 || perf_output_stalls != 0)
      $fatal(1, "counter mismatch accepted=%0d completed=%0d stalls=%0d",
             perf_accepted, perf_completed, perf_output_stalls);
    $display("STREAM_SUMMARY|status=PASS|vectors=16|acceptance_cycles=16|vectors_per_cycle=1.000");
    $finish;
  end
endmodule
