`timescale 1ns/1ps

// Converts the DMA's one-at-a-time 32-bit memory requests into legal
// single-beat accesses on the 64-bit AXI subset used by the portfolio fabric.
module protected_dma_axi_adapter #(
  parameter logic [3:0] AXI_ID = 4'h1
) (
  input  logic clk,
  input  logic rst_n,
  input  logic req_valid,
  output logic req_ready,
  input  logic req_write,
  input  logic [31:0] req_addr,
  input  logic [31:0] req_wdata,
  input  logic [3:0] req_wstrb,
  input  logic [3:0] req_qos,
  output logic rsp_valid,
  input  logic rsp_ready,
  output logic [31:0] rsp_rdata,
  output logic rsp_error,

  output logic awvalid,
  input  logic awready,
  output logic [3:0] awid,
  output logic [31:0] awaddr,
  output logic [7:0] awlen,
  output logic [2:0] awsize,
  output logic [1:0] awburst,
  output logic [2:0] awprot,
  output logic [3:0] awqos,
  output logic wvalid,
  input  logic wready,
  output logic [63:0] wdata,
  output logic [7:0] wstrb,
  output logic wlast,
  input  logic bvalid,
  output logic bready,
  input  logic [3:0] bid,
  input  logic [1:0] bresp,
  output logic arvalid,
  input  logic arready,
  output logic [3:0] arid,
  output logic [31:0] araddr,
  output logic [7:0] arlen,
  output logic [2:0] arsize,
  output logic [1:0] arburst,
  output logic [2:0] arprot,
  output logic [3:0] arqos,
  input  logic rvalid,
  output logic rready,
  input  logic [3:0] rid,
  input  logic [63:0] rdata,
  input  logic [1:0] rresp,
  input  logic rlast
);
  typedef enum logic [2:0] {IDLE, WRITE_SEND, WRITE_RESP, READ_SEND, READ_RESP, RESPOND} state_t;
  state_t state;
  logic [31:0] address_q, write_data_q;
  logic [3:0] write_strobe_q, qos_q;
  logic upper_q, aw_done, w_done;

  assign req_ready = state == IDLE;
  assign rsp_valid = state == RESPOND;
  assign awvalid = state == WRITE_SEND && !aw_done;
  assign wvalid = state == WRITE_SEND && !w_done;
  assign bready = state == WRITE_RESP;
  assign arvalid = state == READ_SEND;
  assign rready = state == READ_RESP;
  assign awid = AXI_ID;
  assign arid = AXI_ID;
  assign awaddr = {address_q[31:2], 2'b00};
  assign araddr = {address_q[31:2], 2'b00};
  assign awlen = 8'd0;
  assign arlen = 8'd0;
  assign awsize = 3'd2;
  assign arsize = 3'd2;
  assign awburst = 2'b01;
  assign arburst = 2'b01;
  assign awprot = 3'b000;
  assign arprot = 3'b000;
  assign awqos = qos_q;
  assign arqos = qos_q;
  assign wdata = upper_q ? {write_data_q, 32'd0} : {32'd0, write_data_q};
  assign wstrb = upper_q ? {write_strobe_q, 4'd0} : {4'd0, write_strobe_q};
  assign wlast = 1'b1;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      address_q <= '0;
      write_data_q <= '0;
      write_strobe_q <= '0;
      qos_q <= '0;
      upper_q <= 1'b0;
      aw_done <= 1'b0;
      w_done <= 1'b0;
      rsp_rdata <= '0;
      rsp_error <= 1'b0;
    end else begin
      case (state)
        IDLE: if (req_valid) begin
          address_q <= req_addr;
          write_data_q <= req_wdata;
          write_strobe_q <= req_wstrb;
          qos_q <= req_qos;
          upper_q <= req_addr[2];
          rsp_error <= 1'b0;
          aw_done <= 1'b0;
          w_done <= 1'b0;
          state <= req_write ? WRITE_SEND : READ_SEND;
        end
        WRITE_SEND: begin
          if (awvalid && awready) aw_done <= 1'b1;
          if (wvalid && wready) w_done <= 1'b1;
          if ((aw_done || (awvalid && awready)) && (w_done || (wvalid && wready)))
            state <= WRITE_RESP;
        end
        WRITE_RESP: if (bvalid) begin
          rsp_error <= bresp != 2'b00 || bid != AXI_ID;
          state <= RESPOND;
        end
        READ_SEND: if (arvalid && arready) state <= READ_RESP;
        READ_RESP: if (rvalid) begin
          rsp_rdata <= upper_q ? rdata[63:32] : rdata[31:0];
          rsp_error <= rresp != 2'b00 || rid != AXI_ID || !rlast;
          state <= RESPOND;
        end
        RESPOND: if (rsp_ready) state <= IDLE;
        default: state <= IDLE;
      endcase
    end
  end

`ifndef SYNTHESIS
  a_aw_stable: assert property (@(posedge clk) disable iff (!rst_n)
    awvalid && !awready |=> !awvalid || $stable({awid,awaddr,awlen,awsize,awburst,awprot,awqos}));
  a_w_stable: assert property (@(posedge clk) disable iff (!rst_n)
    wvalid && !wready |=> !wvalid || $stable({wdata,wstrb,wlast}));
  a_ar_stable: assert property (@(posedge clk) disable iff (!rst_n)
    arvalid && !arready |=> !arvalid || $stable({arid,araddr,arlen,arsize,arburst,arprot,arqos}));
  a_single_beat_last: assert property (@(posedge clk) disable iff (!rst_n) wvalid |-> wlast);
  a_aligned_aw_address: assert property (@(posedge clk) disable iff (!rst_n)
    awvalid |-> awaddr[1:0] == 0);
  a_aligned_ar_address: assert property (@(posedge clk) disable iff (!rst_n)
    arvalid |-> araddr[1:0] == 0);
  a_response_stable: assert property (@(posedge clk) disable iff (!rst_n)
    rsp_valid && !rsp_ready |=> !rsp_valid || $stable({rsp_rdata,rsp_error}));
`endif
endmodule
