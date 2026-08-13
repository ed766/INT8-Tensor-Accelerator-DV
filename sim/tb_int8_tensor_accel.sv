`timescale 1ns/1ps

module tb_int8_tensor_accel;
  logic clk = 1'b0;
  logic rst_n = 1'b0;
  logic cfg_valid, cfg_ready, cfg_bank;
  logic [2:0] cfg_kind;
  logic [1:0] cfg_output;
  logic [5:0] cfg_index;
  logic [31:0] cfg_data;
  logic cmd_valid, cmd_ready, cmd_bank, cmd_error;
  logic [6:0] cmd_k;
  logic [7:0] cmd_tag;
  logic in_valid, in_ready;
  logic [31:0] in_data;
  logic [7:0] in_tag;
  logic out_valid, out_ready;
  logic [31:0] out_data;
  logic [7:0] out_tag;
  logic [31:0] perf_accepted, perf_completed, perf_input_chunks;
  logic [31:0] perf_output_stalls, perf_bank_swaps;

  always #5 clk <= ~clk;
  int8_tensor_accel dut (.*);
`include "generated_vectors.svh"

  task automatic configure_word(input logic [2:0] kind, input logic bank,
      input logic [1:0] output_sel, input logic [5:0] index_sel, input integer signed value);
    begin
      @(negedge clk); cfg_valid = 1'b1; cfg_kind = kind; cfg_bank = bank;
      cfg_output = output_sel; cfg_index = index_sel; cfg_data = value;
      do @(posedge clk); while (!cfg_ready);
      @(negedge clk); cfg_valid = 1'b0;
    end
  endtask

  integer case_index, output_index, k_index, lane_index, chunk;
  integer latency, failures;
  initial begin
    cfg_valid = 0; cfg_kind = 0; cfg_bank = 0; cfg_output = 0; cfg_index = 0; cfg_data = 0;
    cmd_valid = 0; cmd_bank = 0; cmd_k = 0; cmd_tag = 0;
    in_valid = 0; in_data = 0; in_tag = 0; out_ready = 0; failures = 0;
    repeat (4) @(posedge clk); rst_n = 1;

    for (case_index = 0; case_index < NUM_CASES; case_index++) begin
      for (output_index = 0; output_index < 4; output_index++) begin
        for (k_index = 0; k_index < case_k(case_index); k_index++)
          configure_word(3'd0, 1'(case_bank(case_index)), output_index[1:0], k_index[5:0],
                         case_weight(case_index, output_index, k_index));
        configure_word(3'd1, 1'(case_bank(case_index)), output_index[1:0], 0,
                       case_bias(case_index, output_index));
        configure_word(3'd2, 1'(case_bank(case_index)), output_index[1:0], 0,
                       (case_shift(case_index, output_index) << 16) |
                       (case_multiplier(case_index, output_index) & 32'hffff));
        configure_word(3'd3, 1'(case_bank(case_index)), output_index[1:0], 0,
                       ((case_output_zp(case_index, output_index) & 32'hff) << 24) |
                       ((case_weight_zp(case_index, output_index) & 32'hff) << 16) |
                       ((case_input_zp(case_index) & 32'hff) << 8) |
                       ((case_relu_mask(case_index) >> output_index) & 1));
      end

      @(negedge clk); cmd_valid = 1; cmd_bank = 1'(case_bank(case_index));
      cmd_k = 7'(case_k(case_index)); cmd_tag = 8'(case_tag(case_index));
      do @(posedge clk); while (!cmd_ready);
      @(negedge clk); cmd_valid = 0; latency = 1;
      repeat (case_source_gap(case_index)) begin @(posedge clk); latency = latency + 1; end

      for (chunk = 0; chunk < case_k(case_index)/4; chunk++) begin
        @(negedge clk);
        for (lane_index = 0; lane_index < 4; lane_index++)
          in_data[lane_index*8 +: 8] = 8'(case_input(case_index, chunk*4 + lane_index));
        in_tag = 8'(case_tag(case_index)); in_valid = 1;
        do begin @(posedge clk); latency = latency + 1; end while (!in_ready);
        @(negedge clk); in_valid = 0;
      end
      repeat (case_sink_stall(case_index)) begin @(posedge clk); latency = latency + 1; end
      @(negedge clk); out_ready = 1;
      while (!out_valid) begin @(posedge clk); latency = latency + 1; end
      if (cmd_error || (out_data !== case_expected_word(case_index)) ||
          (out_tag !== 8'(case_tag(case_index)))) begin
        failures = failures + 1;
        $display("RESULT|case=%0d|name=%s|status=FAIL|tag=%0d|expected=%08x|observed=%08x|observed_tag=%0d|latency=%0d|k=%0d|bank=%0d",
          case_index, case_name(case_index), case_tag(case_index), case_expected_word(case_index),
          out_data, out_tag, latency, case_k(case_index), case_bank(case_index));
`ifdef MUTATION_TEST
        $fatal(1, "expected mutation detected");
`endif
      end else begin
        $display("RESULT|case=%0d|name=%s|status=PASS|tag=%0d|expected=%08x|observed=%08x|observed_tag=%0d|latency=%0d|k=%0d|bank=%0d",
          case_index, case_name(case_index), case_tag(case_index), case_expected_word(case_index),
          out_data, out_tag, latency, case_k(case_index), case_bank(case_index));
      end
      @(posedge clk); @(negedge clk); out_ready = 0;
    end
    $display("SUMMARY|cases=%0d|failures=%0d|accepted=%0d|completed=%0d|chunks=%0d|stall_cycles=%0d|bank_swaps=%0d",
      NUM_CASES, failures, perf_accepted, perf_completed, perf_input_chunks,
      perf_output_stalls, perf_bank_swaps);
    if (failures != 0) $fatal(1, "PyTorch/RTL comparison failed");
    $finish;
  end
endmodule
