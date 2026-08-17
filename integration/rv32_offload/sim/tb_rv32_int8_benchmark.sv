`timescale 1ns/1ps
module tb_rv32_int8_benchmark;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic firmware_done,commit_valid,halted;logic[31:0]firmware_result,commit_pc,commit_instr;
  logic[31:0]benchmark_stats[0:15];integer cycles=0;string wave_file;integer expect_batch=1,expect_k=4;
  logic previous_out_valid=0;
  rv32_int8_benchmark_top dut(.*);
  always @(posedge clk) begin
    if (rst_n && dut.awvalid && dut.awready && dut.awaddr==8'h08)
      $display("BENCH_EVENT|cycle=%0d|event=command_aw",cycles);
    if (rst_n && dut.axis_in_valid && dut.axis_in_ready)
      $display("BENCH_EVENT|cycle=%0d|event=input_chunk",cycles);
    if (rst_n && dut.axis_out_valid && !previous_out_valid)
      $display("BENCH_EVENT|cycle=%0d|event=result_valid",cycles);
    if (rst_n && dut.axis_out_valid && dut.axis_out_ready)
      $display("BENCH_EVENT|cycle=%0d|event=result_pop",cycles);
    if (rst_n && firmware_done)
      $display("BENCH_EVENT|cycle=%0d|event=firmware_done",cycles);
    previous_out_valid <= dut.axis_out_valid;
  end
  initial begin
    wave_file="";
    void'($value$plusargs("EXPECT_BATCH=%d",expect_batch));
    void'($value$plusargs("EXPECT_K=%d",expect_k));
    if($value$plusargs("WAVE_FILE=%s",wave_file))begin $dumpfile(wave_file);$dumpvars(0,tb_rv32_int8_benchmark);end
    repeat(5)@(posedge clk);rst_n=1;
    while(!firmware_done && cycles<8000000)begin @(posedge clk);cycles++;
      if(commit_valid && cycles<20)$display("RV32_COMMIT|pc=%08x|insn=%08x",commit_pc,commit_instr);
    end
    if(!firmware_done)$fatal(1,"benchmark timeout");
    $display("BENCH_RESULT|result=%08x|cycles=%0d|scalar_cycles=%0d|accel_cycles=%0d|scalar_instret=%0d|accel_instret=%0d|counter_overhead=%0d|compute_latency=%0d|active_cycles=%0d|input_stalls=%0d|output_stalls=%0d|accepted=%0d|completed=%0d|chunks=%0d|configuration_cycles=%0d|stream_cycles=%0d|poll_cycles=%0d|output_read_cycles=%0d",
      firmware_result,cycles,benchmark_stats[0],benchmark_stats[1],benchmark_stats[2],benchmark_stats[3],benchmark_stats[4],benchmark_stats[5],benchmark_stats[6],benchmark_stats[7],benchmark_stats[8],benchmark_stats[9],benchmark_stats[10],benchmark_stats[11],benchmark_stats[12],benchmark_stats[13],benchmark_stats[14],benchmark_stats[15]);
    $display("BENCH_COUNTERS|mcycle=%0d|minstret=%0d",dut.cpu.mcycle_q,dut.cpu.minstret_q);
    if(firmware_result[31:16]!=16'h600d)$fatal(1,"firmware comparison failed: %08x",firmware_result);
    if(benchmark_stats[9]!=expect_batch || benchmark_stats[10]!=expect_batch)
      $fatal(1,"command accounting mismatch accepted=%0d completed=%0d expected=%0d",benchmark_stats[9],benchmark_stats[10],expect_batch);
    if(benchmark_stats[11]!=(expect_batch*(expect_k/4)))
      $fatal(1,"chunk accounting mismatch chunks=%0d expected=%0d",benchmark_stats[11],expect_batch*(expect_k/4));
    if(benchmark_stats[5]==0)$fatal(1,"latency counter did not progress");
    $finish;
  end
endmodule
