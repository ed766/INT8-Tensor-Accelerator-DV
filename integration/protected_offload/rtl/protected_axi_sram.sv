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
  logic write_active;logic[ID_W-1:0]awid_q;logic[31:0]awaddr_q;logic[7:0]awlen_q,write_beat;
  logic[ID_W-1:0]arid_q;logic[31:0]araddr_q;logic[7:0]arlen_q,read_beat;
  logic[63:0]memory[WORDS];integer idx;
  assign awready=!write_active&&!bvalid;assign wready=write_active&&!bvalid;assign arready=!rvalid;
  function automatic int word_index(input logic[31:0]a);return int'((a-BASE)>>3);endfunction
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin write_active<=0;bvalid<=0;rvalid<=0;bid<=0;rid<=0;rdata<=0;bresp<=0;rresp<=0;rlast<=0;write_beat<=0;read_beat<=0;end
    else begin
      if(awvalid&&awready)begin write_active<=1;awid_q<=awid;awaddr_q<=awaddr;awlen_q<=awlen;write_beat<=0;end
      if(wvalid&&wready)begin
        idx=word_index(awaddr_q)+int'(write_beat);if(!FORCE_ERROR)for(int b=0;b<8;b++)if(wstrb[b])memory[idx][8*b+:8]<=wdata[8*b+:8];
        if(wlast||write_beat==awlen_q)begin bid<=awid_q;bresp<=FORCE_ERROR?2'b10:2'b00;bvalid<=1;write_active<=0;end else write_beat<=write_beat+1'b1;
      end
      if(bvalid&&bready)bvalid<=0;
      if(arvalid&&arready)begin arid_q<=arid;araddr_q<=araddr;arlen_q<=arlen;read_beat<=0;rid<=arid;rdata<=memory[word_index(araddr)];rresp<=FORCE_ERROR?2'b10:2'b00;rlast<=arlen==0;rvalid<=1;end
      if(rvalid&&rready)begin if(read_beat==arlen_q)begin rvalid<=0;rlast<=0;end else begin read_beat<=read_beat+1'b1;rid<=arid_q;rdata<=memory[word_index(araddr_q)+int'(read_beat)+1];rresp<=FORCE_ERROR?2'b10:2'b00;rlast<=read_beat+1'b1==arlen_q;end end
    end
  end
`ifndef SYNTHESIS
  a_supported_aw:assert property(@(posedge clk)disable iff(!rst_n)awvalid|->awlen<=3&&awsize<=3);
  a_supported_ar:assert property(@(posedge clk)disable iff(!rst_n)arvalid|->arlen<=3&&arsize<=3);
  a_wlast_matches_length:assert property(@(posedge clk)disable iff(!rst_n)wvalid&&wready|->wlast==(write_beat==awlen_q));
`endif
endmodule
