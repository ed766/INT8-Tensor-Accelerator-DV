`timescale 1ns/1ps
module protected_axi_sram #(
  parameter int ID_W=6,parameter int WORDS=8192,parameter logic[31:0]BASE=32'h1000_0000,
  parameter bit FORCE_ERROR=0
)(
  input logic clk,input logic rst_n,
  input logic awvalid,output logic awready,input logic[ID_W-1:0]awid,input logic[31:0]awaddr,input logic[7:0]awlen,input logic[2:0]awsize,
  input logic wvalid,output logic wready,input logic[63:0]wdata,input logic[7:0]wstrb,input logic wlast,
  output logic bvalid,input logic bready,output logic[ID_W-1:0]bid,output logic[1:0]bresp,
  input logic arvalid,output logic arready,input logic[ID_W-1:0]arid,input logic[31:0]araddr,input logic[7:0]arlen,input logic[2:0]arsize,
  output logic rvalid,input logic rready,output logic[ID_W-1:0]rid,output logic[63:0]rdata,output logic[1:0]rresp,output logic rlast
);
  logic aw_pending,w_pending;logic[ID_W-1:0]awid_q;logic[31:0]awaddr_q;logic[63:0]wdata_q;logic[7:0]wstrb_q;
  logic[63:0]effective_wdata;logic[7:0]effective_wstrb;
  logic[63:0]memory[WORDS];integer idx;
  assign awready=!aw_pending&&!bvalid;assign wready=!w_pending&&!bvalid;assign arready=!rvalid;
  assign effective_wdata=w_pending?wdata_q:wdata;assign effective_wstrb=w_pending?wstrb_q:wstrb;
  function automatic int word_index(input logic[31:0]a);return int'((a-BASE)>>3);endfunction
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin aw_pending<=0;w_pending<=0;bvalid<=0;rvalid<=0;bid<=0;rid<=0;rdata<=0;bresp<=0;rresp<=0;rlast<=0;end
    else begin
      if(awvalid&&awready)begin aw_pending<=1;awid_q<=awid;awaddr_q<=awaddr;end
      if(wvalid&&wready)begin w_pending<=1;wdata_q<=wdata;wstrb_q<=wstrb;end
      if((aw_pending||(awvalid&&awready))&&(w_pending||(wvalid&&wready))&&!bvalid)begin
        idx=word_index(aw_pending?awaddr_q:awaddr);bid<=aw_pending?awid_q:awid;bresp<=FORCE_ERROR?2'b10:2'b00;bvalid<=1;
        if(!FORCE_ERROR)for(int b=0;b<8;b++)if(effective_wstrb[b])memory[idx][8*b+:8]<=effective_wdata[8*b+:8];
        aw_pending<=0;w_pending<=0;
      end
      if(bvalid&&bready)bvalid<=0;
      if(arvalid&&arready)begin rid<=arid;rdata<=memory[word_index(araddr)];rresp<=FORCE_ERROR?2'b10:2'b00;rlast<=1;rvalid<=1;end
      if(rvalid&&rready)begin rvalid<=0;rlast<=0;end
    end
  end
`ifndef SYNTHESIS
  a_single_beat_aw:assert property(@(posedge clk)disable iff(!rst_n)awvalid|->awlen==0&&awsize<=3);
  a_single_beat_ar:assert property(@(posedge clk)disable iff(!rst_n)arvalid|->arlen==0&&arsize<=3);
  a_single_beat_wlast:assert property(@(posedge clk)disable iff(!rst_n)wvalid|->wlast);
`endif
endmodule
