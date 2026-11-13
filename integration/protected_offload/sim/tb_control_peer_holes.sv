`timescale 1ns/1ps
module tb_control_peer_holes;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic psel=0,penable=0,pwrite=0,pready,pslverr,cfg_valid,cfg_write,cfg_ready=0;
  logic [31:0] paddr=0,pwdata=0,prdata,cfg_wdata,cfg_rdata=32'h11223344;
  logic [7:0] cfg_addr;
  logic req_valid=0,req_ready,rsp_valid,rsp_ready=0;
  logic [2:0] req_op=0;logic [31:0] req_lhs=0,req_rhs=0,rsp_result;
  protected_chiplet_apb_bridge bridge(.*);
  rv32_muldiv arithmetic(.*);

  task automatic arithmetic_case(input logic [2:0] op,input logic [31:0] a,b,expected,input int hold_cycles);
    int compute_cycles;
    @(negedge clk);req_valid=1;req_op=op;req_lhs=a;req_rhs=b;
    if(!req_ready)$fatal(1,"arithmetic request not ready");
    @(negedge clk);req_valid=0;
    compute_cycles=1;
    while(!rsp_valid&&compute_cycles<36)begin @(negedge clk);compute_cycles++;end
    if(!rsp_valid)$fatal(1,"arithmetic exceeded 36-clock computation contract");
    repeat(hold_cycles)begin
      @(negedge clk);
      if(!rsp_valid||rsp_result!==expected||req_ready)$fatal(1,"held arithmetic result changed");
    end
    $display("HOLE_EVT|module=rv32_muldiv|phase=response_hold|opcode=%0d|waits=%0d|compute_clocks=%0d",op,hold_cycles,compute_cycles);
    rsp_ready=1;@(negedge clk);rsp_ready=0;
    if(rsp_valid||!req_ready)$fatal(1,"arithmetic response consumed more than once");
  endtask

  initial begin
    repeat(3)@(negedge clk);rst_n=1;
    for(int direction=0;direction<2;direction++)begin
      @(negedge clk);psel=1;penable=0;pwrite=1'(direction);paddr=32'h50000040;pwdata=32'habcdf00d;
      @(negedge clk);if(pready||cfg_valid)$fatal(1,"setup side effect");penable=1;
      @(negedge clk);
      repeat(5)begin
        if(!cfg_valid||pready||cfg_addr!=8'h40||cfg_wdata!=pwdata||cfg_write!=pwrite)$fatal(1,"CSR request hold");
        @(negedge clk);
      end
      $display("HOLE_EVT|module=protected_chiplet_apb_bridge|phase=cfg_wait|direction=%0d|waits=5",direction);
      cfg_ready=1;#1;if(!pready||pslverr||prdata!=cfg_rdata)$fatal(1,"CSR response");
      @(negedge clk);psel=0;penable=0;cfg_ready=0;
    end
    arithmetic_case(0,32'hfffffff9,3,32'hffffffeb,1);
    arithmetic_case(1,32'hfffffff9,3,32'hffffffff,2);
    arithmetic_case(2,32'hfffffff9,3,32'hffffffff,3);
    arithmetic_case(3,32'hfffffff9,3,2,4);
    arithmetic_case(4,32'hfffffff9,3,32'hfffffffe,5);
    arithmetic_case(5,32'hfffffff9,3,32'h55555553,6);
    arithmetic_case(6,32'hfffffff9,3,32'hffffffff,7);
    arithmetic_case(7,32'hfffffff9,3,0,8);
    arithmetic_case(4,32'h80000000,32'hffffffff,32'h80000000,9);
    arithmetic_case(6,32'h80000000,32'hffffffff,0,10);
    arithmetic_case(5,32'h87654321,0,32'hffffffff,11);
    arithmetic_case(7,32'h87654321,0,32'h87654321,12);
    @(negedge clk);req_valid=1;req_op=4;req_lhs=99;req_rhs=3;
    @(negedge clk);req_valid=0;wait(rsp_valid);
    @(negedge clk);rst_n=0;repeat(2)@(negedge clk);rst_n=1;
    repeat(3)begin @(negedge clk);if(rsp_valid)$fatal(1,"reset ghost result");end
    arithmetic_case(4,21,3,7,3);
    $display("PEER_HOLES_PASS|bridge_cases=2|arithmetic_cases=13|reset_pending_response=1");$finish;
  end
  initial begin repeat(3000)@(posedge clk);$fatal(1,"peer holes timeout");end
endmodule
