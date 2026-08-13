`timescale 1ns/1ps

module tb_pytorch_mlp;
  logic clk=0, rst_n=0;
  logic cfg_valid, cfg_ready, cfg_bank;
  logic [2:0] cfg_kind; logic [1:0] cfg_output; logic [5:0] cfg_index; logic [31:0] cfg_data;
  logic cmd_valid, cmd_ready, cmd_bank, cmd_error; logic [6:0] cmd_k; logic [7:0] cmd_tag;
  logic in_valid, in_ready; logic [31:0] in_data; logic [7:0] in_tag;
  logic out_valid, out_ready; logic [31:0] out_data; logic [7:0] out_tag;
  logic [31:0] perf_accepted, perf_completed, perf_input_chunks, perf_output_stalls, perf_bank_swaps;
  always #5 clk=~clk;
  int8_tensor_accel dut (.*);
`include "generated_mlp.svh"

  task automatic configure(input logic [2:0] kind, input logic bank, input integer output_sel,
      input integer index_sel, input integer signed value);
    begin
      @(negedge clk); cfg_valid=1; cfg_kind=kind; cfg_bank=bank; cfg_output=output_sel[1:0];
      cfg_index=index_sel[5:0]; cfg_data=value;
      do @(posedge clk); while (!cfg_ready);
      @(negedge clk); cfg_valid=0;
    end
  endtask

  task automatic execute_layer(input logic bank, input integer k, input logic [7:0] tag,
      input logic [8*64-1:0] packed_input, output logic [31:0] result);
    integer chunk, lane;
    begin
      @(negedge clk); cmd_valid=1; cmd_bank=bank; cmd_k=k[6:0]; cmd_tag=tag;
      do @(posedge clk); while (!cmd_ready);
      @(negedge clk); cmd_valid=0;
      for (chunk=0; chunk<k/4; chunk++) begin
        for (lane=0; lane<4; lane++) in_data[lane*8 +: 8]=packed_input[(chunk*4+lane)*8 +: 8];
        in_tag=tag; in_valid=1;
        do @(posedge clk); while (!in_ready);
        @(negedge clk); in_valid=0;
      end
      out_ready=1;
      while (!out_valid) @(posedge clk);
      result=out_data;
      @(posedge clk); @(negedge clk); out_ready=0;
    end
  endtask

  integer o, k, sample, lane, failures;
  logic [8*64-1:0] layer_input;
  logic [31:0] hidden_word, logits_word;
  initial begin
    cfg_valid=0; cfg_kind=0; cfg_bank=0; cfg_output=0; cfg_index=0; cfg_data=0;
    cmd_valid=0; cmd_bank=0; cmd_k=0; cmd_tag=0; in_valid=0; in_data=0; in_tag=0; out_ready=0; failures=0;
    repeat(4) @(posedge clk); rst_n=1;
    for (o=0;o<4;o++) begin
      for (k=0;k<16;k++) configure(3'd0,0,o,k,mlp_w1(o*16+k));
      configure(3'd1,0,o,0,mlp_b1(o)); configure(3'd2,0,o,0,(MLP_SHIFT1<<16)|1);
      configure(3'd3,0,o,0,1);
      for (k=0;k<4;k++) configure(3'd0,1,o,k,mlp_w2(o*4+k));
      configure(3'd1,1,o,0,mlp_b2(o)); configure(3'd2,1,o,0,(MLP_SHIFT2<<16)|1);
      configure(3'd3,1,o,0,0);
    end
    for (sample=0;sample<MLP_SAMPLES;sample++) begin
      layer_input='0;
      for (k=0;k<16;k++) layer_input[k*8 +: 8]=mlp_input(sample*16+k);
      execute_layer(0,16,sample[7:0],layer_input,hidden_word);
      for (lane=0;lane<4;lane++)
        if ($signed(hidden_word[lane*8 +: 8]) != mlp_expected_hidden(sample*4+lane)) failures++;
      layer_input='0; layer_input[31:0]=hidden_word;
      execute_layer(1,4,sample[7:0],layer_input,logits_word);
      for (lane=0;lane<4;lane++)
        if ($signed(logits_word[lane*8 +: 8]) != mlp_expected_logits(sample*4+lane)) failures++;
    end
    $display("MLP_SUMMARY|status=%s|samples=16|intermediate_words=64|final_words=64|failures=%0d|bank_swaps=%0d",
             failures==0 ? "PASS" : "FAIL", failures, perf_bank_swaps);
    if (failures) $fatal(1,"two-layer PyTorch/RTL mismatch");
    $finish;
  end
endmodule
