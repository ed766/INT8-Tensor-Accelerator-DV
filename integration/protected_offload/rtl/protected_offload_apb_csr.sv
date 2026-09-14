`timescale 1ns/1ps

module protected_offload_apb_csr (
  input logic clk,
  input logic rst_n,
  input logic [11:0] paddr,
  input logic psel,
  input logic penable,
  input logic pwrite,
  input logic [31:0] pwdata,
  output logic [31:0] prdata,
  output logic pready,
  output logic pslverr,
  output logic submit_valid,
  input logic submit_ready,
  output logic [31:0] submit_input_iova,
  output logic [31:0] submit_output_iova,
  output logic [15:0] submit_input_stride,
  output logic [15:0] submit_output_stride,
  output logic [6:0] submit_k,
  output logic [6:0] submit_batch,
  output logic [7:0] submit_tag,
  output logic [7:0] submit_asid,
  output logic submit_bank,
  output logic [7:0] submit_bank_generation,
  output logic [3:0] submit_qos,
  input logic submit_accepted,
  input logic submit_rejected,
  input logic busy,
  input logic [2:0] submit_occupancy,
  input logic completion_valid,
  output logic completion_ready,
  input logic [7:0] completion_tag,
  input logic [3:0] completion_status,
  input logic [7:0] completion_asid,
  input logic [31:0] completion_fault_iova,
  input logic [2:0] completion_fault_stage,
  input logic [6:0] completion_vectors_done,
  input logic [2:0] completion_occupancy,
  input logic irq
);
  logic sticky_submit_reject;
  logic access;

  assign access = psel && penable;
  assign pready = access;

  always_comb begin
    pslverr = 1'b0;
    prdata = 32'd0;
    if (access) begin
      case (paddr)
        12'h000: prdata = submit_input_iova;
        12'h004: prdata = submit_output_iova;
        12'h008: prdata = {submit_output_stride, submit_input_stride};
        12'h00c: prdata = {18'd0, submit_batch, submit_k};
        12'h010: prdata = {7'd0, submit_bank_generation, submit_bank, submit_asid, submit_tag};
        12'h014: prdata = {28'd0, submit_qos};
        12'h01c: prdata = {22'd0, completion_occupancy, submit_occupancy,
                          sticky_submit_reject, irq, busy, submit_ready};
        12'h020: prdata = {13'd0, completion_vectors_done, completion_asid,
                          completion_status};
        12'h024: prdata = completion_fault_iova;
        12'h028: prdata = {21'd0, completion_fault_stage, completion_tag};
        12'h018, 12'h02c, 12'h030: prdata = 32'd0;
        default: pslverr = 1'b1;
      endcase
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      submit_input_iova <= 32'd0;
      submit_output_iova <= 32'd0;
      submit_input_stride <= 16'd0;
      submit_output_stride <= 16'd0;
      submit_k <= 7'd0;
      submit_batch <= 7'd0;
      submit_tag <= 8'd0;
      submit_asid <= 8'd0;
      submit_bank <= 1'b0;
      submit_bank_generation <= 8'd0;
      submit_qos <= 4'd0;
      submit_valid <= 1'b0;
      completion_ready <= 1'b0;
      sticky_submit_reject <= 1'b0;
    end else begin
      submit_valid <= 1'b0;
      completion_ready <= 1'b0;
      if (submit_rejected) sticky_submit_reject <= 1'b1;
      if (submit_accepted) sticky_submit_reject <= 1'b0;
      if (access && pwrite && !pslverr) begin
        case (paddr)
          12'h000: submit_input_iova <= pwdata;
          12'h004: submit_output_iova <= pwdata;
          12'h008: begin
            submit_input_stride <= pwdata[15:0];
            submit_output_stride <= pwdata[31:16];
          end
          12'h00c: begin submit_k <= pwdata[6:0]; submit_batch <= pwdata[13:7]; end
          12'h010: begin
            submit_tag <= pwdata[7:0];
            submit_asid <= pwdata[15:8];
            submit_bank <= pwdata[16];
            submit_bank_generation <= pwdata[24:17];
          end
          12'h014: submit_qos <= pwdata[3:0];
          12'h018: submit_valid <= 1'b1;
          12'h02c: completion_ready <= completion_valid;
          12'h030: sticky_submit_reject <= sticky_submit_reject && !pwdata[0];
          default: begin end
        endcase
      end
    end
  end

`ifndef SYNTHESIS
  a_one_doorbell_pulse: assert property (@(posedge clk) disable iff (!rst_n)
    submit_valid |=> !submit_valid);
  a_one_completion_pop_pulse: assert property (@(posedge clk) disable iff (!rst_n)
    completion_ready |=> !completion_ready);
  a_no_pop_without_completion: assert property (@(posedge clk) disable iff (!rst_n)
    completion_ready |-> completion_valid);
`endif
endmodule
