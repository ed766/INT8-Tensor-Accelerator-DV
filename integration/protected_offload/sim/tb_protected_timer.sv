`timescale 1ns/1ps

module tb_protected_timer;
  logic clk = 1'b0;
  logic rst_n = 1'b0;
  always #5 clk = ~clk;

  logic [31:0] paddr = '0, pwdata = '0, prdata;
  logic psel = 1'b0, penable = 1'b0, pwrite = 1'b0;
  logic pready, pslverr, irq_timer;
  logic [63:0] mtime, mtimecmp;

  apb_machine_timer #(.MMIO_BASE(32'h4000_2300)) dut (
    .pclk(clk), .presetn(rst_n), .paddr, .psel, .penable, .pwrite, .pwdata,
    .prdata, .pready, .pslverr, .irq_timer, .mtime, .mtimecmp);

  task automatic apb_write(input logic [31:0] addr, input logic [31:0] data);
    begin
      @(negedge clk); paddr = addr; pwdata = data; pwrite = 1'b1; psel = 1'b1; penable = 1'b0;
      @(posedge clk); #1;
      if (pready || pslverr) $fatal(1, "timer completed during APB setup");
      @(negedge clk); penable = 1'b1;
      #1;
      if (!pready || pslverr) $fatal(1, "timer write did not complete");
      @(posedge clk);
      @(negedge clk); psel = 1'b0; penable = 1'b0; pwrite = 1'b0;
    end
  endtask

  task automatic apb_read(input logic [31:0] addr, output logic [31:0] data);
    begin
      @(negedge clk); paddr = addr; pwrite = 1'b0; psel = 1'b1; penable = 1'b0;
      @(posedge clk); #1;
      if (pready || pslverr) $fatal(1, "timer read completed during APB setup");
      @(negedge clk); penable = 1'b1;
      #1;
      if (!pready || pslverr) $fatal(1, "timer read did not complete");
      @(posedge clk);
      data = prdata;
      @(negedge clk); psel = 1'b0; penable = 1'b0;
    end
  endtask

  logic [31:0] readback;
  initial begin
    repeat (3) @(posedge clk);
    rst_n = 1'b1;
    apb_write(32'h4000_2308, 32'd12);
    apb_write(32'h4000_230c, 32'd0);
    apb_read(32'h4000_2308, readback);
    if (readback !== 32'd12) $fatal(1, "mtimecmp readback mismatch");
    repeat (12) @(posedge clk);
    if (!irq_timer) $fatal(1, "timer interrupt did not assert");
    apb_write(32'h4000_2308, 32'hffff_ffff);
    apb_write(32'h4000_230c, 32'hffff_ffff);
    if (irq_timer) $fatal(1, "timer interrupt did not clear");
    @(negedge clk); paddr = 32'h4000_2310; psel = 1'b1; penable = 1'b0;
    @(negedge clk); penable = 1'b1;
    #1;
    if (!pready || !pslverr) $fatal(1, "invalid timer address not rejected");
    @(posedge clk);
    $display("PROTECTED_TIMER|status=PASS|setup_guard=1|irq=1|invalid=1");
    $finish;
  end
  initial begin repeat (200) @(posedge clk); $fatal(1, "timer timeout"); end
endmodule
