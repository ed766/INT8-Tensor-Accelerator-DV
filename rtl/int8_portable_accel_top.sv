`timescale 1ns/1ps
module int8_portable_accel_top (
  input logic clk,input logic rst_n,
  input logic record_valid,output logic record_ready,input logic[63:0]record_data,
  output logic result_valid,input logic result_ready,output logic[31:0]result_data,output logic[7:0]result_tag,
  output logic expect_valid,input logic expect_ready,output logic[31:0]expect_data,output logic[7:0]expect_tag,output logic[7:0]expect_stall,
  output logic stream_done,output logic malformed,output logic cmd_error,
  output logic[31:0]monitor_accepted,output logic[31:0]monitor_completed,output logic monitor_error
);
  logic cfg_valid,cfg_ready,cfg_bank;logic[2:0]cfg_kind;logic[1:0]cfg_output;logic[5:0]cfg_index;logic[31:0]cfg_data;
  logic cmd_valid,cmd_ready,cmd_bank;logic[6:0]cmd_k;logic[7:0]cmd_tag;
  logic in_valid,in_ready;logic[31:0]in_data;logic[7:0]in_tag;
  logic[31:0]perf_accepted,perf_completed,perf_input_chunks,perf_output_stalls,perf_bank_swaps;
  logic[31:0]mon_chunks,mon_cmd_stalls,mon_input_stalls,mon_output_stalls,mon_max_outstanding;
  logic[31:0]mon_last_latency,mon_active_cycles;
  int8_portable_record_decoder decoder(.clk,.rst_n,.record_valid,.record_ready,.record_data,
    .cfg_valid,.cfg_ready,.cfg_kind,.cfg_bank,.cfg_output,.cfg_index,.cfg_data,
    .cmd_valid,.cmd_ready,.cmd_bank,.cmd_k,.cmd_tag,.in_valid,.in_ready,.in_data,.in_tag,
    .expect_valid,.expect_ready,.expect_data,.expect_tag,.expect_stall,.done(stream_done),.malformed);
  int8_tensor_accel accelerator(.clk,.rst_n,.cfg_valid,.cfg_ready,.cfg_kind,.cfg_bank,.cfg_output,.cfg_index,.cfg_data,
    .cmd_valid,.cmd_ready,.cmd_bank,.cmd_k,.cmd_tag,.cmd_error,.in_valid,.in_ready,.in_data,.in_tag,
    .out_valid(result_valid),.out_ready(result_ready),.out_data(result_data),.out_tag(result_tag),
    .perf_accepted,.perf_completed,.perf_input_chunks,.perf_output_stalls,.perf_bank_swaps);
  int8_accel_health_monitor monitor(.clk,.rst_n,.clear(1'b0),.cmd_valid,.cmd_ready,.in_valid,.in_ready,
    .out_valid(result_valid),.out_ready(result_ready),.out_tag(result_tag),.accepted_commands(monitor_accepted),
    .completed_commands(monitor_completed),.accepted_chunks(mon_chunks),.command_stall_cycles(mon_cmd_stalls),
    .input_stall_cycles(mon_input_stalls),.output_stall_cycles(mon_output_stalls),.max_outstanding(mon_max_outstanding),
    .last_command_latency(mon_last_latency),.active_compute_cycles(mon_active_cycles),
    .protocol_error(monitor_error));
endmodule
