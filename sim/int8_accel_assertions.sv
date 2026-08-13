`timescale 1ns/1ps

module int8_accel_assertions #(
  parameter int LANES = 4,
  parameter int OUTPUTS = 4,
  parameter int MAX_K = 64,
  parameter int FIFO_DEPTH = 4,
  parameter int TAG_W = 8
) (
  input logic clk,
  input logic rst_n,
  input logic cfg_valid,
  input logic cfg_ready,
  input logic cfg_bank,
  input logic cmd_valid,
  input logic cmd_ready,
  input logic cmd_bank,
  input logic [$clog2(MAX_K+1)-1:0] cmd_k,
  input logic cmd_error,
  input logic command_active,
  input logic active_bank,
  input logic [TAG_W-1:0] active_tag,
  input logic last_chunk,
  input logic in_valid,
  input logic in_ready,
  input logic [LANES*8-1:0] in_data,
  input logic [TAG_W-1:0] in_tag,
  input logic out_valid,
  input logic out_ready,
  input logic [OUTPUTS*8-1:0] out_data,
  input logic [TAG_W-1:0] out_tag,
  input logic [$clog2(FIFO_DEPTH+1)-1:0] fifo_count,
  input logic [31:0] perf_accepted,
  input logic [31:0] perf_completed,
  input logic [31:0] perf_input_chunks
);
  default clocking cb @(posedge clk); endclocking

  a_output_stable_under_backpressure:
    assert property (disable iff (!rst_n) out_valid && !out_ready |=> out_valid && $stable(out_data) && $stable(out_tag));
  a_input_stable_when_blocked:
    assert property (disable iff (!rst_n) in_valid && !in_ready |=> in_valid && $stable(in_data) && $stable(in_tag));
  a_completion_not_ahead_of_accept:
    assert property (disable iff (!rst_n) perf_completed <= perf_accepted);
  a_fifo_count_bounded:
    assert property (disable iff (!rst_n) int'(fifo_count) <= FIFO_DEPTH);
  a_output_matches_fifo_occupancy:
    assert property (disable iff (!rst_n) out_valid == (fifo_count != 0));
  a_config_active_bank_blocked:
    assert property (disable iff (!rst_n) command_active && cfg_valid && (cfg_bank == active_bank) |-> !cfg_ready);
  a_accepted_config_not_active_bank:
    assert property (disable iff (!rst_n) command_active && cfg_valid && cfg_ready |-> cfg_bank != active_bank);
  a_command_only_when_idle:
    assert property (disable iff (!rst_n) cmd_valid && cmd_ready |-> !command_active && !cfg_valid);
  a_illegal_command_reports_error:
    assert property (disable iff (!rst_n) cmd_valid && cmd_ready && ((int'(cmd_k) < LANES) || (int'(cmd_k) > MAX_K) || ((int'(cmd_k) % LANES) != 0)) |=> cmd_error);
  a_legal_command_becomes_active:
    assert property (disable iff (!rst_n) cmd_valid && cmd_ready && (int'(cmd_k) >= LANES) && (int'(cmd_k) <= MAX_K) && ((int'(cmd_k) % LANES) == 0) |=> command_active);
  a_command_selects_requested_bank:
    assert property (disable iff (!rst_n) cmd_valid && cmd_ready && (int'(cmd_k) >= LANES) && (int'(cmd_k) <= MAX_K) && ((int'(cmd_k) % LANES) == 0) |=> active_bank == $past(cmd_bank));
  a_input_only_during_command:
    assert property (disable iff (!rst_n) in_valid && in_ready |-> command_active);
  a_input_tag_matches_command:
    assert property (disable iff (!rst_n) in_valid && in_ready |-> in_tag == active_tag);
  a_chunk_count_not_ahead_of_capacity:
    assert property (disable iff (!rst_n) perf_input_chunks <= (perf_accepted * (MAX_K / LANES)));
  a_reset_clears_protocol_state:
    assert property (disable iff (!rst_n) $rose(rst_n) |-> !out_valid && !command_active && (fifo_count == 0));
  a_no_input_without_ready:
    assert property (disable iff (!rst_n) !command_active |-> !in_ready);
  a_command_and_config_mutually_exclusive:
    assert property (disable iff (!rst_n) !(cmd_ready && cfg_ready && cmd_valid && cfg_valid));
  a_output_requires_prior_command:
    assert property (disable iff (!rst_n) out_valid |-> perf_accepted > perf_completed);
  a_fifo_pop_decrements_or_replaces:
    assert property (disable iff (!rst_n) out_valid && out_ready && !(in_valid && in_ready && last_chunk) |=> fifo_count == ($past(fifo_count) - 1'b1));
  a_fifo_push_increments_or_replaces:
    assert property (disable iff (!rst_n) in_valid && in_ready && last_chunk && !(out_valid && out_ready) |=> fifo_count == ($past(fifo_count) + 1'b1));
  a_bank_stable_during_command:
    assert property (disable iff (!rst_n) command_active && $past(command_active) |-> $stable(active_bank));
endmodule

bind int8_tensor_accel int8_accel_assertions #(
  .LANES(LANES), .OUTPUTS(OUTPUTS), .MAX_K(MAX_K), .FIFO_DEPTH(FIFO_DEPTH), .TAG_W(TAG_W)
) protocol_assertions (
  .clk(clk), .rst_n(rst_n),
  .cfg_valid(cfg_valid), .cfg_ready(cfg_ready), .cfg_bank(cfg_bank),
  .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_bank(cmd_bank), .cmd_k(cmd_k),
  .cmd_error(cmd_error), .command_active(command_active), .active_bank(active_bank),
  .active_tag(active_tag), .last_chunk(last_chunk),
  .in_valid(in_valid), .in_ready(in_ready), .in_data(in_data), .in_tag(in_tag),
  .out_valid(out_valid), .out_ready(out_ready), .out_data(out_data), .out_tag(out_tag),
  .fifo_count(fifo_count), .perf_accepted(perf_accepted), .perf_completed(perf_completed),
  .perf_input_chunks(perf_input_chunks)
);
