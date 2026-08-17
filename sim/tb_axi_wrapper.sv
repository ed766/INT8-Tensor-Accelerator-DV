`timescale 1ns/1ps
module tb_axi_wrapper;
  logic clk=0,rst_n=0; always #5 clk<=~clk;
  logic [7:0] s_axil_awaddr; logic s_axil_awvalid,s_axil_awready;
  logic [31:0] s_axil_wdata; logic [3:0] s_axil_wstrb; logic s_axil_wvalid,s_axil_wready;
  logic [1:0] s_axil_bresp; logic s_axil_bvalid,s_axil_bready;
  logic [7:0] s_axil_araddr; logic s_axil_arvalid,s_axil_arready;
  logic [31:0] s_axil_rdata; logic [1:0] s_axil_rresp; logic s_axil_rvalid,s_axil_rready;
  logic [31:0] s_axis_tdata; logic [7:0] s_axis_tuser; logic s_axis_tvalid,s_axis_tready;
  logic [31:0] m_axis_tdata; logic [7:0] m_axis_tuser; logic m_axis_tvalid,m_axis_tready;
  logic irq_error; integer checks=0,failures=0;
  int8_accel_axi_wrapper dut(.*);

  task automatic axi_write(input logic [7:0] addr,input logic [31:0] data,input logic [3:0] strb,
                           input int order,input logic [1:0] expected);
    if(order==1)begin @(negedge clk);s_axil_awaddr=addr;s_axil_awvalid=1;do @(posedge clk);while(!s_axil_awready);@(negedge clk);s_axil_awvalid=0;repeat(2)@(posedge clk);end
    if(order==2)begin @(negedge clk);s_axil_wdata=data;s_axil_wstrb=strb;s_axil_wvalid=1;do @(posedge clk);while(!s_axil_wready);@(negedge clk);s_axil_wvalid=0;repeat(2)@(posedge clk);end
    @(negedge clk);
    if(order!=1)begin s_axil_awaddr=addr;s_axil_awvalid=1;end
    if(order!=2)begin s_axil_wdata=data;s_axil_wstrb=strb;s_axil_wvalid=1;end
    do @(posedge clk);while((order!=1&&!s_axil_awready)||(order!=2&&!s_axil_wready));
    @(negedge clk);s_axil_awvalid=0;s_axil_wvalid=0;
    wait(s_axil_bvalid); checks++;
    if(s_axil_bresp!==expected)begin failures++;$display("AXI_CHECK|name=write_%02x|status=FAIL",addr);end
    else $display("AXI_CHECK|name=write_%02x|status=PASS",addr);
    if(expected==2'b00)begin
      if(order==0)$display("AXI_COVER|point=write_order_simultaneous");
      else if(order==1)$display("AXI_COVER|point=write_order_aw_first");
      else $display("AXI_COVER|point=write_order_w_first");
    end
    @(posedge clk);
  endtask
  task automatic axi_read(input logic [7:0] addr,input logic [1:0] expected_resp,output logic [31:0] data);
    @(negedge clk);s_axil_araddr=addr;s_axil_arvalid=1;do @(posedge clk);while(!s_axil_arready);
    @(negedge clk);s_axil_arvalid=0;wait(s_axil_rvalid);data=s_axil_rdata;checks++;
    if(s_axil_rresp!==expected_resp)begin failures++;$display("AXI_CHECK|name=read_%02x|status=FAIL",addr);end
    else $display("AXI_CHECK|name=read_%02x|status=PASS",addr);
    @(posedge clk);
  endtask
  task automatic configure(input int kind,input int output_idx,input int index,input logic [31:0] data);
    logic [31:0] select_word;
    select_word=(index<<6)|(output_idx<<4)|kind;
    axi_write(8'h00,select_word,4'hf,(index+output_idx)%3,2'b00);
    axi_write(8'h04,data,4'hf,0,2'b00);
  endtask
  initial begin
    s_axil_awvalid=0;s_axil_wvalid=0;s_axil_bready=1;s_axil_arvalid=0;s_axil_rready=1;
    s_axis_tvalid=0;s_axis_tdata=0;s_axis_tuser=0;m_axis_tready=0;
    repeat(4)@(posedge clk);rst_n=1;
    for(int output_idx=0;output_idx<4;output_idx++)begin
      for(int lane=0;lane<4;lane++)configure(0,output_idx,lane,lane==output_idx?1:0);
      configure(1,output_idx,0,0); configure(2,output_idx,0,1); configure(3,output_idx,0,0);
    end
    axi_write(8'h08,(8'h5a<<8)|(4<<1),4'hf,0,2'b00);
    @(negedge clk);s_axis_tvalid=1;s_axis_tuser=8'h5a;s_axis_tdata=32'h04030201;
    do @(posedge clk);while(!s_axis_tready);@(negedge clk);s_axis_tvalid=0;
    wait(m_axis_tvalid);repeat(3)@(posedge clk);checks++;
    $display("AXI_COVER|point=axis_output_backpressure");
    if(m_axis_tdata!==32'h04030201||m_axis_tuser!==8'h5a)begin failures++;$display("AXI_CHECK|name=stream_result|status=FAIL");end
    else $display("AXI_CHECK|name=stream_result|status=PASS");
    @(negedge clk);m_axis_tready=1;@(posedge clk);@(negedge clk);m_axis_tready=0;
    begin logic[31:0] value;axi_read(8'h10,0,value);checks++;if(value!=1)begin failures++;$display("AXI_CHECK|name=accepted_counter|status=FAIL");end else $display("AXI_CHECK|name=accepted_counter|status=PASS");
      axi_read(8'h14,0,value);checks++;if(value!=1)begin failures++;$display("AXI_CHECK|name=completed_counter|status=FAIL");end else $display("AXI_CHECK|name=completed_counter|status=PASS");end
    $display("AXI_COVER|point=counter_readback");
    axi_write(8'h04,32'hdeadbeef,4'h3,0,2'b10);
    $display("AXI_COVER|point=partial_strobe_slverr");
    axi_write(8'h48,32'h0,4'hf,0,2'b10);
    $display("AXI_COVER|point=unmapped_write_slverr");
    begin logic[31:0] value;axi_read(8'h42,2'b10,value);end
    $display("AXI_COVER|point=unaligned_read_slverr");
    checks++;if(!irq_error)begin failures++;$display("AXI_CHECK|name=sticky_error|status=FAIL");end else $display("AXI_CHECK|name=sticky_error|status=PASS");
    axi_write(8'h28,1,4'hf,0,0);checks++;if(irq_error)begin failures++;$display("AXI_CHECK|name=clear_error|status=FAIL");end else $display("AXI_CHECK|name=clear_error|status=PASS");
    $display("AXI_COVER|point=sticky_error_w1c");
    $display("AXI_SUMMARY|checks=%0d|failures=%0d",checks,failures);if(failures)$fatal(1,"AXI wrapper failed");$finish;
  end
  initial begin repeat(20000)@(posedge clk);$fatal(1,"timeout");end
endmodule
