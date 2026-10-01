`timescale 1ns/1ps
module tb_protected_dma_axi_adapter;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic req_valid,req_ready,req_write,rsp_valid,rsp_ready,rsp_error;
  logic[31:0]req_addr,req_wdata,rsp_rdata;logic[3:0]req_wstrb,req_qos;
  logic awvalid,awready,wvalid,wready,bvalid,bready,arvalid,arready,rvalid,rready,wlast,rlast;
  logic[3:0]awid,bid,arid,rid;logic[31:0]awaddr,araddr;logic[7:0]awlen,arlen;
  logic[2:0]awsize,arlsize,awprot,arprot;logic[1:0]awburst,arburst,bresp,rresp;
  logic[3:0]awqos,arqos;logic[63:0]wdata,rdata;logic[7:0]wstrb;
  int failures=0;

  protected_dma_axi_adapter dut(.*,.arsize(arlsize));

  task automatic issue(input logic wr,input logic[31:0]addr,input logic[31:0]data,
    input logic[3:0]strb,input logic expect_error,input logic[31:0]expect_data);
    begin
      @(negedge clk);req_valid=1;req_write=wr;req_addr=addr;req_wdata=data;req_wstrb=strb;req_qos=4'ha;
      do @(posedge clk); while(!req_ready);@(negedge clk);req_valid=0;
      if(wr) begin
        if(awaddr!==addr||awsize!==3'd2)failures++;
        repeat(2)@(posedge clk);awready=1;@(posedge clk);awready=0;
        repeat(2)@(posedge clk);wready=1;@(posedge clk);wready=0;
        if(addr[2]) begin if(wdata!=={data,32'd0}||wstrb!=={strb,4'd0})failures++;end
        else begin if(wdata!=={32'd0,data}||wstrb!=={4'd0,strb})failures++;end
        @(negedge clk);bvalid=1;bid=4'h1;bresp=expect_error?2'b10:2'b00;
        @(posedge clk);@(negedge clk);bvalid=0;
      end else begin
        if(araddr!==addr||arlsize!==3'd2)failures++;
        repeat(2)@(posedge clk);arready=1;@(posedge clk);arready=0;
        @(negedge clk);rvalid=1;rid=4'h1;rresp=expect_error?2'b10:2'b00;rlast=1;
        rdata={32'h89abcdef,32'h01234567};@(posedge clk);@(negedge clk);rvalid=0;
      end
      wait(rsp_valid);if(rsp_error!==expect_error)failures++;
      if(!wr&&!expect_error&&rsp_rdata!==expect_data)failures++;
      repeat(2)@(posedge clk);rsp_ready=1;@(posedge clk);rsp_ready=0;
    end
  endtask

  initial begin
    req_valid=0;req_write=0;req_addr=0;req_wdata=0;req_wstrb=0;req_qos=0;rsp_ready=0;
    awready=0;wready=0;bvalid=0;bid=0;bresp=0;arready=0;rvalid=0;rid=0;rdata=0;rresp=0;rlast=0;
    repeat(4)@(posedge clk);rst_n=1;
    issue(1,32'h1000_0000,32'hdeadbeef,4'hf,0,0);
    issue(1,32'h1000_0004,32'hcafef00d,4'h5,0,0);
    issue(0,32'h1000_0000,0,0,0,32'h01234567);
    issue(0,32'h1000_0004,0,0,0,32'h89abcdef);
    issue(0,32'h1000_0000,0,0,1,0);
    issue(1,32'h1000_0004,32'h1,4'hf,1,0);
    if(failures != 0) $fatal(1,"PROTECTED_AXI_ADAPTER_FAIL failures=%0d",failures);
    $display("PROTECTED_AXI_ADAPTER_PASS|cases=6|lower_lane=1|upper_lane=1|errors=2|backpressure=1");
    $finish;
  end
endmodule
