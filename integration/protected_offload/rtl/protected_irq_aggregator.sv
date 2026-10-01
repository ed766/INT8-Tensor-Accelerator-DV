`timescale 1ns/1ps
module protected_irq_aggregator (
  input logic clk, input logic rst_n,
  input logic chiplet_dma_event,
  input logic accelerator_event,
  input logic device_fault_event,
  input logic [5:0] paddr,
  input logic psel, input logic penable, input logic pwrite,
  input logic [31:0] pwdata,
  output logic [31:0] prdata, output logic pready, output logic pslverr,
  output logic irq_ext,
  output logic [2:0] raw_status,
  output logic [2:0] pending_status,
  output logic [2:0] enable_mask
);
  logic [2:0] events, acknowledge;
  logic [2:0] acknowledged_events_q;
  logic access;
  assign events={device_fault_event,accelerator_event,chiplet_dma_event};
  assign access=psel&&penable;
  assign pready=access;
  assign pending_status=raw_status&enable_mask;
  assign irq_ext=|pending_status;

  always_comb begin
    prdata='0;pslverr=1'b0;acknowledge='0;
    if(access) begin
      unique case(paddr)
        6'h00:prdata={29'd0,raw_status};
        6'h04:prdata={29'd0,pending_status};
        6'h08:prdata={29'd0,enable_mask};
        6'h0c:begin prdata='0;if(pwrite)acknowledge=pwdata[2:0];end
        default:pslverr=1'b1;
      endcase
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin raw_status<='0;enable_mask<='0;end
    else begin
      // New events win over a simultaneous W1C acknowledgement.
`ifdef PROTECTED_MUT_LOST_SIMULTANEOUS_IRQ
      raw_status<=(raw_status&~acknowledge)|(events&~acknowledge);
`else
      raw_status<=(raw_status&~acknowledge)|events;
`endif
      if(access&&pwrite&&!pslverr&&paddr==6'h08)enable_mask<=pwdata[2:0];
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) acknowledged_events_q <= '0;
    else acknowledged_events_q <= events & acknowledge;
  end

`ifndef SYNTHESIS
  a_set_dominates_ack: assert property(@(posedge clk) disable iff(!rst_n)
    (|acknowledged_events_q) |-> (|(raw_status & acknowledged_events_q)));
  a_irq_matches_enabled_pending: assert property(@(posedge clk) disable iff(!rst_n)
    irq_ext==|(raw_status&enable_mask));
`endif
endmodule
