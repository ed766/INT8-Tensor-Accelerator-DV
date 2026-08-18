`timescale 1ns/1ps

module tb_fx_graphs;
  localparam integer MAX_K = 64;
  localparam integer MAX_LAYERS = 3;
  logic clk=0, rst_n=0;
  logic cfg_valid, cfg_ready, cfg_bank;
  logic [2:0] cfg_kind; logic [1:0] cfg_output; logic [5:0] cfg_index; logic [31:0] cfg_data;
  logic cmd_valid, cmd_ready, cmd_bank, cmd_error; logic [6:0] cmd_k; logic [7:0] cmd_tag;
  logic in_valid, in_ready; logic [31:0] in_data; logic [7:0] in_tag;
  logic out_valid, out_ready; logic [31:0] out_data; logic [7:0] out_tag;
  logic [31:0] perf_accepted, perf_completed, perf_input_chunks, perf_output_stalls, perf_bank_swaps;
  always #5 clk=~clk;
  int8_tensor_accel dut (.*);
`include "generated_fx_graphs.svh"

  task automatic configure(input logic [2:0] kind, input logic bank, input integer output_sel,
      input integer index_sel, input integer signed value);
    begin
      @(negedge clk); cfg_valid=1; cfg_kind=kind; cfg_bank=bank; cfg_output=output_sel[1:0];
      cfg_index=index_sel[5:0]; cfg_data=value;
      do @(posedge clk); while (!cfg_ready);
      @(negedge clk); cfg_valid=0;
    end
  endtask

  task automatic execute(input logic bank, input integer k, input logic [7:0] tag,
      input logic [8*MAX_K-1:0] packed_input, output logic [31:0] result);
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

  integer graph_index, layer_index, sample_index, output_index, k_index;
  integer failures, words_checked, commands;
  logic [8*MAX_K-1:0] layer_input;
  logic [31:0] result;
  logic bank;
  initial begin
    cfg_valid=0; cfg_kind=0; cfg_bank=0; cfg_output=0; cfg_index=0; cfg_data=0;
    cmd_valid=0; cmd_bank=0; cmd_k=0; cmd_tag=0; in_valid=0; in_data=0; in_tag=0; out_ready=0;
    failures=0; words_checked=0; commands=0;
    repeat(4) @(posedge clk); rst_n=1;
    for (graph_index=0; graph_index<FX_GRAPH_COUNT; graph_index++) begin
      for (sample_index=0; sample_index<FX_SAMPLES; sample_index++) begin
        layer_input='0;
        for (k_index=0; k_index<fx_input_k(graph_index); k_index++)
          layer_input[k_index*8 +: 8]=fx_input((graph_index*FX_SAMPLES+sample_index)*MAX_K+k_index);
        for (layer_index=0; layer_index<fx_layer_count(graph_index); layer_index++) begin
          bank=layer_index[0];
          for (output_index=0; output_index<4; output_index++) begin
            for (k_index=0; k_index<fx_layer_k(graph_index*MAX_LAYERS+layer_index); k_index++)
              configure(3'd0,bank,output_index,k_index,
                fx_weight((((graph_index*MAX_LAYERS+layer_index)*4+output_index)*MAX_K)+k_index));
            configure(3'd1,bank,output_index,0,fx_bias((graph_index*MAX_LAYERS+layer_index)*4+output_index));
            configure(3'd2,bank,output_index,0,(fx_layer_shift(graph_index*MAX_LAYERS+layer_index)<<16)|1);
            configure(3'd3,bank,output_index,0,fx_layer_relu(graph_index*MAX_LAYERS+layer_index));
          end
          execute(bank,fx_layer_k(graph_index*MAX_LAYERS+layer_index),
                  8'(graph_index*8+sample_index),layer_input,result);
          commands++;
          for (output_index=0; output_index<4; output_index++) begin
            words_checked++;
            if ($signed(result[output_index*8 +: 8]) !=
                fx_expected((((graph_index*FX_SAMPLES+sample_index)*MAX_LAYERS+layer_index)*4)+output_index))
              failures++;
          end
          layer_input='0; layer_input[31:0]=result;
        end
      end
    end
    $display("FX_RTL_SUMMARY|status=%s|graphs=%0d|samples=%0d|commands=%0d|words_checked=%0d|failures=%0d|bank_swaps=%0d",
             failures==0 ? "PASS" : "FAIL",FX_GRAPH_COUNT,FX_GRAPH_COUNT*FX_SAMPLES,commands,words_checked,failures,perf_bank_swaps);
    if (failures) $fatal(1,"FX graph RTL comparison failed");
    $finish;
  end
endmodule
