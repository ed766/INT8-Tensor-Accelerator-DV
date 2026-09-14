`timescale 1ns/1ps
module tb_protected_queue;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic submit_valid,submit_ready,submit_accepted,submit_rejected;
  logic[31:0]submit_input_iova=32'h80001000,submit_output_iova=32'h80004000;
  logic[15:0]submit_input_stride=64,submit_output_stride=4;logic[6:0]submit_k=16,submit_batch=1;
  logic[7:0]submit_tag,submit_asid=1,submit_bank_generation=7;logic submit_bank=0;logic[3:0]submit_qos=0;logic[1:0][7:0]bank_generation=16'h0207;
  logic xlate_req_valid,xlate_req_ready=0,xlate_req_write,xlate_rsp_valid=0,xlate_rsp_ready;logic[31:0]xlate_req_iova,xlate_rsp_paddr=0;logic[7:0]xlate_req_asid;logic[1:0]xlate_rsp_fault=0;
  logic mem_req_valid,mem_req_ready=0,mem_req_write,mem_rsp_valid=0,mem_rsp_ready;logic[31:0]mem_req_addr,mem_req_wdata,mem_rsp_rdata=0;logic[3:0]mem_req_wstrb,mem_req_qos;logic mem_rsp_error=0;
  logic accel_cmd_valid,accel_cmd_ready=0,accel_cmd_bank;logic[6:0]accel_cmd_k;logic[7:0]accel_cmd_tag;logic accel_in_valid,accel_in_ready=0,accel_out_valid=0,accel_out_ready;logic[31:0]accel_in_data,accel_out_data=0;logic[7:0]accel_in_tag,accel_out_tag=0;
  logic completion_valid,completion_ready=0,irq,busy;logic[7:0]completion_tag,completion_asid;logic[3:0]completion_status;logic[31:0]completion_fault_iova;logic[2:0]completion_fault_stage,submit_occupancy,completion_occupancy;logic[6:0]completion_vectors_done;
  int failures=0;
  protected_offload_dma dut(.*);

  task automatic push(input logic[7:0]tag);
    begin
      @(negedge clk);submit_tag=tag;submit_valid=1;
      if(!submit_ready)failures++;
      @(posedge clk);@(negedge clk);submit_valid=0;
      if(!submit_accepted)failures++;
    end
  endtask

  initial begin
    submit_valid=0;submit_tag=0;repeat(4)@(posedge clk);rst_n=1;
    push(8'h10);
    // Enqueue tag 0x11 on the exact cycle tag 0x10 leaves the submit FIFO.
    @(negedge clk);submit_tag=8'h11;submit_valid=1;@(posedge clk);@(negedge clk);submit_valid=0;
    if(dut.active.tag!=8'h10||submit_occupancy!=1)failures++;
    push(8'h12);push(8'h13);push(8'h14);
    if(submit_occupancy!=4||submit_ready)failures++;
    @(negedge clk);submit_tag=8'h15;submit_valid=1;repeat(3)@(posedge clk);
    if(submit_accepted||submit_occupancy!=4)failures++;
    @(negedge clk);submit_valid=0;
    if(failures!=0)$fatal(1,"PROTECTED_QUEUE_FAIL failures=%0d",failures);
    $display("PROTECTED_QUEUE_PASS|simultaneous_push_pop=1|full_occupancy=4|backpressure=1|ordering=1");
    $finish;
  end
endmodule
