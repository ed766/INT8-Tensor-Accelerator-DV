`timescale 1ns/1ps
module tb_dma_peer_holes;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic submit_valid=0,submit_ready,submit_accepted,submit_rejected;
  logic [31:0] submit_input_iova=32'h80001000,submit_output_iova=32'h80004000;
  logic [15:0] submit_input_stride=4,submit_output_stride=4;
  logic [6:0] submit_k=4,submit_batch=1;
  logic [7:0] submit_tag=0,submit_asid=1,submit_bank_generation=7;
  logic submit_bank=0,block_submissions=0;logic [3:0] submit_qos=8;
  logic [1:0][7:0] bank_generation=16'h0207;logic [1:0] bank_referenced;
  logic [4:0] owned_valid;logic [4:0][31:0] owned_start,owned_end,owned_input_start,owned_input_end,owned_output_start,owned_output_end;
  logic xlate_req_valid,xlate_req_ready=0,xlate_req_write,xlate_rsp_valid=0,xlate_rsp_ready;
  logic [31:0] xlate_req_iova,xlate_rsp_paddr=0;logic [7:0] xlate_req_asid;logic [1:0] xlate_rsp_fault=0;
  logic mem_req_valid,mem_req_ready=0,mem_req_write,mem_rsp_valid=0,mem_rsp_ready;
  logic [31:0] mem_req_addr,mem_req_wdata,mem_rsp_rdata=32'h01020304;logic [3:0] mem_req_wstrb,mem_req_qos;logic mem_rsp_error=0;
  logic accel_cmd_valid,accel_cmd_ready=0,accel_cmd_bank;logic [6:0] accel_cmd_k;logic [7:0] accel_cmd_tag;
  logic accel_in_valid,accel_in_ready=0,accel_out_valid=0,accel_out_ready;
  logic [31:0] accel_in_data,accel_out_data=32'h11223344;logic [7:0] accel_in_tag,accel_out_tag=0;
  logic completion_valid,completion_ready=0,completion_published,irq,busy;
  logic [7:0] completion_tag,completion_asid,completion_publish_tag,completion_publish_asid;
  logic [3:0] completion_status,completion_publish_status;
  logic [31:0] completion_fault_iova;logic [2:0] completion_fault_stage,completion_publish_fault_stage,submit_occupancy,completion_occupancy;
  logic [6:0] completion_vectors_done,completion_publish_vectors_done;
  int writes=0;int seed=1;int jobs=0;int checks=0;
  protected_offload_dma dut(.*);
  task automatic stall(input int phase);
    int delay;
    seed=(seed*1664525)+1013904223;delay=int'((unsigned'(seed)>>16)%7)+1;
    repeat(delay)begin
      @(negedge clk);
      case(phase)
        0,5:if(!xlate_req_valid||xlate_req_write!=(phase==5)||xlate_req_asid!=1)$fatal(1,"translation request hold");
        1,6:if(!mem_req_valid||mem_req_write!=(phase==6))$fatal(1,"memory request hold");
        2:if(!accel_cmd_valid||accel_cmd_tag!=submit_tag||accel_cmd_k!=4)$fatal(1,"command hold");
        3:if(!accel_in_valid||accel_in_data!=32'h01020304||accel_in_tag!=submit_tag)$fatal(1,"stream hold");
        4:if(!busy||!accel_out_ready)$fatal(1,"result delay state");
        default:$fatal(1,"unknown phase");
      endcase
      checks++;
    end
    $display("HOLE_EVT|module=protected_offload_dma|job=%0d|phase=%0d|waits=%0d",jobs,phase,delay);
  endtask
  task automatic translate(input logic write_access,input int vector_number);
    wait(xlate_req_valid);stall(write_access?5:0);
    if(xlate_req_iova!=(write_access?submit_output_iova:submit_input_iova)+32'(vector_number*4))$fatal(1,"translation vector address");
    xlate_req_ready=1;@(negedge clk);xlate_req_ready=0;
    xlate_rsp_valid=1;xlate_rsp_paddr=(write_access?32'h10004000:32'h10001000)+32'(vector_number*4);
    @(negedge clk);xlate_rsp_valid=0;
  endtask
  task automatic memory_access(input logic write_access,input int vector_number);
    wait(mem_req_valid);stall(write_access?6:1);
    if(mem_req_addr!=(write_access?32'h10004000:32'h10001000)+32'(vector_number*4)||mem_req_qos!=8)$fatal(1,"memory address/QoS");
    if(write_access)begin
      if(mem_req_wdata!=accel_out_data||mem_req_wstrb!=4'hf)$fatal(1,"output payload");writes++;
    end
    mem_req_ready=1;@(negedge clk);mem_req_ready=0;mem_rsp_valid=1;
    @(negedge clk);mem_rsp_valid=0;
  endtask
  task automatic job(input int error_vector,input int batch_size);
    int before_writes;
    before_writes=writes;jobs++;
    @(negedge clk);submit_tag=8'(jobs);submit_batch=7'(batch_size);submit_valid=1;
    if(!submit_ready)$fatal(1,"submit not ready");
    @(negedge clk);submit_valid=0;if(!submit_accepted)$fatal(1,"submit not accepted");
    for(int v=0;v<batch_size;v++)begin
      translate(0,v);memory_access(0,v);
      wait(accel_cmd_valid);stall(2);accel_cmd_ready=1;@(negedge clk);accel_cmd_ready=0;
      wait(accel_in_valid);stall(3);accel_in_ready=1;@(negedge clk);accel_in_ready=0;
      stall(4);accel_out_tag=submit_tag^((v==error_vector)?8'h1:8'h0);accel_out_valid=1;
      @(negedge clk);accel_out_valid=0;
      if(v==error_vector)break;
      translate(1,v);memory_access(1,v);
    end
    wait(completion_valid);#1;
    if(completion_tag!=submit_tag||completion_asid!=1||completion_status!=(error_vector>=0?6:0)||completion_vectors_done!=7'(error_vector>=0?error_vector:batch_size))$fatal(1,"completion metadata");
    if(writes-before_writes!=(error_vector>=0?error_vector:batch_size))$fatal(1,"wrong-tag committed prefix");
    if(error_vector>=0&&(completion_fault_stage!=5||completion_fault_iova!=submit_output_iova+32'(error_vector*4)))$fatal(1,"wrong-tag fault metadata");
    repeat(3)begin @(negedge clk);if(!completion_valid||!irq||completion_tag!=submit_tag)$fatal(1,"completion hold");end
    completion_ready=1;@(negedge clk);completion_ready=0;
    if(completion_valid||irq)$fatal(1,"duplicate completion");
    $display("DMA_PEER_JOB_PASS|job=%0d|error_vector=%0d|batch=%0d|writes=%0d",jobs,error_vector,batch_size,writes-before_writes);
  endtask
  initial begin
    if($value$plusargs("SEED=%d",seed))begin end
    repeat(3)@(negedge clk);rst_n=1;
    for(int i=0;i<16;i++)job(i%4==3?0:-1,1);
    job(1,3);job(2,3);job(-1,3);
    if(writes!=18)$fatal(1,"final committed write count");
    $display("DMA_PEER_HOLES_PASS|jobs=%0d|wrong_tag_cases=6|successful_writes=%0d|hold_checks=%0d",jobs,writes,checks);$finish;
  end
  initial begin repeat(10000)@(posedge clk);$fatal(1,"DMA peer timeout");end
endmodule
