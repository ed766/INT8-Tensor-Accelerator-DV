`timescale 1ns/1ps
module tb_protected_host_axi_bridge;
  logic clk=0,rst_n=0; always #5 clk=~clk;
  logic psel=0,penable=0,pwrite=0,pready,pslverr;
  logic[31:0]paddr=0,pwdata=0,prdata;
  logic awvalid,awready=0,wvalid,wready=0,bvalid=0,bready;
  logic arvalid,arready=0,rvalid=0,rready,wlast,rlast=0;
  logic[3:0]awid,bid=0,arid,rid=0,awqos,arqos;
  logic[31:0]awaddr,araddr;logic[7:0]awlen,arlen,wstrb;
  logic[2:0]awsize,arsize,awprot,arprot;
  logic[1:0]awburst,arburst,bresp=0,rresp=0;
  logic[63:0]wdata,rdata=0;
  integer requests=0;

  protected_host_axi_bridge #(.AXI_ID(4'h3)) dut(.*);

  task automatic apb_write(input logic[31:0]addr,input logic[31:0]data,input logic error);
    @(negedge clk);psel=1;pwrite=1;paddr=addr;pwdata=data;
    @(posedge clk);@(negedge clk);penable=1;
    wait(awvalid);repeat(2)@(posedge clk);awready=1;@(posedge clk);awready=0;
    wait(wvalid);repeat(2)@(posedge clk);wready=1;@(posedge clk);wready=0;
    requests++;
    if(awid!=3 || awaddr!={addr[31:3],3'b0})$fatal(1,"write route");
    if(addr[2] ? (wdata!={data,32'd0}||wstrb!=8'hf0) : (wdata!={32'd0,data}||wstrb!=8'h0f))$fatal(1,"write lane");
    @(negedge clk);bvalid=1;bid=3;bresp=error?2'b10:2'b00;
    @(posedge clk);@(negedge clk);bvalid=0;
    wait(pready);if(pslverr!==error)$fatal(1,"write error propagation");
    @(posedge clk);@(negedge clk);psel=0;penable=0;pwrite=0;
    @(posedge clk);
  endtask

  task automatic apb_read(input logic[31:0]addr,input logic error,input logic[31:0]expected);
    @(negedge clk);psel=1;pwrite=0;paddr=addr;
    @(posedge clk);@(negedge clk);penable=1;
    wait(arvalid);repeat(2)@(posedge clk);arready=1;@(posedge clk);arready=0;
    requests++;
    @(negedge clk);rvalid=1;rid=3;rresp=error?2'b10:2'b00;rlast=1;
    rdata=addr[2]?{expected,32'h0}:{32'h0,expected};
    @(posedge clk);@(negedge clk);rvalid=0;rlast=0;
    wait(pready);if(pslverr!==error)$fatal(1,"read error propagation");
    if(!error&&prdata!==expected)$fatal(1,"read data");
    @(posedge clk);@(negedge clk);psel=0;penable=0;
    @(posedge clk);
  endtask

  initial begin
    repeat(4)@(posedge clk);rst_n=1;
    apb_write(32'h1000_0004,32'hcafe_f00d,0);
    apb_read(32'h3000_0000,0,32'h1122_3344);
    apb_read(32'h2000_0004,1,0);
    if(requests!=3)$fatal(1,"duplicate or missing AXI request");
    $display("PROTECTED_HOST_BRIDGE|status=PASS|requests=3|errors=1|waits=1");
    $finish;
  end
  initial begin repeat(500)@(posedge clk);$fatal(1,"host bridge timeout");end
endmodule
