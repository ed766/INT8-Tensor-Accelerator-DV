`timescale 1ns/1ps
module tb_protected_axi_sram;
  logic clk=0, rst_n=0;
  always #5 clk=~clk;
  logic awvalid=0, awready, wvalid=0, wready, bvalid, bready=0;
  logic arvalid=0, arready, rvalid, rready=0;
  logic [5:0] awid=1, arid=2, bid, rid;
  logic [31:0] awaddr=32'h10000000, araddr=32'h10000000;
  logic [63:0] wdata=64'h0123456789abcdef, rdata;
  logic [1:0] bresp,rresp;
  logic rlast;
  protected_axi_sram #(.WORDS(8)) dut (
    .clk,.rst_n,.awvalid,.awready,.awid,.awaddr,.awlen(8'd0),.awsize(3'd3),
    .wvalid,.wready,.wdata,.wstrb(8'hff),.wlast(1'b1),.bvalid,.bready,.bid,.bresp,
    .arvalid,.arready,.arid,.araddr,.arlen(8'd0),.arsize(3'd3),
    .rvalid,.rready,.rid,.rdata,.rresp,.rlast
  );
  initial begin
    repeat(3) @(negedge clk);
    rst_n=1; awvalid=1;
    @(posedge clk); if(!awready)$fatal(1,"initial AW not accepted");
    @(negedge clk); awvalid=0; wvalid=1;
    @(posedge clk); if(!wready)$fatal(1,"W not accepted");
    @(negedge clk); wvalid=0; awvalid=1; awid=3; awaddr=32'h10000008;
    // A new address must not overwrite delayed response ownership.
    repeat(3) begin
      @(posedge clk);
      if(awready || bvalid)$fatal(1,"B delay lost transaction ownership");
    end
    wait(bvalid);
    repeat(3) begin
      @(posedge clk);
      if(awready || bid!=1 || bresp!=0)$fatal(1,"B response not stable");
    end
    @(negedge clk); awvalid=0; bready=1;
    @(posedge clk);
    @(negedge clk); bready=0; arvalid=1;
    @(posedge clk); if(!arready)$fatal(1,"initial AR not accepted");
    @(negedge clk); arid=4; araddr=32'h10000008;
    repeat(3) begin
      @(posedge clk);
      if(arready || rvalid)$fatal(1,"R delay lost transaction ownership");
    end
    wait(rvalid);
    repeat(3) begin
      @(posedge clk);
      if(arready || rid!=2 || rdata!=64'h0123456789abcdef || rresp!=0 || !rlast)
        $fatal(1,"R response ownership/data not stable");
    end
    @(negedge clk); arvalid=0; rready=1;
    @(posedge clk);
    @(negedge clk); rready=0; arvalid=1;
    @(posedge clk); if(!arready)$fatal(1,"second AR not accepted");
    @(negedge clk); arvalid=0; rst_n=0;
    repeat(2) @(negedge clk);
    rst_n=1;
    repeat(8) begin
      @(posedge clk);
      if(rvalid || bvalid)$fatal(1,"reset produced stale response");
    end
    $display("PROTECTED_AXI_SRAM|status=PASS|checks=5");
    $finish;
  end
  initial begin #5000; $fatal(1,"SRAM test timeout"); end
endmodule
