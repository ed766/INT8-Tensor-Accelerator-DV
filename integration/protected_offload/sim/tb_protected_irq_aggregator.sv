`timescale 1ns/1ps
module tb_protected_irq_aggregator;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic chiplet_dma_event=0,accelerator_event=0,device_fault_event=0;
  logic[5:0]paddr=0;logic psel=0,penable=0,pwrite=0;
  logic[31:0]pwdata=0,prdata;logic pready,pslverr,irq_ext;
  logic[2:0]raw_status,pending_status,enable_mask;
  protected_irq_aggregator dut(.*);

  task automatic write_reg(input logic[5:0]addr,input logic[31:0]data);
    @(negedge clk);paddr=addr;pwdata=data;psel=1;pwrite=1;
    @(posedge clk);@(negedge clk);penable=1;
    @(posedge clk);if(!pready||pslverr)$fatal(1,"APB write");
    @(negedge clk);psel=0;penable=0;pwrite=0;
  endtask
  task automatic pulse(input integer which);
    @(negedge clk);if(which==0)chiplet_dma_event=1;else if(which==1)accelerator_event=1;else device_fault_event=1;
    @(posedge clk);@(negedge clk);chiplet_dma_event=0;accelerator_event=0;device_fault_event=0;
  endtask
  initial begin
    repeat(3)@(posedge clk);rst_n=1;
    pulse(1);if(raw_status!=3'b010||irq_ext)$fatal(1,"masked pending");
    write_reg(6'h08,32'h2);if(!irq_ext||pending_status!=3'b010||enable_mask!=3'b010)$fatal(1,"pending then enable");
    write_reg(6'h0c,32'h2);if(raw_status!=0||irq_ext)$fatal(1,"ack");
    pulse(0);write_reg(6'h08,32'h7);
    @(negedge clk);paddr=6'h0c;pwdata=1;psel=1;penable=1;pwrite=1;chiplet_dma_event=1;
    @(posedge clk);@(negedge clk);psel=0;penable=0;pwrite=0;chiplet_dma_event=0;
    @(posedge clk);if(!raw_status[0]||!irq_ext)$fatal(1,"set did not dominate ack");
    pulse(2);if(raw_status!=3'b101)$fatal(1,"source accumulation");
    paddr=6'h00;psel=1;penable=1;#1;if(prdata[2:0]!=3'b101)$fatal(1,"status readback");
    $display("PROTECTED_IRQ_AGGREGATOR|status=PASS|sources=3|set_dominant=1|masked_pending=1");
    $finish;
  end
endmodule
