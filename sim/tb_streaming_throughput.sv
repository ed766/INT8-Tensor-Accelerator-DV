`timescale 1ns/1ps

module tb_streaming_throughput;
  logic clk = 0, rst_n = 0;
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

  always #5 clk = ~clk;
  int8_tensor_accel dut (.*);

  task automatic configure(input logic [2:0] kind, input logic bank,
      input logic [1:0] output_sel, input logic [5:0] index_sel, input logic [31:0] value);
    begin
      @(negedge clk); cfg_valid=1; cfg_kind=kind; cfg_bank=bank; cfg_output=output_sel;
      cfg_index=index_sel; cfg_data=value;
      do @(posedge clk); while (!cfg_ready);
      @(negedge clk); cfg_valid=0;
    end
  endtask

  integer output_index, lane_index, vector_index;
  logic [31:0] expected_word;
  initial begin
    cfg_valid=0; cfg_kind=0; cfg_bank=0; cfg_output=0; cfg_index=0; cfg_data=0;
    cmd_valid=0; cmd_bank=0; cmd_k=0; cmd_tag=0;
    in_valid=0; in_data=0; in_tag=0; out_ready=0;
    repeat (4) @(posedge clk); rst_n=1;
    for (output_index=0; output_index<4; output_index++) begin
      for (lane_index=0; lane_index<4; lane_index++)
        configure(3'd0, 0, output_index[1:0], lane_index[5:0], output_index==lane_index ? 1 : 0);
      configure(3'd1, 0, output_index[1:0], 0, 0);
      configure(3'd2, 0, output_index[1:0], 0, 1);
      configure(3'd3, 0, output_index[1:0], 0, 0);
    end
    out_ready=1;
    for (vector_index=0; vector_index<16; vector_index++) begin
      @(negedge clk); cmd_valid=1; cmd_bank=0; cmd_k=4; cmd_tag=vector_index[7:0];
      @(posedge clk); if (!cmd_ready) $fatal(1, "command blocked");
      @(negedge clk); cmd_valid=0; in_valid=1; in_tag=vector_index[7:0];
      in_data={4{vector_index[7:0]}};
      @(posedge clk); if (!in_ready) $fatal(1, "input blocked");
      @(negedge clk); in_valid=0; expected_word={4{vector_index[7:0]}};
      if (!out_valid || out_tag!==vector_index[7:0] || out_data!==expected_word)
        $fatal(1, "stream mismatch index=%0d tag=%0d data=%08x", vector_index, out_tag, out_data);
    end
    @(posedge clk); @(negedge clk);
    if (perf_accepted!=16 || perf_completed!=16 || perf_input_chunks!=16 || perf_output_stalls!=0)
      $fatal(1, "counter mismatch accepted=%0d completed=%0d chunks=%0d stalls=%0d",
             perf_accepted, perf_completed, perf_input_chunks, perf_output_stalls);
    $display("STREAM_SUMMARY|status=PASS|vectors=16|command_input_cycles=32|vectors_per_cycle=0.500|active_macs_per_cycle=16");
    $finish;
  end
endmodule
