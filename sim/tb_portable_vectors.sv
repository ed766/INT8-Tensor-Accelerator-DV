`timescale 1ns/1ps

module tb_portable_vectors;
  logic clk = 0;
  logic rst_n = 0;
  always #5 clk <= ~clk;
  logic cfg_valid, cfg_ready, cfg_bank;
  logic [2:0] cfg_kind;
  logic [1:0] cfg_output;
  logic [5:0] cfg_index;
  logic [31:0] cfg_data;
  logic cmd_valid, cmd_ready, cmd_bank, cmd_error;
  logic [6:0] cmd_k;
  logic [7:0] cmd_tag;
  logic in_valid, in_ready;
  logic [31:0] in_data;
  logic [7:0] in_tag;
  logic out_valid, out_ready;
  logic [31:0] out_data;
  logic [7:0] out_tag;
  logic [31:0] perf_accepted, perf_completed, perf_input_chunks;
  logic [31:0] perf_output_stalls, perf_bank_swaps;
  logic monitor_clear, protocol_error;
  logic [31:0] mon_accepted, mon_completed, mon_chunks;
  logic [31:0] mon_cmd_stalls, mon_input_stalls, mon_output_stalls, mon_max_outstanding;
  logic [63:0] records [0:1023];
  string vector_file;
  integer vector_count;
  integer index;
  integer checks = 0;
  integer failures = 0;
  integer stall_cycles = 0;

  int8_tensor_accel dut (.*);
  int8_accel_health_monitor monitor (
    .clk, .rst_n, .clear(monitor_clear), .cmd_valid, .cmd_ready,
    .in_valid, .in_ready, .out_valid, .out_ready, .out_tag,
    .accepted_commands(mon_accepted), .completed_commands(mon_completed),
    .accepted_chunks(mon_chunks), .command_stall_cycles(mon_cmd_stalls),
    .input_stall_cycles(mon_input_stalls), .output_stall_cycles(mon_output_stalls),
    .max_outstanding(mon_max_outstanding), .protocol_error
  );

  initial begin
    if (!$value$plusargs("VECTOR_FILE=%s", vector_file)) $fatal(1, "VECTOR_FILE is required");
    if (!$value$plusargs("VECTOR_COUNT=%d", vector_count)) $fatal(1, "VECTOR_COUNT is required");
    $readmemh(vector_file, records, 0, vector_count - 1);
  end

  initial begin
    cfg_valid = 0; cfg_kind = 0; cfg_bank = 0; cfg_output = 0; cfg_index = 0; cfg_data = 0;
    cmd_valid = 0; cmd_bank = 0; cmd_k = 0; cmd_tag = 0;
    in_valid = 0; in_data = 0; in_tag = 0; out_ready = 0; monitor_clear = 0;
    repeat (4) @(posedge clk); rst_n = 1;
    index = 0;
    while (index < vector_count && records[index][63:60] != 4'hf) begin
      case (records[index][63:60])
        4'h0: begin
          @(negedge clk);
          cfg_valid = 1; cfg_bank = records[index][59]; cfg_kind = records[index][58:56];
          cfg_output = records[index][55:54]; cfg_index = records[index][53:48];
          cfg_data = records[index][47:16];
          do @(posedge clk); while (!cfg_ready);
          @(negedge clk); cfg_valid = 0;
        end
        4'h1: begin
          @(negedge clk);
          cmd_valid = 1; cmd_bank = records[index][59]; cmd_k = records[index][58:52];
          cmd_tag = records[index][51:44];
          do @(posedge clk); while (!cmd_ready);
          @(negedge clk); cmd_valid = 0;
        end
        4'h2: begin
          @(negedge clk);
          in_valid = 1; in_tag = records[index][55:48]; in_data = records[index][31:0];
          do @(posedge clk); while (!in_ready);
          @(negedge clk); in_valid = 0;
        end
        4'h4: stall_cycles = int'(records[index][55:48]);
        4'h3: begin
          if (stall_cycles != 0) begin
            repeat (stall_cycles) @(posedge clk);
          end
          @(negedge clk); out_ready = 1;
          wait (out_valid);
          checks++;
          if (out_tag !== records[index][55:48] || out_data !== records[index][31:0]) begin
            failures++;
            $display("PORTABLE_CHECK|case=%0d|status=FAIL|tag=%0d|expected=%08x|observed=%08x|observed_tag=%0d",
              checks-1, records[index][55:48], records[index][31:0], out_data, out_tag);
          end else begin
            $display("PORTABLE_CHECK|case=%0d|status=PASS|tag=%0d|expected=%08x|observed=%08x|observed_tag=%0d",
              checks-1, records[index][55:48], records[index][31:0], out_data, out_tag);
          end
          @(posedge clk);
          @(negedge clk); out_ready = 0;
          stall_cycles = 0;
        end
        default: begin failures++; $display("PORTABLE_CHECK|case=%0d|status=FAIL|reason=unknown_record", checks); end
      endcase
      index++;
    end
    repeat (3) @(posedge clk);
    if (mon_accepted != checks || mon_completed != checks || protocol_error || cmd_error ||
        mon_max_outstanding == 0 || mon_output_stalls == 0 ||
        mon_cmd_stalls != 0 || mon_input_stalls != 0 ||
        perf_accepted != mon_accepted || perf_completed != mon_completed ||
        perf_input_chunks != mon_chunks || perf_output_stalls != mon_output_stalls ||
        perf_bank_swaps == 0) begin
      failures++;
      $display("PORTABLE_MONITOR|status=FAIL|accepted=%0d|completed=%0d|max_outstanding=%0d|output_stalls=%0d|protocol_error=%0d",
        mon_accepted, mon_completed, mon_max_outstanding, mon_output_stalls, protocol_error);
    end else begin
      $display("PORTABLE_MONITOR|status=PASS|accepted=%0d|completed=%0d|chunks=%0d|max_outstanding=%0d|output_stalls=%0d",
        mon_accepted, mon_completed, mon_chunks, mon_max_outstanding, mon_output_stalls);
    end
    $display("PORTABLE_SUMMARY|cases=%0d|failures=%0d", checks, failures);
    if (failures != 0) $fatal(1, "portable vector validation failed");
    $finish;
  end

  initial begin
    repeat (20000) @(posedge clk);
    $fatal(1, "portable vector timeout");
  end
endmodule
