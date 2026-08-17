`timescale 1ns/1ps
module tb_record_decoder;
  logic clk=0,rst_n=0;always #5 clk<=~clk;
  logic record_valid,record_ready;logic[63:0]record_data;
  logic cfg_valid,cfg_ready;logic[2:0]cfg_kind;logic cfg_bank;logic[1:0]cfg_output;logic[5:0]cfg_index;logic[31:0]cfg_data;
  logic cmd_valid,cmd_ready,cmd_bank;logic[6:0]cmd_k;logic[7:0]cmd_tag;
  logic in_valid,in_ready;logic[31:0]in_data;logic[7:0]in_tag;
  logic expect_valid,expect_ready;logic[31:0]expect_data;logic[7:0]expect_tag,expect_stall;logic done,malformed;
  integer checks=0,failures=0;
  int8_portable_record_decoder dut(.*);
  task automatic send(input logic[63:0]word,input string name);
    @(negedge clk);record_valid=1;record_data=word;
    if(name=="expectation"&&expect_stall!=3)begin failures++;$display("DECODER_CHECK|name=stall_carry|status=FAIL");end
    do @(posedge clk);while(!record_ready);
    checks++;
    if((name=="malformed"&&!malformed)||(name=="end"&&!done))begin
      failures++;$display("DECODER_CHECK|name=%s|status=FAIL",name);
    end else $display("DECODER_CHECK|name=%s|status=PASS",name);
    $display("AXI_COVER|point=decoder_%s",name);@(negedge clk);record_valid=0;
  endtask
  initial begin record_valid=0;record_data=0;cfg_ready=1;cmd_ready=1;in_ready=1;expect_ready=1;repeat(3)@(posedge clk);rst_n=1;
    send({4'h0,1'b1,3'd3,2'd2,6'd17,32'h89abcdef,16'd0},"config");
    checks++;if(cfg_kind!=3||!cfg_bank||cfg_output!=2||cfg_index!=17||cfg_data!=32'h89abcdef)failures++;
    send({4'h1,1'b1,7'd16,8'h66,44'd0},"command");checks++;if(!cmd_bank||cmd_k!=16||cmd_tag!=8'h66)failures++;
    send({4'h2,4'd0,8'h66,16'd0,32'h04030201},"activation");checks++;if(in_tag!=8'h66||in_data!=32'h04030201)failures++;
    send({4'h4,4'd0,8'd3,48'd0},"stall");send({4'h3,4'd0,8'h66,16'd0,32'h01020304},"expectation");checks++;
    send(64'h9000000000000000,"malformed");send(64'hf000000000000000,"end");
    $display("DECODER_SUMMARY|checks=%0d|failures=%0d",checks,failures);if(failures)$fatal(1,"decoder failed");$finish;
  end
endmodule
