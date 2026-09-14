`timescale 1ns/1ps
module tb_protected_descriptor_guard;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic submit_valid,submit_ready,submit_accepted,submit_rejected;
  logic[31:0]submit_input_iova,submit_output_iova;logic[15:0]submit_input_stride,submit_output_stride;
  logic[6:0]submit_k,submit_batch;logic[7:0]submit_tag,submit_asid,submit_bank_generation;logic submit_bank;logic[3:0]submit_qos;logic[1:0][7:0]bank_generation=16'h0207;
  logic xlate_req_valid,xlate_req_ready=0,xlate_req_write,xlate_rsp_valid=0,xlate_rsp_ready;logic[31:0]xlate_req_iova,xlate_rsp_paddr=0;logic[7:0]xlate_req_asid;logic[1:0]xlate_rsp_fault=0;
  logic mem_req_valid,mem_req_ready=0,mem_req_write,mem_rsp_valid=0,mem_rsp_ready;logic[31:0]mem_req_addr,mem_req_wdata,mem_rsp_rdata=0;logic[3:0]mem_req_wstrb,mem_req_qos;logic mem_rsp_error=0;
  logic accel_cmd_valid,accel_cmd_ready=0,accel_cmd_bank;logic[6:0]accel_cmd_k;logic[7:0]accel_cmd_tag;logic accel_in_valid,accel_in_ready=0,accel_out_valid=0,accel_out_ready;logic[31:0]accel_in_data,accel_out_data=0;logic[7:0]accel_in_tag,accel_out_tag=0;
  logic completion_valid,completion_ready=0,irq,busy;logic[7:0]completion_tag,completion_asid;logic[3:0]completion_status;logic[31:0]completion_fault_iova;logic[2:0]completion_fault_stage,submit_occupancy,completion_occupancy;logic[6:0]completion_vectors_done;
  int failures=0,checks=0;protected_offload_dma dut(.*);
  task automatic defaults;begin submit_input_iova=32'h80001000;submit_output_iova=32'h80004000;submit_input_stride=64;submit_output_stride=4;submit_k=16;submit_batch=1;submit_tag=8'h40;submit_asid=1;submit_bank=0;submit_bank_generation=7;submit_qos=0;end endtask
  task automatic reject_case;begin @(negedge clk);submit_valid=1;@(posedge clk);@(negedge clk);submit_valid=0;checks++;if(!submit_rejected||submit_accepted)failures++;end endtask
  initial begin
    submit_valid=0;defaults();repeat(4)@(posedge clk);rst_n=1;
    submit_k=12;reject_case();defaults();submit_batch=0;reject_case();defaults();submit_input_iova[0]=1;reject_case();
    defaults();submit_output_iova[1]=1;reject_case();defaults();submit_input_stride=8;reject_case();
    defaults();submit_bank_generation=6;reject_case();defaults();submit_output_iova=32'h80001008;reject_case();
    defaults();submit_input_iova=32'hfffffff0;submit_input_stride=64;submit_batch=2;reject_case();
    defaults();submit_output_iova=32'hfffffffc;submit_output_stride=4;submit_batch=2;reject_case();
    defaults();@(negedge clk);submit_valid=1;@(posedge clk);@(negedge clk);submit_valid=0;checks++;if(!submit_accepted||submit_rejected)failures++;
    if(failures!=0)$fatal(1,"PROTECTED_DESCRIPTOR_GUARD_FAIL failures=%0d",failures);
    $display("PROTECTED_DESCRIPTOR_GUARD_PASS|checks=%0d|geometry=5|generation=1|overlap=1|overflow=2|valid=1",checks);$finish;
  end
endmodule
