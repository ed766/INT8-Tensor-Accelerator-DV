`timescale 1ns/1ps

module int8_portable_record_decoder (
  input logic clk, input logic rst_n,
  input logic record_valid, output logic record_ready, input logic [63:0] record_data,
  output logic cfg_valid, input logic cfg_ready, output logic [2:0] cfg_kind,
  output logic cfg_bank, output logic [1:0] cfg_output, output logic [5:0] cfg_index,
  output logic [31:0] cfg_data,
  output logic cmd_valid, input logic cmd_ready, output logic cmd_bank,
  output logic [6:0] cmd_k, output logic [7:0] cmd_tag,
  output logic in_valid, input logic in_ready, output logic [31:0] in_data,
  output logic [7:0] in_tag,
  output logic expect_valid, input logic expect_ready, output logic [31:0] expect_data,
  output logic [7:0] expect_tag, output logic [7:0] expect_stall,
  output logic done, output logic malformed
);
  logic [7:0] pending_stall;
  always_comb begin
    cfg_valid = 0; cmd_valid = 0; in_valid = 0; expect_valid = 0; done = 0; malformed = 0;
    cfg_bank = record_data[59]; cfg_kind = record_data[58:56];
    cfg_output = record_data[55:54]; cfg_index = record_data[53:48]; cfg_data = record_data[47:16];
    cmd_bank = record_data[59]; cmd_k = record_data[58:52]; cmd_tag = record_data[51:44];
    in_tag = record_data[55:48]; in_data = record_data[31:0];
    expect_tag = record_data[55:48]; expect_data = record_data[31:0]; expect_stall = pending_stall;
    record_ready = 0;
    case (record_data[63:60])
      4'h0: begin cfg_valid = record_valid; record_ready = cfg_ready; end
      4'h1: begin cmd_valid = record_valid; record_ready = cmd_ready; end
      4'h2: begin in_valid = record_valid; record_ready = in_ready; end
      4'h3: begin expect_valid = record_valid; record_ready = expect_ready; end
      4'h4: record_ready = 1;
      4'hf: begin done = record_valid; record_ready = 1; end
      default: begin malformed = record_valid; record_ready = 1; end
    endcase
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pending_stall <= 0;
    else if (record_valid && record_ready && record_data[63:60] == 4'h4)
      pending_stall <= record_data[55:48];
    else if (record_valid && record_ready && record_data[63:60] == 4'h3)
      pending_stall <= 0;
  end
endmodule
