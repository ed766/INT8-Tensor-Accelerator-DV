`timescale 1ns/1ps

// CPU-independent protected accelerator service. The host owns configuration,
// page tables, and payload memory through the explicit interfaces below.
module protected_offload_service #(
  parameter int QUEUE_DEPTH = 4,
  parameter int COMPLETION_DEPTH = 4,
  parameter int TLB_ENTRIES = 4
) (
  input  logic clk,
  input  logic rst_n,

  input  logic [11:0] apb_addr,
  input  logic apb_sel,
  input  logic apb_enable,
  input  logic apb_write,
  input  logic [31:0] apb_wdata,
  output logic [31:0] apb_rdata,
  output logic apb_ready,
  output logic apb_error,

  input  logic [31:0] root_pt_addr,
  input  logic tlb_inv_valid,
  input  logic tlb_inv_all,
  input  logic [7:0] tlb_inv_asid,
  output logic ptw_req_valid,
  input  logic ptw_req_ready,
  output logic [31:0] ptw_req_addr,
  input  logic ptw_rsp_valid,
  output logic ptw_rsp_ready,
  input  logic [31:0] ptw_rsp_data,
  input  logic ptw_rsp_error,

  output logic mem_req_valid,
  input  logic mem_req_ready,
  output logic mem_req_write,
  output logic [31:0] mem_req_addr,
  output logic [31:0] mem_req_wdata,
  output logic [3:0] mem_req_wstrb,
  output logic [3:0] mem_req_qos,
  input  logic mem_rsp_valid,
  output logic mem_rsp_ready,
  input  logic [31:0] mem_rsp_rdata,
  input  logic mem_rsp_error,

  input  logic cfg_valid,
  output logic cfg_ready,
  input  logic [2:0] cfg_kind,
  input  logic cfg_bank,
  input  logic [1:0] cfg_output,
  input  logic [5:0] cfg_index,
  input  logic [31:0] cfg_data,
  input  logic [1:0][7:0] bank_generation,

  output logic irq,
  output logic busy,
  output logic [2:0] submit_occupancy,
  output logic [2:0] completion_occupancy,
  output logic [31:0] perf_tlb_hits,
  output logic [31:0] perf_tlb_misses,
  output logic [31:0] perf_walk_reads,
  output logic [31:0] perf_faults,
  output logic last_translation_tlb_hit,
  output logic accel_command_error,
  output logic [31:0] perf_accel_accepted,
  output logic [31:0] perf_accel_completed,
  output logic [31:0] perf_accel_input_chunks,
  output logic [31:0] perf_accel_output_stalls,
  output logic [31:0] perf_accel_bank_swaps
);
  logic submit_valid, submit_ready, submit_accepted, submit_rejected;
  logic [31:0] submit_input_iova, submit_output_iova;
  logic [15:0] submit_input_stride, submit_output_stride;
  logic [6:0] submit_k, submit_batch;
  logic [7:0] submit_tag, submit_asid, submit_bank_generation;
  logic submit_bank;
  logic [3:0] submit_qos;
  logic completion_valid, completion_ready;
  logic [7:0] completion_tag, completion_asid;
  logic [3:0] completion_status;
  logic [31:0] completion_fault_iova;
  logic [2:0] completion_fault_stage;
  logic [6:0] completion_vectors_done;
  logic xlate_req_valid, xlate_req_ready, xlate_req_write;
  logic [31:0] xlate_req_iova, xlate_rsp_paddr;
  logic [7:0] xlate_req_asid;
  logic xlate_rsp_valid, xlate_rsp_ready;
  logic [1:0] xlate_rsp_fault;
  logic tlb_hit;
  logic accel_cmd_valid, accel_cmd_ready, accel_cmd_bank, cmd_error;
  logic [6:0] accel_cmd_k;
  logic [7:0] accel_cmd_tag;
  logic accel_in_valid, accel_in_ready, accel_out_valid, accel_out_ready;
  logic [31:0] accel_in_data, accel_out_data;
  logic [7:0] accel_in_tag, accel_out_tag;
  logic [31:0] perf_accepted, perf_completed, perf_input_chunks;
  logic [31:0] perf_output_stalls, perf_bank_swaps;

  assign last_translation_tlb_hit = tlb_hit;
  assign accel_command_error = cmd_error;
  assign perf_accel_accepted = perf_accepted;
  assign perf_accel_completed = perf_completed;
  assign perf_accel_input_chunks = perf_input_chunks;
  assign perf_accel_output_stalls = perf_output_stalls;
  assign perf_accel_bank_swaps = perf_bank_swaps;

  protected_offload_apb_csr csr (
    .clk, .rst_n, .paddr(apb_addr), .psel(apb_sel), .penable(apb_enable),
    .pwrite(apb_write), .pwdata(apb_wdata), .prdata(apb_rdata),
    .pready(apb_ready), .pslverr(apb_error), .submit_valid, .submit_ready,
    .submit_input_iova, .submit_output_iova, .submit_input_stride,
    .submit_output_stride, .submit_k, .submit_batch, .submit_tag,
    .submit_asid, .submit_bank, .submit_bank_generation, .submit_qos,
    .submit_accepted, .submit_rejected, .busy, .submit_occupancy,
    .completion_valid, .completion_ready, .completion_tag,
    .completion_status, .completion_asid, .completion_fault_iova,
    .completion_fault_stage, .completion_vectors_done,
    .completion_occupancy, .irq
  );

  protected_offload_dma #(
    .QUEUE_DEPTH(QUEUE_DEPTH), .COMPLETION_DEPTH(COMPLETION_DEPTH)
  ) dma (
    .clk, .rst_n, .submit_valid, .submit_ready, .submit_input_iova,
    .submit_output_iova, .submit_input_stride, .submit_output_stride,
    .submit_k, .submit_batch, .submit_tag, .submit_asid, .submit_bank,
    .submit_bank_generation, .submit_qos, .bank_generation,
    .submit_accepted, .submit_rejected, .xlate_req_valid,
    .xlate_req_ready, .xlate_req_iova, .xlate_req_asid,
    .xlate_req_write, .xlate_rsp_valid, .xlate_rsp_ready,
    .xlate_rsp_paddr, .xlate_rsp_fault, .mem_req_valid, .mem_req_ready,
    .mem_req_write, .mem_req_addr, .mem_req_wdata, .mem_req_wstrb,
    .mem_req_qos, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata,
    .mem_rsp_error, .accel_cmd_valid, .accel_cmd_ready, .accel_cmd_bank,
    .accel_cmd_k, .accel_cmd_tag, .accel_in_valid, .accel_in_ready,
    .accel_in_data, .accel_in_tag, .accel_out_valid, .accel_out_ready,
    .accel_out_data, .accel_out_tag, .completion_valid,
    .completion_ready, .completion_tag, .completion_status,
    .completion_asid, .completion_fault_iova, .completion_fault_stage,
    .completion_vectors_done, .irq, .busy, .submit_occupancy,
    .completion_occupancy
  );

  dma_iommu #(.TLB_ENTRIES(TLB_ENTRIES)) iommu (
    .clk, .rst_n, .root_pt_addr, .req_valid(xlate_req_valid),
    .req_ready(xlate_req_ready), .req_iova(xlate_req_iova),
    .req_asid(xlate_req_asid), .req_write(xlate_req_write),
    .req_user(1'b0), .rsp_valid(xlate_rsp_valid),
    .rsp_ready(xlate_rsp_ready), .rsp_paddr(xlate_rsp_paddr),
    .rsp_fault(xlate_rsp_fault), .rsp_tlb_hit(tlb_hit),
    .inv_valid(tlb_inv_valid), .inv_all(tlb_inv_all),
    .inv_asid(tlb_inv_asid), .ptw_req_valid, .ptw_req_ready,
    .ptw_req_addr, .ptw_rsp_valid, .ptw_rsp_ready, .ptw_rsp_data,
    .ptw_rsp_error, .perf_tlb_hits, .perf_tlb_misses,
    .perf_walk_reads, .perf_faults
  );

  int8_tensor_accel accelerator (
    .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_kind, .cfg_bank,
    .cfg_output, .cfg_index, .cfg_data, .cmd_valid(accel_cmd_valid),
    .cmd_ready(accel_cmd_ready), .cmd_bank(accel_cmd_bank),
    .cmd_k(accel_cmd_k), .cmd_tag(accel_cmd_tag), .cmd_error,
    .in_valid(accel_in_valid), .in_ready(accel_in_ready),
    .in_data(accel_in_data), .in_tag(accel_in_tag),
    .out_valid(accel_out_valid), .out_ready(accel_out_ready),
    .out_data(accel_out_data), .out_tag(accel_out_tag),
    .perf_accepted, .perf_completed, .perf_input_chunks,
    .perf_output_stalls, .perf_bank_swaps
  );

`ifndef SYNTHESIS
  a_no_payload_before_translation: assert property (@(posedge clk) disable iff (!rst_n)
    mem_req_valid |-> !$isunknown(mem_req_addr));
  a_invalidation_not_during_walk: assert property (@(posedge clk) disable iff (!rst_n)
    tlb_inv_valid |-> !ptw_req_valid);
`endif
endmodule
