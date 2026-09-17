`timescale 1ns/1ps
module tb_protected_tlb_control;
  logic clk=0,rst_n=0; always #5 clk=~clk;
  logic[7:0] paddr; logic psel,penable,pwrite; logic[31:0] pwdata,prdata;
  logic pready,pslverr,translation_idle,service_busy,inv_valid,inv_all; logic[7:0] inv_asid;
  integer checks=0,failures=0;
  protected_tlb_control_apb dut(.*);
  task automatic write_control(input logic all,input logic[7:0] asid);
    begin
      @(negedge clk); paddr=0;pwdata={16'd0,asid,6'd0,all,1'b1};pwrite=1;psel=1;penable=1;
      do @(posedge clk); while(!pready);
      @(negedge clk);psel=0;penable=0;pwrite=0;
    end
  endtask
  initial begin
    paddr=0;psel=0;penable=0;pwrite=0;pwdata=0;translation_idle=0;service_busy=1;
    repeat(3)@(posedge clk);rst_n=1;
    write_control(0,8'h3a); checks++;
    if(!dut.pending||inv_valid||inv_all||inv_asid!=8'h3a)begin failures++;$display("TLBCTL_FAIL|held_request");end
    @(negedge clk);service_busy=0;@(posedge clk);checks++;
    if(inv_valid)begin failures++;$display("TLBCTL_FAIL|wait_translation");end
    @(negedge clk);translation_idle=1;@(posedge clk);checks++;
    if(!inv_valid||inv_all||inv_asid!=8'h3a)begin failures++;$display("TLBCTL_FAIL|targeted_pulse");end
    @(posedge clk);checks++;
    if(inv_valid||dut.pending)begin failures++;$display("TLBCTL_FAIL|single_pulse");end
    write_control(1,8'h00);@(posedge clk);checks++;
    if(!inv_valid||!inv_all)begin failures++;$display("TLBCTL_FAIL|global_pulse");end
    $display("TLBCTL_RESULT|status=%s|checks=%0d",failures==0?"PASS":"FAIL",checks);
    if(failures)$fatal(1,"tlb control failures=%0d",failures);$finish;
  end
endmodule
