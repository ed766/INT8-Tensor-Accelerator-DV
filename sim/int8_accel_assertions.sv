`timescale 1ns/1ps

module int8_accel_assertions #(
  parameter int LANES = 4,
  parameter int OUTPUTS = 4,
  parameter int TAG_W = 8
) (
  input logic clk,
  input logic rst_n,
  input logic cfg_valid,
  input logic cfg_ready,
  input logic in_valid,
  input logic in_ready,
  input logic [LANES*8-1:0] in_data,
  input logic [TAG_W-1:0] in_tag,
  input logic out_valid,
  input logic out_ready,
  input logic [OUTPUTS*8-1:0] out_data,
  input logic [TAG_W-1:0] out_tag,
  input logic [31:0] perf_accepted,
  input logic [31:0] perf_completed
);
  default clocking cb @(posedge clk); endclocking

  a_output_stable_under_backpressure:
    assert property (disable iff (!rst_n) out_valid && !out_ready |=> out_valid && $stable(out_data) && $stable(out_tag));

  a_input_stable_when_blocked:
    assert property (disable iff (!rst_n) in_valid && !in_ready |=> in_valid && $stable(in_data) && $stable(in_tag));

  a_completion_not_ahead_of_accept:
    assert property (disable iff (!rst_n) perf_completed <= perf_accepted);

  a_single_entry_occupancy:
    assert property (disable iff (!rst_n) (perf_accepted - perf_completed) <= 1);

  a_config_only_when_idle:
    assert property (disable iff (!rst_n) cfg_valid && cfg_ready |-> !out_valid && !in_valid);

  a_reset_clears_output:
    assert property (disable iff (!rst_n) $rose(rst_n) |-> !out_valid);

  a_accept_eventually_visible:
    assert property (disable iff (!rst_n) in_valid && in_ready |=> out_valid);

  a_output_requires_prior_accept:
    assert property (disable iff (!rst_n) out_valid |-> (perf_accepted > perf_completed));
endmodule

bind int8_tensor_accel int8_accel_assertions #(
  .LANES(LANES), .OUTPUTS(OUTPUTS), .TAG_W(TAG_W)
) protocol_assertions (
  .clk(clk), .rst_n(rst_n),
  .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
  .in_valid(in_valid), .in_ready(in_ready), .in_data(in_data), .in_tag(in_tag),
  .out_valid(out_valid), .out_ready(out_ready), .out_data(out_data), .out_tag(out_tag),
  .perf_accepted(perf_accepted), .perf_completed(perf_completed)
);
