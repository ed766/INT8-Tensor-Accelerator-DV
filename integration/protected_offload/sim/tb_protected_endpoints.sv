`timescale 1ns/1ps
module tb_protected_endpoints;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic psel=0,penable=0,pwrite=0;logic[31:0]paddr=0,pwdata=0,prdata;logic pready,pslverr;
  logic awvalid,awready,wvalid,wready,bvalid,bready,arvalid,arready,rvalid,rready,wlast,rlast;
  logic[3:0]awid,bid,arid,rid,awqos,arqos;logic[31:0]awaddr,araddr;logic[7:0]awlen,arlen,wstrb;
  logic[2:0]awsize,arsize,awprot,arprot;logic[1:0]awburst,arburst,bresp,rresp;logic[63:0]wdata,rdata;
  logic csel=0,cenable=0,cwrite=0;logic[11:0]caddr=0;logic[31:0]cwdata=0,crdata;logic cready,cerror,cfg_valid,cfg_ready=0,cfg_bank;logic[2:0]cfg_kind;logic[1:0]cfg_output;logic[5:0]cfg_index;logic[31:0]cfg_data;logic[1:0][7:0]bank_generation;
  protected_host_axi_bridge host(.*);
  protected_axi_sram #(.ID_W(4),.WORDS(64),.BASE(32'h1000_0000)) mem(.clk,.rst_n,.awvalid,.awready,.awid,.awaddr,.awlen,.awsize,.wvalid,.wready,.wdata,.wstrb,.wlast,.bvalid,.bready,.bid,.bresp,.arvalid,.arready,.arid,.araddr,.arlen,.arsize,.rvalid,.rready,.rid,.rdata,.rresp,.rlast);
  protected_accel_apb_config cfg(.clk,.rst_n,.paddr(caddr),.psel(csel),.penable(cenable),.pwrite(cwrite),.pwdata(cwdata),.prdata(crdata),.pready(cready),.pslverr(cerror),.cfg_valid,.cfg_ready,.cfg_kind,.cfg_bank,.cfg_output,.cfg_index,.cfg_data,.bank_generation);
  task automatic host_access(input logic wr,input logic[31:0]a,input logic[31:0]d);
    @(negedge clk);psel=1;pwrite=wr;paddr=a;pwdata=d;@(posedge clk);@(negedge clk);penable=1;wait(pready);if(pslverr)$fatal(1,"host error");@(posedge clk);@(negedge clk);psel=0;penable=0;pwrite=0;@(posedge clk);
  endtask
  task automatic cfg_write(input logic[11:0]a,input logic[31:0]d);
    @(negedge clk);csel=1;cwrite=1;caddr=a;cwdata=d;@(posedge clk);@(negedge clk);cenable=1;
    if(a==12'h014)begin repeat(3)@(posedge clk);if(cready)$fatal(1,"config did not stall");cfg_ready=1;end
    wait(cready);@(posedge clk);@(negedge clk);csel=0;cenable=0;cwrite=0;cfg_ready=0;@(posedge clk);
  endtask
  initial begin
    repeat(4)@(posedge clk);rst_n=1;
    host_access(1,32'h1000_0000,32'h1122_3344);host_access(1,32'h1000_0004,32'haabb_ccdd);
    host_access(0,32'h1000_0000,0);if(prdata!==32'h1122_3344)$fatal(1,"lower lane");
    host_access(0,32'h1000_0004,0);if(prdata!==32'haabb_ccdd)$fatal(1,"upper lane");
    cfg_write(12'h000,3);cfg_write(12'h004,5);cfg_write(12'h008,17);cfg_write(12'h00c,32'h55aa);cfg_write(12'h010,32'h0207);cfg_write(12'h014,1);
    if(cfg_kind!=3||!cfg_bank||cfg_output!=1||cfg_index!=17||cfg_data!=32'h55aa||bank_generation[0]!=7||bank_generation[1]!=2)$fatal(1,"config fields");
    $display("PROTECTED_ENDPOINTS|status=PASS|memory_lanes=2|cfg_wait=3");$finish;
  end
  initial begin repeat(1000)@(posedge clk);$fatal(1,"endpoint timeout");end
endmodule
