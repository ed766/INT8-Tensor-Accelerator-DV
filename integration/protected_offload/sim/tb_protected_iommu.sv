`timescale 1ns/1ps
module tb_protected_iommu;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic req_valid,req_ready,req_write,req_user,rsp_valid,rsp_ready,rsp_tlb_hit;
  logic[31:0]root_pt_addr,req_iova,rsp_paddr;logic[7:0]req_asid;logic[1:0]rsp_fault;
  logic inv_valid,inv_all;logic[7:0]inv_asid;logic ptw_req_valid,ptw_req_ready,ptw_rsp_valid,ptw_rsp_ready,ptw_rsp_error;
  logic[31:0]ptw_req_addr,ptw_rsp_data,perf_tlb_hits,perf_tlb_misses,perf_walk_reads,perf_faults;
  logic deny_page;int failures=0;

  dma_iommu #(.TLB_ENTRIES(4)) dut(.*);

  // Two-level Sv32-inspired page table: 0x8000_1000 -> 0x1000_1000.
  always_ff @(posedge clk) begin
    ptw_rsp_valid<=0;ptw_rsp_error<=0;
    if(ptw_req_valid&&ptw_req_ready) begin
      ptw_rsp_valid<=1;
      if(ptw_req_addr==32'h3000_0800) ptw_rsp_data<=32'h0c00_0401;
      else if(ptw_req_addr==32'h3000_1004)
        ptw_rsp_data<=deny_page ? 32'h0400_0443 : 32'h0400_04cf;
      else begin ptw_rsp_data<=0;ptw_rsp_error<=1;end
    end
  end

  task automatic translate(input logic[7:0]asid,input logic wr,input logic[1:0]fault,
    input logic hit,input logic[31:0]paddr);
    begin
      @(negedge clk);req_valid=1;req_asid=asid;req_write=wr;req_iova=32'h8000_1000;
      do @(posedge clk);while(!req_ready);@(negedge clk);req_valid=0;
      wait(rsp_valid);if(rsp_fault!==fault||rsp_tlb_hit!==hit||(fault==0&&rsp_paddr!==paddr))failures++;
      @(negedge clk);rsp_ready=1;@(posedge clk);@(negedge clk);rsp_ready=0;
    end
  endtask

  initial begin
    root_pt_addr=32'h3000_0000;req_valid=0;req_iova=0;req_asid=0;req_write=0;req_user=0;rsp_ready=0;
    inv_valid=0;inv_all=0;inv_asid=0;ptw_req_ready=1;ptw_rsp_valid=0;ptw_rsp_data=0;ptw_rsp_error=0;deny_page=0;
    repeat(4)@(posedge clk);rst_n=1;
    translate(8'h11,0,0,0,32'h1000_1000);
    translate(8'h11,0,0,1,32'h1000_1000);
    translate(8'h22,0,0,0,32'h1000_1000);
    @(negedge clk);inv_valid=1;inv_asid=8'h11;@(posedge clk);@(negedge clk);inv_valid=0;
    translate(8'h11,0,0,0,32'h1000_1000);
    @(negedge clk);inv_valid=1;inv_all=1;@(posedge clk);@(negedge clk);inv_valid=0;inv_all=0;deny_page=1;
    translate(8'h11,1,2,0,0);
    if(perf_tlb_hits!=1||perf_tlb_misses!=4||perf_faults!=1)failures++;
    if(failures!=0)$fatal(1,"PROTECTED_IOMMU_FAIL failures=%0d",failures);
    $display("PROTECTED_IOMMU_PASS|cases=5|hits=%0d|misses=%0d|faults=%0d|invalidations=2",
      perf_tlb_hits,perf_tlb_misses,perf_faults);
    $finish;
  end
endmodule
