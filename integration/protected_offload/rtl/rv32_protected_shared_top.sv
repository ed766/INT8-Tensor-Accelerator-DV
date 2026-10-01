`timescale 1ns/1ps
// Coverage builds define SYNTHESIS to avoid unsupported SVA
// lowering. Keep simulation-only ownership checks enabled in those builds
// when explicitly requested, without turning on the trace observer.
`ifndef SYNTHESIS
`define PROTECTED_OWNERSHIP_CHECKS
`endif
`ifdef PROTECTED_COVERAGE
`define PROTECTED_OWNERSHIP_CHECKS
`endif
module rv32_protected_shared_top #(
  parameter int ROM_WORDS=4096,parameter int DATA_MEM_WORDS=4096,
  parameter int COMPLETION_POP_WAIT_CYCLES=0,
  parameter bit USE_CACHE=0,parameter bit CPU_ENABLE_M=0,parameter bit CPU_ENABLE_TRAPS=1,parameter bit ENABLE_CHIPLET=0
)(input logic clk,input logic rst_n,input logic recovery_snapshot_valid,input logic[31:0]recovery_snapshot_addr,input logic[63:0]recovery_snapshot_data,output logic firmware_done,output logic[31:0]firmware_result,
   output logic commit_valid,output logic[31:0]commit_pc,output logic irq,output logic[31:0]cycles,
   output logic[31:0]benchmark_cycles,output logic chip_active_debug,output logic[2:0]chip_state_debug,
   output logic[2:0]chip_submit_debug,output logic[2:0]chip_comp_debug,output logic[8:0]chip_send_debug,
   output logic[8:0]chip_recv_debug,output logic chip_link_debug);
  localparam int NM=4,NS=4,IDW=4,TIDW=6;
  logic instr_valid,instr_ready;logic[31:0]instr,commit_instr,commit_next_pc;logic[63:0] commit_order;
  logic commit_trap,commit_intr;logic[4:0] commit_rs1_addr,commit_rs2_addr,commit_rd_addr;
  logic[31:0] commit_rs1_data,commit_rs2_data,commit_rd_data,commit_mem_addr,commit_mem_rdata,commit_mem_wdata;
  logic[3:0] commit_mem_rmask,commit_mem_wmask;logic[31:0] commit_mstatus,commit_mie,commit_mtvec,commit_mscratch,commit_mepc,commit_mcause,commit_mtval;
  logic[31:0]paddr,pwdata,prdata;logic psel,penable,pwrite,pready,pslverr;
  logic dma_sel,cfg_sel,irq_sel,maint_sel,tlb_sel,timer_sel,mail_sel,host_sel,chip_sel;logic[31:0]dma_rdata,cfg_rdata,irq_rdata,maint_rdata,tlb_rdata,timer_rdata,host_rdata,chip_rdata;
  logic dma_ready,dma_error,cfg_ready_apb,cfg_error,irq_ready,irq_error,maint_ready_apb,maint_error_apb,tlb_ready,tlb_error,timer_ready,timer_error,host_ready,host_error;
  logic dma_apb_enable,dma_pop_wait_armed_q;logic[7:0]dma_pop_wait_count_q;
  logic cfg_valid,cfg_ready,cfg_bank;logic[2:0]cfg_kind;logic[1:0]cfg_output;logic[5:0]cfg_index;logic[31:0]cfg_data;logic[1:0][7:0]bank_generation;
  logic svc_irq,busy;logic[2:0]submit_occupancy,completion_occupancy;logic[31:0]perf_tlb_hits,perf_tlb_misses,perf_walk_reads,perf_faults;
  logic completion_published;logic[7:0]completion_publish_tag,completion_publish_asid;logic[3:0]completion_publish_status;logic[2:0]completion_publish_fault_stage;logic[6:0]completion_publish_vectors_done;
  logic[4:0] owned_valid;logic[4:0][31:0] owned_start,owned_end,owned_input_start,owned_input_end,owned_output_start,owned_output_end;
  logic ptw_req_valid,ptw_req_ready,ptw_rsp_valid,ptw_rsp_ready,ptw_rsp_error,translation_idle,tlb_inv_valid,tlb_inv_all,block_submissions;logic[7:0]tlb_inv_asid;logic[31:0]ptw_req_addr,ptw_rsp_data;
  logic mem_req_valid,mem_req_ready,mem_req_write,mem_rsp_valid,mem_rsp_ready,mem_rsp_error;logic[31:0]mem_req_addr,mem_req_wdata,mem_rsp_rdata;logic[3:0]mem_req_wstrb,mem_req_qos;
  logic[NM-1:0]s_awvalid,s_awready,s_wvalid,s_wready,s_bvalid,s_bready,s_arvalid,s_arready,s_rvalid,s_rready,s_wlast,s_rlast;
  logic[NM-1:0][IDW-1:0]s_awid,s_bid,s_arid,s_rid;logic[NM-1:0][31:0]s_awaddr,s_araddr;logic[NM-1:0][7:0]s_awlen,s_arlen,s_wstrb;logic[NM-1:0][2:0]s_awsize,s_arsize,s_awprot,s_arprot;logic[NM-1:0][1:0]s_awburst,s_arburst,s_bresp,s_rresp;logic[NM-1:0][3:0]s_awqos,s_arqos;logic[NM-1:0][63:0]s_wdata,s_rdata;
  logic[NS-1:0]m_awvalid,m_awready,m_wvalid,m_wready,m_bvalid,m_bready,m_arvalid,m_arready,m_rvalid,m_rready,m_wlast,m_rlast;
  logic[NS-1:0][TIDW-1:0]m_awid,m_bid,m_arid,m_rid;logic[NS-1:0][31:0]m_awaddr,m_araddr;logic[NS-1:0][7:0]m_awlen,m_arlen,m_wstrb;logic[NS-1:0][2:0]m_awsize,m_arsize,m_awprot,m_arprot;logic[NS-1:0][1:0]m_awburst,m_arburst,m_bresp,m_rresp;logic[NS-1:0][3:0]m_awqos,m_arqos;logic[NS-1:0][63:0]m_wdata,m_rdata;logic[NS-1:0]age_ar,age_aw;
  logic[2:0]irq_raw,irq_pending,irq_enable;
  logic irq_apb_enable;
`ifdef TEST_IRQ_ACK_COLLISION
  logic irq_collision_seen_q;
  assign irq_apb_enable=penable && !(irq_sel&&pwrite&&paddr[5:0]==6'h0c&&
      !irq_collision_seen_q&&!completion_published);
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)irq_collision_seen_q<=1'b0;
    else if(irq_sel&&irq_apb_enable&&pwrite&&paddr[5:0]==6'h0c&&completion_published)
      irq_collision_seen_q<=1'b1;
  end
`else
  assign irq_apb_enable=penable;
`endif
`ifdef PROTECTED_OWNERSHIP_CHECKS
  // Verification ownership monitor shadows firmware-written Sv32 PTEs so it
  // can compare CPU physical accesses against each descriptor's translated
  // input/output spans, including non-contiguous pages.
  logic [31:0] ownership_pte_shadow [0:16383] = '{default:32'b0};
  logic [31:0] ownership_aw_addr_q;
`endif
  logic chip_ready,chip_bridge_ready,chip_power_sel,chip_cfg_ready,chip_irq,chip_busy,chip_done,chip_error;logic[1:0]chip_power_state;logic[31:0]chip_bridge_rdata;logic[15:0]chip_tag;logic[63:0]chip_plaintext,chip_ciphertext,chip_die_b_ciphertext;logic chip_plaintext_valid,chip_ciphertext_valid,chip_die_b_ciphertext_valid;logic[63:0]chip_plaintext_data,chip_ciphertext_data,chip_die_b_ciphertext_data;logic chip_crypto_error,chip_irq_monitor;logic chip_cfg_valid,chip_cfg_write;logic[7:0]chip_cfg_addr;logic[31:0]chip_cfg_wdata,chip_cfg_rdata;logic timer_irq;logic[63:0]timer_mtime,timer_mtimecmp;
  logic cache_data_sel,uncached_ext_sel;logic[31:0]direct_rdata;logic direct_ready,direct_error;
  logic cache_req_valid,cache_req_ready,cache_req_write,cache_rsp_valid,cache_rsp_ready,cache_rsp_error;logic[31:0]cache_req_addr,cache_req_wdata,cache_rsp_rdata;logic[3:0]cache_req_wstrb;logic[2:0]cache_req_size;logic[7:0]cache_req_id,cache_rsp_id;
  logic maint_valid,maint_ready,maint_busy,maint_done,maint_error;logic[1:0]maint_cmd;logic[4:0]cache_state;logic cache_hit,cache_miss,cache_evict;logic[1:0]refill_beat,writeback_beat;

  assign dma_sel=psel&&paddr>=32'h4000_0000&&paddr<32'h4000_1000;
  assign mail_sel=psel&&paddr>=32'h4000_1fe0&&paddr<32'h4000_2000;
  assign cfg_sel=psel&&paddr>=32'h4000_1000&&paddr<32'h4000_2000&&!mail_sel;
  assign irq_sel=psel&&paddr>=32'h4000_2000&&paddr<32'h4000_2100;
  assign maint_sel=psel&&paddr>=32'h4000_2100&&paddr<32'h4000_2200;
  assign tlb_sel=psel&&paddr>=32'h4000_2200&&paddr<32'h4000_2300;
  assign timer_sel=psel&&paddr>=32'h4000_2300&&paddr<32'h4000_2400;
  assign host_sel=psel&&((paddr>=32'h1000_0000&&paddr<32'h3001_0000));
  assign chip_sel=ENABLE_CHIPLET&&psel&&paddr>=32'h5000_0000&&paddr<32'h5000_0100;
  assign chip_power_sel=chip_sel&&(paddr[7:0]==8'hf0);
  assign chip_ready=chip_power_sel ? (psel&&penable) : chip_bridge_ready;
  always_comb chip_rdata=chip_power_sel ? {30'd0,chip_power_state} : chip_bridge_rdata;
`ifdef PROTECTED_OWNERSHIP_CHECKS
  // Translate using the same firmware-authored root/leaf PTEs that the DMA
  // page walker sees.  This is verification-only shadow state; it avoids
  // assuming a linear IOVA-to-PA mapping in the ownership checker.
  function automatic logic [31:0] iova_to_phys(input logic [31:0] iova);
    logic [31:0] root_pte,leaf_pte,leaf_base;
    logic [13:0] root_index,leaf_index;
    root_index = 14'((iova >> 22) & 32'h0000_03ff);
    root_pte = ownership_pte_shadow[root_index];
    if (!root_pte[0] || root_pte[31:30] != 0) return 32'b0;
    leaf_base = {root_pte[29:10],12'b0};
    if (leaf_base < 32'h3000_0000 || leaf_base >= 32'h3001_0000) return 32'b0;
    leaf_index = 14'(((leaf_base - 32'h3000_0000) >> 2) + ((iova >> 12) & 32'h0000_03ff));
    leaf_pte = ownership_pte_shadow[leaf_index];
    if (!leaf_pte[0] || leaf_pte[31:30] != 0) return 32'b0;
    return {leaf_pte[29:10],iova[11:0]};
  endfunction
  function automatic logic owned_physical_access(input logic [31:0] start_iova,
                                                  input logic [31:0] end_iova,
                                                  input logic [31:0] physical_addr);
    logic [31:0] page_iova,physical_page,physical_low,physical_high;
    logic [31:0] final_page;
    owned_physical_access = 1'b0;
    final_page = {end_iova[31:12],12'b0};
    for (int page=0; page<64; page++) begin
      page_iova = {start_iova[31:12],12'b0} + (32'(page) << 12);
      if (page_iova <= final_page) begin
        physical_page = iova_to_phys(page_iova);
        if (physical_page != 0) begin
          physical_low = physical_page + ((page == 0) ? {20'b0,start_iova[11:0]} : 32'b0);
          physical_high = physical_page + ((page_iova == final_page) ? {20'b0,end_iova[11:0]} : 32'hfff);
          if (physical_addr >= physical_low && physical_addr <= physical_high)
            owned_physical_access = 1'b1;
        end
      end
    end
  endfunction
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      ownership_aw_addr_q <= 32'b0;
      for (int pte_i=0; pte_i<16384; pte_i++) ownership_pte_shadow[pte_i] = 32'b0;
    end else begin
      // Page-table writes are routed through the uncached direct host port
      // (master 3); shared payload accesses use master 0.
      if (s_awvalid[3] && s_awready[3]) ownership_aw_addr_q <= s_awaddr[3];
      if (s_wvalid[3] && s_wready[3] && ownership_aw_addr_q >= 32'h3000_0000 && ownership_aw_addr_q < 32'h3001_0000) begin
        for (int lane=0; lane<8; lane++) begin
          logic [31:0] byte_addr;
          byte_addr = {ownership_aw_addr_q[31:3],3'b000} + 32'(lane);
          if (s_wstrb[3][lane] && byte_addr >= 32'h3000_0000 && byte_addr < 32'h3001_0000)
            ownership_pte_shadow[(byte_addr-32'h3000_0000)>>2][(((byte_addr-32'h3000_0000)&3)*8) +: 8] <= s_wdata[3][lane*8 +: 8];
        end
      end
    end
  end
`endif
  assign cache_data_sel=host_sel&&paddr<32'h2000_0000;
  assign uncached_ext_sel=host_sel&&!cache_data_sel;
  // Verification-only timing variation at the APB slave boundary. The
  // downstream peripheral sees PENABLE low for each injected wait cycle, so
  // neither the CPU nor the CSR block can treat setup as a side effect.
`ifdef TEST_INDEPENDENT_PUBLISH_POP
  // Verification slave wait policy: delay only the first software pop until
  // the cycle before publication: the CSR registers its pop pulse, so the
  // FIFO consumes it on the following edge. Neither FIFO event is forced.
  logic aligned_pop_seen_q;
  wire next_vector_retires = svc.dma.state == svc.dma.NEXT_VECTOR &&
                            svc.dma.vector_index + 1 == svc.dma.active.batch;
  wire align_pop_wait=dma_sel&&pwrite&&paddr[11:0]==12'h02c&&!aligned_pop_seen_q&&!next_vector_retires;
  assign dma_apb_enable=penable&&!align_pop_wait;
  always_ff @(posedge clk or negedge rst_n)
    if(!rst_n)aligned_pop_seen_q<=1'b0;
    else if(dma_sel&&dma_apb_enable&&pwrite&&paddr[11:0]==12'h02c&&dma_ready)
      aligned_pop_seen_q<=1'b1;
`else
  assign dma_apb_enable=penable&&!(dma_pop_wait_armed_q&&(dma_pop_wait_count_q!=0));
`endif
  always_ff @(posedge clk) begin
    if(!rst_n)begin dma_pop_wait_armed_q<=1'b0;dma_pop_wait_count_q<='0;end
    else if(COMPLETION_POP_WAIT_CYCLES==0)begin dma_pop_wait_armed_q<=1'b0;dma_pop_wait_count_q<='0;end
    else if(dma_sel&&psel&&!penable&&pwrite&&paddr[7:0]==8'h2c&&!dma_pop_wait_armed_q)begin
      dma_pop_wait_armed_q<=1'b1;
      dma_pop_wait_count_q<=8'(COMPLETION_POP_WAIT_CYCLES);
    end else if(dma_pop_wait_armed_q&&dma_sel&&penable&&pwrite&&paddr[7:0]==8'h2c)begin
      if(dma_pop_wait_count_q!=0)dma_pop_wait_count_q<=dma_pop_wait_count_q-1'b1;
      else dma_pop_wait_armed_q<=1'b0;
    end else if(!psel)begin dma_pop_wait_armed_q<=1'b0;dma_pop_wait_count_q<='0;end
  end
  always_comb begin
    prdata='0;pready=psel&&penable;pslverr=psel&&penable;
    if(dma_sel)begin prdata=dma_rdata;pready=dma_ready;pslverr=dma_error;end
    else if(cfg_sel)begin prdata=cfg_rdata;pready=cfg_ready_apb;pslverr=cfg_error;end
    else if(irq_sel)begin prdata=irq_rdata;pready=irq_ready;pslverr=irq_error;end
    else if(maint_sel)begin prdata=maint_rdata;pready=maint_ready_apb;pslverr=maint_error_apb;end
    else if(tlb_sel)begin prdata=tlb_rdata;pready=tlb_ready;pslverr=tlb_error;end
    else if(timer_sel)begin prdata=timer_rdata;pready=timer_ready;pslverr=timer_error;end
    else if(host_sel)begin prdata=host_rdata;pready=host_ready;pslverr=host_error;end
    else if(chip_sel)begin prdata=chip_rdata;pready=chip_ready;pslverr=1'b0;end
    else if(mail_sel)begin prdata=firmware_result;pready=psel&&penable;pslverr=0;end
`ifdef TB_SETUP_PREADY_HIGH
    if(psel&&!penable)pready=1'b1;
`endif
  end

  rv32_core #(.MMIO_BASE(32'h4000_0000),.MMIO_END(32'h5000_00ff),.EXT_MEM_BASE(32'h1000_0000),.EXT_MEM_END(32'h3000_ffff),.DATA_MEM_WORDS(DATA_MEM_WORDS),.ENABLE_TRAPS(CPU_ENABLE_TRAPS),.EBREAK_TEST_HALT(0),.ENABLE_M(CPU_ENABLE_M)) cpu(
    .clk,.rst_n,.instr_valid,.instr_ready,.instr,.irq_ext(irq),.irq_timer(timer_irq),.paddr,.psel,.penable,.pwrite,.pwdata,.prdata,.pready,.pslverr,.commit_valid,.commit_instr,.commit_pc,.commit_next_pc,.halted(),.wb_valid(),.wb_rd(),.wb_data(),.mem_valid(),.mem_write(),.mem_addr(),.mem_wdata(),.mem_rdata(),.branch_taken(),.illegal_instr(),.bus_error(),.retire(),.rvfi_valid(),.rvfi_order(commit_order),.rvfi_insn(),.rvfi_trap(commit_trap),.rvfi_intr(commit_intr),.rvfi_pc_rdata(),.rvfi_pc_wdata(),.rvfi_rs1_addr(commit_rs1_addr),.rvfi_rs2_addr(commit_rs2_addr),.rvfi_rs1_rdata(commit_rs1_data),.rvfi_rs2_rdata(commit_rs2_data),.rvfi_rd_addr(commit_rd_addr),.rvfi_rd_wdata(commit_rd_data),.rvfi_mem_addr(commit_mem_addr),.rvfi_mem_rmask(commit_mem_rmask),.rvfi_mem_wmask(commit_mem_wmask),.rvfi_mem_rdata(commit_mem_rdata),.rvfi_mem_wdata(commit_mem_wdata),.rvfi_mstatus(commit_mstatus),.rvfi_mie(commit_mie),.rvfi_mtvec(commit_mtvec),.rvfi_mscratch(commit_mscratch),.rvfi_mscratch_state(),.rvfi_mepc(commit_mepc),.rvfi_mcause(commit_mcause),.rvfi_mtval(commit_mtval));
  rv32_rom_feeder #(.ROM_WORDS(ROM_WORDS),.DEFAULT_HEX("build/protected_offload/shared_firmware/firmware.hex")) rom(.clk,.rst_n,.instr_ready,.instr_valid,.instr,.commit_valid,.commit_next_pc,.halted(1'b0));
  // The service resolves whether the selected configuration bank is still
  // referenced by queued/active work.  Surface that as a normal APB error.
  protected_accel_apb_config cfg(.clk,.rst_n,.paddr(paddr[11:0]),.psel(cfg_sel),.penable,.pwrite,.pwdata,.prdata(cfg_rdata),.pready(cfg_ready_apb),.pslverr(cfg_error),.cfg_valid,.cfg_ready,.cfg_reject(svc.cfg_reject),.generation_referenced(svc.bank_referenced),.cfg_kind,.cfg_bank,.cfg_output,.cfg_index,.cfg_data,.bank_generation);
  protected_offload_service svc(.clk,.rst_n,.apb_addr(paddr[11:0]),.apb_sel(dma_sel),.apb_enable(dma_apb_enable),.apb_write(pwrite),.apb_wdata(pwdata),.apb_rdata(dma_rdata),.apb_ready(dma_ready),.apb_error(dma_error),.root_pt_addr(32'h3000_0000),.tlb_inv_valid,.block_submissions,.tlb_inv_all,.tlb_inv_asid,.translation_idle,.ptw_req_valid,.ptw_req_ready,.ptw_req_addr,.ptw_rsp_valid,.ptw_rsp_ready,.ptw_rsp_data,.ptw_rsp_error,.mem_req_valid,.mem_req_ready,.mem_req_write,.mem_req_addr,.mem_req_wdata,.mem_req_wstrb,.mem_req_qos,.mem_rsp_valid,.mem_rsp_ready,.mem_rsp_rdata,.mem_rsp_error,.cfg_valid,.cfg_ready,.cfg_kind,.cfg_bank,.cfg_output,.cfg_index,.cfg_data,.bank_generation,.irq(svc_irq),.busy,.submit_occupancy,.completion_occupancy,.completion_published,.completion_publish_tag,.completion_publish_asid,.completion_publish_status,.completion_publish_fault_stage,.completion_publish_vectors_done,.perf_tlb_hits,.perf_tlb_misses,.perf_walk_reads,.perf_faults,.last_translation_tlb_hit(),.accel_command_error(),.perf_accel_accepted(),.perf_accel_completed(),.perf_accel_input_chunks(),.perf_accel_output_stalls(),.perf_accel_bank_swaps(),.owned_valid,.owned_start,.owned_end,.owned_input_start,.owned_input_end,.owned_output_start,.owned_output_end);
  protected_irq_aggregator irqs(.clk,.rst_n,.chiplet_dma_event(chip_irq),.accelerator_event(svc_irq),.device_fault_event(chip_error),.paddr(paddr[5:0]),.psel(irq_sel),.penable(irq_apb_enable),.pwrite,.pwdata,.prdata(irq_rdata),.pready(irq_ready),.pslverr(irq_error),.irq_ext(irq),.raw_status(irq_raw),.pending_status(irq_pending),.enable_mask(irq_enable));
  generate if(ENABLE_CHIPLET)begin:chiplet_service
    protected_chiplet_apb_bridge chiplet_apb(
      .clk,.rst_n,.psel(chip_sel&&!chip_power_sel),.penable,.pwrite,.paddr,.pwdata,
      .prdata(chip_bridge_rdata),.pready(chip_bridge_ready),.pslverr(),.cfg_valid(chip_cfg_valid),
      .cfg_write(chip_cfg_write),.cfg_addr(chip_cfg_addr),.cfg_wdata(chip_cfg_wdata),
      .cfg_rdata(chip_cfg_rdata),.cfg_ready(chip_cfg_ready));
    // This integration submits only firmware-owned DMA jobs. Disable the
    // wrapper's autonomous legacy stream so an old return cannot satisfy a
    // new DMA descriptor before its own AES result arrives.
    soc_chiplet_top chiplet(.clk,.rst_n,.power_state(chip_power_state),.dma_mode_force(1'b1),
      .cfg_valid(chip_cfg_valid),.cfg_write(chip_cfg_write),.cfg_addr(chip_cfg_addr),.cfg_wdata(chip_cfg_wdata),.cfg_rdata(chip_cfg_rdata),.cfg_ready(chip_cfg_ready),.irq_done(chip_irq),
      .plaintext_monitor(chip_plaintext),.ciphertext_monitor(chip_ciphertext),.die_b_ciphertext_monitor(chip_die_b_ciphertext),.plaintext_handshake_monitor(chip_plaintext_valid),.plaintext_handshake_data(chip_plaintext_data),.ciphertext_handshake_monitor(chip_ciphertext_valid),.ciphertext_handshake_data(chip_ciphertext_data),.die_b_ciphertext_handshake_monitor(chip_die_b_ciphertext_valid),.die_b_ciphertext_handshake_data(chip_die_b_ciphertext_data),.crypto_error_flag(chip_crypto_error),
      .dma_busy_monitor(chip_busy),.dma_done_monitor(chip_done),.dma_error_monitor(chip_error),.irq_done_monitor(chip_irq_monitor),.dma_tag_monitor(chip_tag));
    // Keep debug ports within the public chiplet monitor contract so the
    // disabled configuration does not elaborate vendor implementation paths.
    assign chip_active_debug=chip_busy;
    assign chip_state_debug='0;
    assign chip_submit_debug='0;
    assign chip_comp_debug='0;
    assign chip_send_debug='0;
    assign chip_recv_debug='0;
    assign chip_link_debug=chip_busy|chip_done|chip_irq_monitor;
  end else begin:no_chiplet_service
    assign chip_bridge_rdata=0;assign chip_bridge_ready=chip_sel&&penable;assign chip_power_state=0;assign chip_cfg_rdata=0;assign chip_cfg_ready=1'b0;assign chip_irq=0;assign chip_busy=0;assign chip_done=0;assign chip_error=0;assign chip_tag=0;
    assign chip_plaintext=0;assign chip_ciphertext=0;assign chip_die_b_ciphertext=0;assign chip_plaintext_valid=0;assign chip_ciphertext_valid=0;assign chip_die_b_ciphertext_valid=0;assign chip_plaintext_data=0;assign chip_ciphertext_data=0;assign chip_die_b_ciphertext_data=0;assign chip_crypto_error=0;assign chip_irq_monitor=0;
    assign chip_active_debug=0;assign chip_state_debug=0;assign chip_submit_debug=0;assign chip_comp_debug=0;assign chip_send_debug=0;assign chip_recv_debug=0;assign chip_link_debug=0;
  end endgenerate
  generate if(ENABLE_CHIPLET) begin:chiplet_power_register
    always_ff @(posedge clk or negedge rst_n) begin
      if(!rst_n) chip_power_state<=2'd0;
      else if(chip_power_sel&&penable&&pwrite&&chip_ready&&!pslverr)
        chip_power_state<=pwdata[1:0];
    end
  end endgenerate
  protected_cache_maintenance_apb maint(.clk,.rst_n,.paddr(paddr[5:0]),.psel(maint_sel),.penable,.pwrite,.pwdata,.prdata(maint_rdata),.pready(maint_ready_apb),.pslverr(maint_error_apb),.maint_valid,.maint_ready,.maint_cmd,.maint_busy,.maint_done,.maint_error);
  protected_tlb_control_apb tlbctl(.clk,.rst_n,.paddr(paddr[7:0]),.psel(tlb_sel),.penable,.pwrite,.pwdata,.prdata(tlb_rdata),.pready(tlb_ready),.pslverr(tlb_error),.translation_idle,.service_busy(busy),.submit_occupancy,.completion_occupancy,.inv_valid(tlb_inv_valid),.inv_all(tlb_inv_all),.inv_asid(tlb_inv_asid),.block_submissions);
  apb_machine_timer #(.MMIO_BASE(32'h4000_2300)) timer(.pclk(clk),.presetn(rst_n),.paddr,.psel(timer_sel),.penable,.pwrite,.pwdata,.prdata(timer_rdata),.pready(timer_ready),.pslverr(timer_error),.irq_timer(timer_irq),.mtime(timer_mtime),.mtimecmp(timer_mtimecmp));
  always_ff @(posedge clk or negedge rst_n)begin if(!rst_n)begin firmware_done<=0;firmware_result<=0;cycles<=0;benchmark_cycles<=0;end else begin cycles<=cycles+1;if(mail_sel&&penable&&pwrite)begin if(paddr[4:0]==0)benchmark_cycles<=pwdata;else if(paddr[3:0]==0)firmware_result<=pwdata;else if(paddr[3:0]==4)firmware_done<=pwdata[0];end end end

  generate if(!USE_CACHE)begin:uncached_host
   protected_host_axi_bridge #(.AXI_ID(0)) host(.clk,.rst_n,.psel(host_sel),.penable,.pwrite,.paddr,.pwdata,.prdata(host_rdata),.pready(host_ready),.pslverr(host_error),.awvalid(s_awvalid[0]),.awready(s_awready[0]),.awid(s_awid[0]),.awaddr(s_awaddr[0]),.awlen(s_awlen[0]),.awsize(s_awsize[0]),.awburst(s_awburst[0]),.awprot(s_awprot[0]),.awqos(s_awqos[0]),.wvalid(s_wvalid[0]),.wready(s_wready[0]),.wdata(s_wdata[0]),.wstrb(s_wstrb[0]),.wlast(s_wlast[0]),.bvalid(s_bvalid[0]),.bready(s_bready[0]),.bid(s_bid[0]),.bresp(s_bresp[0]),.arvalid(s_arvalid[0]),.arready(s_arready[0]),.arid(s_arid[0]),.araddr(s_araddr[0]),.arlen(s_arlen[0]),.arsize(s_arsize[0]),.arburst(s_arburst[0]),.arprot(s_arprot[0]),.arqos(s_arqos[0]),.rvalid(s_rvalid[0]),.rready(s_rready[0]),.rid(s_rid[0]),.rdata(s_rdata[0]),.rresp(s_rresp[0]),.rlast(s_rlast[0]));
   assign maint_ready=0;assign maint_busy=0;assign maint_done=maint_valid;assign maint_error=0;assign cache_state=0;assign cache_hit=0;assign cache_miss=0;assign cache_evict=0;assign refill_beat=0;assign writeback_beat=0;
   assign s_awvalid[3]=0;assign s_awid[3]=0;assign s_awaddr[3]=0;assign s_awlen[3]=0;assign s_awsize[3]=0;assign s_awburst[3]=0;assign s_awprot[3]=0;assign s_awqos[3]=0;assign s_wvalid[3]=0;assign s_wdata[3]=0;assign s_wstrb[3]=0;assign s_wlast[3]=0;assign s_bready[3]=1;assign s_arvalid[3]=0;assign s_arid[3]=0;assign s_araddr[3]=0;assign s_arlen[3]=0;assign s_arsize[3]=0;assign s_arburst[3]=0;assign s_arprot[3]=0;assign s_arqos[3]=0;assign s_rready[3]=1;
  end else begin:cached_host
   logic[31:0]cache_rdata;logic cache_ready_apb,cache_error_apb;
   protected_apb_cache_bridge cb(.clk,.rst_n,.psel(cache_data_sel),.penable,.pwrite,.paddr,.pwdata,.prdata(cache_rdata),.pready(cache_ready_apb),.pslverr(cache_error_apb),.cpu_req_valid(cache_req_valid),.cpu_req_ready(cache_req_ready),.cpu_req_addr(cache_req_addr),.cpu_req_write(cache_req_write),.cpu_req_wdata(cache_req_wdata),.cpu_req_wstrb(cache_req_wstrb),.cpu_req_size(cache_req_size),.cpu_req_id(cache_req_id),.cpu_rsp_valid(cache_rsp_valid),.cpu_rsp_ready(cache_rsp_ready),.cpu_rsp_rdata(cache_rsp_rdata),.cpu_rsp_error(cache_rsp_error));
   protected_host_axi_bridge #(.AXI_ID(3)) direct(.clk,.rst_n,.psel(uncached_ext_sel),.penable,.pwrite,.paddr,.pwdata,.prdata(direct_rdata),.pready(direct_ready),.pslverr(direct_error),.awvalid(s_awvalid[3]),.awready(s_awready[3]),.awid(s_awid[3]),.awaddr(s_awaddr[3]),.awlen(s_awlen[3]),.awsize(s_awsize[3]),.awburst(s_awburst[3]),.awprot(s_awprot[3]),.awqos(s_awqos[3]),.wvalid(s_wvalid[3]),.wready(s_wready[3]),.wdata(s_wdata[3]),.wstrb(s_wstrb[3]),.wlast(s_wlast[3]),.bvalid(s_bvalid[3]),.bready(s_bready[3]),.bid(s_bid[3]),.bresp(s_bresp[3]),.arvalid(s_arvalid[3]),.arready(s_arready[3]),.arid(s_arid[3]),.araddr(s_araddr[3]),.arlen(s_arlen[3]),.arsize(s_arsize[3]),.arburst(s_arburst[3]),.arprot(s_arprot[3]),.arqos(s_arqos[3]),.rvalid(s_rvalid[3]),.rready(s_rready[3]),.rid(s_rid[3]),.rdata(s_rdata[3]),.rresp(s_rresp[3]),.rlast(s_rlast[3]));
   always_comb begin if(cache_data_sel)begin host_rdata=cache_rdata;host_ready=cache_ready_apb;host_error=cache_error_apb;end else begin host_rdata=direct_rdata;host_ready=direct_ready;host_error=direct_error;end end
   l1_dcache_top cache(.clk,.rst_n,.cpu_req_valid(cache_req_valid),.cpu_req_ready(cache_req_ready),.cpu_req_addr(cache_req_addr),.cpu_req_write(cache_req_write),.cpu_req_wdata(cache_req_wdata),.cpu_req_wstrb(cache_req_wstrb),.cpu_req_size(cache_req_size),.cpu_req_id(cache_req_id),.cpu_rsp_valid(cache_rsp_valid),.cpu_rsp_ready(cache_rsp_ready),.cpu_rsp_rdata(cache_rsp_rdata),.cpu_rsp_id(cache_rsp_id),.cpu_rsp_error(cache_rsp_error),.maint_valid,.maint_ready,.maint_cmd,.maint_busy,.maint_done,.maint_error,.m_axi_awaddr(s_awaddr[0]),.m_axi_awlen(s_awlen[0]),.m_axi_awsize(s_awsize[0]),.m_axi_awburst(s_awburst[0]),.m_axi_awvalid(s_awvalid[0]),.m_axi_awready(s_awready[0]),.m_axi_wdata(s_wdata[0]),.m_axi_wstrb(s_wstrb[0]),.m_axi_wlast(s_wlast[0]),.m_axi_wvalid(s_wvalid[0]),.m_axi_wready(s_wready[0]),.m_axi_bresp(s_bresp[0]),.m_axi_bvalid(s_bvalid[0]),.m_axi_bready(s_bready[0]),.m_axi_araddr(s_araddr[0]),.m_axi_arlen(s_arlen[0]),.m_axi_arsize(s_arsize[0]),.m_axi_arburst(s_arburst[0]),.m_axi_arvalid(s_arvalid[0]),.m_axi_arready(s_arready[0]),.m_axi_rdata(s_rdata[0]),.m_axi_rresp(s_rresp[0]),.m_axi_rlast(s_rlast[0]),.m_axi_rvalid(s_rvalid[0]),.m_axi_rready(s_rready[0]),.mon_state(cache_state),.mon_hit(cache_hit),.mon_miss(cache_miss),.mon_evict(cache_evict),.mon_refill_beat(refill_beat),.mon_writeback_beat(writeback_beat));
   assign s_awid[0]=0;assign s_awprot[0]=0;assign s_awqos[0]=8;assign s_arid[0]=0;assign s_arprot[0]=0;assign s_arqos[0]=8;
  end endgenerate
  protected_dma_axi_adapter #(.AXI_ID(1)) dmax(.clk,.rst_n,.req_valid(mem_req_valid),.req_ready(mem_req_ready),.req_write(mem_req_write),.req_addr(mem_req_addr),.req_wdata(mem_req_wdata),.req_wstrb(mem_req_wstrb),.req_qos(mem_req_qos),.rsp_valid(mem_rsp_valid),.rsp_ready(mem_rsp_ready),.rsp_rdata(mem_rsp_rdata),.rsp_error(mem_rsp_error),.awvalid(s_awvalid[1]),.awready(s_awready[1]),.awid(s_awid[1]),.awaddr(s_awaddr[1]),.awlen(s_awlen[1]),.awsize(s_awsize[1]),.awburst(s_awburst[1]),.awprot(s_awprot[1]),.awqos(s_awqos[1]),.wvalid(s_wvalid[1]),.wready(s_wready[1]),.wdata(s_wdata[1]),.wstrb(s_wstrb[1]),.wlast(s_wlast[1]),.bvalid(s_bvalid[1]),.bready(s_bready[1]),.bid(s_bid[1]),.bresp(s_bresp[1]),.arvalid(s_arvalid[1]),.arready(s_arready[1]),.arid(s_arid[1]),.araddr(s_araddr[1]),.arlen(s_arlen[1]),.arsize(s_arsize[1]),.arburst(s_arburst[1]),.arprot(s_arprot[1]),.arqos(s_arqos[1]),.rvalid(s_rvalid[1]),.rready(s_rready[1]),.rid(s_rid[1]),.rdata(s_rdata[1]),.rresp(s_rresp[1]),.rlast(s_rlast[1]));
  protected_dma_axi_adapter #(.AXI_ID(2)) ptwx(.clk,.rst_n,.req_valid(ptw_req_valid),.req_ready(ptw_req_ready),.req_write(1'b0),.req_addr(ptw_req_addr),.req_wdata('0),.req_wstrb('0),.req_qos(4'hf),.rsp_valid(ptw_rsp_valid),.rsp_ready(ptw_rsp_ready),.rsp_rdata(ptw_rsp_data),.rsp_error(ptw_rsp_error),.awvalid(s_awvalid[2]),.awready(s_awready[2]),.awid(s_awid[2]),.awaddr(s_awaddr[2]),.awlen(s_awlen[2]),.awsize(s_awsize[2]),.awburst(s_awburst[2]),.awprot(s_awprot[2]),.awqos(s_awqos[2]),.wvalid(s_wvalid[2]),.wready(s_wready[2]),.wdata(s_wdata[2]),.wstrb(s_wstrb[2]),.wlast(s_wlast[2]),.bvalid(s_bvalid[2]),.bready(s_bready[2]),.bid(s_bid[2]),.bresp(s_bresp[2]),.arvalid(s_arvalid[2]),.arready(s_arready[2]),.arid(s_arid[2]),.araddr(s_araddr[2]),.arlen(s_arlen[2]),.arsize(s_arsize[2]),.arburst(s_arburst[2]),.arprot(s_arprot[2]),.arqos(s_arqos[2]),.rvalid(s_rvalid[2]),.rready(s_rready[2]),.rid(s_rid[2]),.rdata(s_rdata[2]),.rresp(s_rresp[2]),.rlast(s_rlast[2]));
  axi4_qos_fabric fabric(.clk,.rst_n,.*,.mon_ar_age_override(age_ar),.mon_aw_age_override(age_aw));
  protected_axi_sram #(.ID_W(TIDW),.WORDS(16),.BASE(0),.FORCE_ERROR(1)) reserved(.clk,.rst_n,.awvalid(m_awvalid[0]),.awready(m_awready[0]),.awid(m_awid[0]),.awaddr(m_awaddr[0]),.awlen(m_awlen[0]),.awsize(m_awsize[0]),.wvalid(m_wvalid[0]),.wready(m_wready[0]),.wdata(m_wdata[0]),.wstrb(m_wstrb[0]),.wlast(m_wlast[0]),.bvalid(m_bvalid[0]),.bready(m_bready[0]),.bid(m_bid[0]),.bresp(m_bresp[0]),.arvalid(m_arvalid[0]),.arready(m_arready[0]),.arid(m_arid[0]),.araddr(m_araddr[0]),.arlen(m_arlen[0]),.arsize(m_arsize[0]),.rvalid(m_rvalid[0]),.rready(m_rready[0]),.rid(m_rid[0]),.rdata(m_rdata[0]),.rresp(m_rresp[0]),.rlast(m_rlast[0]));
`define SRAM(I,N,B,E) protected_axi_sram #(.ID_W(TIDW),.WORDS(N),.BASE(B),.FORCE_ERROR(E)) mem``I(.clk,.rst_n,.awvalid(m_awvalid[I]),.awready(m_awready[I]),.awid(m_awid[I]),.awaddr(m_awaddr[I]),.awlen(m_awlen[I]),.awsize(m_awsize[I]),.wvalid(m_wvalid[I]),.wready(m_wready[I]),.wdata(m_wdata[I]),.wstrb(m_wstrb[I]),.wlast(m_wlast[I]),.bvalid(m_bvalid[I]),.bready(m_bready[I]),.bid(m_bid[I]),.bresp(m_bresp[I]),.arvalid(m_arvalid[I]),.arready(m_arready[I]),.arid(m_arid[I]),.araddr(m_araddr[I]),.arlen(m_arlen[I]),.arsize(m_arsize[I]),.rvalid(m_rvalid[I]),.rready(m_rready[I]),.rid(m_rid[I]),.rdata(m_rdata[I]),.rresp(m_rresp[I]),.rlast(m_rlast[I]));
  `SRAM(1,8192,32'h1000_0000,0)
  `SRAM(2,8192,32'h2000_0000,1)
  `SRAM(3,8192,32'h3000_0000,0)
`undef SRAM
`ifdef PROTECTED_OWNERSHIP_CHECKS
  // Keep all firmware-controlled crossings observable without adding ports to
  // the integration top.  The off-line model treats this trace as evidence,
  // not as the oracle for the RTL itself.
  protected_crossover_observer crossover_observer(
    .dma_awvalid(s_awvalid[1]),.dma_awready(s_awready[1]),.dma_awaddr(s_awaddr[1]),
    .dma_bvalid(s_bvalid[1]),.dma_bready(s_bready[1]),
    .maint_busy,
    .clk,.rst_n,.commit_valid,.commit_pc,.commit_instr,.psel,.penable,.pwrite,.pwdata,.pready,.pslverr,.paddr,
    .cpu_shared_access(cache_data_sel&&psel&&penable&&pready),.cpu_shared_write(pwrite),.cpu_physical_addr(paddr),
    .commit_trap,.commit_intr,.commit_rs1_addr,.commit_rs2_addr,.commit_rs1_data,.commit_rs2_data,.commit_rd_addr,.commit_rd_data,.commit_mem_addr,.commit_mem_rmask,.commit_mem_wmask,.commit_mem_rdata,.commit_mem_wdata,.commit_mstatus,.commit_mie,.commit_mtvec,.commit_mscratch,.commit_mepc,.commit_mcause,.commit_mtval,.cpu_enable_m(CPU_ENABLE_M),.irq_ext_level(irq),.irq_timer_level(timer_irq),.muldiv_busy(cpu.muldiv_active_q),.muldiv_result_valid(cpu.muldiv_rsp_valid),
    .xlate_req_valid(svc.xlate_req_valid),.xlate_req_ready(svc.xlate_req_ready),.xlate_rsp_valid(svc.xlate_rsp_valid),.xlate_rsp_ready(svc.xlate_rsp_ready),
    .xlate_iova(svc.xlate_req_iova),.xlate_paddr(svc.xlate_rsp_paddr),.xlate_asid(svc.xlate_req_asid),.xlate_write(svc.xlate_req_write),.xlate_fault(svc.xlate_rsp_fault),.xlate_tlb_hit(svc.tlb_hit),.xlate_job_tag(svc.dma.active.tag),.xlate_vector_index(svc.dma.vector_index),
    .ptw_req_valid,.ptw_req_ready,.ptw_req_addr,.ptw_rsp_valid,.ptw_rsp_ready,.ptw_rsp_data,.ptw_rsp_error,
    .host_awvalid(USE_CACHE ? (s_awvalid[3]||s_awvalid[0]) : s_awvalid[0]),
    .host_awready(USE_CACHE ? (s_awvalid[3]?s_awready[3]:s_awready[0]) : s_awready[0]),
    .host_aw_master_index(USE_CACHE ? (s_awvalid[3]?2'd3:2'd0) : 2'd0),
    .host_awid(USE_CACHE ? (s_awvalid[3]?s_awid[3]:s_awid[0]) : s_awid[0]),
    .host_awaddr(USE_CACHE ? (s_awvalid[3]?s_awaddr[3]:s_awaddr[0]) : s_awaddr[0]),
    .host_awlen(USE_CACHE ? (s_awvalid[3]?s_awlen[3]:s_awlen[0]) : s_awlen[0]),
    .host_awsize(USE_CACHE ? (s_awvalid[3]?s_awsize[3]:s_awsize[0]) : s_awsize[0]),
    .host_awburst(USE_CACHE ? (s_awvalid[3]?s_awburst[3]:s_awburst[0]) : s_awburst[0]),
    .host_wvalid(USE_CACHE ? (s_wvalid[3]||s_wvalid[0]) : s_wvalid[0]),
    .host_wready(USE_CACHE ? (s_wvalid[3]?s_wready[3]:s_wready[0]) : s_wready[0]),
    .host_w_master_index(USE_CACHE ? (s_wvalid[3]?2'd3:2'd0) : 2'd0),
    .host_wdata(USE_CACHE ? (s_wvalid[3]?s_wdata[3]:s_wdata[0]) : s_wdata[0]),
    .host_wstrb(USE_CACHE ? (s_wvalid[3]?s_wstrb[3]:s_wstrb[0]) : s_wstrb[0]),
    .host_wlast(USE_CACHE ? (s_wvalid[3]?s_wlast[3]:s_wlast[0]) : s_wlast[0]),
    .host_bvalid(USE_CACHE ? (s_bvalid[3]||s_bvalid[0]) : s_bvalid[0]),
    .host_bready(USE_CACHE ? (s_bvalid[3]?s_bready[3]:s_bready[0]) : s_bready[0]),
    .host_b_master_index(USE_CACHE ? (s_bvalid[3]?2'd3:2'd0) : 2'd0),
    .host_bid(USE_CACHE ? (s_bvalid[3]?s_bid[3]:s_bid[0]) : s_bid[0]),
    .host_bresp(USE_CACHE ? (s_bvalid[3]?s_bresp[3]:s_bresp[0]) : s_bresp[0]),
    .host_arvalid(USE_CACHE ? (s_arvalid[3]||s_arvalid[0]) : s_arvalid[0]),
    .host_arready(USE_CACHE ? (s_arvalid[3]?s_arready[3]:s_arready[0]) : s_arready[0]),
    .host_ar_master_index(USE_CACHE ? (s_arvalid[3]?2'd3:2'd0) : 2'd0),
    .host_arid(USE_CACHE ? (s_arvalid[3]?s_arid[3]:s_arid[0]) : s_arid[0]),
    .host_araddr(USE_CACHE ? (s_arvalid[3]?s_araddr[3]:s_araddr[0]) : s_araddr[0]),
    .host_arlen(USE_CACHE ? (s_arvalid[3]?s_arlen[3]:s_arlen[0]) : s_arlen[0]),
    .host_arsize(USE_CACHE ? (s_arvalid[3]?s_arsize[3]:s_arsize[0]) : s_arsize[0]),
    .host_arburst(USE_CACHE ? (s_arvalid[3]?s_arburst[3]:s_arburst[0]) : s_arburst[0]),
    .host_rvalid(USE_CACHE ? (s_rvalid[3]||s_rvalid[0]) : s_rvalid[0]),
    .host_rready(USE_CACHE ? (s_rvalid[3]?s_rready[3]:s_rready[0]) : s_rready[0]),
    .host_r_master_index(USE_CACHE ? (s_rvalid[3]?2'd3:2'd0) : 2'd0),
    .host_rid(USE_CACHE ? (s_rvalid[3]?s_rid[3]:s_rid[0]) : s_rid[0]),
    .host_rdata(USE_CACHE ? (s_rvalid[3]?s_rdata[3]:s_rdata[0]) : s_rdata[0]),
    .host_rresp(USE_CACHE ? (s_rvalid[3]?s_rresp[3]:s_rresp[0]) : s_rresp[0]),
    .host_rlast(USE_CACHE ? (s_rvalid[3]?s_rlast[3]:s_rlast[0]) : s_rlast[0]),
    .tlb_inv_valid,.tlb_inv_all,.tlb_inv_asid,
    .mem_req_valid,.mem_req_ready,.mem_rsp_valid,.mem_rsp_ready,.mem_write(mem_req_write),.mem_addr(mem_req_addr),.mem_wdata(mem_req_wdata),.mem_wstrb(mem_req_wstrb),.mem_rsp_rdata,.mem_rsp_error,.mem_job_tag(svc.dma.active.tag),.mem_vector_index(svc.dma.vector_index),.axi_wait((|(m_awvalid&~m_awready))||(|(m_wvalid&~m_wready))||(|(m_arvalid&~m_arready))),
    .cfg_valid,.cfg_ready,.cfg_kind,.cfg_bank,.cfg_output,.cfg_index,.cfg_data,
    .accel_cmd_valid(svc.accel_cmd_valid),.accel_cmd_ready(svc.accel_cmd_ready),.accel_cmd_bank(svc.accel_cmd_bank),.accel_cmd_k(svc.accel_cmd_k),.accel_cmd_tag(svc.accel_cmd_tag),
    .accel_in_valid(svc.accel_in_valid),.accel_in_ready(svc.accel_in_ready),.accel_in_data(svc.accel_in_data),.accel_in_tag(svc.accel_in_tag),.accel_out_valid(svc.accel_out_valid),.accel_out_ready(svc.accel_out_ready),.accel_out_tag(svc.accel_out_tag),.accel_out_data(svc.accel_out_data),
    .completion_valid(svc.completion_valid),.completion_ready(svc.completion_ready),.completion_tag(svc.completion_tag),.completion_status(svc.completion_status),.completion_asid(svc.completion_asid),.completion_fault_iova(svc.completion_fault_iova),.completion_fault_stage(svc.completion_fault_stage),.completion_vectors_done(svc.completion_vectors_done),.completion_published,.completion_publish_tag,.completion_publish_asid,.completion_publish_status,.completion_publish_fault_stage,.completion_publish_vectors_done,.submit_accepted(svc.submit_accepted),.submit_rejected(svc.dma.submit_rejected),.submit_tag(svc.submit_tag),.submit_asid(svc.submit_asid),.submit_input_iova(svc.dma.submit_input_iova),.submit_output_iova(svc.dma.submit_output_iova),.submit_input_stride(svc.dma.submit_input_stride),.submit_output_stride(svc.dma.submit_output_stride),.submit_k(svc.dma.submit_k),.submit_batch(svc.dma.submit_batch),.submit_bank(svc.dma.submit_bank),.submit_bank_generation(svc.dma.submit_bank_generation),.irq_raw_status(irq_raw),.irq_pending_status(irq_pending),.irq_enable_mask(irq_enable),.cache_enabled(USE_CACHE),.active_descriptor_tag(svc.dma.active.tag),.dma_busy(svc.dma.busy),.commit_next_pc,.commit_order,.owned_valid,.owned_start,.owned_end,.owned_input_start,.owned_input_end,.owned_output_start,.owned_output_end,
    .irq,.chip_busy,.chip_done,.chip_error,.chip_power_state,.chip_plaintext,.chip_ciphertext,.chip_die_b_ciphertext,
    .chip_plaintext_valid,.chip_plaintext_data,.chip_ciphertext_valid,.chip_ciphertext_data,
    .chip_die_b_ciphertext_valid,.chip_die_b_ciphertext_data,.submit_occupancy,.completion_occupancy,.maint_valid,.maint_ready,.maint_cmd,.maint_done,.maint_error,.recovery_snapshot_valid,.recovery_snapshot_addr,.recovery_snapshot_data,.firmware_done);
`endif
`ifdef PROTECTED_OWNERSHIP_CHECKS
  always_ff @(posedge clk) begin
    if (rst_n && USE_CACHE) begin
      if ((s_awvalid[0] && s_awvalid[3]) || (s_wvalid[0] && s_wvalid[3]) ||
          (s_bvalid[0] && s_bvalid[3]) || (s_arvalid[0] && s_arvalid[3]) ||
          (s_rvalid[0] && s_rvalid[3]))
        $fatal(1, "observer host-port mux cannot represent simultaneous CPU master 0 and 3 channel activity");
    end
  end
  generate if(USE_CACHE)begin:ownership_checks
    always_ff @(posedge clk) begin
      if (rst_n && cache_data_sel && penable) begin
        for (int oi = 0; oi < 5; oi++) begin
          if (owned_valid[oi] &&
              (owned_physical_access(owned_input_start[oi],owned_input_end[oi],paddr) ||
               owned_physical_access(owned_output_start[oi],owned_output_end[oi],paddr)))
            $fatal(1, "OWNERSHIP_VIOLATION: CPU accessed owned line %08x (input %08x..%08x output %08x..%08x)", paddr,
                   owned_input_start[oi], owned_input_end[oi], owned_output_start[oi], owned_output_end[oi]);
        end
      end
    end
  end endgenerate
`endif
`undef PROTECTED_OWNERSHIP_CHECKS
endmodule
