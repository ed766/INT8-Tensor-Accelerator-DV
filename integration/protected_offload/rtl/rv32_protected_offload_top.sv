`timescale 1ns/1ps
module rv32_protected_offload_top #(
  parameter int ROM_WORDS=4096,
  parameter int DATA_MEM_WORDS=4096,
  parameter int MEM_WORDS=8192
)(
  input logic clk,input logic rst_n,
  output logic firmware_done,output logic[31:0]firmware_result,
  output logic commit_valid,output logic[31:0]commit_pc,output logic[31:0]commit_instr,
  output logic irq,output logic[31:0]cycles
);
  localparam logic[31:0]PHYS_BASE=32'h10000000;
  logic cpu_rst_n,config_done;logic instr_valid,instr_ready;logic[31:0]instr,commit_next_pc;
  logic[31:0]paddr,pwdata,prdata;logic psel,penable,pwrite,pready,pslverr,csr_sel,mail_sel;
  logic[31:0]csr_prdata;logic csr_pready,csr_pslverr;
  logic submit_valid,submit_ready,submit_accepted,submit_rejected;logic[31:0]submit_input_iova,submit_output_iova;
  logic[15:0]submit_input_stride,submit_output_stride;logic[6:0]submit_k,submit_batch;logic[7:0]submit_tag,submit_asid,submit_bank_generation;logic submit_bank;logic[3:0]submit_qos;logic[1:0][7:0]bank_generation=16'h0207;
  logic xlate_req_valid,xlate_req_ready,xlate_req_write,xlate_rsp_valid,xlate_rsp_ready;logic[31:0]xlate_req_iova,xlate_rsp_paddr;logic[7:0]xlate_req_asid;logic[1:0]xlate_rsp_fault;
  logic mem_req_valid,mem_req_ready,mem_req_write,mem_rsp_valid,mem_rsp_ready;logic[31:0]mem_req_addr,mem_req_wdata,mem_rsp_rdata;logic[3:0]mem_req_wstrb,mem_req_qos;logic mem_rsp_error;
  logic accel_cmd_valid,accel_cmd_ready,accel_cmd_bank;logic[6:0]accel_cmd_k;logic[7:0]accel_cmd_tag;logic accel_in_valid,accel_in_ready,accel_out_valid,accel_out_ready;logic[31:0]accel_in_data,accel_out_data;logic[7:0]accel_in_tag,accel_out_tag;
  logic completion_valid,completion_ready,busy;logic[7:0]completion_tag,completion_asid;logic[3:0]completion_status;logic[31:0]completion_fault_iova;logic[2:0]completion_fault_stage,submit_occupancy,completion_occupancy;logic[6:0]completion_vectors_done;
  logic completion_published;logic[7:0]completion_publish_tag,completion_publish_asid;logic[3:0]completion_publish_status;logic[2:0]completion_publish_fault_stage;logic[6:0]completion_publish_vectors_done;
  logic[4:0] owned_valid;logic[4:0][31:0]owned_start,owned_end,owned_input_start,owned_input_end,owned_output_start,owned_output_end;
  logic[1:0] bank_referenced;logic iommu_idle;
  logic cfg_valid,cfg_ready,cfg_bank;logic[2:0]cfg_kind;logic[1:0]cfg_output;logic[5:0]cfg_index;logic[31:0]cfg_data;logic cmd_error;
  logic[31:0]perf_accepted,perf_completed,perf_input_chunks,perf_output_stalls,perf_bank_swaps;
  logic[31:0]memory[MEM_WORDS];logic mem_pending,pending_mem_write;logic[31:0]pending_addr,pending_wdata;logic[3:0]pending_wstrb;
  logic ptw_req_valid,ptw_req_ready,ptw_rsp_valid,ptw_rsp_ready,ptw_rsp_error,tlb_hit;
  logic[31:0]ptw_req_addr,ptw_rsp_data,perf_tlb_hits,perf_tlb_misses,perf_walk_reads,perf_faults;
  logic[1:0]cfg_phase;logic[1:0]cfg_out;logic[5:0]cfg_weight;
  assign cpu_rst_n=rst_n&&config_done;
  assign csr_sel=psel&&(paddr>=32'h40000000)&&(paddr<32'h40001000)&&!mail_sel;
  assign mail_sel=psel&&(paddr>=32'h40001ff0)&&(paddr<32'h40002000);
  assign prdata=csr_sel?csr_prdata:(mail_sel?firmware_result:0);
  assign pready=csr_sel?csr_pready:(psel&&penable);
  assign pslverr=csr_sel?csr_pslverr:(psel&&penable&&!mail_sel);
  assign mem_req_ready=!mem_pending;
  assign ptw_req_ready=1'b1;
  function automatic int mem_index(input logic[31:0]address);return int'((address-PHYS_BASE)>>2);endfunction

  rv32_core #(.MMIO_BASE(32'h40000000),.MMIO_END(32'h40001fff),.DATA_MEM_WORDS(DATA_MEM_WORDS),.ENABLE_TRAPS(0),.EBREAK_TEST_HALT(1)) cpu(
    .clk,.rst_n(cpu_rst_n),.instr_valid,.instr_ready,.instr,.irq_ext(irq),.irq_timer(1'b0),.paddr,.psel,.penable,.pwrite,.pwdata,.prdata,.pready,.pslverr,
    .commit_valid,.commit_instr,.commit_pc,.commit_next_pc,.halted(),.wb_valid(),.wb_rd(),.wb_data(),.mem_valid(),.mem_write(),.mem_addr(),.mem_wdata(),.mem_rdata(),.branch_taken(),.illegal_instr(),.bus_error(),.retire(),
    .rvfi_valid(),.rvfi_order(),.rvfi_insn(),.rvfi_trap(),.rvfi_intr(),.rvfi_pc_rdata(),.rvfi_pc_wdata(),.rvfi_rs1_addr(),.rvfi_rs2_addr(),.rvfi_rs1_rdata(),.rvfi_rs2_rdata(),.rvfi_rd_addr(),.rvfi_rd_wdata(),.rvfi_mem_addr(),.rvfi_mem_rmask(),.rvfi_mem_wmask(),.rvfi_mem_rdata(),.rvfi_mem_wdata(),.rvfi_mstatus(),.rvfi_mie(),.rvfi_mtvec(),.rvfi_mscratch(),.rvfi_mscratch_state(),.rvfi_mepc(),.rvfi_mcause(),.rvfi_mtval());
  rv32_rom_feeder #(.ROM_WORDS(ROM_WORDS),.DEFAULT_HEX("build/protected_offload/firmware/workflow_0_O2/firmware.hex")) rom(.clk,.rst_n(cpu_rst_n),.instr_ready,.instr_valid,.instr,.commit_valid,.commit_next_pc,.halted(1'b0));
  protected_offload_apb_csr csr(.clk,.rst_n,.paddr(paddr[11:0]),.psel(csr_sel),.penable,.pwrite,.pwdata,.prdata(csr_prdata),.pready(csr_pready),.pslverr(csr_pslverr),.submit_valid,.submit_ready,.submit_input_iova,.submit_output_iova,.submit_input_stride,.submit_output_stride,.submit_k,.submit_batch,.submit_tag,.submit_asid,.submit_bank,.submit_bank_generation,.submit_qos,.submit_accepted,.submit_rejected,.busy,.submit_occupancy,.completion_valid,.completion_ready,.completion_tag,.completion_status,.completion_asid,.completion_fault_iova,.completion_fault_stage,.completion_vectors_done,.completion_occupancy,.irq);
  protected_offload_dma #(.QUEUE_DEPTH(4)) dma(.clk,.rst_n,.submit_valid,.submit_ready,.submit_input_iova,.submit_output_iova,.submit_input_stride,.submit_output_stride,.submit_k,.submit_batch,.submit_tag,.submit_asid,.submit_bank,.submit_bank_generation,.submit_qos,.bank_generation,.block_submissions(1'b0),.submit_accepted,.submit_rejected,.xlate_req_valid,.xlate_req_ready,.xlate_req_iova,.xlate_req_asid,.xlate_req_write,.xlate_rsp_valid,.xlate_rsp_ready,.xlate_rsp_paddr,.xlate_rsp_fault,.mem_req_valid,.mem_req_ready,.mem_req_write,.mem_req_addr,.mem_req_wdata,.mem_req_wstrb,.mem_req_qos,.mem_rsp_valid,.mem_rsp_ready,.mem_rsp_rdata,.mem_rsp_error,.accel_cmd_valid,.accel_cmd_ready,.accel_cmd_bank,.accel_cmd_k,.accel_cmd_tag,.accel_in_valid,.accel_in_ready,.accel_in_data,.accel_in_tag,.accel_out_valid,.accel_out_ready,.accel_out_data,.accel_out_tag,.completion_valid,.completion_ready,.completion_tag,.completion_status,.completion_asid,.completion_fault_iova,.completion_fault_stage,.completion_vectors_done,.completion_published,.completion_publish_tag,.completion_publish_asid,.completion_publish_status,.completion_publish_fault_stage,.completion_publish_vectors_done,.irq,.busy,.submit_occupancy,.completion_occupancy,.bank_referenced,.owned_valid,.owned_start,.owned_end,.owned_input_start,.owned_input_end,.owned_output_start,.owned_output_end);
  dma_iommu #(.TLB_ENTRIES(4)) iommu(
    .clk,.rst_n,.root_pt_addr(32'h30000000),.req_valid(xlate_req_valid),.req_ready(xlate_req_ready),
    .req_iova(xlate_req_iova),.req_asid(xlate_req_asid),.req_write(xlate_req_write),.req_user(1'b0),
    .rsp_valid(xlate_rsp_valid),.rsp_ready(xlate_rsp_ready),.rsp_paddr(xlate_rsp_paddr),
    .rsp_fault(xlate_rsp_fault),.rsp_tlb_hit(tlb_hit),.inv_valid(1'b0),.inv_all(1'b0),.inv_asid('0),
    .ptw_req_valid,.ptw_req_ready,.ptw_req_addr,.ptw_rsp_valid,.ptw_rsp_ready,.ptw_rsp_data,.ptw_rsp_error,
    .perf_tlb_hits,.perf_tlb_misses,.perf_walk_reads,.perf_faults,.idle(iommu_idle));
  int8_tensor_accel accelerator(.clk,.rst_n,.cfg_valid,.cfg_ready,.cfg_kind,.cfg_bank,.cfg_output,.cfg_index,.cfg_data,.cmd_valid(accel_cmd_valid),.cmd_ready(accel_cmd_ready),.cmd_bank(accel_cmd_bank),.cmd_k(accel_cmd_k),.cmd_tag(accel_cmd_tag),.cmd_error,.in_valid(accel_in_valid),.in_ready(accel_in_ready),.in_data(accel_in_data),.in_tag(accel_in_tag),.out_valid(accel_out_valid),.out_ready(accel_out_ready),.out_data(accel_out_data),.out_tag(accel_out_tag),.perf_accepted,.perf_completed,.perf_input_chunks,.perf_output_stalls,.perf_bank_swaps);

  always_comb begin
    cfg_valid=rst_n&&!config_done;cfg_bank=0;cfg_output=cfg_out;cfg_index=cfg_weight;cfg_kind={1'b0,cfg_phase};
    case(cfg_phase) 0:cfg_data=1;1:cfg_data=0;2:cfg_data=1;default:cfg_data=0;endcase
  end
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin config_done<=0;cfg_phase<=0;cfg_out<=0;cfg_weight<=0;cycles<=0;firmware_done<=0;firmware_result<=0;ptw_rsp_valid<=0;ptw_rsp_data<=0;ptw_rsp_error<=0;mem_pending<=0;mem_rsp_valid<=0;end
    else begin
      cycles<=cycles+1;ptw_rsp_valid<=0;ptw_rsp_error<=0;mem_rsp_valid<=0;
      if(!config_done&&cfg_valid&&cfg_ready)begin
        if(cfg_phase==0&&cfg_weight!=63)cfg_weight<=cfg_weight+1'b1;
        else begin cfg_weight<=0;if(cfg_phase!=3)cfg_phase<=cfg_phase+1'b1;else if(cfg_out!=3)begin cfg_phase<=0;cfg_out<=cfg_out+1'b1;end else config_done<=1;end
      end
      if(mail_sel&&penable&&pwrite)begin if(paddr[3:0]==0)firmware_result<=pwdata;else if(paddr[3:0]==4)firmware_done<=pwdata[0];end
      if(ptw_req_valid&&ptw_req_ready)begin
        ptw_rsp_valid<=1;
        case(ptw_req_addr)
          32'h30000800:ptw_rsp_data<=32'h0c000401;
          32'h30001004:ptw_rsp_data<=32'h040004cf;
          32'h30001010:ptw_rsp_data<=32'h040010cf;
          default:begin ptw_rsp_data<=0;ptw_rsp_error<=1;end
        endcase
      end
      if(mem_req_valid&&mem_req_ready)begin mem_pending<=1;pending_addr<=mem_req_addr;pending_wdata<=mem_req_wdata;pending_wstrb<=mem_req_wstrb;pending_mem_write<=mem_req_write;end
      if(mem_pending)begin mem_pending<=0;mem_rsp_valid<=1;mem_rsp_error<=0;mem_rsp_rdata<=memory[mem_index(pending_addr)];if(pending_mem_write)for(int b=0;b<4;b++)if(pending_wstrb[b])memory[mem_index(pending_addr)][8*b+:8]<=pending_wdata[8*b+:8];end
    end
  end
endmodule
