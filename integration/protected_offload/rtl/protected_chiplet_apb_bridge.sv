`timescale 1ns/1ps

// Converts a standard APB access into the chiplet's request/ready CSR
// interface.  Capturing setup/access controls prevents a PREADY-high target
// from creating a setup-phase side effect or a duplicate request while APB
// waits for the slave response.
module protected_chiplet_apb_bridge (
  input logic clk, input logic rst_n,
  input logic psel, input logic penable, input logic pwrite,
  input logic [31:0] paddr, input logic [31:0] pwdata,
  output logic [31:0] prdata, output logic pready, output logic pslverr,
  output logic cfg_valid, output logic cfg_write, output logic [7:0] cfg_addr,
  output logic [31:0] cfg_wdata, input logic [31:0] cfg_rdata,
  input logic cfg_ready
);
  typedef enum logic {IDLE, ISSUE} state_t;
  state_t state;
  logic write_q;
  logic [7:0] addr_q;
  logic [31:0] wdata_q;

  assign cfg_valid = state == ISSUE;
  assign cfg_write = write_q;
  assign cfg_addr = addr_q;
  assign cfg_wdata = wdata_q;
  assign prdata = cfg_rdata;
  assign pready = (state == ISSUE) && cfg_ready;
  assign pslverr = 1'b0;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      write_q <= 1'b0;
      addr_q <= '0;
      wdata_q <= '0;
    end else begin
      case (state)
        IDLE: if (psel && penable) begin
          write_q <= pwrite;
          addr_q <= paddr[7:0];
          wdata_q <= pwdata;
          state <= ISSUE;
        end
        ISSUE: if (cfg_ready) state <= IDLE;
      endcase
    end
  end

`ifndef SYNTHESIS
  a_cfg_stable_while_waiting: assert property (@(posedge clk) disable iff (!rst_n)
    cfg_valid && !cfg_ready |=> $stable({cfg_write, cfg_addr, cfg_wdata}));
  a_no_setup_phase_completion: assert property (@(posedge clk) disable iff (!rst_n)
    psel && !penable |-> !pready && !cfg_valid);
`endif
endmodule
