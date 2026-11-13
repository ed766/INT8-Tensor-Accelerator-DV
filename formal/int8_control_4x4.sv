module int8_control_4x4;
  (* gclk *) logic clk;
  (* anyseq *) logic rst_n, cmd_valid, cmd_bank, cfg_valid, cfg_bank;
  (* anyseq *) logic in_valid, out_ready;
  (* anyseq *) logic [6:0] cmd_k;
  (* anyseq *) logic [7:0] cmd_tag;
  wire cmd_ready, cmd_error, cfg_ready, in_ready, out_valid;
  wire [7:0] out_tag;
  wire [31:0] out_data, perf_accepted, perf_completed;

  int8_tensor_accel dut (
    .clk(clk), .rst_n(rst_n),
    .cfg_valid(cfg_valid), .cfg_ready(cfg_ready), .cfg_bank(cfg_bank),
    .cfg_kind(3'd1), .cfg_output(2'd0), .cfg_index(6'd0), .cfg_data(32'd1),
    .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_error(cmd_error),
    .cmd_bank(cmd_bank), .cmd_k(cmd_k), .cmd_tag(cmd_tag),
    .in_valid(in_valid), .in_ready(in_ready), .in_data(32'd0), .in_tag(8'd0),
    .out_valid(out_valid), .out_ready(out_ready), .out_tag(out_tag), .out_data(out_data),
    .perf_accepted(perf_accepted), .perf_completed(perf_completed),
    .perf_input_chunks(), .perf_output_stalls(), .perf_bank_swaps()
  );

  logic started = 0;
  logic past_two = 0;
  logic [4:0] remaining;
  logic [7:0] active_tag;
  logic active_bank, rejected, max_k_command;
  logic [2:0] queued;
  logic [31:0] tags;
  logic [31:0] accepted, completed;
  wire legal = cmd_k >= 4 && cmd_k <= 64 && cmd_k[1:0] == 0;
  wire push = in_valid && in_ready && remaining == 1;
  wire pop = out_valid && out_ready;
  wire [31:0] shifted_tags = pop ? tags >> 8 : tags;
  wire [2:0] after_pop = queued - {2'b0, pop};

  always @(posedge clk) begin
    started <= 1;
    past_two <= started;
    if (!started) assume(!rst_n);
    if (started && !$past(rst_n)) begin
      assert(!out_valid && !in_ready);
      assert(perf_accepted == 0 && perf_completed == 0);
    end

    if (!rst_n) begin
      remaining <= 0;
      active_tag <= 0;
      active_bank <= 0;
      rejected <= 0;
      max_k_command <= 0;
      queued <= 0;
      tags <= 0;
      accepted <= 0;
      completed <= 0;
    end else if (started) begin
      assert(cmd_ready == (remaining == 0 && !cfg_valid));
      assert(cmd_error == rejected);
      assert(cfg_ready == (!cmd_valid && (remaining == 0 || cfg_bank != active_bank)));
      assert(in_ready == (remaining != 0 && (remaining != 1 || queued < 4)));
      assert(out_valid == (queued != 0));
      if (queued != 0) assert(out_tag == tags[7:0]);
      assert(queued <= 4 && perf_accepted == accepted && perf_completed == completed);
      if ($past(rst_n && out_valid && !out_ready))
        assert(out_valid && $stable(out_tag) && $stable(out_data));

      rejected <= cmd_valid && cmd_ready && !legal;
      if (cmd_valid && cmd_ready && legal) begin
        remaining <= cmd_k[6:2];
        active_tag <= cmd_tag;
        active_bank <= cmd_bank;
        max_k_command <= cmd_k == 64;
        accepted <= accepted + 1;
      end else if (in_valid && in_ready) begin
        remaining <= remaining - 1;
      end

      if (pop) completed <= completed + 1;
      queued <= after_pop + {2'b0, push};
      if (push)
        tags <= shifted_tags | ({24'd0, active_tag} << (8 * after_pop));
      else
        tags <= shifted_tags;

      cover(queued == 4 && remaining == 1 && in_valid && !in_ready);
      cover(push && pop);
      cover(push && accepted == 1 && max_k_command);
      cover(remaining != 0 && cfg_valid && cfg_ready);
      cover(rejected);
      cover(past_two && !$past(rst_n) && $past(rst_n && queued != 0, 2));
    end
  end
endmodule
