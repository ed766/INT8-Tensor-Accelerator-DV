`timescale 1ns/1ps

module apb_to_axil_bridge (
  input logic clk, input logic rst_n,
  input logic [31:0] paddr, input logic psel, input logic penable,
  input logic pwrite, input logic [31:0] pwdata,
  output logic [31:0] prdata, output logic pready, output logic pslverr,
  output logic [7:0] m_awaddr, output logic m_awvalid, input logic m_awready,
  output logic [31:0] m_wdata, output logic [3:0] m_wstrb,
  output logic m_wvalid, input logic m_wready,
  input logic [1:0] m_bresp, input logic m_bvalid, output logic m_bready,
  output logic [7:0] m_araddr, output logic m_arvalid, input logic m_arready,
  input logic [31:0] m_rdata, input logic [1:0] m_rresp,
  input logic m_rvalid, output logic m_rready
);
  typedef enum logic [2:0] {IDLE, WRITE_SEND, WRITE_RESP, READ_SEND, READ_RESP, WAIT_DROP} state_t;
  state_t state;
  logic aw_done, w_done;

  assign m_awaddr = paddr[7:0];
  assign m_wdata = pwdata;
  assign m_wstrb = 4'hf;
  assign m_araddr = paddr[7:0];
  assign m_awvalid = state == WRITE_SEND && !aw_done;
  assign m_wvalid = state == WRITE_SEND && !w_done;
  assign m_bready = state == WRITE_RESP;
  assign m_arvalid = state == READ_SEND;
  assign m_rready = state == READ_RESP;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE; aw_done <= 0; w_done <= 0;
      prdata <= 0; pready <= 0; pslverr <= 0;
    end else begin
      pready <= 0;
      pslverr <= 0;
      case (state)
        IDLE: if (psel && penable) begin
          aw_done <= 0; w_done <= 0;
          state <= pwrite ? WRITE_SEND : READ_SEND;
        end
        WRITE_SEND: begin
          if (m_awvalid && m_awready) aw_done <= 1;
          if (m_wvalid && m_wready) w_done <= 1;
          if ((aw_done || (m_awvalid && m_awready)) &&
              (w_done || (m_wvalid && m_wready))) state <= WRITE_RESP;
        end
        WRITE_RESP: if (m_bvalid) begin
          pready <= 1; pslverr <= m_bresp != 2'b00; state <= WAIT_DROP;
        end
        READ_SEND: if (m_arvalid && m_arready) state <= READ_RESP;
        READ_RESP: if (m_rvalid) begin
          prdata <= m_rdata; pready <= 1; pslverr <= m_rresp != 2'b00; state <= WAIT_DROP;
        end
        WAIT_DROP: if (!psel) state <= IDLE;
        default: state <= IDLE;
      endcase
    end
  end

`ifndef SYNTHESIS
  a_apb_stable_wait: assert property (@(posedge clk) disable iff (!rst_n)
    psel && penable && !pready |=> $stable({paddr,pwrite,pwdata}));
  a_one_response: assert property (@(posedge clk) disable iff (!rst_n)
    pready |=> !pready);
  a_no_reaccept_until_apb_drop: assert property (@(posedge clk) disable iff (!rst_n)
    state == WAIT_DROP && psel |-> !m_awvalid && !m_wvalid && !m_arvalid);
`endif
endmodule
