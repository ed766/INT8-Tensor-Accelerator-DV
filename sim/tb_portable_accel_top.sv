`timescale 1ns/1ps
module tb_portable_accel_top;
 logic clk=0,rst_n=0;always #5 clk<=~clk;
 logic record_valid,record_ready;logic[63:0]record_data;logic result_valid,result_ready;logic[31:0]result_data;logic[7:0]result_tag;
 logic expect_valid,expect_ready;logic[31:0]expect_data;logic[7:0]expect_tag,expect_stall;logic stream_done,malformed,cmd_error;
 logic[31:0]monitor_accepted,monitor_completed;logic monitor_error;
 logic[63:0]records[0:1023];string vector_file;integer vector_count,index,checks=0,failures=0;
 int8_portable_accel_top dut(.*);
 initial begin
  if(!$value$plusargs("VECTOR_FILE=%s",vector_file)||!$value$plusargs("VECTOR_COUNT=%d",vector_count))$fatal(1,"vectors required");
  $readmemh(vector_file,records,0,vector_count-1);record_valid=0;record_data=0;result_ready=0;expect_ready=0;
  repeat(4)@(posedge clk);rst_n=1;index=0;
  while(index<vector_count)begin
   @(negedge clk);record_valid=1;record_data=records[index];
   if(records[index][63:60]==4'h3)begin
    do @(posedge clk);while(!expect_valid);
    repeat(expect_stall)@(posedge clk);@(negedge clk);result_ready=1;expect_ready=1;
    do @(posedge clk);while(!(result_valid&&expect_valid));checks++;
    if(result_data!==expect_data||result_tag!==expect_tag)begin failures++;$display("PORTABLE_TOP_CHECK|case=%0d|status=FAIL",checks-1);end
    else $display("PORTABLE_TOP_CHECK|case=%0d|status=PASS",checks-1);
    @(negedge clk);result_ready=0;expect_ready=0;record_valid=0;index++;
   end else begin
    do @(posedge clk);while(!record_ready);@(negedge clk);record_valid=0;index++;
   end
  end
  repeat(3)@(posedge clk);
  if(malformed||cmd_error||monitor_error||monitor_accepted!=checks||monitor_completed!=checks)failures++;
  if(!failures)$display("AXI_COVER|point=portable_end_to_end_replay");
  $display("PORTABLE_TOP_SUMMARY|checks=%0d|failures=%0d",checks,failures);if(failures)$fatal(1,"portable top failed");$finish;
 end
 initial begin repeat(30000)@(posedge clk);$fatal(1,"timeout");end
endmodule
