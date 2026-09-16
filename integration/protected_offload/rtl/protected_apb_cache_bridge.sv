`timescale 1ns/1ps
module protected_apb_cache_bridge(
 input logic clk,input logic rst_n,input logic psel,input logic penable,input logic pwrite,input logic[31:0]paddr,input logic[31:0]pwdata,
 output logic[31:0]prdata,output logic pready,output logic pslverr,
 output logic cpu_req_valid,input logic cpu_req_ready,output logic[31:0]cpu_req_addr,output logic cpu_req_write,output logic[31:0]cpu_req_wdata,output logic[3:0]cpu_req_wstrb,output logic[2:0]cpu_req_size,output logic[7:0]cpu_req_id,
 input logic cpu_rsp_valid,output logic cpu_rsp_ready,input logic[31:0]cpu_rsp_rdata,input logic cpu_rsp_error);
 logic active;
 assign cpu_req_valid=psel&&penable&&!active;assign cpu_req_addr=paddr;assign cpu_req_write=pwrite;assign cpu_req_wdata=pwdata;assign cpu_req_wstrb=4'hf;assign cpu_req_size=2;assign cpu_req_id=8'hc0;
 assign cpu_rsp_ready=active&&psel&&penable;assign pready=cpu_rsp_valid&&cpu_rsp_ready;assign pslverr=pready&&cpu_rsp_error;
`ifdef PROTECTED_MUT_CACHE_RESPONSE_CORRUPT
 assign prdata=cpu_rsp_rdata^32'h1;
`else
 assign prdata=cpu_rsp_rdata;
`endif
 always_ff@(posedge clk or negedge rst_n)if(!rst_n)active<=0;else begin if(cpu_req_valid&&cpu_req_ready)active<=1;if(cpu_rsp_valid&&cpu_rsp_ready)active<=0;end
`ifndef SYNTHESIS
 a_one_request:assert property(@(posedge clk)disable iff(!rst_n)active|->!cpu_req_valid);
 a_waits_for_cache:assert property(@(posedge clk)disable iff(!rst_n)pready|->cpu_rsp_valid);
`endif
endmodule
