`timescale 1ns/1ps

module dma_iommu #(
  parameter int TLB_ENTRIES = 8,
  parameter int ASID_W = 8
) (
  input  logic clk,
  input  logic rst_n,
  input  logic [31:0] root_pt_addr,
  input  logic req_valid,
  output logic req_ready,
  input  logic [31:0] req_iova,
  input  logic [ASID_W-1:0] req_asid,
  input  logic req_write,
  input  logic req_user,
  output logic rsp_valid,
  input  logic rsp_ready,
  output logic [31:0] rsp_paddr,
  output logic [1:0] rsp_fault,
  output logic rsp_tlb_hit,
  input  logic inv_valid,
  input  logic inv_all,
  input  logic [ASID_W-1:0] inv_asid,
  output logic ptw_req_valid,
  input  logic ptw_req_ready,
  output logic [31:0] ptw_req_addr,
  input  logic ptw_rsp_valid,
  output logic ptw_rsp_ready,
  input  logic [31:0] ptw_rsp_data,
  input  logic ptw_rsp_error,
  output logic [31:0] perf_tlb_hits,
  output logic [31:0] perf_tlb_misses,
  output logic [31:0] perf_walk_reads,
  output logic [31:0] perf_faults
);
  localparam logic [1:0] FAULT_NONE=2'd0,FAULT_INVALID=2'd1,FAULT_PERMISSION=2'd2,FAULT_ACCESS=2'd3;
  localparam int INDEX_W=$clog2(TLB_ENTRIES);
  typedef enum logic [2:0] {IDLE,L1_REQ,L1_WAIT,L2_REQ,L2_WAIT,RESPOND} state_t;
  state_t state;
  logic [31:0] request_iova;
  logic [ASID_W-1:0] request_asid;
  logic request_write,request_user;
  logic [21:0] l2_ppn;
  logic [INDEX_W-1:0] replace_ptr;
  logic [31:0] response_paddr;
  logic [1:0] response_fault;
  logic response_hit;
  logic [31:0] accepted_count,response_count;

  logic [TLB_ENTRIES-1:0] tlb_valid,tlb_superpage,tlb_read,tlb_write,tlb_user,tlb_accessed,tlb_dirty;
  logic [TLB_ENTRIES-1:0][ASID_W-1:0] tlb_asid;
  logic [TLB_ENTRIES-1:0][9:0] tlb_vpn1,tlb_vpn0;
  logic [TLB_ENTRIES-1:0][21:0] tlb_ppn;
  logic tlb_match,tlb_permission;
  logic [INDEX_W-1:0] tlb_match_index;

  function automatic logic pte_leaf(input logic [31:0] pte);
    pte_leaf=|pte[3:1];
  endfunction
  function automatic logic pte_valid(input logic [31:0] pte);
    pte_valid=pte[0] && !(pte[2] && !pte[1]);
  endfunction
  function automatic logic permission_ok(input logic [31:0] pte,input logic write_access,input logic user_access);
    permission_ok=pte_valid(pte) && pte_leaf(pte) && pte[6] && (!write_access || (pte[2] && pte[7]))
      && (write_access || pte[1]) && (!user_access || pte[4]);
  endfunction

  always_comb begin
    tlb_match=1'b0;tlb_match_index='0;
    for(int index=0;index<TLB_ENTRIES;index++) begin
      if(tlb_valid[index] && tlb_asid[index]==req_asid && tlb_vpn1[index]==req_iova[31:22]
          && (tlb_superpage[index] || tlb_vpn0[index]==req_iova[21:12])) begin
        tlb_match=1'b1;tlb_match_index=INDEX_W'(index);
      end
    end
    tlb_permission=tlb_read[tlb_match_index] && tlb_accessed[tlb_match_index]
      && (!req_write || (tlb_write[tlb_match_index] && tlb_dirty[tlb_match_index]))
      && (!req_user || tlb_user[tlb_match_index]);
  end

  assign req_ready=state==IDLE && !inv_valid;
  assign rsp_valid=state==RESPOND;
  assign rsp_paddr=response_paddr;
  assign rsp_fault=response_fault;
  assign rsp_tlb_hit=response_hit;
  assign ptw_req_valid=state==L1_REQ || state==L2_REQ;
  assign ptw_req_addr=state==L1_REQ ? 32'(root_pt_addr+{20'd0,request_iova[31:22],2'b00})
    : 32'({l2_ppn[19:0],12'b0}+{20'd0,request_iova[21:12],2'b00});
  assign ptw_rsp_ready=state==L1_WAIT || state==L2_WAIT;

  task automatic finish_fault(input logic [1:0] fault);
    begin response_paddr<=0;response_fault<=fault;response_hit<=0;perf_faults<=perf_faults+1;state<=RESPOND;end
  endtask
  task automatic install_translation(input logic [31:0] pte,input logic superpage);
    begin
      tlb_valid[replace_ptr]<=1;tlb_superpage[replace_ptr]<=superpage;tlb_asid[replace_ptr]<=request_asid;
      tlb_vpn1[replace_ptr]<=request_iova[31:22];tlb_vpn0[replace_ptr]<=request_iova[21:12];tlb_ppn[replace_ptr]<=pte[31:10];
      tlb_read[replace_ptr]<=pte[1];tlb_write[replace_ptr]<=pte[2];tlb_user[replace_ptr]<=pte[4];
      tlb_accessed[replace_ptr]<=pte[6];tlb_dirty[replace_ptr]<=pte[7];replace_ptr<=replace_ptr+1'b1;
    end
  endtask

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=IDLE;request_iova<=0;request_asid<=0;request_write<=0;request_user<=0;l2_ppn<=0;replace_ptr<=0;
      response_paddr<=0;response_fault<=0;response_hit<=0;tlb_valid<=0;tlb_superpage<=0;tlb_read<=0;tlb_write<=0;
      tlb_user<=0;tlb_accessed<=0;tlb_dirty<=0;tlb_asid<=0;tlb_vpn1<=0;tlb_vpn0<=0;tlb_ppn<=0;
      perf_tlb_hits<=0;perf_tlb_misses<=0;perf_walk_reads<=0;perf_faults<=0;accepted_count<=0;response_count<=0;
    end else begin
      if(inv_valid) begin
        for(int index=0;index<TLB_ENTRIES;index++)
          if(inv_all || tlb_asid[index]==inv_asid) tlb_valid[index]<=0;
      end
      case(state)
        IDLE: if(req_valid && req_ready) begin
          accepted_count<=accepted_count+1;
          if(tlb_match) begin
            response_hit<=1;
            if(!tlb_permission) begin response_paddr<=0;response_fault<=FAULT_PERMISSION;perf_faults<=perf_faults+1;end
            else begin
              response_paddr<=tlb_superpage[tlb_match_index] ? {tlb_ppn[tlb_match_index][19:10],req_iova[21:0]}
                : {tlb_ppn[tlb_match_index][19:0],req_iova[11:0]};
              response_fault<=FAULT_NONE;
            end
            perf_tlb_hits<=perf_tlb_hits+1;state<=RESPOND;
          end else begin
            request_iova<=req_iova;request_asid<=req_asid;request_write<=req_write;request_user<=req_user;
            perf_tlb_misses<=perf_tlb_misses+1;response_hit<=0;state<=L1_REQ;
          end
        end
        L1_REQ: if(ptw_req_ready) begin perf_walk_reads<=perf_walk_reads+1;state<=L1_WAIT;end
        L1_WAIT: if(ptw_rsp_valid) begin
          if(ptw_rsp_error) finish_fault(FAULT_ACCESS);
          else if(!pte_valid(ptw_rsp_data)) finish_fault(FAULT_INVALID);
          else if(pte_leaf(ptw_rsp_data)) begin
            if(!permission_ok(ptw_rsp_data,request_write,request_user)) finish_fault(FAULT_PERMISSION);
            else begin
              install_translation(ptw_rsp_data,1);response_paddr<={ptw_rsp_data[29:20],request_iova[21:0]};
              response_fault<=FAULT_NONE;response_hit<=0;state<=RESPOND;
            end
          end else begin l2_ppn<=ptw_rsp_data[31:10];state<=L2_REQ;end
        end
        L2_REQ: if(ptw_req_ready) begin perf_walk_reads<=perf_walk_reads+1;state<=L2_WAIT;end
        L2_WAIT: if(ptw_rsp_valid) begin
          if(ptw_rsp_error) finish_fault(FAULT_ACCESS);
          else if(!pte_valid(ptw_rsp_data) || !pte_leaf(ptw_rsp_data)) finish_fault(FAULT_INVALID);
          else if(!permission_ok(ptw_rsp_data,request_write,request_user)) finish_fault(FAULT_PERMISSION);
          else begin
            install_translation(ptw_rsp_data,0);response_paddr<={ptw_rsp_data[29:10],request_iova[11:0]};
            response_fault<=FAULT_NONE;response_hit<=0;state<=RESPOND;
          end
        end
        RESPOND: if(rsp_ready) begin response_count<=response_count+1;state<=IDLE;end
        default: state<=IDLE;
      endcase
    end
  end

`ifndef SYNTHESIS
  a_ptw_address_stable: assert property (@(posedge clk) disable iff(!rst_n) ptw_req_valid&&!ptw_req_ready |=> !ptw_req_valid||$stable(ptw_req_addr));
  a_response_stable: assert property (@(posedge clk) disable iff(!rst_n) rsp_valid&&!rsp_ready |=> !rsp_valid||$stable({rsp_paddr,rsp_fault,rsp_tlb_hit}));
  a_fault_has_no_paddr: assert property (@(posedge clk) disable iff(!rst_n) rsp_valid&&(rsp_fault!=FAULT_NONE) |-> rsp_paddr==0);
  a_response_not_ahead: assert property (@(posedge clk) disable iff(!rst_n) response_count<=accepted_count);
  a_invalidate_blocks_accept: assert property (@(posedge clk) disable iff(!rst_n) inv_valid |-> !req_ready);
  a_walk_only_for_miss: assert property (@(posedge clk) disable iff(!rst_n) ptw_req_valid |-> !response_hit);
`endif
endmodule
