`timescale 1ns/1ps

module tb_protected_reset_uvm;
  import uvm_pkg::*;
  import protected_reset_uvm_pkg::*;

  localparam int SAMPLES = 16;
  localparam logic [31:0] INPUT_BASE = 32'h1000101c;
  localparam logic [31:0] OUTPUT_BASE = 32'h1000401c;
  localparam logic [31:0] GUARD = 32'ha53c79e1;
  localparam logic [7:0] TAG = 8'h61;

  logic clk = 0;
  always #5 clk = !clk;
  protected_reset_if control(clk);
  logic firmware_done, irq;
  logic [31:0] firmware_result;

  rv32_protected_shared_top #(.CPU_ENABLE_M(1)) dut(
    .clk, .rst_n(control.rst_n), .offload_reset_req(control.offload_reset_req),
    .firmware_done, .firmware_result, .irq,
    .recovery_snapshot_valid(1'b0), .recovery_snapshot_addr('0),
    .recovery_snapshot_data('0), .commit_valid(), .commit_pc(),
    .cycles(), .benchmark_cycles(), .chip_active_debug(), .chip_state_debug(),
    .chip_submit_debug(), .chip_comp_debug(), .chip_send_debug(),
    .chip_recv_debug(), .chip_link_debug()
  );

  int old_submits, old_reads, old_writes, old_publications, old_pops;
  int old_write_responses;
  int new_submits, new_publications, new_pops;
  bit retained_checked;
  logic [31:0] golden[SAMPLES];
  string golden_path;

  // Observe the target handshake, where the SRAM actually commits byte strobes.
  wire dma_write = dut.mem1.write_active && dut.mem1.awid_q == 6'h11;
  wire read_pending = old_reads == 0 && dut.mem1.r_pending_q &&
                      dut.mem1.arid_q == 6'h11 && dut.mem1.araddr_q == INPUT_BASE;
  wire write_stalled = old_writes > 0 && old_writes < SAMPLES && dma_write &&
                       dut.mem1.wvalid && !dut.mem1.wready;
  wire irq_pending = dut.svc.completion_valid && dut.irq_pending[1] && old_pops == 0;
  wire write_response_pending = old_writes == 1 && old_write_responses == 0 &&
                                dut.mem1.b_pending_q && !dut.mem1.bvalid &&
                                dut.mem1.bid == 6'h11;
  wire completion_pop = dut.svc.completion_valid && dut.svc.completion_ready;
  wire irq_ack = dut.irq_sel && dut.irq_apb_enable && dut.pwrite &&
                 dut.paddr[5:0] == 6'h0c && dut.pwdata[1];

  localparam logic [31:0] JOB_STRIDE = 32'h100;
  int local_old_submits, local_old_publications, local_writes[3];
  int local_submits, local_publications, local_pops, local_drained_r, local_drained_b;
  int live_retires;
  bit local_started, local_released, local_ack;
  wire queued_case = control.stage == 6;
  wire local_read_pending = dut.mem1.r_pending_q && dut.mem1.arid_q == 6'h11 &&
    dut.mem1.araddr_q == INPUT_BASE + (queued_case ? JOB_STRIDE : 0);
  wire local_b_pending = dut.mem1.b_pending_q && dut.mem1.bid == 6'h11;
  wire local_window = !local_started && (queued_case
    ? local_old_submits == 3 && local_old_publications == 1 && dut.completion_occupancy == 1 &&
      dut.svc.completion_tag == TAG && dut.svc.dma.active.tag == TAG + 1 &&
      dut.submit_occupancy == 1 && local_read_pending
    : local_old_submits == 1 && local_old_publications == 0 &&
      (control.stage == 4 ? local_read_pending : local_b_pending && local_writes[0] == 1));

  wire local_recovered = control.rst_n && local_released && firmware_done &&
                         firmware_result == 32'h600d5000 && !control.verified;
  c_local_read: cover property (@(posedge clk)
    control.stage == 4 && local_drained_r == 1 && local_recovered);
  c_local_b: cover property (@(posedge clk)
    control.stage == 5 && local_drained_b == 1 && local_recovered);
  c_local_queued: cover property (@(posedge clk)
    queued_case && local_old_submits == 3 && local_drained_r == 1 && local_recovered);

  typedef enum int {READ_RESPONSE, WRITE_DATA, UNACKED_IRQ, WRITE_RESPONSE, NO_WINDOW} outstanding_t;
  outstanding_t outstanding, reset_outstanding;
  always_comb begin
    if (read_pending) outstanding = READ_RESPONSE;
    else if (write_stalled) outstanding = WRITE_DATA;
    else if (irq_pending) outstanding = UNACKED_IRQ;
    else if (write_response_pending) outstanding = WRITE_RESPONSE;
    else outstanding = NO_WINDOW;
    control.window_ready = control.stage >= 4 ? local_window :
                           old_submits == 1 && outstanding != NO_WINDOW &&
                           int'(outstanding) == control.stage;
  end

  // The legal cross bins. Use cover properties for native Verilator
  // user coverage, with the independent output checks required for run acceptance.
  wire recovered = control.rst_n && control.injected && firmware_done &&
                   firmware_result == 32'h600d5000 && new_pops == 1 && !control.verified;
  c_read_recovered: cover property (@(posedge clk)
    control.stage == 0 && reset_outstanding == READ_RESPONSE && recovered);
  c_write_recovered: cover property (@(posedge clk)
    control.stage == 1 && reset_outstanding == WRITE_DATA && recovered);
  c_irq_recovered: cover property (@(posedge clk)
    control.stage == 2 && reset_outstanding == UNACKED_IRQ && recovered);
  c_write_response_recovered: cover property (@(posedge clk)
    control.stage == 3 && reset_outstanding == WRITE_RESPONSE && recovered);

  function automatic logic [31:0] read_word(logic [31:0] address);
    logic [63:0] word_pair;
    word_pair = dut.mem1.memory[(address - 32'h10000000) >> 3];
    return address[2] ? word_pair[63:32] : word_pair[31:0];
  endfunction

  task automatic check_output(int prefix, bit reversed_order);
    for (int i = 0; i < SAMPLES; ++i) begin
      logic [31:0] expected, actual;
      expected = i < prefix ? golden[reversed_order ? SAMPLES - 1 - i : i] : GUARD;
      actual = read_word(OUTPUT_BASE + 4 * i);
      if (actual !== expected)
        $fatal(1, "output word %0d (prefix %0d, reversed %0b): got %08x expected %08x",
               i, prefix, reversed_order, actual, expected);
    end
    if (read_word(OUTPUT_BASE - 4) !== GUARD ||
        read_word(OUTPUT_BASE + SAMPLES * 4) !== GUARD)
      $fatal(1, "output guard corrupted");
  endtask

  task automatic check_job(int job, int prefix, bit replacement);
    logic [31:0] base, expected;
    int sample;
    base = OUTPUT_BASE + JOB_STRIDE * job;
    for (int i = 0; i < SAMPLES; ++i) begin
      sample = ((replacement ? SAMPLES - 1 - i : i) + 3 * job) % SAMPLES;
      expected = i < prefix ? golden[sample] : GUARD;
      if (read_word(base + 4 * i) !== expected)
        $fatal(1, "job %0d word %0d: actual %08x expected %08x", job, i,
               read_word(base + 4 * i), expected);
    end
    if (read_word(base - 4) !== GUARD || read_word(base + 4 * SAMPLES) !== GUARD)
      $fatal(1, "job %0d guard corrupted", job);
  endtask

  always @(posedge clk) if (control.rst_n && control.stage >= 4) begin
    if (!local_started) begin
      if (dut.svc.submit_accepted) begin
        if (dut.svc.submit_tag != TAG + 8'(local_old_submits))
          $fatal(1, "unexpected initial descriptor tag");
        local_old_submits <= local_old_submits + 1;
      end
      if (dut.completion_published) begin
        if (!queued_case || dut.completion_publish_tag != TAG || dut.completion_publish_status != 0 ||
            dut.completion_publish_vectors_done != 7'(SAMPLES))
          $fatal(1, "unexpected original completion");
        local_old_publications <= local_old_publications + 1;
      end
      if (dma_write && dut.mem1.wvalid && dut.mem1.wready) begin
        int job;
        job = int'((dut.mem1.awaddr_q - OUTPUT_BASE) / JOB_STRIDE);
        if (job < 0 || job >= (queued_case ? 3 : 1))
          $fatal(1, "unexpected original output buffer");
        if (dut.mem1.awaddr_q != OUTPUT_BASE + JOB_STRIDE * job + 4 * local_writes[job])
          $fatal(1, "noncontiguous original output");
        local_writes[job] <= local_writes[job] + 1;
      end
      if (completion_pop || irq_ack) $fatal(1, "original completion consumed");
      if (control.offload_reset_req) begin
        if (!local_window || local_writes[0] != (queued_case ? SAMPLES : int'(control.stage == 5)) ||
            local_writes[1] != 0 || local_writes[2] != 0)
          $fatal(1, "local reset did not hit intended request and queue state");
        for (int job = 0; job < (queued_case ? 3 : 1); ++job)
          check_job(job, local_writes[job], 0);
        $display("LOCAL_RESET_WINDOW|stage=%0d|old_submits=%0d|queued=%0d|completed=%0d|first_prefix=%0d",
                 control.stage, local_old_submits, dut.submit_occupancy,
                 local_old_publications, local_writes[0]);
        local_started <= 1;
      end
    end else if (dut.offload_reset_active) begin
      if (dut.commit_valid) live_retires <= live_retires + 1;
      if (dut.s_rvalid[1] && dut.s_rready[1]) local_drained_r <= local_drained_r + 1;
      if (dut.s_bvalid[1] && dut.s_bready[1]) local_drained_b <= local_drained_b + 1;
      if (dut.mem_rsp_valid || dut.ptw_rsp_valid || dut.completion_published || dut.svc.submit_accepted)
        $fatal(1, "draining response leaked into reset offload domain");
    end else if (dut.offload_reset_done) begin
      if (!local_released) begin
        if ((control.stage == 5 ? local_drained_b != 1 || local_drained_r != 0
                                : local_drained_r != 1 || local_drained_b != 0) ||
            live_retires == 0 || dut.submit_occupancy != 0 || dut.completion_occupancy != 0)
          $fatal(1, "incorrect local drain, live hart retirement, or canceled queue state");
        for (int job = 0; job < (queued_case ? 3 : 1); ++job)
          check_job(job, local_writes[job], 0);
        local_released <= 1;
      end
      if (local_submits == 0 && (dut.mem_rsp_valid || dut.svc.completion_valid))
        $fatal(1, "old response or completion appeared after local reset");
      if (irq_ack && local_submits == 0) local_ack <= 1;
      if (dut.svc.submit_accepted) begin
        if (!local_ack || irq || dut.svc.submit_tag != TAG + 8'(local_submits))
          $fatal(1, "replacement submitted without IRQ cleanup or with wrong tag");
        local_submits <= local_submits + 1;
      end
      if (dut.completion_published) begin
        if (local_publications >= local_submits || dut.completion_publish_status != 0 ||
            dut.completion_publish_tag != TAG + 8'(local_publications) ||
            dut.completion_publish_vectors_done != 7'(SAMPLES))
          $fatal(1, "invalid replacement completion");
        local_publications <= local_publications + 1;
      end
      if (completion_pop) begin
        if (local_pops >= local_publications || dut.svc.completion_tag != TAG + 8'(local_pops))
          $fatal(1, "invalid replacement pop");
        local_pops <= local_pops + 1;
      end
      if (firmware_done && !control.verified) begin
        if (firmware_result != 32'h600d5000 || local_submits != (queued_case ? 3 : 1) ||
            local_publications != local_submits || local_pops != local_submits || irq)
          $fatal(1, "local recovery failed result=%08x submits=%0d pubs=%0d pops=%0d",
                 firmware_result, local_submits, local_publications, local_pops);
        for (int job = 0; job < local_submits; ++job) check_job(job, SAMPLES, 1);
        $display("LOCAL_RESET_PASS|stage=%0d|drained_r=%0d|drained_b=%0d|live_retires=%0d|replacements=%0d",
                 control.stage, local_drained_r, local_drained_b, live_retires, local_submits);
        control.verified <= 1;
      end
    end
  end

  initial begin
    if (!$value$plusargs("GOLDEN_HEX=%s", golden_path)) $fatal(1, "GOLDEN_HEX is required");
    $readmemh(golden_path, golden);
    foreach (dut.mem1.memory[i]) begin
      dut.mem1.memory[i] = '0;
      dut.mem2.memory[i] = '0;
      dut.mem3.memory[i] = '0;
    end
    wait (control.configured);
    dut.mem1.r_delay_cycles = control.read_delay;
    dut.mem1.w_ready_delay_cycles = control.write_delay;
    dut.mem1.b_delay_cycles = control.write_response_delay;
  end

  always @(negedge control.rst_n) if (control.injected) begin
    reset_outstanding = outstanding;
    if (!control.window_ready || old_pops != 0)
      $fatal(1, "reset window was not independently observed");
    if ((outstanding == READ_RESPONSE && (old_writes != 0 || old_publications != 0)) ||
        ((outstanding == WRITE_DATA || outstanding == WRITE_RESPONSE) && old_publications != 0) ||
        (outstanding == UNACKED_IRQ && (old_writes != SAMPLES || old_publications != 1)))
      $fatal(1, "incorrect write/publication counts before reset");
    check_output(old_writes, 0);
    $display("RESET_WINDOW|stage=%0d|outstanding=%0d|committed=%0d|old_publications=%0d|dma_b_responses=%0d",
             control.stage, reset_outstanding, old_writes, old_publications, old_write_responses);
  end

  always @(posedge clk) if (control.rst_n && control.stage < 4) begin
    if (!control.injected) begin
      if (dut.svc.submit_accepted) begin
        if (dut.svc.submit_tag != TAG) $fatal(1, "wrong initial tag");
        old_submits <= old_submits + 1;
      end
      if (dut.s_rvalid[1] && dut.s_rready[1]) old_reads <= old_reads + 1;
      if (dut.s_bvalid[1] && dut.s_bready[1]) old_write_responses <= old_write_responses + 1;
      if (dma_write && dut.mem1.wvalid && dut.mem1.wready) begin
        if (dut.mem1.awaddr_q != OUTPUT_BASE + 4 * old_writes)
          $fatal(1, "noncontiguous DMA output at beat %0d", old_writes);
        old_writes <= old_writes + 1;
      end
      if (dut.completion_published) old_publications <= old_publications + 1;
      if (completion_pop) old_pops <= old_pops + 1;
      if (irq_ack) $fatal(1, "firmware acknowledged the original interrupt");
    end else begin
      if (!retained_checked) begin
        check_output(old_writes, 0);
        retained_checked <= 1;
      end
      if (dut.svc.submit_accepted) begin
        if (dut.svc.submit_tag != TAG) $fatal(1, "recovery did not reuse the original tag");
        new_submits <= new_submits + 1;
      end
      if (dut.completion_published) begin
        if (dut.completion_publish_tag != TAG || dut.completion_publish_status != 0 ||
            dut.completion_publish_vectors_done != SAMPLES)
          $fatal(1, "incorrect recovery completion metadata");
        new_publications <= new_publications + 1;
      end
      if (completion_pop) new_pops <= new_pops + 1;
      if (firmware_done && !control.verified) begin
        if (firmware_result != 32'h600d5000 || new_submits != 1 ||
            new_publications != 1 || new_pops != 1 || irq || dut.svc.completion_valid)
          $fatal(1, "reboot regression: result=%08x submits=%0d publications=%0d pops=%0d",
                 firmware_result, new_submits, new_publications, new_pops);
        check_output(SAMPLES, 1);
        $display("RESET_CROSS_PASS|stage=%0d|outstanding=%0d|outcome=same_tag_recovered",
                 control.stage, reset_outstanding);
        control.verified <= 1;
      end
    end
  end

  a_quiet_before_resubmit: assert property (@(posedge clk) disable iff (!control.rst_n)
    control.stage < 4 && control.injected && new_submits == 0 |->
      !dut.completion_published && !dut.svc.completion_valid && !irq && !dut.irq_raw[1] &&
      !dut.mem_rsp_valid && !dut.s_rvalid[1] && !dut.s_bvalid[1])
    else $fatal(1, "a_quiet_before_resubmit: stale completion, IRQ, or DMA response");
  a_single_publication: assert property (@(posedge clk) disable iff (!control.rst_n)
    control.stage < 4 && control.injected && dut.completion_published |-> new_submits == 1 && new_publications == 0)
    else $fatal(1, "a_single_publication: unexpected or duplicate completion");
  a_no_stale_target_b: assert property (@(posedge clk) disable iff (!control.rst_n)
    control.stage < 4 && control.injected && new_submits == 0 |->
      !(dut.mem1.bid == 6'h11 && (dut.mem1.b_pending_q || dut.mem1.bvalid)))
    else $fatal(1, "a_no_stale_target_b: SRAM retained an old DMA write response");
  a_fresh_irq: assert property (@(posedge clk) disable iff (!control.rst_n)
    control.stage < 4 && control.injected && (irq || completion_pop || irq_ack) |-> new_publications == 1)
    else $fatal(1, "a_fresh_irq: IRQ or consumption without a replacement completion");

  initial begin
    uvm_config_db#(virtual protected_reset_if)::set(null, "uvm_test_top", "bus", control);
    run_test("protected_reset_test");
  end
  initial begin
    repeat (100000) @(posedge clk);
    $fatal(1, "reset recovery timed out stage=%0d pc=%08x injected=%0b writes=%0d",
           control.stage, dut.commit_pc, control.injected, old_writes);
  end
endmodule
