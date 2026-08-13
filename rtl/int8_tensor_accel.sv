`timescale 1ns/1ps

module int8_tensor_accel #(
  parameter int LANES = 4,
  parameter int OUTPUTS = 4,
  parameter int MAX_K = 64,
  parameter int FIFO_DEPTH = 4,
  parameter int TAG_W = 8
) (
  input  logic                           clk,
  input  logic                           rst_n,

  input  logic                           cfg_valid,
  output logic                           cfg_ready,
  input  logic [2:0]                     cfg_kind,
  input  logic                           cfg_bank,
  input  logic [$clog2(OUTPUTS)-1:0]     cfg_output,
  input  logic [$clog2(MAX_K)-1:0]       cfg_index,
  input  logic [31:0]                    cfg_data,

  input  logic                           cmd_valid,
  output logic                           cmd_ready,
  input  logic                           cmd_bank,
  input  logic [$clog2(MAX_K+1)-1:0]     cmd_k,
  input  logic [TAG_W-1:0]               cmd_tag,
  output logic                           cmd_error,

  input  logic                           in_valid,
  output logic                           in_ready,
  input  logic [LANES*8-1:0]             in_data,
  input  logic [TAG_W-1:0]               in_tag,

  output logic                           out_valid,
  input  logic                           out_ready,
  output logic [OUTPUTS*8-1:0]           out_data,
  output logic [TAG_W-1:0]               out_tag,

  output logic [31:0]                    perf_accepted,
  output logic [31:0]                    perf_completed,
  output logic [31:0]                    perf_input_chunks,
  output logic [31:0]                    perf_output_stalls,
  output logic [31:0]                    perf_bank_swaps
);
  localparam logic [2:0] CFG_WEIGHT  = 3'd0;
  localparam logic [2:0] CFG_BIAS    = 3'd1;
  localparam logic [2:0] CFG_SCALE   = 3'd2;
  localparam logic [2:0] CFG_CONTROL = 3'd3;
  localparam int FIFO_PTR_W = $clog2(FIFO_DEPTH);
  localparam int CHUNK_W = $clog2((MAX_K / LANES) + 1);

  logic signed [7:0] weights [0:1][0:OUTPUTS-1][0:MAX_K-1];
  logic signed [31:0] biases [0:1][0:OUTPUTS-1];
  logic signed [15:0] multipliers [0:1][0:OUTPUTS-1];
  logic [4:0] shifts [0:1][0:OUTPUTS-1];
  logic relu_enable [0:1][0:OUTPUTS-1];
  logic signed [7:0] input_zero_point [0:1];
  logic signed [7:0] weight_zero_point [0:1][0:OUTPUTS-1];
  logic signed [7:0] output_zero_point [0:1][0:OUTPUTS-1];

  logic command_active;
  logic active_bank;
  logic previous_bank;
  logic previous_bank_valid;
  logic [CHUNK_W-1:0] chunk_index;
  logic [CHUNK_W-1:0] chunk_count;
  logic [TAG_W-1:0] active_tag;
  logic signed [31:0] accumulators [0:OUTPUTS-1];

  logic [OUTPUTS*8-1:0] result_fifo_data [0:FIFO_DEPTH-1];
  logic [TAG_W-1:0] result_fifo_tag [0:FIFO_DEPTH-1];
  logic [FIFO_PTR_W-1:0] fifo_head;
  logic [FIFO_PTR_W-1:0] fifo_tail;
  logic [$clog2(FIFO_DEPTH+1)-1:0] fifo_count;

  logic last_chunk;
  logic legal_command;
  logic [31:0] cmd_k_extended;
  logic [31:0] fifo_count_extended;

  function automatic logic signed [7:0] requantize(
    input logic signed [31:0] accumulator,
    input logic signed [15:0] multiplier,
    input logic [4:0] shift,
    input logic relu,
    input logic signed [7:0] output_zero
  );
    logic signed [63:0] product;
    logic signed [63:0] magnitude;
    logic signed [63:0] rounded;
    logic signed [63:0] scaled;
    begin
      product = accumulator * multiplier;
      magnitude = product < 0 ? -product : product;
`ifdef MUT_ROUND_TRUNCATE
      rounded = magnitude;
`else
      rounded = shift == 0 ? magnitude : magnitude + (64'sd1 <<< (shift - 1'b1));
`endif
      scaled = shift == 0 ? product : (product < 0 ? -(rounded >>> shift) : rounded >>> shift);
      scaled = scaled + $signed({{56{output_zero[7]}}, output_zero});
`ifdef MUT_RELU_BYPASS
      if (1'b0 && relu && (scaled < 0))
`else
      if (relu && (scaled < 0))
`endif
        scaled = 0;
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

  assign cmd_k_extended = {{(32-$clog2(MAX_K+1)){1'b0}}, cmd_k};
  assign fifo_count_extended = {{(32-$clog2(FIFO_DEPTH+1)){1'b0}}, fifo_count};
  assign legal_command = (cmd_k_extended >= LANES) && (cmd_k_extended <= MAX_K) &&
                         ((cmd_k_extended % LANES) == 0);
  assign cmd_ready = !command_active && !cfg_valid;
  assign cfg_ready = !cmd_valid && !(command_active && (cfg_bank == active_bank));
  assign last_chunk = command_active && ((chunk_index + 1'b1) == chunk_count);
  assign in_ready = command_active && (!last_chunk || (fifo_count_extended < FIFO_DEPTH));
  assign out_valid = fifo_count != 0;
  assign out_data = result_fifo_data[fifo_head];
`ifdef MUT_TAG_CORRUPT
  assign out_tag = result_fifo_tag[fifo_head] ^ {{(TAG_W-1){1'b0}}, 1'b1};
`else
  assign out_tag = result_fifo_tag[fifo_head];
`endif

  integer bank_index;
  integer output_index;
  integer lane_index;
  integer weight_index;
  always_ff @(posedge clk or negedge rst_n) begin : accelerator_state
    integer signed dot_sum;
    integer signed activation_delta;
    integer signed weight_delta;
    logic signed [31:0] activation_full;
    logic signed [31:0] input_zero_full;
    logic signed [31:0] weight_full;
    logic signed [31:0] weight_zero_full;
    logic signed [31:0] accumulated_value;
    logic [OUTPUTS*8-1:0] packed_result;
    logic selected_bank;
    logic do_pop;
    logic do_push;
    if (!rst_n) begin
      command_active <= 1'b0;
      active_bank <= 1'b0;
      previous_bank <= 1'b0;
      previous_bank_valid <= 1'b0;
      chunk_index <= '0;
      chunk_count <= '0;
      active_tag <= '0;
      cmd_error <= 1'b0;
      fifo_head <= '0;
      fifo_tail <= '0;
      fifo_count <= '0;
      perf_accepted <= '0;
      perf_completed <= '0;
      perf_input_chunks <= '0;
      perf_output_stalls <= '0;
      perf_bank_swaps <= '0;
      for (output_index = 0; output_index < OUTPUTS; output_index++)
        accumulators[output_index] <= '0;
      for (bank_index = 0; bank_index < 2; bank_index++) begin
        input_zero_point[bank_index] <= '0;
        for (output_index = 0; output_index < OUTPUTS; output_index++) begin
          biases[bank_index][output_index] <= '0;
          multipliers[bank_index][output_index] <= 16'sd1;
          shifts[bank_index][output_index] <= '0;
          relu_enable[bank_index][output_index] <= 1'b0;
          weight_zero_point[bank_index][output_index] <= '0;
          output_zero_point[bank_index][output_index] <= '0;
          for (weight_index = 0; weight_index < MAX_K; weight_index++)
            weights[bank_index][output_index][weight_index] <= '0;
        end
      end
    end else begin
      cmd_error <= 1'b0;
      do_pop = out_valid && out_ready;
      do_push = in_valid && in_ready && last_chunk;

      if (do_pop) begin
        fifo_head <= fifo_head + 1'b1;
        perf_completed <= perf_completed + 1'b1;
      end
      if (out_valid && !out_ready)
        perf_output_stalls <= perf_output_stalls + 1'b1;

      case ({do_push, do_pop})
        2'b10: fifo_count <= fifo_count + 1'b1;
        2'b01: fifo_count <= fifo_count - 1'b1;
        default: fifo_count <= fifo_count;
      endcase

      if (cfg_valid && cfg_ready) begin
        case (cfg_kind)
          CFG_WEIGHT: weights[cfg_bank][cfg_output][cfg_index] <= cfg_data[7:0];
          CFG_BIAS: biases[cfg_bank][cfg_output] <= cfg_data;
          CFG_SCALE: begin
            multipliers[cfg_bank][cfg_output] <= cfg_data[15:0];
            shifts[cfg_bank][cfg_output] <= cfg_data[20:16];
          end
          CFG_CONTROL: begin
            relu_enable[cfg_bank][cfg_output] <= cfg_data[0];
            input_zero_point[cfg_bank] <= cfg_data[15:8];
            weight_zero_point[cfg_bank][cfg_output] <= cfg_data[23:16];
            output_zero_point[cfg_bank][cfg_output] <= cfg_data[31:24];
          end
          default: begin end
        endcase
      end

      if (cmd_valid && cmd_ready) begin
        if (!legal_command) begin
          cmd_error <= 1'b1;
        end else begin
`ifdef MUT_BANK_ALIAS
          selected_bank = 1'b0;
`else
          selected_bank = cmd_bank;
`endif
          active_bank <= selected_bank;
          active_tag <= cmd_tag;
          chunk_index <= '0;
          chunk_count <= cmd_k[$clog2(LANES) +: CHUNK_W];
          command_active <= 1'b1;
          perf_accepted <= perf_accepted + 1'b1;
          if (previous_bank_valid && (previous_bank != selected_bank))
            perf_bank_swaps <= perf_bank_swaps + 1'b1;
          previous_bank <= selected_bank;
          previous_bank_valid <= 1'b1;
          for (output_index = 0; output_index < OUTPUTS; output_index++)
            accumulators[output_index] <= biases[selected_bank][output_index];
        end
      end

      if (in_valid && in_ready) begin
        packed_result = '0;
        perf_input_chunks <= perf_input_chunks + 1'b1;
        for (output_index = 0; output_index < OUTPUTS; output_index++) begin
          dot_sum = 0;
          for (lane_index = 0; lane_index < LANES; lane_index++) begin
`ifdef MUT_ZEROPOINT_BYPASS
            activation_delta = $signed(in_data[lane_index*8 +: 8]);
            weight_delta = $signed(weights[active_bank][output_index][chunk_index*LANES + lane_index]);
`else
            activation_full = {{24{in_data[lane_index*8+7]}}, in_data[lane_index*8 +: 8]};
            input_zero_full = {{24{input_zero_point[active_bank][7]}}, input_zero_point[active_bank]};
            weight_full = {{24{weights[active_bank][output_index][chunk_index*LANES + lane_index][7]}},
                           weights[active_bank][output_index][chunk_index*LANES + lane_index]};
            weight_zero_full = {{24{weight_zero_point[active_bank][output_index][7]}},
                                weight_zero_point[active_bank][output_index]};
            activation_delta = activation_full - input_zero_full;
            weight_delta = weight_full - weight_zero_full;
`endif
`ifdef MUT_UNSIGNED_MAC
            dot_sum = dot_sum + ($unsigned(in_data[lane_index*8 +: 8]) *
                                 $unsigned(weights[active_bank][output_index][chunk_index*LANES + lane_index]));
`else
`ifdef MUT_K_LAST_EARLY
            if (!(last_chunk && (lane_index == LANES-1)))
`endif
            dot_sum = dot_sum + (activation_delta * weight_delta);
`endif
          end
          accumulated_value = accumulators[output_index] + dot_sum;
          accumulators[output_index] <= accumulated_value;
          if (last_chunk) begin
`ifdef MUT_OUTPUT_ORDER
            packed_result[(OUTPUTS-1-output_index)*8 +: 8] = requantize(
`else
            packed_result[output_index*8 +: 8] = requantize(
`endif
              accumulated_value, multipliers[active_bank][output_index],
              shifts[active_bank][output_index], relu_enable[active_bank][output_index],
              output_zero_point[active_bank][output_index]);
          end
        end
        if (last_chunk) begin
          result_fifo_data[fifo_tail] <= packed_result;
          result_fifo_tag[fifo_tail] <= active_tag;
          fifo_tail <= fifo_tail + 1'b1;
          command_active <= 1'b0;
        end else begin
          chunk_index <= chunk_index + 1'b1;
        end
      end
    end
  end

  initial begin
    if (LANES < 2 || OUTPUTS < 2)
      $fatal(1, "LANES and OUTPUTS must each be at least two");
    if ((MAX_K < LANES) || ((MAX_K % LANES) != 0))
      $fatal(1, "MAX_K must be a positive multiple of LANES");
    if ((FIFO_DEPTH < 2) || ((FIFO_DEPTH & (FIFO_DEPTH - 1)) != 0))
      $fatal(1, "FIFO_DEPTH must be a power of two of at least two entries");
  end
endmodule
