`timescale 1ns/1ps
module protected_cache_maintenance_apb(
 input logic clk,input logic rst_n,input logic[5:0]paddr,input logic psel,input logic penable,input logic pwrite,input logic[31:0]pwdata,
 output logic[31:0]prdata,output logic pready,output logic pslverr,output logic maint_valid,input logic maint_ready,output logic[1:0]maint_cmd,input logic maint_busy,input logic maint_done,input logic maint_error);
 logic waiting;
`ifdef PROTECTED_MUT_FALSE_MAINTENANCE
 assign maint_valid=1'b0;
`else
 assign maint_valid=psel&&penable&&pwrite&&paddr==6'h04&&!waiting;
`endif
 always_comb begin prdata=0;pslverr=0;pready=psel&&penable&&!waiting;if(psel&&penable)case(paddr)6'h00:prdata={30'd0,maint_cmd};6'h04:begin
`ifdef PROTECTED_MUT_FALSE_MAINTENANCE
 pready=1'b1;pslverr=1'b0;
`else
 pready=maint_done;pslverr=maint_done&&maint_error;
`endif
 end 6'h08:prdata={29'd0,maint_error,maint_busy,waiting};default:pslverr=1;endcase end
 always_ff@(posedge clk or negedge rst_n)if(!rst_n)begin maint_cmd<=0;waiting<=0;end else begin if(psel&&penable&&pwrite&&paddr==0)maint_cmd<=pwdata[1:0];if(maint_valid&&maint_ready)waiting<=1;if(maint_done)waiting<=0;end
endmodule
