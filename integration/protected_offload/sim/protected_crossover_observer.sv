`timescale 1ns/1ps

// Verification-only transaction observer for the firmware-owned crossover.
// The DUT interface is unchanged; normalized events are correlated off-line
// by run, reset epoch, software tag, ASID, and transport direction.
module protected_crossover_observer (
  input logic clk, input logic rst_n,
  input logic dma_awvalid, input logic dma_awready,
  input logic [31:0] dma_awaddr,
  input logic dma_bvalid, input logic dma_bready,
  input logic commit_valid, input logic [31:0] commit_pc, input logic [31:0] commit_instr,
  input logic [31:0] commit_next_pc, input logic [63:0] commit_order,
  input logic commit_trap, input logic commit_intr,
  input logic [4:0] commit_rs1_addr, input logic [4:0] commit_rs2_addr,
  input logic [31:0] commit_rs1_data, input logic [31:0] commit_rs2_data,
  input logic [4:0] commit_rd_addr, input logic [31:0] commit_rd_data,
  input logic [31:0] commit_mem_addr, input logic [3:0] commit_mem_rmask,
  input logic [3:0] commit_mem_wmask, input logic [31:0] commit_mem_rdata,
  input logic [31:0] commit_mem_wdata, input logic [31:0] commit_mstatus,
  input logic [31:0] commit_mie, input logic [31:0] commit_mtvec,
  input logic [31:0] commit_mscratch, input logic [31:0] commit_mepc,
  input logic [31:0] commit_mcause, input logic [31:0] commit_mtval,
  input logic cpu_enable_m, input logic irq_ext_level, input logic irq_timer_level,
  input logic muldiv_busy,
  input logic muldiv_result_valid,
  input logic psel, input logic penable, input logic pwrite, input logic [31:0] pwdata,
  input logic pready, input logic pslverr, input logic [31:0] paddr,
  input logic cpu_shared_access, input logic cpu_shared_write,
  input logic [31:0] cpu_physical_addr,
  input logic xlate_req_valid, input logic xlate_req_ready,
  input logic xlate_rsp_valid, input logic xlate_rsp_ready,
  input logic [31:0] xlate_iova, input logic [31:0] xlate_paddr,
  input logic [7:0] xlate_asid, input logic xlate_write,
  input logic [1:0] xlate_fault, input logic xlate_tlb_hit,
  input logic [7:0] xlate_job_tag, input logic [6:0] xlate_vector_index,
  input logic ptw_req_valid, input logic ptw_req_ready,
  input logic [31:0] ptw_req_addr, input logic ptw_rsp_valid,
  input logic ptw_rsp_ready, input logic [31:0] ptw_rsp_data,
  input logic ptw_rsp_error,
  input logic host_awvalid, input logic host_awready,
  input logic [1:0] host_aw_master_index, input logic [1:0] host_w_master_index,
  input logic [1:0] host_b_master_index, input logic [1:0] host_ar_master_index,
  input logic [1:0] host_r_master_index,
  input logic [3:0] host_awid, input logic [31:0] host_awaddr,
  input logic [7:0] host_awlen, input logic [2:0] host_awsize, input logic [1:0] host_awburst,
  input logic host_wvalid, input logic host_wready,
  input logic [63:0] host_wdata, input logic [7:0] host_wstrb,
  input logic host_wlast,
  input logic host_arvalid, input logic host_arready,
  input logic [3:0] host_arid, input logic [31:0] host_araddr,
  input logic [7:0] host_arlen, input logic [2:0] host_arsize, input logic [1:0] host_arburst,
  input logic host_rvalid, input logic host_rready,
  input logic [3:0] host_rid, input logic [63:0] host_rdata,
  input logic [1:0] host_rresp, input logic host_rlast,
  input logic host_bvalid, input logic host_bready,
  input logic [3:0] host_bid, input logic [1:0] host_bresp,
  input logic tlb_inv_valid, input logic tlb_inv_all,
  input logic [7:0] tlb_inv_asid,
  input logic mem_req_valid, input logic mem_req_ready,
  input logic mem_rsp_valid, input logic mem_rsp_ready,
  input logic mem_write, input logic [31:0] mem_addr,
  input logic [31:0] mem_wdata, input logic [3:0] mem_wstrb,
  input logic [31:0] mem_rsp_rdata,
  input logic mem_rsp_error, input logic [7:0] mem_job_tag,
  input logic [6:0] mem_vector_index,
  input logic axi_wait,
  input logic cfg_valid, input logic cfg_ready, input logic [2:0] cfg_kind,
  input logic cfg_bank, input logic [1:0] cfg_output, input logic [5:0] cfg_index,
  input logic [31:0] cfg_data,
  input logic accel_cmd_valid, input logic accel_cmd_ready,
  input logic accel_cmd_bank, input logic [6:0] accel_cmd_k,
  input logic [7:0] accel_cmd_tag, input logic accel_in_valid,
  input logic accel_in_ready, input logic accel_out_valid, input logic accel_out_ready,
  input logic [7:0] accel_out_tag,
  input logic [31:0] accel_in_data, input logic [7:0] accel_in_tag,
  input logic [31:0] accel_out_data,
  input logic completion_valid, input logic completion_ready,
  input logic [7:0] completion_tag, input logic [3:0] completion_status,
  input logic [7:0] completion_asid, input logic [31:0] completion_fault_iova,
  input logic [2:0] completion_fault_stage, input logic [6:0] completion_vectors_done,
  input logic completion_published, input logic [7:0] completion_publish_tag,
  input logic [7:0] completion_publish_asid, input logic [3:0] completion_publish_status,
  input logic [2:0] completion_publish_fault_stage, input logic [6:0] completion_publish_vectors_done,
  input logic irq,
  input logic chip_busy, input logic chip_done, input logic chip_error,
  input logic [1:0] chip_power_state,
  input logic [63:0] chip_plaintext, input logic [63:0] chip_ciphertext,
  input logic [63:0] chip_die_b_ciphertext,
  input logic chip_plaintext_valid, input logic [63:0] chip_plaintext_data,
  input logic chip_ciphertext_valid, input logic [63:0] chip_ciphertext_data,
  input logic chip_die_b_ciphertext_valid, input logic [63:0] chip_die_b_ciphertext_data,
  input logic submit_accepted, input logic submit_rejected,
  input logic [7:0] submit_tag, input logic [7:0] submit_asid,
  input logic [31:0] submit_input_iova, input logic [31:0] submit_output_iova,
  input logic [15:0] submit_input_stride, input logic [15:0] submit_output_stride,
  input logic [6:0] submit_k, input logic [6:0] submit_batch,
  input logic submit_bank, input logic [7:0] submit_bank_generation,
  input logic [2:0] irq_raw_status, input logic [2:0] irq_pending_status,
  input logic [2:0] irq_enable_mask,
  input logic cache_enabled,
  input logic [7:0] active_descriptor_tag, input logic dma_busy,
  input logic [2:0] submit_occupancy, input logic [2:0] completion_occupancy,
  input logic [4:0] owned_valid, input logic [4:0][31:0] owned_start,
  input logic [4:0][31:0] owned_end,
  input logic [4:0][31:0] owned_input_start, input logic [4:0][31:0] owned_input_end,
  input logic [4:0][31:0] owned_output_start, input logic [4:0][31:0] owned_output_end,
  input logic maint_valid, input logic maint_ready, input logic [1:0] maint_cmd,
  input logic maint_done, input logic maint_error, input logic maint_busy,
  input logic recovery_snapshot_valid, input logic [31:0] recovery_snapshot_addr,
  input logic [63:0] recovery_snapshot_data,
  input logic firmware_done
);
  integer fd;
  integer cycle;
  integer epoch;
  integer event_id;
  integer submit_seq;
  logic was_reset;
  logic prev_irq, prev_maint_valid, prev_firmware_done;
  logic prev_chip_busy, prev_chip_done, prev_muldiv_busy;
  logic prev_dma_busy;
  logic [7:0] prev_active_descriptor_tag;
  logic [1:0] prev_chip_power_state;
  logic [63:0] prev_chip_plaintext, prev_chip_ciphertext, prev_chip_die_b_ciphertext;
  logic apb_active;
  integer apb_wait_cycles;
  logic mem_write_pending;
  logic [31:0] mem_pending_addr, mem_pending_wdata;
  logic [7:0] mem_pending_tag;
  logic [6:0] mem_pending_vector;
  logic [3:0] mem_pending_wstrb;
  integer apb_seq;
  integer xlate_seq;
  integer mem_seq;
  integer xlate_pending_id;
  logic [7:0] xlate_pending_tag;
  logic [7:0] xlate_pending_asid;
  logic xlate_pending_write;
  logic [6:0] xlate_pending_vector;
  logic [31:0] xlate_pending_iova;
  integer mem_pending_id;
  integer ptw_seq, ptw_pending_id;
  logic ptw_pending;
  logic [31:0] ptw_pending_addr;
  logic host_aw_pending, host_w_pending;
  logic [3:0] host_aw_pending_id;
  logic [1:0] host_aw_pending_master, host_w_pending_master, host_ar_pending_master;
  logic [31:0] host_aw_pending_addr;
  logic [7:0] host_aw_pending_len;
  logic [2:0] host_aw_pending_size;
  logic [1:0] host_aw_pending_burst;
  logic host_ar_pending;
  logic [3:0] host_ar_pending_id;
  logic [31:0] host_ar_pending_addr;
  logic [7:0] host_ar_pending_len;
  logic [7:0] host_ar_beat;
  logic [2:0] host_ar_pending_size;
  logic [63:0] host_w_data_q [0:15];
  logic [7:0] host_w_strb_q [0:15];
  logic host_w_last_q [0:15];
  integer host_w_count;
  logic [1:0] host_ar_pending_burst;
  logic xlate_pending;
  logic mem_pending;
  integer previous_owned_count;
  logic [7:0] previous_owned_tag;
  logic reset_completion_pending_q;
  logic reset_mem_response_valid_q;
  logic reset_muldiv_result_valid_q;
  logic [2:0] reset_completion_occupancy_q;
  logic [7:0] reset_completion_tag_q;
  logic [3:0] reset_completion_status_q;
  logic [2:0] reset_irq_pending_q;
  logic reset_maint_active_q;
  string trace_path, run_id, source_build_id;
  bit flush_trace;

  task automatic emit(input string kind, input string payload);
    if (fd != 0)
      $fdisplay(fd, "CROSS_EVT|schema=3|eid=%0d|run=%s|build=%s|epoch=%0d|cycle=%0d|kind=%s|%s", event_id, run_id, source_build_id, epoch, cycle, kind, payload);
    if (fd != 0 && flush_trace) $fflush(fd);
    event_id = event_id + 1;
  endtask

  initial begin
    fd = 0;
    cycle = 0;
    epoch = 0;
    event_id = 0;
    submit_seq = 0;
    prev_irq = 1'b0;
    prev_maint_valid = 1'b0;
    prev_firmware_done = 1'b0;
    prev_chip_busy = 1'b0;
    prev_chip_done = 1'b0;
    prev_muldiv_busy = 1'b0;
    prev_dma_busy = 1'b0;
    prev_active_descriptor_tag = '0;
    reset_completion_pending_q = 1'b0;
    reset_mem_response_valid_q = 1'b0;
    reset_muldiv_result_valid_q = 1'b0;
    reset_completion_occupancy_q = '0;
    reset_completion_tag_q = '0;
    reset_completion_status_q = '0;
    reset_irq_pending_q = '0;
    reset_maint_active_q = 1'b0;
    prev_chip_power_state = '0;
    prev_chip_plaintext = '0;
    prev_chip_ciphertext = '0;
    prev_chip_die_b_ciphertext = '0;
    apb_active = 1'b0;
    apb_wait_cycles = 0;
    mem_write_pending = 1'b0;
    mem_pending_addr = '0;
    mem_pending_wdata = '0;
    mem_pending_wstrb = '0;
    mem_pending_tag = '0;
    mem_pending_vector = '0;
    apb_seq = 0;
    xlate_seq = 0;
    mem_seq = 0;
    xlate_pending_id = -1;
    xlate_pending_tag = '0;
    xlate_pending_asid = '0;
    xlate_pending_write = 1'b0;
    xlate_pending_vector = '0;
    xlate_pending_iova = '0;
    mem_pending_id = -1;
    ptw_seq = 0;
    ptw_pending_id = -1;
    ptw_pending = 1'b0;
    ptw_pending_addr = '0;
    host_aw_pending = 1'b0;
    host_w_pending = 1'b0;
    host_ar_pending = 1'b0;
    host_ar_pending_id = '0;
    host_ar_pending_addr = '0;
    host_ar_pending_len = '0;
    host_ar_beat = '0;
    host_ar_pending_size = '0;
    host_ar_pending_burst = '0;
    host_aw_pending_id = '0;
    host_aw_pending_master = '0;
    host_w_pending_master = '0;
    host_ar_pending_master = '0;
    host_aw_pending_addr = '0;
    host_aw_pending_len = '0;
    host_aw_pending_size = '0;
    host_aw_pending_burst = '0;
    host_w_count = 0;
    xlate_pending = 1'b0;
    mem_pending = 1'b0;
    previous_owned_count = 0;
    previous_owned_tag = 8'hff;
    run_id = "unknown";
    source_build_id = "unknown";
    void'($value$plusargs("RUN_ID=%s", run_id));
    void'($value$plusargs("SOURCE_BUILD_ID=%s", source_build_id));
    flush_trace = $test$plusargs("CROSS_TRACE_FLUSH");
    was_reset = 1'b1;
    if ($value$plusargs("CROSS_TRACE=%s", trace_path)) begin
      fd = $fopen(trace_path, "w");
      if (fd == 0) $fatal(1, "cannot open crossover trace %s", trace_path);
    end
  end

  // Capture pre-reset asynchronous state before DUT reset logic clears the
  // completion FIFO. The next sampled RESET_ASSERT event can then prove the
  // reset really interrupted an unread completion.
  always @(negedge rst_n) begin
    if (cycle > 0) begin
      reset_completion_pending_q = completion_valid;
      reset_mem_response_valid_q = mem_rsp_valid;
      reset_muldiv_result_valid_q = muldiv_result_valid;
      reset_completion_occupancy_q = completion_occupancy;
      reset_completion_tag_q = completion_tag;
      reset_completion_status_q = completion_status;
      reset_irq_pending_q = irq_pending_status;
      reset_maint_active_q = maint_busy;
    end
  end

  always @(posedge clk) begin
    cycle <= cycle + 1;
      if (!rst_n) begin
      if (!was_reset) begin
        epoch = epoch + 1;
        emit("RESET_IRQ_SNAPSHOT", $sformatf("pending=%0d",reset_irq_pending_q));
        submit_seq = 0;
        mem_write_pending = 1'b0;
        apb_seq = 0;
        xlate_pending_id = -1;
        mem_pending_id = -1;
        ptw_pending_id = -1;
        emit("RESET_ASSERT", $sformatf("xlate_pending=%0d|mem_pending=%0d|ptw_pending=%0d|host_aw_pending=%0d|host_w_pending=%0d|host_ar_pending=%0d|apb_active=%0d|chip_busy=%0d|dma_busy=%0d|maint_active=%0d|muldiv_busy=%0d|completion_pending=%0d|completion_occupancy=%0d|completion_tag=%0d|completion_status=%0d|mem_response_valid=%0d|muldiv_result_valid=%0d", xlate_pending, mem_pending, ptw_pending, host_aw_pending, host_w_pending, host_ar_pending, apb_active, prev_chip_busy, prev_dma_busy, reset_maint_active_q, prev_muldiv_busy, reset_completion_pending_q, reset_completion_occupancy_q, reset_completion_tag_q, reset_completion_status_q, reset_mem_response_valid_q, reset_muldiv_result_valid_q));
        apb_active = 1'b0;
        apb_wait_cycles = 0;
        xlate_pending = 1'b0;
        mem_pending = 1'b0;
        ptw_pending = 1'b0;
        host_aw_pending = 1'b0;
        host_w_pending = 1'b0;
        host_w_count = 0;
        host_ar_pending = 1'b0;
        host_ar_beat = '0;
        previous_owned_count = 0;
        previous_owned_tag = 8'hff;
      end
      prev_dma_busy <= 1'b0;
      prev_active_descriptor_tag <= '0;
      was_reset <= 1'b1;
    end else begin
      if (was_reset) emit("RESET_RELEASE", "");
      was_reset <= 1'b0;
      if (commit_valid) emit("RETIRE", $sformatf("pc=%08x|next_pc=%08x|insn=%08x|retire_order=%0d|trap=%0d|intr=%0d|rs1_addr=%0d|rs1_data=%08x|rs2_addr=%0d|rs2_data=%08x|rd_addr=%0d|rd_data=%08x|mem_addr=%08x|mem_rmask=%x|mem_wmask=%x|mem_rdata=%08x|mem_wdata=%08x|mstatus=%08x|mie=%08x|mtvec=%08x|mscratch=%08x|mepc=%08x|mcause=%08x|mtval=%08x|irq_level=%0d|irq_timer_level=%0d|m_ext=%0d", commit_pc, commit_next_pc, commit_instr, commit_order, commit_trap, commit_intr, commit_rs1_addr, commit_rs1_data, commit_rs2_addr, commit_rs2_data, commit_rd_addr, commit_rd_data, commit_mem_addr, commit_mem_rmask, commit_mem_wmask, commit_mem_rdata, commit_mem_wdata, commit_mstatus, commit_mie, commit_mtvec, commit_mscratch, commit_mepc, commit_mcause, commit_mtval, irq_ext_level, irq_timer_level, cpu_enable_m));
      if (muldiv_busy != prev_muldiv_busy)
        emit("MDIV_BUSY", $sformatf("busy=%0d",muldiv_busy));
      if (psel && !penable && !apb_active) begin
        apb_active = 1'b1;
        apb_wait_cycles = 0;
        // Capture setup-phase PREADY explicitly. The integration test has an
        // adversarial mode that holds it high here; this must not be mistaken
        // for an APB transfer or an architectural MMIO retirement.
        emit("APB_SETUP", $sformatf("op=%0d|write=%0d|addr=%08x|wdata=%08x|pready=%0d|penable=%0d", apb_seq, pwrite, paddr, pwdata, pready, penable));
      end else if (apb_active && !(psel && penable && pready)) begin
        apb_wait_cycles = apb_wait_cycles + 1;
        emit("APB_WAIT", $sformatf("op=%0d|wait_cycles=%0d", apb_seq, apb_wait_cycles));
      end
      if (psel && penable && pready) begin
        emit("APB", $sformatf("op=%0d|write=%0d|addr=%08x|wdata=%08x|error=%0d|wait_cycles=%0d", apb_seq, pwrite, paddr, pwdata, pslverr, apb_wait_cycles));
        apb_seq = apb_seq + 1;
        apb_active = 1'b0;
      end
      if (xlate_req_valid && xlate_req_ready) begin
        if (xlate_pending) $fatal(1, "observer found a second translation before prior response");
        xlate_pending_id = xlate_seq;
        xlate_seq = xlate_seq + 1;
        xlate_pending = 1'b1;
        xlate_pending_tag = xlate_job_tag;
        xlate_pending_vector = xlate_vector_index;
        xlate_pending_iova = xlate_iova;
        xlate_pending_asid = xlate_asid;
        xlate_pending_write = xlate_write;
        emit("XLATE_REQ", $sformatf("txn=%0d|iova=%08x|asid=%0d|write=%0d|tag=%0d|vector=%0d", xlate_pending_id, xlate_iova, xlate_asid, xlate_write, xlate_job_tag, xlate_vector_index));
      end
      if (xlate_rsp_valid && xlate_rsp_ready)
        begin
          emit("XLATE_RSP", $sformatf("txn=%0d|fault=%0d|tag=%0d|vector=%0d|iova=%08x|asid=%0d|write=%0d|paddr=%08x|tlb_hit=%0d", xlate_pending_id, xlate_fault, xlate_pending_tag, xlate_pending_vector, xlate_pending_iova, xlate_pending_asid, xlate_pending_write, xlate_paddr, xlate_tlb_hit));
          xlate_pending = 1'b0;
        end
      if (ptw_req_valid && ptw_req_ready) begin
        if (ptw_pending) $fatal(1, "observer found overlapping page-table reads in single-request IOMMU");
        ptw_pending = 1'b1;
        ptw_pending_id = ptw_seq;
        ptw_pending_addr = ptw_req_addr;
        ptw_seq = ptw_seq + 1;
        emit("PTW_REQ", $sformatf("txn=%0d|addr=%08x", ptw_pending_id, ptw_req_addr));
      end
      if (ptw_rsp_valid && ptw_rsp_ready) begin
        if (!ptw_pending) $fatal(1, "observer found page-table response without accepted request");
        emit("PTW_RSP", $sformatf("txn=%0d|addr=%08x|data=%08x|error=%0d", ptw_pending_id, ptw_pending_addr, ptw_rsp_data, ptw_rsp_error));
        ptw_pending = 1'b0;
      end
      // Observe the real CPU host master write transaction. PTE memory is
      // updated in the replay model only when its AXI B response succeeds.
      if (host_awvalid && host_awready) begin
        if (host_aw_pending) $fatal(1, "observer found a second host AW before B completion");
        host_aw_pending = 1'b1;
        host_aw_pending_id = host_awid;
        host_aw_pending_master = host_aw_master_index;
        host_aw_pending_addr = host_awaddr;
        host_aw_pending_len = host_awlen;
        host_aw_pending_size = host_awsize;
        host_aw_pending_burst = host_awburst;
        if (host_awlen > 15) $fatal(1, "observer host write burst exceeds trace buffer");
        emit("AXI_AW", $sformatf("master=%0d|id=%0d|addr=%08x|len=%0d|size=%0d|burst=%0d", host_aw_master_index, host_awid, host_awaddr, host_awlen, host_awsize, host_awburst));
      end
      if (dma_awvalid && dma_awready)
        emit("DMA_AXI_AW", $sformatf("master=1|addr=%08x|tag=%0d|vector=%0d",dma_awaddr,mem_pending_tag,mem_pending_vector));
      if (dma_bvalid && dma_bready) emit("DMA_AXI_B","master=1");
      if (host_wvalid && host_wready) begin
        if (host_w_count >= 16) $fatal(1, "observer host write burst exceeds trace buffer");
        if (host_w_count == 0) host_w_pending_master = host_w_master_index;
        else if (host_w_pending_master != host_w_master_index) $fatal(1, "host W master changed within a burst");
        host_w_pending = 1'b1;
        host_w_data_q[host_w_count] = host_wdata;
        host_w_strb_q[host_w_count] = host_wstrb;
        host_w_last_q[host_w_count] = host_wlast;
        emit("AXI_W", $sformatf("master=%0d|beat=%0d|data=%016x|strb=%02x|last=%0d", host_w_master_index, host_w_count, host_wdata, host_wstrb, host_wlast));
        host_w_count = host_w_count + 1;
      end
      if (host_arvalid && host_arready) begin
        if (host_ar_pending) $fatal(1, "observer found a second host AR before final R");
        host_ar_pending = 1'b1;
        host_ar_pending_id = host_arid;
        host_ar_pending_master = host_ar_master_index;
        host_ar_pending_addr = host_araddr;
        host_ar_pending_len = host_arlen;
        host_ar_pending_size = host_arsize;
        host_ar_pending_burst = host_arburst;
        host_ar_beat = '0;
        emit("AXI_AR", $sformatf("master=%0d|id=%0d|addr=%08x|len=%0d|size=%0d|burst=%0d", host_ar_master_index, host_arid, host_araddr, host_arlen, host_arsize, host_arburst));
      end
      if (host_rvalid && host_rready) begin
        if (!host_ar_pending || host_rid != host_ar_pending_id || host_r_master_index != host_ar_pending_master)
          $fatal(1, "observer found host R without matching accepted AR");
        emit("AXI_R", $sformatf("master=%0d|id=%0d|addr=%08x|beat=%0d|size=%0d|data=%016x|resp=%0d|last=%0d", host_r_master_index, host_rid, host_ar_pending_addr + (32'(host_ar_beat) << host_ar_pending_size), host_ar_beat, host_ar_pending_size, host_rdata, host_rresp, host_rlast));
        if (host_rlast != (host_ar_beat == host_ar_pending_len))
          $fatal(1, "observer found host RLAST at an invalid beat");
        if (host_rlast) host_ar_pending = 1'b0;
        else host_ar_beat = host_ar_beat + 1'b1;
      end
      if (host_bvalid && host_bready) begin
        if (!host_aw_pending || !host_w_pending || host_bid != host_aw_pending_id ||
            host_w_count != (int'(host_aw_pending_len) + 1) ||
            host_b_master_index != host_aw_pending_master || host_w_pending_master != host_aw_pending_master)
          $fatal(1, "observer found host B without matching accepted AW/W");
        for (int beat = 0; beat < host_w_count; beat++) begin
          if (host_w_last_q[beat] != (beat == int'(host_aw_pending_len)))
            $fatal(1, "observer found WLAST at incorrect beat %0d", beat);
        end
        emit("AXI_B", $sformatf("master=%0d|id=%0d|resp=%0d", host_b_master_index, host_bid, host_bresp));
        if (host_bresp == 0) begin
          for (int beat = 0; beat < host_w_count; beat++)
            emit("AXI_WRITE", $sformatf("master=%0d|addr=%08x|beat=%0d|len=%0d|size=%0d|data=%016x|strb=%02x", host_b_master_index, host_aw_pending_addr + (32'(beat) << host_aw_pending_size), beat, host_aw_pending_len, host_aw_pending_size, host_w_data_q[beat], host_w_strb_q[beat]));
          if (host_aw_pending_addr >= 32'h3000_0000 && host_aw_pending_addr < 32'h3001_0000 && host_aw_pending_len == 0)
            emit("PTE_WRITE", $sformatf("addr=%08x|data=%016x|strb=%02x", host_aw_pending_addr, host_w_data_q[0], host_w_strb_q[0]));
        end
        host_aw_pending = 1'b0;
        host_w_pending = 1'b0;
        host_w_count = 0;
      end
      if (tlb_inv_valid)
        emit("TLB_INVALIDATE", $sformatf("all=%0d|asid=%0d", tlb_inv_all, tlb_inv_asid));
      if (mem_req_valid && mem_req_ready)
        begin
          if (mem_pending) $fatal(1, "observer found a second memory request before prior response");
          mem_write_pending = mem_write;
          mem_pending_id = mem_seq;
          mem_seq = mem_seq + 1;
          mem_pending = 1'b1;
          mem_pending_addr = mem_addr;
          mem_pending_wdata = mem_wdata;
          mem_pending_wstrb = mem_wstrb;
          mem_pending_tag = mem_job_tag;
          mem_pending_vector = mem_vector_index;
          emit("MEM_REQ", $sformatf("txn=%0d|write=%0d|addr=%08x|wdata=%08x|wstrb=%x|tag=%0d|vector=%0d", mem_pending_id, mem_write, mem_addr, mem_wdata, mem_wstrb, mem_job_tag, mem_vector_index));
        end
      if (mem_rsp_valid && mem_rsp_ready)
        begin
          emit("MEM_RSP", $sformatf("txn=%0d|write=%0d|error=%0d|addr=%08x|wdata=%08x|wstrb=%x|rdata=%08x|committed=%0d|tag=%0d|vector=%0d", mem_pending_id, mem_write_pending, mem_rsp_error, mem_pending_addr, mem_pending_wdata, mem_pending_wstrb, mem_rsp_rdata, mem_write_pending && !mem_rsp_error, mem_pending_tag, mem_pending_vector));
          mem_write_pending = 1'b0;
          mem_pending = 1'b0;
        end
      if (axi_wait) emit("AXI_WAIT", "channel=address_or_data");
      if (cfg_valid && cfg_ready)
        emit("ACCEL_CFG", $sformatf("cfg_kind=%0d|bank=%0d|output=%0d|index=%0d|data=%08x", cfg_kind, cfg_bank, cfg_output, cfg_index, cfg_data));
      if (accel_cmd_valid && accel_cmd_ready)
        emit("ACCEL_CMD", $sformatf("tag=%0d|bank=%0d|k=%0d", accel_cmd_tag, accel_cmd_bank, accel_cmd_k));
      if (submit_accepted) begin
        emit("SUBMIT", $sformatf("tag=%0d|seq=%0d|asid=%0d|input_iova=%08x|output_iova=%08x|input_stride=%0d|output_stride=%0d|k=%0d|batch=%0d|bank=%0d|generation=%0d", submit_tag, submit_seq, submit_asid, submit_input_iova, submit_output_iova, submit_input_stride, submit_output_stride, submit_k, submit_batch, submit_bank, submit_bank_generation));
        submit_seq = submit_seq + 1;
      end
      if (dma_busy && (!prev_dma_busy || active_descriptor_tag != prev_active_descriptor_tag))
        emit("DMA_ACTIVE_START", $sformatf("tag=%0d", active_descriptor_tag));
      if (prev_dma_busy && (!dma_busy || active_descriptor_tag != prev_active_descriptor_tag))
        emit("DMA_ACTIVE_END", $sformatf("tag=%0d", prev_active_descriptor_tag));
      if (submit_rejected)
        emit("SUBMIT_REJECT", $sformatf("tag=%0d|asid=%0d|occupancy=%0d", submit_tag, submit_asid, submit_occupancy));
      if (accel_in_valid && accel_in_ready)
        emit("ACCEL_IN", $sformatf("tag=%0d|vector=%0d|data=%08x", accel_in_tag, mem_vector_index, accel_in_data));
      if (accel_out_valid && accel_out_ready)
        emit("ACCEL_OUT", $sformatf("tag=%0d|vector=%0d|data=%08x", accel_out_tag, mem_vector_index, accel_out_data));
      if (completion_published)
        emit("COMPLETE_PUBLISH", $sformatf("tag=%0d|asid=%0d|status=%0d|fault_stage=%0d|vectors_done=%0d", completion_publish_tag, completion_publish_asid, completion_publish_status, completion_publish_fault_stage, completion_publish_vectors_done));
      if (completion_valid && completion_ready)
        emit("COMPLETE", $sformatf("tag=%0d|asid=%0d|status=%0d|fault_iova=%08x|fault_stage=%0d|vectors_done=%0d|submit_occ=%0d|comp_occ=%0d", completion_tag, completion_asid, completion_status, completion_fault_iova, completion_fault_stage, completion_vectors_done, submit_occupancy, completion_occupancy));
      begin : ownership_events
        integer owned_count;
        owned_count = 0;
        for (int oi = 0; oi < 5; oi++)
          if (owned_valid[oi]) owned_count = owned_count + 1;
        // Ownership can remain non-empty while the queued descriptor becomes
        // the active descriptor. Emit that identity transition as well as
        // count changes so coverage never associates a CPU access with a
        // stale or zero active tag.
        if (owned_count != previous_owned_count || active_descriptor_tag != previous_owned_tag)
        emit("OWNERSHIP", $sformatf("count=%0d|active_tag=%0d|dma_busy=%0d|start=%08x|end=%08x|input_start=%08x|input_end=%08x|output_start=%08x|output_end=%08x", owned_count, active_descriptor_tag, dma_busy,
            owned_count != 0 ? owned_start[0] : 0, owned_count != 0 ? owned_end[0] : 0,
            owned_count != 0 ? owned_input_start[0] : 0, owned_count != 0 ? owned_input_end[0] : 0,
            owned_count != 0 ? owned_output_start[0] : 0, owned_count != 0 ? owned_output_end[0] : 0));
        previous_owned_count = owned_count;
        previous_owned_tag = active_descriptor_tag;
      end
      if (cpu_shared_access && (|owned_valid))
        emit("OWNED_CPU_ACCESS", $sformatf("addr=%08x|write=%0d|active_ranges=%0d|active_tag=%0d", cpu_physical_addr, cpu_shared_write, $countones(owned_valid), active_descriptor_tag));
      if (irq && !prev_irq)
        emit("IRQ_SET", $sformatf("raw=%0d|pending=%0d|enable=%0d|ext=%0d|timer=%0d|muldiv_busy=%0d|apb_active=%0d|apb_wait_cycles=%0d|retire_order=%0d",
             irq_raw_status, irq_pending_status, irq_enable_mask, irq_ext_level, irq_timer_level,
             muldiv_busy, apb_active, apb_wait_cycles, commit_order));
      if(psel&&penable&&pready&&!pslverr&&pwrite&&paddr==32'h4000200c)
        emit("IRQ_ACK", $sformatf("mask=%0d|raw=%0d|pending=%0d|completion_published=%0d|completion_tag=%0d",
             pwdata[2:0],irq_raw_status,irq_pending_status,completion_published,completion_publish_tag));
      if (chip_busy != prev_chip_busy || chip_done != prev_chip_done || chip_error)
        emit("CHIPLET_EVT", $sformatf("busy=%0d|done=%0d|error=%0d", chip_busy, chip_done, chip_error));
      if (chip_power_state != prev_chip_power_state)
        emit("CHIPLET_POWER", $sformatf("state=%0d", chip_power_state));
      if (chip_plaintext_valid || chip_ciphertext_valid || chip_die_b_ciphertext_valid || chip_plaintext != prev_chip_plaintext || chip_ciphertext != prev_chip_ciphertext || chip_die_b_ciphertext != prev_chip_die_b_ciphertext)
        emit("CHIPLET_DATA", $sformatf("plaintext=%016x|ciphertext=%016x|die_b_ciphertext=%016x", chip_plaintext, chip_ciphertext, chip_die_b_ciphertext));
      if (chip_plaintext_valid)
        emit("CHIPLET_IN", $sformatf("data=%016x", chip_plaintext_data));
      if (chip_ciphertext_valid)
        emit("CHIPLET_OUT", $sformatf("data=%016x", chip_ciphertext_data));
      if (chip_die_b_ciphertext_valid)
        emit("CHIPLET_DIE_B_OUT", $sformatf("data=%016x", chip_die_b_ciphertext_data));
      if (maint_valid && maint_ready)
        emit("MAINT_START", $sformatf("cmd=%0d|cache_enabled=%0d|completion_occupancy=%0d", maint_cmd, cache_enabled, completion_occupancy));
      if (maint_done)
        emit("MAINT_DONE", $sformatf("cmd=%0d|error=%0d|completion_occupancy=%0d", maint_cmd, maint_error, completion_occupancy));
      if (recovery_snapshot_valid)
        emit("MEM_SNAPSHOT", $sformatf("addr=%08x|data=%016x|purpose=pre_retry_committed_prefix", recovery_snapshot_addr, recovery_snapshot_data));
      if (firmware_done && !prev_firmware_done) emit("FIRMWARE_DONE", "");
      prev_irq <= irq;
      prev_chip_busy <= chip_busy;
      prev_chip_done <= chip_done;
      prev_muldiv_busy <= muldiv_busy;
      prev_dma_busy <= dma_busy;
      prev_active_descriptor_tag <= active_descriptor_tag;
      prev_chip_power_state <= chip_power_state;
      prev_chip_plaintext <= chip_plaintext;
      prev_chip_ciphertext <= chip_ciphertext;
      prev_chip_die_b_ciphertext <= chip_die_b_ciphertext;
      prev_maint_valid <= maint_valid;
      prev_firmware_done <= firmware_done;
    end
  end

  final if (fd != 0) $fclose(fd);
endmodule
