`timescale 1ns/1ps

module tb_protected_offload;
  localparam logic [31:0] INPUT_IOVA = 32'h8000_1000;
  localparam logic [31:0] OUTPUT_IOVA = 32'h8000_4000;
  localparam logic [31:0] PHYS_BASE = 32'h1000_0000;
  localparam int MEM_WORDS = 8192;

  logic clk = 0;
  logic rst_n = 0;
  always #5 clk = ~clk;

  logic submit_valid, submit_ready, submit_accepted, submit_rejected;
  logic [31:0] submit_input_iova, submit_output_iova;
  logic [15:0] submit_input_stride, submit_output_stride;
  logic [6:0] submit_k, submit_batch;
  logic [7:0] submit_tag, submit_asid, submit_bank_generation;
  logic submit_bank;
  logic [3:0] submit_qos;
  logic [1:0][7:0] bank_generation;
  logic xlate_req_valid, xlate_req_ready, xlate_req_write, xlate_rsp_valid, xlate_rsp_ready;
  logic [31:0] xlate_req_iova, xlate_rsp_paddr;
  logic [7:0] xlate_req_asid;
  logic [1:0] xlate_rsp_fault;
  logic mem_req_valid, mem_req_ready, mem_req_write, mem_rsp_valid, mem_rsp_ready;
  logic [31:0] mem_req_addr, mem_req_wdata, mem_rsp_rdata;
  logic [3:0] mem_req_wstrb, mem_req_qos;
  logic mem_rsp_error;
  logic accel_cmd_valid, accel_cmd_ready, accel_cmd_bank;
  logic [6:0] accel_cmd_k;
  logic [7:0] accel_cmd_tag;
  logic accel_in_valid, accel_in_ready, accel_out_valid, accel_out_ready;
  logic [31:0] accel_in_data, accel_out_data;
  logic [7:0] accel_in_tag, accel_out_tag, accelerator_out_tag;
  logic completion_valid, completion_ready, irq, busy;
  logic [7:0] completion_tag, completion_asid;
  logic [3:0] completion_status;
  logic [31:0] completion_fault_iova;
  logic [2:0] completion_fault_stage;
  logic [6:0] completion_vectors_done;
  logic [2:0] submit_occupancy, completion_occupancy;
  logic [11:0] paddr;
  logic psel, penable, pwrite, pready, pslverr;
  logic [31:0] pwdata, prdata;

  logic cfg_valid, cfg_ready, cfg_bank;
  logic [2:0] cfg_kind;
  logic [1:0] cfg_output;
  logic [5:0] cfg_index;
  logic [31:0] cfg_data;
  logic cmd_error;
  logic [31:0] perf_accepted, perf_completed, perf_input_chunks, perf_output_stalls, perf_bank_swaps;
  logic [31:0] memory [MEM_WORDS];
  logic xlate_pending, mem_pending;
  logic [31:0] pending_iova, pending_addr, pending_wdata;
  logic [3:0] pending_wstrb;
  logic pending_xlate_write, pending_mem_write;
  integer k_value, batch_value, bp_percent, fault_kind, completion_stall, asid_value, qos_value;
  integer bad_generation, pattern_value;
  integer cycles, failures, reads, writes, translations, stalls, irq_cycles, job_start_cycle;
  integer event_fd;
  logic [31:0] expected_word;

  protected_offload_dma dut (
    .clk, .rst_n, .submit_valid, .submit_ready, .submit_input_iova,
    .submit_output_iova, .submit_input_stride, .submit_output_stride, .submit_k,
    .submit_batch, .submit_tag, .submit_asid, .submit_bank,
    .submit_bank_generation, .submit_qos, .bank_generation, .submit_accepted,
    .submit_rejected, .xlate_req_valid, .xlate_req_ready, .xlate_req_iova,
    .xlate_req_asid, .xlate_req_write, .xlate_rsp_valid, .xlate_rsp_ready,
    .xlate_rsp_paddr, .xlate_rsp_fault, .mem_req_valid, .mem_req_ready,
    .mem_req_write, .mem_req_addr, .mem_req_wdata, .mem_req_wstrb,
    .mem_req_qos, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata,
    .mem_rsp_error, .accel_cmd_valid, .accel_cmd_ready, .accel_cmd_bank,
    .accel_cmd_k, .accel_cmd_tag, .accel_in_valid, .accel_in_ready,
    .accel_in_data, .accel_in_tag, .accel_out_valid, .accel_out_ready,
    .accel_out_data, .accel_out_tag, .completion_valid, .completion_ready,
    .completion_tag, .completion_status, .completion_asid,
    .completion_fault_iova, .completion_fault_stage, .completion_vectors_done,
    .irq, .busy, .submit_occupancy, .completion_occupancy);

  protected_offload_apb_csr csr (
    .clk, .rst_n, .paddr, .psel, .penable, .pwrite, .pwdata, .prdata,
    .pready, .pslverr, .submit_valid, .submit_ready, .submit_input_iova,
    .submit_output_iova, .submit_input_stride, .submit_output_stride,
    .submit_k, .submit_batch, .submit_tag, .submit_asid, .submit_bank,
    .submit_bank_generation, .submit_qos, .submit_accepted, .submit_rejected,
    .busy, .submit_occupancy, .completion_valid, .completion_ready,
    .completion_tag, .completion_status, .completion_asid,
    .completion_fault_iova, .completion_fault_stage, .completion_vectors_done,
    .completion_occupancy, .irq);

  int8_tensor_accel accelerator (
    .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_kind, .cfg_bank, .cfg_output,
    .cfg_index, .cfg_data, .cmd_valid(accel_cmd_valid), .cmd_ready(accel_cmd_ready),
    .cmd_bank(accel_cmd_bank), .cmd_k(accel_cmd_k), .cmd_tag(accel_cmd_tag),
    .cmd_error, .in_valid(accel_in_valid), .in_ready(accel_in_ready),
    .in_data(accel_in_data), .in_tag(accel_in_tag), .out_valid(accel_out_valid),
    .out_ready(accel_out_ready), .out_data(accel_out_data), .out_tag(accelerator_out_tag),
    .perf_accepted, .perf_completed, .perf_input_chunks, .perf_output_stalls,
    .perf_bank_swaps);

  function automatic int mem_index(input logic [31:0] address);
    return int'((address - PHYS_BASE) >> 2);
  endfunction

  task automatic configure_accelerator;
    begin
      for (int output_index = 0; output_index < 4; output_index++) begin
        for (int weight_index = 0; weight_index < 64; weight_index++) begin
          @(negedge clk);
          cfg_valid = 1; cfg_kind = 0; cfg_bank = 0;
          cfg_output = 2'(output_index); cfg_index = 6'(weight_index); cfg_data = 1;
          do @(negedge clk); while (!cfg_ready);
          cfg_valid = 0;
        end
        @(negedge clk);
        cfg_valid = 1; cfg_kind = 1; cfg_bank = 0;
        cfg_output = 2'(output_index); cfg_index = 0; cfg_data = 0;
        do @(negedge clk); while (!cfg_ready);
        cfg_valid = 0;
        @(negedge clk);
        cfg_valid = 1; cfg_kind = 2; cfg_bank = 0;
        cfg_output = 2'(output_index); cfg_index = 0; cfg_data = 1;
        do @(negedge clk); while (!cfg_ready);
        cfg_valid = 0;
        @(negedge clk);
        cfg_valid = 1; cfg_kind = 3; cfg_bank = 0;
        cfg_output = 2'(output_index); cfg_index = 0; cfg_data = 0;
        do @(negedge clk); while (!cfg_ready);
        cfg_valid = 0;
      end
    end
  endtask

  task automatic apb_write(input logic [11:0] address, input logic [31:0] data);
    begin
      @(negedge clk); paddr = address; pwdata = data; pwrite = 1; psel = 1; penable = 0;
      @(negedge clk); penable = 1;
      do @(negedge clk); while (!pready);
      if (pslverr) begin
        $display("APB_WRITE_ERROR|address=%03x|data=%08x", address, data);
        failures++;
      end
      if (event_fd != 0) $fwrite(event_fd, "%0d,apb_write,%0d,%0d,%03x,%08x\n",
        cycles, 8'h35, 0, address, data);
      psel = 0; penable = 0; pwrite = 0;
    end
  endtask

  task automatic apb_read(input logic [11:0] address, input logic expect_error);
    begin
      @(negedge clk); paddr = address; pwrite = 0; psel = 1; penable = 0;
      @(negedge clk); penable = 1;
      do @(negedge clk); while (!pready);
      if (pslverr != expect_error) failures++;
      psel = 0; penable = 0;
    end
  endtask

  task automatic program_and_submit;
    begin
      apb_write(12'h000, INPUT_IOVA);
      apb_write(12'h004, OUTPUT_IOVA);
      apb_write(12'h008, {16'd4, 16'd64});
      apb_write(12'h00c, {18'd0, 7'(batch_value), 7'(k_value)});
      apb_write(12'h010, {7'd0, bad_generation != 0 ? 8'h6 : 8'h7, 1'b0, 8'(asid_value), 8'h35});
      apb_write(12'h014, 32'(qos_value));
      apb_write(12'h018, 32'h1);
    end
  endtask

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      xlate_pending <= 0; xlate_rsp_valid <= 0; xlate_rsp_fault <= 0;
      xlate_rsp_paddr <= 0; pending_iova <= 0; pending_xlate_write <= 0;
      mem_pending <= 0; mem_rsp_valid <= 0; mem_rsp_rdata <= 0;
      mem_rsp_error <= 0; pending_addr <= 0; pending_wdata <= 0;
      pending_wstrb <= 0; pending_mem_write <= 0;
    end else begin
      xlate_rsp_valid <= 0;
      mem_rsp_valid <= 0;
      if (xlate_req_valid && xlate_req_ready) begin
        xlate_pending <= 1;
        pending_iova <= xlate_req_iova;
        pending_xlate_write <= xlate_req_write;
        translations <= translations + 1;
      end
      if (xlate_pending) begin
        xlate_pending <= 0;
        xlate_rsp_valid <= 1;
        xlate_rsp_paddr <= PHYS_BASE + (pending_iova - 32'h8000_0000);
        xlate_rsp_fault <= ((fault_kind == 1 && !pending_xlate_write) ||
                            (fault_kind == 2 && pending_xlate_write)) ? 2'd2 : 2'd0;
      end
      if (mem_req_valid && mem_req_ready) begin
        mem_pending <= 1;
        pending_addr <= mem_req_addr;
        pending_wdata <= mem_req_wdata;
        pending_wstrb <= mem_req_wstrb;
        pending_mem_write <= mem_req_write;
        if (mem_req_write) writes <= writes + 1; else reads <= reads + 1;
      end
      if (mem_pending) begin
        mem_pending <= 0;
        mem_rsp_valid <= 1;
        mem_rsp_error <= ((fault_kind == 3 && !pending_mem_write) ||
                          (fault_kind == 4 && pending_mem_write));
        mem_rsp_rdata <= memory[mem_index(pending_addr)];
        if (pending_mem_write && fault_kind != 4) begin
          for (int byte_index = 0; byte_index < 4; byte_index++)
            if (pending_wstrb[byte_index])
              memory[mem_index(pending_addr)][byte_index*8 +: 8] <= pending_wdata[byte_index*8 +: 8];
        end
      end
    end
  end

  assign xlate_req_ready = !xlate_pending && ((cycles % 4) != 1 || bp_percent == 0);
  assign mem_req_ready = !mem_pending && ((cycles * 37) % 100 >= bp_percent);
  assign accel_out_tag = fault_kind == 5 ? accelerator_out_tag ^ 8'h1 : accelerator_out_tag;

  always @(posedge clk) begin
    if (rst_n) begin
      cycles <= cycles + 1;
      if ((xlate_req_valid && !xlate_req_ready) || (mem_req_valid && !mem_req_ready)) stalls <= stalls + 1;
      if (irq) irq_cycles <= irq_cycles + 1;
      if (event_fd != 0) begin
        if (submit_accepted) $fwrite(event_fd, "%0d,submit,%0d,%0d,%0d,%0d\n", cycles, submit_tag, submit_asid, submit_k, submit_batch);
        if (xlate_req_valid && xlate_req_ready) $fwrite(event_fd, "%0d,xlate,%0d,%0d,%08x,%0d\n", cycles, submit_tag, xlate_req_asid, xlate_req_iova, xlate_req_write);
        if (mem_req_valid && mem_req_ready) $fwrite(event_fd, "%0d,memory,%0d,%0d,%08x,%0d\n", cycles, submit_tag, mem_req_write, mem_req_addr, mem_req_qos);
        if (accel_cmd_valid && accel_cmd_ready) $fwrite(event_fd, "%0d,command,%0d,%0d,%0d,%0d\n", cycles, accel_cmd_tag, accel_cmd_bank, accel_cmd_k, 0);
        if (accel_in_valid && accel_in_ready) $fwrite(event_fd, "%0d,chunk,%0d,%0d,%08x,%0d\n", cycles, accel_in_tag, 0, accel_in_data, 0);
        if (accel_out_valid && accel_out_ready) $fwrite(event_fd, "%0d,result,%0d,%0d,%08x,%0d\n", cycles, accel_out_tag, 0, accel_out_data, 0);
        if (completion_valid && completion_ready) $fwrite(event_fd, "%0d,completion,%0d,%0d,%0d,%0d\n", cycles, completion_tag, completion_status, completion_vectors_done, completion_fault_stage);
      end
    end
  end

  initial begin
    string event_path;
    k_value = 16; batch_value = 1; bp_percent = 0; fault_kind = 0; completion_stall = 0;
    asid_value = 18; qos_value = 8; bad_generation = 0; pattern_value = 0;
    void'($value$plusargs("K=%d", k_value));
    void'($value$plusargs("BATCH=%d", batch_value));
    void'($value$plusargs("BP_PCT=%d", bp_percent));
    void'($value$plusargs("FAULT=%d", fault_kind));
    void'($value$plusargs("COMP_STALL=%d", completion_stall));
    void'($value$plusargs("ASID=%d", asid_value));
    void'($value$plusargs("QOS=%d", qos_value));
    void'($value$plusargs("BAD_GENERATION=%d", bad_generation));
    void'($value$plusargs("PATTERN=%d", pattern_value));
    if (!$value$plusargs("EVENT_FILE=%s", event_path)) event_path = "build/protected_offload/events.csv";
    event_fd = $fopen(event_path, "w");
    $fwrite(event_fd, "cycle,event,tag,arg0,arg1,arg2\n");
    paddr = 0; psel = 0; penable = 0; pwrite = 0; pwdata = 0;
    bank_generation[0] = 8'h7; bank_generation[1] = 8'h2;
    cfg_valid = 0; cfg_bank = 0; cfg_kind = 0; cfg_output = 0; cfg_index = 0; cfg_data = 0;
    cycles = 0; failures = 0; reads = 0; writes = 0; translations = 0; stalls = 0; irq_cycles = 0;
    for (int i = 0; i < MEM_WORDS; i++) memory[i] = 0;
    for (int vector_index = 0; vector_index < batch_value; vector_index++)
      for (int word_index = 0; word_index < k_value / 4; word_index++)
        case(pattern_value)
          1: memory[mem_index(PHYS_BASE + 32'h1000 + vector_index * 64 + word_index * 4)] = 32'hff01ff01;
          2: memory[mem_index(PHYS_BASE + 32'h1000 + vector_index * 64 + word_index * 4)] = 32'h04030201;
          3: memory[mem_index(PHYS_BASE + 32'h1000 + vector_index * 64 + word_index * 4)] = 32'hffffffff;
          4: memory[mem_index(PHYS_BASE + 32'h1000 + vector_index * 64 + word_index * 4)] = 32'h7f7f7f7f;
          default: memory[mem_index(PHYS_BASE + 32'h1000 + vector_index * 64 + word_index * 4)] = 32'h01010101;
        endcase

    repeat (4) @(negedge clk); rst_n = 1;
    configure_accelerator();
    job_start_cycle = cycles;
    program_and_submit();
    if (bad_generation != 0) begin
      repeat (2) @(negedge clk);
      if (!csr.sticky_submit_reject || busy) failures++;
      apb_read(12'h01c, 0);
      apb_write(12'h030, 32'h1);
      if (csr.sticky_submit_reject) failures++;
      apb_read(12'h034, 1);
      $display("PROTECTED_OFFLOAD|status=%s|k=%0d|batch=%0d|fault=%0d|cycles=%0d|job_cycles=%0d|reads=%0d|writes=%0d|translations=%0d|stalls=%0d|irq_cycles=%0d|failures=%0d",
        failures == 0 ? "PASS" : "FAIL", k_value, batch_value, fault_kind, cycles,
        cycles-job_start_cycle, reads, writes, translations, stalls, irq_cycles, failures);
      $fclose(event_fd);
      if (failures != 0) $fatal(1);
      $finish;
    end
    case(pattern_value)
      1: expected_word = 32'h00000000;
      2: expected_word = 10 * (k_value / 4) > 127 ? 32'h7f7f7f7f : {4{8'(10 * (k_value / 4))}};
      3: expected_word = {4{8'(256-k_value)}};
      4: expected_word = 32'h7f7f7f7f;
      default: expected_word = {4{8'(k_value)}};
    endcase
    while (!completion_valid && cycles < 10000) @(posedge clk);
    if (!completion_valid) begin
      $display("PROTECTED_OFFLOAD|status=FAIL|reason=timeout");
      $fatal(1);
    end
    $display("COMPLETION_OBSERVED|tag=%0d|asid=%0d|status=%0d|vectors=%0d|stage=%0d",
      completion_tag, completion_asid, completion_status, completion_vectors_done,
      completion_fault_stage);
    if (completion_tag != 8'h35 || completion_asid != 8'(asid_value)) failures++;
    case (fault_kind)
      0: if (completion_status != 0 || int'(completion_vectors_done) != batch_value) failures++;
      1: if (completion_status != 2 || completion_fault_stage != 1) failures++;
      2: if (completion_status != 3 || completion_fault_stage != 3) failures++;
      3: if (completion_status != 4 || completion_fault_stage != 2) failures++;
      4: if (completion_status != 5 || completion_fault_stage != 4) failures++;
      5: if (completion_status != 6 || completion_fault_stage != 5) failures++;
      default: failures++;
    endcase
    if (!irq) failures++;
    apb_read(12'h000, 0); apb_read(12'h004, 0); apb_read(12'h008, 0);
    apb_read(12'h00c, 0); apb_read(12'h010, 0); apb_read(12'h014, 0);
    apb_read(12'h01c, 0); apb_read(12'h020, 0); apb_read(12'h024, 0);
    apb_read(12'h028, 0); apb_read(12'h018, 0); apb_read(12'h02c, 0);
    apb_read(12'h030, 0); apb_read(12'h034, 1);
    $fwrite(event_fd, "%0d,completion,%0d,%0d,%0d,%0d\n", cycles, completion_tag,
      completion_status, completion_vectors_done, completion_fault_stage);
    if (completion_stall != 0) repeat (completion_stall) @(posedge clk);
    apb_write(12'h02c, 32'h1);
    if (fault_kind == 0) begin
      for (int vector_index = 0; vector_index < batch_value; vector_index++)
        if (memory[mem_index(PHYS_BASE + 32'h4000 + vector_index * 4)] !== expected_word) begin
          $display("OUTPUT_MISMATCH|vector=%0d|expected=%08x|observed=%08x", vector_index,
            expected_word, memory[mem_index(PHYS_BASE + 32'h4000 + vector_index * 4)]);
          failures++;
        end
    end else if (writes != 0 && fault_kind < 4) failures++;

    $display("PROTECTED_OFFLOAD|status=%s|k=%0d|batch=%0d|fault=%0d|cycles=%0d|job_cycles=%0d|reads=%0d|writes=%0d|translations=%0d|stalls=%0d|irq_cycles=%0d|failures=%0d",
      failures == 0 ? "PASS" : "FAIL", k_value, batch_value, fault_kind, cycles, cycles-job_start_cycle,
      reads, writes, translations, stalls, irq_cycles, failures);
    $fclose(event_fd);
    if (failures != 0) $fatal(1);
    $finish;
  end

  initial begin
    $dumpfile("build/protected_offload/protected_offload.vcd");
    $dumpvars(0, tb_protected_offload);
  end

  a_translation_context_matches_descriptor: assert property (@(posedge clk) disable iff (!rst_n)
    xlate_req_valid |-> xlate_req_asid == 8'(asid_value));
endmodule
