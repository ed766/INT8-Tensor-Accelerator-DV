`timescale 1ns/1ps

// Firmware-visible invalidate request register.  The request is retained
// until the DMA and page walker are idle, preventing a context update from
// racing an accepted translation or payload access.
module protected_tlb_control_apb (
  input logic clk, input logic rst_n,
  input logic [7:0] paddr, input logic psel, input logic penable, input logic pwrite,
  input logic [31:0] pwdata, output logic [31:0] prdata, output logic pready,
  output logic pslverr, input logic translation_idle, input logic service_busy,
  input logic [2:0] submit_occupancy, input logic [2:0] completion_occupancy,
  output logic inv_valid, output logic inv_all, output logic [7:0] inv_asid,
  output logic block_submissions
);
  logic pending;
  logic access;
  assign access = psel && penable;
  assign pready = access && (!pwrite || paddr != 8'h00 || !pending);
  assign pslverr = access && (paddr != 8'h00 && paddr != 8'h04);
  assign block_submissions = pending || (access && pwrite && paddr == 8'h00 && pwdata[0]);
  assign inv_valid = pending && translation_idle && !service_busy &&
                     submit_occupancy == 0 && completion_occupancy == 0;
  always_comb begin
    prdata = '0;
    if (access && paddr == 8'h04) prdata = {22'd0, inv_asid, inv_all, pending};
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin pending <= 1'b0; inv_all <= 1'b0; inv_asid <= '0; end
    else begin
      if (access && pwrite && paddr == 8'h00 && !pending) begin
        pending <= pwdata[0]; inv_all <= pwdata[1]; inv_asid <= pwdata[15:8];
      end
      if (inv_valid) pending <= 1'b0;
    end
  end
`ifndef SYNTHESIS
  a_invalidate_only_when_drained: assert property (@(posedge clk) disable iff(!rst_n)
    inv_valid |-> translation_idle && !service_busy &&
      submit_occupancy == 0 && completion_occupancy == 0);
  a_request_remains_pending: assert property (@(posedge clk) disable iff(!rst_n)
    pending && !inv_valid |=> pending);
`endif
endmodule
