`timescale 1ns/1ps

module int8_tensor_accel #(
  parameter int LANES = 4,
  parameter int OUTPUTS = 4,
  parameter int TAG_W = 8
) (
  input  logic                         clk,
  input  logic                         rst_n,

  input  logic                         cfg_valid,
  output logic                         cfg_ready,
  input  logic [1:0]                   cfg_kind,
  input  logic [$clog2(OUTPUTS)-1:0]   cfg_output,
  input  logic [$clog2(LANES)-1:0]     cfg_lane,
  input  logic [31:0]                  cfg_data,

  input  logic                         in_valid,
  output logic                         in_ready,
  input  logic [LANES*8-1:0]           in_data,
  input  logic [TAG_W-1:0]             in_tag,

  output logic                         out_valid,
  input  logic                         out_ready,
  output logic [OUTPUTS*8-1:0]         out_data,
  output logic [TAG_W-1:0]             out_tag,

  output logic [31:0]                  perf_accepted,
  output logic [31:0]                  perf_completed,
  output logic [31:0]                  perf_output_stalls
);
  localparam logic [1:0] CFG_WEIGHT  = 2'd0;
  localparam logic [1:0] CFG_BIAS    = 2'd1;
  localparam logic [1:0] CFG_SCALE   = 2'd2;
  localparam logic [1:0] CFG_CONTROL = 2'd3;

  logic signed [7:0]  weights [0:OUTPUTS-1][0:LANES-1];
  logic signed [31:0] biases [0:OUTPUTS-1];
  logic signed [15:0] multipliers [0:OUTPUTS-1];
  logic [4:0]         shifts [0:OUTPUTS-1];
  logic               relu_enable [0:OUTPUTS-1];

  logic out_valid_q;
  logic [OUTPUTS*8-1:0] out_data_q;
  logic [TAG_W-1:0] out_tag_q;

  function automatic logic signed [7:0] requantize(
    input logic signed [31:0] accumulator,
    input logic signed [15:0] multiplier,
    input logic [4:0] shift,
    input logic relu
  );
    logic signed [63:0] product;
    logic signed [63:0] scaled;
    begin
      product = accumulator * multiplier;
      scaled = product >>> shift;
`ifdef MUT_RELU_BYPASS
      if (1'b0 && relu && (scaled < 0)) begin
`else
      if (relu && (scaled < 0)) begin
`endif
        scaled = 0;
      end
`ifdef MUT_SATURATION_WRAP
      requantize = scaled[7:0];
`else
      if (scaled > 127)
        requantize = 8'sd127;
      else if (scaled < -128)
        requantize = -8'sd128;
      else
        requantize = scaled[7:0];
`endif
    end
  endfunction

  assign cfg_ready = !out_valid_q && !in_valid;
  assign in_ready = !out_valid_q || out_ready;
  assign out_valid = out_valid_q;
  assign out_data = out_data_q;
`ifdef MUT_TAG_CORRUPT
  assign out_tag = out_tag_q ^ {{(TAG_W-1){1'b0}}, 1'b1};
`else
  assign out_tag = out_tag_q;
`endif

  integer output_index;
  integer lane_index;
  always_ff @(posedge clk or negedge rst_n) begin : accelerator_state
    logic signed [31:0] accumulator;
    logic signed [7:0] activation;
    logic signed [7:0] coefficient;
    if (!rst_n) begin
      out_valid_q <= 1'b0;
      out_data_q <= '0;
      out_tag_q <= '0;
      perf_accepted <= '0;
      perf_completed <= '0;
      perf_output_stalls <= '0;
      for (output_index = 0; output_index < OUTPUTS; output_index++) begin
        biases[output_index] <= '0;
        multipliers[output_index] <= 16'sd1;
        shifts[output_index] <= '0;
        relu_enable[output_index] <= 1'b0;
        for (lane_index = 0; lane_index < LANES; lane_index++)
          weights[output_index][lane_index] <= '0;
      end
    end else begin
      if (out_valid_q && out_ready) begin
        out_valid_q <= 1'b0;
        perf_completed <= perf_completed + 1'b1;
      end
      if (out_valid_q && !out_ready)
        perf_output_stalls <= perf_output_stalls + 1'b1;

      if (cfg_valid && cfg_ready) begin
        case (cfg_kind)
          CFG_WEIGHT: weights[cfg_output][cfg_lane] <= cfg_data[7:0];
          CFG_BIAS: biases[cfg_output] <= cfg_data;
          CFG_SCALE: begin
            multipliers[cfg_output] <= cfg_data[15:0];
            shifts[cfg_output] <= cfg_data[20:16];
          end
          CFG_CONTROL: relu_enable[cfg_output] <= cfg_data[0];
          default: begin end
        endcase
      end

      if (in_valid && in_ready) begin
        for (output_index = 0; output_index < OUTPUTS; output_index++) begin
          accumulator = biases[output_index];
          for (lane_index = 0; lane_index < LANES; lane_index++) begin
            activation = in_data[lane_index*8 +: 8];
            coefficient = weights[output_index][lane_index];
`ifdef MUT_UNSIGNED_MAC
            accumulator = accumulator + ($unsigned(activation) * $unsigned(coefficient));
`else
            accumulator = accumulator + (activation * coefficient);
`endif
          end
          out_data_q[output_index*8 +: 8] <= requantize(
            accumulator,
            multipliers[output_index],
            shifts[output_index],
            relu_enable[output_index]
          );
        end
        out_tag_q <= in_tag;
        out_valid_q <= 1'b1;
        perf_accepted <= perf_accepted + 1'b1;
      end
    end
  end

  initial begin
    if (LANES != 4 || OUTPUTS != 4)
      $fatal(1, "This release supports the reviewed 4x4 configuration only");
  end
endmodule
