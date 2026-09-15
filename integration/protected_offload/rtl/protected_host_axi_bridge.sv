`timescale 1ns/1ps

// Converts one wait-stated RV32 APB word access into one 64-bit AXI transfer.
module protected_host_axi_bridge #(
  parameter logic [3:0] AXI_ID = 4'h0
) (
  input logic clk, input logic rst_n,
  input logic psel, input logic penable, input logic pwrite,
  input logic [31:0] paddr, input logic [31:0] pwdata,
  output logic [31:0] prdata, output logic pready, output logic pslverr,
  output logic awvalid, input logic awready, output logic [3:0] awid,
  output logic [31:0] awaddr, output logic [7:0] awlen,
  output logic [2:0] awsize, output logic [1:0] awburst,
  output logic [2:0] awprot, output logic [3:0] awqos,
  output logic wvalid, input logic wready, output logic [63:0] wdata,
  output logic [7:0] wstrb, output logic wlast,
  input logic bvalid, output logic bready, input logic [3:0] bid,
  input logic [1:0] bresp,
  output logic arvalid, input logic arready, output logic [3:0] arid,
  output logic [31:0] araddr, output logic [7:0] arlen,
  output logic [2:0] arsize, output logic [1:0] arburst,
  output logic [2:0] arprot, output logic [3:0] arqos,
  input logic rvalid, output logic rready, input logic [3:0] rid,
  input logic [63:0] rdata, input logic [1:0] rresp, input logic rlast
);
  typedef enum logic [1:0] {IDLE, WAIT_RSP, COMPLETE} state_t;
  state_t state;
  logic req_valid, req_ready, rsp_valid, rsp_ready, rsp_error;
  logic [31:0] rsp_rdata;

  assign req_valid = state == IDLE && psel && penable;
  assign rsp_ready = state == WAIT_RSP && psel && penable;
  assign pready = state == WAIT_RSP && rsp_valid;
  assign pslverr = pready && rsp_error;
  assign prdata = rsp_rdata;

  protected_dma_axi_adapter #(.AXI_ID(AXI_ID)) adapter (
    .clk, .rst_n, .req_valid, .req_ready, .req_write(pwrite),
    .req_addr(paddr), .req_wdata(pwdata), .req_wstrb(4'hf),
    .req_qos(4'h8), .rsp_valid, .rsp_ready, .rsp_rdata, .rsp_error,
    .awvalid, .awready, .awid, .awaddr, .awlen, .awsize, .awburst,
    .awprot, .awqos, .wvalid, .wready, .wdata, .wstrb, .wlast,
    .bvalid, .bready, .bid, .bresp, .arvalid, .arready, .arid,
    .araddr, .arlen, .arsize, .arburst, .arprot, .arqos,
    .rvalid, .rready, .rid, .rdata, .rresp, .rlast
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) state <= IDLE;
    else case(state)
      IDLE: if(req_valid && req_ready) state <= WAIT_RSP;
      WAIT_RSP: if(rsp_valid && rsp_ready) state <= COMPLETE;
      COMPLETE: if(!psel) state <= IDLE;
      default: state <= IDLE;
    endcase
  end

`ifndef SYNTHESIS
  a_apb_stable_while_waiting: assert property (@(posedge clk) disable iff(!rst_n)
    psel && penable && !pready |=> !psel || $stable({paddr,pwrite,pwdata}));
  a_single_axi_request_per_apb: assert property (@(posedge clk) disable iff(!rst_n)
    state != IDLE |-> !req_valid);
  a_error_only_with_completion: assert property (@(posedge clk) disable iff(!rst_n)
    pslverr |-> pready);
`endif
endmodule
