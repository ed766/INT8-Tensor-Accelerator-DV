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
  integer stall_percent=0;integer stall_seed=1;
  integer b_delay_cycles=0;integer r_delay_cycles=0;
  integer w_ready_delay_cycles=0;
  integer w_ready_delay_q=0;
  logic[31:0]stall_aw_rng,stall_w_rng,stall_ar_rng;
  logic stall_aw,stall_w,stall_ar;
  integer b_delay_q,r_delay_q;
  logic b_pending_q,r_pending_q;
  logic write_error_q;
  logic [31:0] fail_write_addr=0;
  integer fail_write_count=0;
  initial begin
    void'($value$plusargs("AXI_STALL_PCT=%d",stall_percent));
    void'($value$plusargs("AXI_STALL_SEED=%d",stall_seed));
    void'($value$plusargs("AXI_B_DELAY=%d",b_delay_cycles));
    void'($value$plusargs("AXI_R_DELAY=%d",r_delay_cycles));
    void'($value$plusargs("AXI_W_READY_DELAY=%d",w_ready_delay_cycles));
    void'($value$plusargs("AXI_FAIL_WRITE_ADDR=%h",fail_write_addr));
    void'($value$plusargs("AXI_FAIL_WRITE_COUNT=%d",fail_write_count));
    if(stall_percent<0||stall_percent>75)$fatal(1,"AXI_STALL_PCT must be in 0..75");
    if(b_delay_cycles<0||r_delay_cycles<0||w_ready_delay_cycles<0)
      $fatal(1,"AXI channel delays must be non-negative");
    stall_aw_rng=32'h1f123bb5^stall_seed^BASE;
    stall_w_rng=32'h5a17c9e3^(stall_seed<<1)^BASE;
    stall_ar_rng=32'h6c8e9cf5^(stall_seed<<2)^BASE;
  end
  always_comb begin
    stall_aw=stall_percent!=0&&(stall_aw_rng%100)<stall_percent;
    stall_w=stall_percent!=0&&(stall_w_rng%100)<stall_percent;
    stall_ar=stall_percent!=0&&(stall_ar_rng%100)<stall_percent;
  end
  assign awready=!write_active&&!bvalid&&!b_pending_q&&!stall_aw;
  assign wready=write_active&&!bvalid&&!stall_w&&(w_ready_delay_q==0);
  assign arready=!rvalid&&!r_pending_q&&!stall_ar;
  function automatic int word_index(input logic[31:0]a);return int'((a-BASE)>>3);endfunction
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin write_active<=0;write_error_q<=0;bvalid<=0;rvalid<=0;bid<=0;rid<=0;rdata<=0;bresp<=0;rresp<=0;rlast<=0;write_beat<=0;read_beat<=0;b_delay_q<=0;r_delay_q<=0;b_pending_q<=0;r_pending_q<=0;w_ready_delay_q<=0;
      stall_aw_rng<=32'h1f123bb5^stall_seed^BASE;stall_w_rng<=32'h5a17c9e3^(stall_seed<<1)^BASE;stall_ar_rng<=32'h6c8e9cf5^(stall_seed<<2)^BASE;end
    else begin
      stall_aw_rng<={stall_aw_rng[30:0],stall_aw_rng[31]^stall_aw_rng[21]^stall_aw_rng[1]^stall_aw_rng[0]};
      stall_w_rng<={stall_w_rng[30:0],stall_w_rng[31]^stall_w_rng[21]^stall_w_rng[1]^stall_w_rng[0]};
      stall_ar_rng<={stall_ar_rng[30:0],stall_ar_rng[31]^stall_ar_rng[21]^stall_ar_rng[1]^stall_ar_rng[0]};
      if(b_pending_q)begin
        if(b_delay_q==0)begin bvalid<=1'b1;b_pending_q<=1'b0;end
        else b_delay_q<=b_delay_q-1;
      end
      if(r_pending_q)begin
        if(r_delay_q==0)begin rvalid<=1'b1;r_pending_q<=1'b0;end
        else r_delay_q<=r_delay_q-1;
      end
      if(write_active && w_ready_delay_q!=0)w_ready_delay_q<=w_ready_delay_q-1;
      if(awvalid&&awready)begin
        write_active<=1;awid_q<=awid;awaddr_q<=awaddr;awlen_q<=awlen;write_beat<=0;w_ready_delay_q<=w_ready_delay_cycles;
        write_error_q<=FORCE_ERROR||(fail_write_count>0&&awaddr==fail_write_addr);
        if(fail_write_count>0&&awaddr==fail_write_addr)fail_write_count<=fail_write_count-1;
      end
      if(wvalid&&wready)begin
        idx=word_index(awaddr_q)+int'(write_beat);if(!write_error_q)for(int b=0;b<8;b++)if(wstrb[b])memory[idx][8*b+:8]<=wdata[8*b+:8];
        if(wlast||write_beat==awlen_q)begin
          bid<=awid_q;bresp<=write_error_q?2'b10:2'b00;write_active<=0;
          if(b_delay_cycles==0)bvalid<=1'b1;
          else begin b_delay_q<=b_delay_cycles;b_pending_q<=1'b1;end
        end else write_beat<=write_beat+1'b1;
      end
      if(bvalid&&bready)bvalid<=0;
      if(arvalid&&arready)begin
        arid_q<=arid;araddr_q<=araddr;arlen_q<=arlen;read_beat<=0;rid<=arid;rdata<=memory[word_index(araddr)];rresp<=FORCE_ERROR?2'b10:2'b00;rlast<=arlen==0;
        if(r_delay_cycles==0)rvalid<=1'b1;
        else begin r_delay_q<=r_delay_cycles;r_pending_q<=1'b1;end
      end
      if(rvalid&&rready)begin if(read_beat==arlen_q)begin rvalid<=0;rlast<=0;end else begin read_beat<=read_beat+1'b1;rid<=arid_q;rdata<=memory[word_index(araddr_q)+int'(read_beat)+1];rresp<=FORCE_ERROR?2'b10:2'b00;rlast<=read_beat+1'b1==arlen_q;end end
    end
  end
`ifndef SYNTHESIS
  a_supported_aw:assert property(@(posedge clk)disable iff(!rst_n)awvalid|->awlen<=3&&awsize<=3);
  a_supported_ar:assert property(@(posedge clk)disable iff(!rst_n)arvalid|->arlen<=3&&arsize<=3);
  a_wlast_matches_length:assert property(@(posedge clk)disable iff(!rst_n)wvalid&&wready|->wlast==(write_beat==awlen_q));
`endif
endmodule
