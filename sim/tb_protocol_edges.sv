`timescale 1ns/1ps

module tb_protocol_edges;
  logic clk=0,rst_n=0;
  logic cfg_valid,cfg_ready,cfg_bank; logic [2:0] cfg_kind; logic [1:0] cfg_output;
  logic [5:0] cfg_index; logic [31:0] cfg_data;
  logic cmd_valid,cmd_ready,cmd_bank,cmd_error; logic [6:0] cmd_k; logic [7:0] cmd_tag;
  logic in_valid,in_ready; logic [31:0] in_data; logic [7:0] in_tag;
  logic out_valid,out_ready; logic [31:0] out_data; logic [7:0] out_tag;
  logic [31:0] perf_accepted,perf_completed,perf_input_chunks,perf_output_stalls,perf_bank_swaps;
  integer checks;
  always #5 clk<=~clk;
  int8_tensor_accel dut(.*);

  task automatic check(input logic condition,input string name);
    if(!condition)$fatal(1,"EDGE_FAIL|%s",name); else begin checks++; $display("EDGE_PASS|%s",name); end
  endtask
  task automatic configure(input logic bank,input logic [1:0] output_sel,
      input logic [5:0] lane,input logic signed [31:0] value);
    begin @(negedge clk);cfg_valid=1;cfg_kind=0;cfg_bank=bank;cfg_output=output_sel;cfg_index=lane;cfg_data=value;
      do @(posedge clk);while(!cfg_ready);@(negedge clk);cfg_valid=0;end
  endtask
  task automatic issue(input logic bank,input logic [6:0] k,input logic [7:0] tag);
    begin @(negedge clk);cmd_valid=1;cmd_bank=bank;cmd_k=k;cmd_tag=tag;
      do @(posedge clk);while(!cmd_ready);@(negedge clk);cmd_valid=0;end
  endtask
  task automatic chunk(input logic [7:0] tag,input logic [31:0] data);
    begin @(negedge clk);in_valid=1;in_tag=tag;in_data=data;
      do @(posedge clk);while(!in_ready);@(negedge clk);in_valid=0;end
  endtask
  integer o,l,i;
  initial begin
    cfg_valid=0;cfg_kind=0;cfg_bank=0;cfg_output=0;cfg_index=0;cfg_data=0;
    cmd_valid=0;cmd_bank=0;cmd_k=0;cmd_tag=0;in_valid=0;in_data=0;in_tag=0;out_ready=0;checks=0;
    repeat(4)@(posedge clk);rst_n=1;
    for(o=0;o<4;o++)for(l=0;l<4;l++)begin
      configure(0,2'(o),6'(l),(o==l)?32'sd1:32'sd0);
      configure(1,2'(o),6'(l),(o==l)?32'sd1:32'sd0);
    end

    @(negedge clk);cfg_valid=1;cfg_kind=3'd7;cfg_bank=0;cfg_output=0;cfg_index=0;cfg_data=32'hdeadbeef;
    @(posedge clk);@(negedge clk);cfg_valid=0;
    check(dut.weights[0][0][0]==8'sd1,"reserved_config_kind_has_no_effect");

    issue(0,6,1); check(cmd_error,"illegal_k_reports_error");
    check(perf_accepted==0,"illegal_k_not_accepted");
    issue(0,8,2);
    @(negedge clk);cfg_valid=1;cfg_bank=0;cfg_kind=0;cfg_output=0;cfg_index=0;cfg_data=7;
    #1;check(!cfg_ready,"active_bank_write_blocked");
    cfg_bank=1;#1;check(cfg_ready,"inactive_bank_write_allowed");@(posedge clk);@(negedge clk);cfg_valid=0;
    chunk(2,32'h04030201);chunk(2,32'h08070605);out_ready=1;@(posedge clk);@(negedge clk);out_ready=0;

    for(i=0;i<4;i++)begin issue(0,4,8'(10+i));chunk(8'(10+i),{4{8'(10+i)}});end
    check(dut.fifo_count==4,"result_fifo_reaches_full");
    issue(0,4,20);@(negedge clk);in_valid=1;in_tag=20;in_data=32'h14141414;
    check(!in_ready,"final_chunk_stalls_on_full_fifo");
    out_ready=1;@(posedge clk);@(negedge clk);check(in_ready,"final_chunk_unblocks_after_pop");
    @(posedge clk);@(negedge clk);in_valid=0;
    while(out_valid)begin check(!$isunknown({out_data,out_tag}),"drained_result_is_known");@(posedge clk);end
    @(negedge clk);out_ready=0;

    issue(1,8,30);check(perf_bank_swaps>=1,"bank_swap_counted");
    chunk(30,32'h01020304);rst_n=0;repeat(2)@(posedge clk);rst_n=1;@(posedge clk);
    check(!dut.command_active && dut.fifo_count==0,"reset_aborts_command_without_ghost_result");
    check({perf_accepted,perf_completed,perf_input_chunks,perf_output_stalls,perf_bank_swaps}=='0,
          "reset_clears_performance_state");
    $display("EDGE_SUMMARY|status=PASS|checks=%0d",checks);$finish;
  end
endmodule
