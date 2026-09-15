`timescale 1ns/1ps
module tb_rv32_protected_shared;
 logic clk=0,rst_n=0,firmware_done,commit_valid,irq;logic[31:0]firmware_result,commit_pc,cycles;always #5 clk=~clk;
 rv32_protected_shared_top dut(.*);integer commits=0;
 integer expected_k=4,expected_batch=1;
 always_ff@(posedge clk)if(commit_valid)commits<=commits+1;
 initial begin void'($value$plusargs("EXPECT_K=%d",expected_k));void'($value$plusargs("EXPECT_BATCH=%d",expected_batch));repeat(5)@(posedge clk);rst_n=1;repeat(400000)begin @(posedge clk);if(firmware_done)begin
   if(firmware_result!==32'h600d5000)$fatal(1,"firmware result %08x",firmware_result);
   if(dut.mem1.memory[13'h200][31:0]!==32'h01010101)$fatal(1,"input memory %016x",dut.mem1.memory[13'h200]);
   for(int v=0;v<expected_batch;v++)begin int wi=(32'h4000+v*4)>>3;logic[31:0]actual;if(v[0])actual=dut.mem1.memory[wi][63:32];else actual=dut.mem1.memory[wi][31:0];if(actual!==((expected_k&255)*32'h01010101))$fatal(1,"output memory v=%0d got=%08x",v,actual);end
   if(dut.perf_tlb_misses<2||dut.perf_walk_reads<4)$fatal(1,"page walk missing");
   $display("PROTECTED_SHARED|status=PASS|commits=%0d|cycles=%0d|k=%0d|batch=%0d|host=1|dma=1|ptw=1|fabric=1",commits,cycles,expected_k,expected_batch);$finish;end end
   $fatal(1,"timeout pc=%08x",commit_pc);end
endmodule
