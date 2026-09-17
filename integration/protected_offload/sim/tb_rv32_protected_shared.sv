`timescale 1ns/1ps
module tb_rv32_protected_shared #(parameter bit USE_CACHE=0,parameter bit CPU_ENABLE_M=0,parameter bit ENABLE_CHIPLET=0);
 logic clk=0,rst_n=0,firmware_done,commit_valid,irq,chip_active_debug,chip_link_debug;logic[2:0]chip_state_debug,chip_submit_debug,chip_comp_debug;logic[8:0]chip_send_debug,chip_recv_debug;logic[31:0]firmware_result,commit_pc,cycles,benchmark_cycles;always #5 clk=~clk;
 rv32_protected_shared_top #(.USE_CACHE(USE_CACHE),.CPU_ENABLE_M(CPU_ENABLE_M),.ENABLE_CHIPLET(ENABLE_CHIPLET)) dut(.*);integer commits=0;
 integer expected_k=4,expected_batch=1,reset_at=-1,expected_fault=0,expected_partial_retry=0;logic reset_issued;
 always_ff@(posedge clk)if(commit_valid)commits<=commits+1;
 always_ff@(posedge clk)if(ENABLE_CHIPLET&&dut.chip_sel&&dut.penable)$display("CHIP_APB|addr=%08x|write=%0b|data=%08x|rdata=%08x",dut.paddr,dut.pwrite,dut.pwdata,dut.chip_rdata);
 initial begin
   reset_issued=0;void'($value$plusargs("EXPECT_K=%d",expected_k));void'($value$plusargs("EXPECT_BATCH=%d",expected_batch));void'($value$plusargs("EXPECT_FAULT=%d",expected_fault));void'($value$plusargs("EXPECT_PARTIAL_RETRY=%d",expected_partial_retry));void'($value$plusargs("RESET_AT=%d",reset_at));
   repeat(5)@(posedge clk);rst_n=1;
   fork
     begin : reset_driver
       integer reset_index;
       if(reset_at>=0) begin
         for(reset_index=0;reset_index<reset_at;reset_index=reset_index+1) @(posedge clk);
         rst_n=0;
         for(reset_index=0;reset_index<3;reset_index=reset_index+1) @(posedge clk);
         rst_n=1; reset_issued=1;
       end
     end
   join_none
   repeat(400000)begin @(posedge clk);if(firmware_done)begin
   if(firmware_result!==32'h600d5000)$fatal(1,"firmware result %08x",firmware_result);
   if(dut.mem1.memory[13'h200][31:0]!==32'h01010101)$fatal(1,"input memory %016x",dut.mem1.memory[13'h200]);
   for(int v=0;v<expected_batch;v++)begin int output_byte_addr,wi;logic[31:0]actual;output_byte_addr=(expected_partial_retry!=0&&v!=0)?32'h8000:(32'h4000+v*4);wi=output_byte_addr>>3;if(output_byte_addr[2])actual=dut.mem1.memory[wi][63:32];else actual=dut.mem1.memory[wi][31:0];if(actual!==((expected_fault!=0)?32'h0:((expected_k&255)*32'h01010101)))$fatal(1,"output memory v=%0d got=%08x",v,actual);end
   if(((expected_fault!=0)&&dut.perf_tlb_misses<1)||((expected_fault==0)&&(dut.perf_tlb_misses<2||dut.perf_walk_reads<4)))$fatal(1,"page walk missing");
   $display("PROTECTED_SHARED|status=PASS|commits=%0d|cycles=%0d|benchmark_cycles=%0d|k=%0d|batch=%0d|cache=%0d|rv32m=%0d|reset=%0d|host=1|dma=1|ptw=1|fabric=1",commits,cycles,benchmark_cycles,expected_k,expected_batch,USE_CACHE,CPU_ENABLE_M,reset_issued);$finish;end end
   if (ENABLE_CHIPLET)
     $fatal(1,"timeout pc=%08x mcause=%08x mtval=%08x paddr=%08x psel=%0b penable=%0b chip_sel=%0b instr=%08x commits=%0d chip_active=%0b chip_state=%0d chip_submit=%0d chip_comp=%0d chip_send=%0d chip_recv=%0d chip_link=%0b",
            commit_pc,dut.cpu.mcause_q,dut.cpu.mtval_q,dut.paddr,dut.psel,dut.penable,dut.chip_sel,dut.instr,commits,
            chip_active_debug,chip_state_debug,chip_submit_debug,chip_comp_debug,
            chip_send_debug,chip_recv_debug,chip_link_debug);
   else
     $fatal(1,"timeout pc=%08x mcause=%08x mtval=%08x paddr=%08x psel=%0b penable=%0b instr=%08x commits=%0d",commit_pc,dut.cpu.mcause_q,dut.cpu.mtval_q,dut.paddr,dut.psel,dut.penable,dut.instr,commits);
 end
endmodule
