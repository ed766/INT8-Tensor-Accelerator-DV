`timescale 1ns/1ps

// Synthesizable protocol/performance monitor suitable for simulation or FPGA use.
module int8_accel_health_monitor #(
  parameter int COUNTER_W = 32
) (
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 clear,
  input  logic                 cmd_valid,
  input  logic                 cmd_ready,
  input  logic                 in_valid,
  input  logic                 in_ready,
  input  logic                 out_valid,
  input  logic                 out_ready,
  input  logic [7:0]           out_tag,
  output logic [COUNTER_W-1:0] accepted_commands,
  output logic [COUNTER_W-1:0] completed_commands,
  output logic [COUNTER_W-1:0] accepted_chunks,
  output logic [COUNTER_W-1:0] command_stall_cycles,
  output logic [COUNTER_W-1:0] input_stall_cycles,
  output logic [COUNTER_W-1:0] output_stall_cycles,
  output logic [COUNTER_W-1:0] max_outstanding,
  output logic [COUNTER_W-1:0] last_command_latency,
  output logic [COUNTER_W-1:0] active_compute_cycles,
  output logic                 protocol_error
);
  logic [COUNTER_W-1:0] outstanding;
  logic [7:0] held_out_tag;
  logic held_out_valid;
  logic command_timing_active;
  logic result_seen;
  logic [COUNTER_W-1:0] command_latency;
  wire cmd_accept = cmd_valid && cmd_ready;
  wire input_accept = in_valid && in_ready;
  wire output_accept = out_valid && out_ready;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      accepted_commands <= '0;
      completed_commands <= '0;
      accepted_chunks <= '0;
      command_stall_cycles <= '0;
      input_stall_cycles <= '0;
      output_stall_cycles <= '0;
      max_outstanding <= '0;
      last_command_latency <= '0;
      active_compute_cycles <= '0;
      outstanding <= '0;
      held_out_tag <= '0;
      held_out_valid <= 1'b0;
      protocol_error <= 1'b0;
      command_timing_active <= 1'b0;
      result_seen <= 1'b0;
      command_latency <= '0;
    end else if (clear) begin
      accepted_commands <= '0;
      completed_commands <= '0;
      accepted_chunks <= '0;
      command_stall_cycles <= '0;
      input_stall_cycles <= '0;
      output_stall_cycles <= '0;
      max_outstanding <= '0;
      last_command_latency <= '0;
      active_compute_cycles <= '0;
      outstanding <= '0;
      held_out_tag <= '0;
      held_out_valid <= 1'b0;
      protocol_error <= 1'b0;
      command_timing_active <= 1'b0;
      result_seen <= 1'b0;
      command_latency <= '0;
    end else begin
      if (cmd_accept) accepted_commands <= accepted_commands + 1'b1;
      if (input_accept) accepted_chunks <= accepted_chunks + 1'b1;
      if (output_accept) completed_commands <= completed_commands + 1'b1;
      if (cmd_valid && !cmd_ready) command_stall_cycles <= command_stall_cycles + 1'b1;
      if (in_valid && !in_ready) input_stall_cycles <= input_stall_cycles + 1'b1;
      if (out_valid && !out_ready) output_stall_cycles <= output_stall_cycles + 1'b1;

      if (cmd_accept) begin
        command_timing_active <= 1'b1;
        result_seen <= 1'b0;
        command_latency <= '0;
      end else if (command_timing_active) begin
        command_latency <= command_latency + 1'b1;
        active_compute_cycles <= active_compute_cycles + 1'b1;
      end
      // Capture first result visibility, excluding firmware polling delay.
      if (command_timing_active && out_valid && !result_seen) begin
`ifdef RV32_BENCH_MUT_FREEZE_LATENCY
        last_command_latency <= '0;
`else
        last_command_latency <= command_latency + 1'b1;
`endif
        result_seen <= 1'b1;
        command_timing_active <= 1'b0;
      end

      case ({cmd_accept, output_accept})
        2'b10: outstanding <= outstanding + 1'b1;
        2'b01: begin
          if (outstanding == 0) protocol_error <= 1'b1;
          else outstanding <= outstanding - 1'b1;
        end
        default: outstanding <= outstanding;
      endcase
      if (cmd_accept && !output_accept && outstanding + 1'b1 > max_outstanding)
        max_outstanding <= outstanding + 1'b1;

      if (out_valid && !out_ready) begin
        if (held_out_valid && out_tag != held_out_tag) protocol_error <= 1'b1;
        held_out_tag <= out_tag;
        held_out_valid <= 1'b1;
      end else begin
        held_out_valid <= 1'b0;
      end
      if (completed_commands > accepted_commands) protocol_error <= 1'b1;
    end
  end

  a_completion_not_ahead: assert property (@(posedge clk) disable iff (!rst_n)
    completed_commands <= accepted_commands);
  a_output_tag_stable: assert property (@(posedge clk) disable iff (!rst_n)
    out_valid && !out_ready |=> out_valid && $stable(out_tag));
  a_latency_progresses: assert property (@(posedge clk) disable iff (!rst_n)
    command_timing_active && !out_valid |=> active_compute_cycles >= $past(active_compute_cycles));
endmodule
