`timescale 1ns/1ps

module tb_int8_tensor_accel;
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

`include "generated_vectors.svh"

  task automatic configure_word(
    input logic [1:0] kind,
    input logic [1:0] output_sel,
    input logic [1:0] lane_sel,
    input integer signed value
  );
    begin
      @(negedge clk);
      cfg_valid = 1'b1;
      cfg_kind = kind;
      cfg_output = output_sel;
      cfg_lane = lane_sel;
      cfg_data = value;
      do @(posedge clk); while (!cfg_ready);
      @(negedge clk);
      cfg_valid = 1'b0;
    end
  endtask

  integer case_index;
  integer output_index;
  integer lane_index;
  integer latency;
  integer failures;
  initial begin
    cfg_valid = 1'b0;
    cfg_kind = '0;
    cfg_output = '0;
    cfg_lane = '0;
    cfg_data = '0;
    in_valid = 1'b0;
    in_data = '0;
    in_tag = '0;
    out_ready = 1'b0;
    failures = 0;
    repeat (4) @(posedge clk);
    rst_n = 1'b1;

    for (case_index = 0; case_index < NUM_CASES; case_index++) begin
      for (output_index = 0; output_index < 4; output_index++) begin
        for (lane_index = 0; lane_index < 4; lane_index++)
          configure_word(2'd0, output_index[1:0], lane_index[1:0], case_field(case_index, F_WEIGHT_BASE + output_index*4 + lane_index));
        configure_word(2'd1, output_index[1:0], 2'd0, case_field(case_index, F_BIAS_BASE + output_index));
        configure_word(2'd2, output_index[1:0], 2'd0,
          (case_field(case_index, F_SHIFT_BASE + output_index) << 16) |
          (case_field(case_index, F_MULT_BASE + output_index) & 32'h0000ffff));
        configure_word(2'd3, output_index[1:0], 2'd0, (case_field(case_index, F_RELU_MASK) >> output_index) & 1);
      end

      repeat (case_field(case_index, F_SOURCE_GAP)) @(posedge clk);
      @(negedge clk);
      in_data = case_field(case_index, F_INPUT_WORD);
      in_tag = 8'(case_field(case_index, F_TAG));
      in_valid = 1'b1;
      do @(posedge clk); while (!in_ready);
      @(negedge clk);
      in_valid = 1'b0;
      out_ready = 1'b0;
      latency = 1;
      repeat (case_field(case_index, F_SINK_STALL)) begin
        @(posedge clk);
        latency = latency + 1;
      end
      @(negedge clk);
      out_ready = 1'b1;
      while (!out_valid) begin
        @(posedge clk);
        latency = latency + 1;
      end
      if ((out_data !== case_field(case_index, F_EXPECTED_WORD)) ||
          (out_tag !== 8'(case_field(case_index, F_TAG)))) begin
        failures = failures + 1;
        $display("RESULT|case=%0d|name=%s|status=FAIL|tag=%0d|expected=%08x|observed=%08x|observed_tag=%0d|latency=%0d",
          case_index, case_name(case_index), case_field(case_index, F_TAG),
          case_field(case_index, F_EXPECTED_WORD), out_data, out_tag, latency);
      end else begin
        $display("RESULT|case=%0d|name=%s|status=PASS|tag=%0d|expected=%08x|observed=%08x|observed_tag=%0d|latency=%0d",
          case_index, case_name(case_index), case_field(case_index, F_TAG),
          case_field(case_index, F_EXPECTED_WORD), out_data, out_tag, latency);
      end
      @(posedge clk);
      @(negedge clk);
      out_ready = 1'b0;
    end

    $display("SUMMARY|cases=%0d|failures=%0d|accepted=%0d|completed=%0d|stall_cycles=%0d",
      NUM_CASES, failures, perf_accepted, perf_completed, perf_output_stalls);
    if (failures != 0)
      $fatal(1, "PyTorch/RTL comparison failed");
    $finish;
  end
endmodule
