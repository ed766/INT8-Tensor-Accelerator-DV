module protected_axi_adapter_formal;
  (* gclk *) logic clk;
  logic [1:0] reset_count = 0;
  wire rst_n = reset_count[1];
  always @(posedge clk) if (!rst_n) reset_count <= reset_count + 1'b1;

  (* anyseq *) logic req_valid, req_write, rsp_ready;
  (* anyseq *) logic [31:0] req_addr, req_wdata;
  (* anyseq *) logic [3:0] req_wstrb, req_qos;
  (* anyseq *) logic awready,wready,bvalid,arready,rvalid;
  (* anyseq *) logic [3:0] bid,rid;
  (* anyseq *) logic [1:0] bresp,rresp;
  (* anyseq *) logic [63:0] rdata;
  (* anyseq *) logic rlast;
  wire req_ready,rsp_valid,rsp_error,awvalid,wvalid,bready,arvalid,rready,wlast;
  wire [31:0] rsp_rdata,awaddr,araddr;
  wire [3:0] awid,arid,awqos,arqos;
  wire [7:0] awlen,arlen,wstrb;
  wire [2:0] awsize,arsize,awprot,arprot;
  wire [1:0] awburst,arburst;
  wire [63:0] wdata;

  protected_dma_axi_adapter dut(.*);

  logic past_valid=0;
  logic [3:0] accepted=0,responded=0;
  logic write_active=0,read_active=0,aw_seen=0,w_seen=0,ar_seen=0;
  always @(posedge clk) begin
    past_valid<=1;
    if(!rst_n) begin
      accepted<=0;responded<=0;write_active<=0;read_active<=0;aw_seen<=0;w_seen<=0;ar_seen<=0;
    end else begin
      if(req_valid&&req_ready) begin
        accepted<=accepted+1'b1;
        write_active<=req_write;read_active<=!req_write;aw_seen<=0;w_seen<=0;ar_seen<=0;
      end
      if(awvalid&&awready)aw_seen<=1;
      if(wvalid&&wready)w_seen<=1;
      if(arvalid&&arready)ar_seen<=1;
      if(rsp_valid&&rsp_ready) begin
        responded<=responded+1'b1;write_active<=0;read_active<=0;
      end

      if(past_valid&&$past(rst_n)) begin
        if($past(req_valid&&!req_ready)) assume(req_valid&&$stable({req_write,req_addr,req_wdata,req_wstrb,req_qos}));
        assert(responded<=accepted);
        assert((accepted-responded)<=1);
        if(awvalid) begin assert(write_active);assert(awaddr[2:0]==0);assert(awlen==0);assert(awsize==2);end
        if(wvalid) begin
          assert(write_active);assert(wlast);
          assert((wdata[31:0]==0&&wstrb[3:0]==0)||(wdata[63:32]==0&&wstrb[7:4]==0));
        end
        if(arvalid) begin assert(read_active);assert(araddr[2:0]==0);assert(arlen==0);assert(arsize==2);end
        if(rsp_valid&&write_active) assert((aw_seen||$past(awvalid&&awready))&&(w_seen||$past(wvalid&&wready)));
        if(rsp_valid&&read_active) assert(ar_seen||$past(arvalid&&arready));
        if($past(rsp_valid&&!rsp_ready)) assert(rsp_valid&&$stable({rsp_rdata,rsp_error}));
        if(!write_active&&!read_active) assert(!awvalid&&!wvalid&&!arvalid);
        cover(aw_seen&&w_seen&&bvalid);
        cover(ar_seen&&rvalid&&rlast);
        cover(rsp_valid&&rsp_error);
      end
    end
  end
endmodule
