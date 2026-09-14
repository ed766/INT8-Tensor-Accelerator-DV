`timescale 1ns/1ps

module protected_offload_dma #(
  parameter int QUEUE_DEPTH = 4,
  parameter int COMPLETION_DEPTH = 4,
  parameter int TAG_W = 8,
  parameter int ASID_W = 8,
  parameter int MAX_K = 64
) (
  input  logic clk,
  input  logic rst_n,

  input  logic submit_valid,
  output logic submit_ready,
  input  logic [31:0] submit_input_iova,
  input  logic [31:0] submit_output_iova,
  input  logic [15:0] submit_input_stride,
  input  logic [15:0] submit_output_stride,
  input  logic [6:0] submit_k,
  input  logic [6:0] submit_batch,
  input  logic [TAG_W-1:0] submit_tag,
  input  logic [ASID_W-1:0] submit_asid,
  input  logic submit_bank,
  input  logic [7:0] submit_bank_generation,
  input  logic [3:0] submit_qos,
  input  logic [1:0][7:0] bank_generation,
  output logic submit_accepted,
  output logic submit_rejected,

  output logic xlate_req_valid,
  input  logic xlate_req_ready,
  output logic [31:0] xlate_req_iova,
  output logic [ASID_W-1:0] xlate_req_asid,
  output logic xlate_req_write,
  input  logic xlate_rsp_valid,
  output logic xlate_rsp_ready,
  input  logic [31:0] xlate_rsp_paddr,
  input  logic [1:0] xlate_rsp_fault,

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

  output logic accel_cmd_valid,
  input  logic accel_cmd_ready,
  output logic accel_cmd_bank,
  output logic [6:0] accel_cmd_k,
  output logic [TAG_W-1:0] accel_cmd_tag,
  output logic accel_in_valid,
  input  logic accel_in_ready,
  output logic [31:0] accel_in_data,
  output logic [TAG_W-1:0] accel_in_tag,
  input  logic accel_out_valid,
  output logic accel_out_ready,
  input  logic [31:0] accel_out_data,
  input  logic [TAG_W-1:0] accel_out_tag,

  output logic completion_valid,
  input  logic completion_ready,
  output logic [TAG_W-1:0] completion_tag,
  output logic [3:0] completion_status,
  output logic [ASID_W-1:0] completion_asid,
  output logic [31:0] completion_fault_iova,
  output logic [2:0] completion_fault_stage,
  output logic [6:0] completion_vectors_done,
  output logic irq,
  output logic busy,
  output logic [2:0] submit_occupancy,
  output logic [2:0] completion_occupancy
);
  localparam int QW = $clog2(QUEUE_DEPTH);
  localparam int CW = $clog2(COMPLETION_DEPTH);
  localparam int CHUNKS = MAX_K / 4;

  localparam logic [3:0] ST_OK = 4'd0;
  localparam logic [3:0] ST_XLATE_READ = 4'd2;
  localparam logic [3:0] ST_XLATE_WRITE = 4'd3;
  localparam logic [3:0] ST_MEM_READ = 4'd4;
  localparam logic [3:0] ST_MEM_WRITE = 4'd5;
  localparam logic [3:0] ST_ACCEL = 4'd6;

  localparam logic [2:0] FS_NONE = 3'd0;
  localparam logic [2:0] FS_INPUT_XLATE = 3'd1;
  localparam logic [2:0] FS_INPUT_READ = 3'd2;
  localparam logic [2:0] FS_OUTPUT_XLATE = 3'd3;
  localparam logic [2:0] FS_OUTPUT_WRITE = 3'd4;
  localparam logic [2:0] FS_ACCEL = 3'd5;

  typedef struct packed {
    logic [31:0] input_iova;
    logic [31:0] output_iova;
    logic [15:0] input_stride;
    logic [15:0] output_stride;
    logic [6:0] k;
    logic [6:0] batch;
    logic [TAG_W-1:0] tag;
    logic [ASID_W-1:0] asid;
    logic bank;
    logic [7:0] bank_gen;
    logic [3:0] qos;
  } descriptor_t;

  typedef struct packed {
    logic [TAG_W-1:0] tag;
    logic [3:0] status;
    logic [ASID_W-1:0] asid;
    logic [31:0] fault_iova;
    logic [2:0] fault_stage;
    logic [6:0] vectors_done;
  } completion_t;

  typedef enum logic [4:0] {
    IDLE, INPUT_XLATE_REQ, INPUT_XLATE_WAIT, INPUT_MEM_REQ, INPUT_MEM_WAIT,
    ACCEL_CMD, ACCEL_STREAM, ACCEL_WAIT, OUTPUT_XLATE_REQ, OUTPUT_XLATE_WAIT,
    OUTPUT_MEM_REQ, OUTPUT_MEM_WAIT, NEXT_VECTOR, RETIRE
  } state_t;

  descriptor_t submit_fifo [QUEUE_DEPTH];
  completion_t completion_fifo [COMPLETION_DEPTH];
  logic [31:0] input_buffer [CHUNKS];
  descriptor_t active;
  state_t state;
  logic [QW-1:0] submit_head, submit_tail;
  logic [CW-1:0] completion_head, completion_tail;
  logic [QW:0] submit_count;
  logic [CW:0] completion_count;
  logic [$clog2(CHUNKS)-1:0] chunk_index;
  logic [6:0] vector_index;
  logic [31:0] translated_addr;
  logic [31:0] result_word;
  logic [3:0] retire_status;
  logic [31:0] retire_fault_iova;
  logic [2:0] retire_fault_stage;
  logic [6:0] retire_vectors_done;
  logic submit_legal, duplicate_tag;
  logic submit_push, submit_pop, completion_push, completion_pop;
  logic [QW:0] submit_count_next;
  logic [CW:0] completion_count_next;
  logic [31:0] current_input_iova, current_output_iova;
  logic [63:0] input_end_calc, output_end_calc;
  logic address_overflow, buffers_overlap;

  function automatic logic legal_k(input logic [6:0] value);
    return value == 7'd4 || value == 7'd8 || value == 7'd16 ||
           value == 7'd32 || value == 7'd64;
  endfunction

  always_comb begin
    input_end_calc = {32'd0,submit_input_iova} +
      ({57'd0,submit_batch} - 1'b1) * submit_input_stride + {57'd0,submit_k} - 1'b1;
    output_end_calc = {32'd0,submit_output_iova} +
      ({57'd0,submit_batch} - 1'b1) * submit_output_stride + 64'd3;
    address_overflow = submit_batch == 0 || input_end_calc[63:32] != 0 || output_end_calc[63:32] != 0;
    buffers_overlap = !address_overflow &&
      !((input_end_calc[31:0] < submit_output_iova) || (output_end_calc[31:0] < submit_input_iova));
    duplicate_tag = busy && active.tag == submit_tag;
    for (int i = 0; i < QUEUE_DEPTH; i++) begin
      if (i < int'(submit_count) && submit_fifo[QW'(submit_head + QW'(i))].tag == submit_tag)
        duplicate_tag = 1'b1;
    end
    submit_legal = legal_k(submit_k) && submit_batch != 0 &&
                   submit_input_iova[1:0] == 0 && submit_output_iova[1:0] == 0 &&
                   submit_input_stride >= 16'(submit_k) && submit_output_stride >= 16'd4 &&
                   !address_overflow && !buffers_overlap &&
`ifdef PROTECTED_MUT_STALE_BANK_GENERATION
                   !duplicate_tag;
`else
                   submit_bank_generation == bank_generation[submit_bank] && !duplicate_tag;
`endif
  end

  assign submit_ready = submit_count < (QW+1)'(QUEUE_DEPTH);
  assign submit_push = submit_valid && submit_ready && submit_legal;
  assign submit_pop = state == IDLE && submit_count != 0;
  assign completion_push = state == RETIRE && completion_count < (CW+1)'(COMPLETION_DEPTH);
  assign completion_pop = completion_valid && completion_ready;
  protected_queue_count_next #(.WIDTH(QW+1)) submit_counter (
    .count(submit_count),.push(submit_push),.pop(submit_pop),.next_count(submit_count_next));
  protected_queue_count_next #(.WIDTH(CW+1)) completion_counter (
    .count(completion_count),.push(completion_push),.pop(completion_pop),.next_count(completion_count_next));
  assign submit_occupancy = 3'(submit_count);
  assign completion_occupancy = 3'(completion_count);
  assign completion_valid = completion_count != 0;
`ifdef PROTECTED_MUT_WRONG_RESPONSE_TAG
  assign completion_tag = completion_fifo[completion_head].tag ^ 8'h1;
`else
  assign completion_tag = completion_fifo[completion_head].tag;
`endif
  assign completion_status = completion_fifo[completion_head].status;
  assign completion_asid = completion_fifo[completion_head].asid;
  assign completion_fault_iova = completion_fifo[completion_head].fault_iova;
  assign completion_fault_stage = completion_fifo[completion_head].fault_stage;
`ifdef PROTECTED_MUT_WRONG_VECTOR_COUNT
  assign completion_vectors_done = completion_fifo[completion_head].vectors_done + 1'b1;
`else
  assign completion_vectors_done = completion_fifo[completion_head].vectors_done;
`endif
`ifdef PROTECTED_MUT_LOST_IRQ
  assign irq = 1'b0;
`else
  assign irq = completion_valid;
`endif
  assign busy = state != IDLE;
  assign current_input_iova = active.input_iova + vector_index * active.input_stride + chunk_index * 4;
  assign current_output_iova = active.output_iova + vector_index * active.output_stride;

  always_comb begin
    xlate_req_valid = state == INPUT_XLATE_REQ || state == OUTPUT_XLATE_REQ;
`ifdef PROTECTED_MUT_STALE_TRANSLATION
    xlate_req_iova = current_input_iova;
`else
    xlate_req_iova = state == OUTPUT_XLATE_REQ ? current_output_iova : current_input_iova;
`endif
`ifdef PROTECTED_MUT_WRONG_ASID
    xlate_req_asid = active.asid ^ 8'h1;
`else
    xlate_req_asid = active.asid;
`endif
    xlate_req_write = state == OUTPUT_XLATE_REQ;
    xlate_rsp_ready = state == INPUT_XLATE_WAIT || state == OUTPUT_XLATE_WAIT;
    mem_req_valid = state == INPUT_MEM_REQ || state == OUTPUT_MEM_REQ;
    mem_req_write = state == OUTPUT_MEM_REQ;
    mem_req_addr = translated_addr;
`ifdef PROTECTED_MUT_CORRUPT_RESULT
    mem_req_wdata = result_word ^ 32'h1;
`else
    mem_req_wdata = result_word;
`endif
`ifdef PROTECTED_MUT_WRONG_BYTE_LANE
    mem_req_wstrb = state == OUTPUT_MEM_REQ ? 4'he : 4'h0;
`else
    mem_req_wstrb = state == OUTPUT_MEM_REQ ? 4'hf : 4'h0;
`endif
    mem_req_qos = active.qos;
    mem_rsp_ready = state == INPUT_MEM_WAIT || state == OUTPUT_MEM_WAIT;
    accel_cmd_valid = state == ACCEL_CMD;
    accel_cmd_bank = active.bank;
    accel_cmd_k = active.k;
    accel_cmd_tag = active.tag;
`ifdef PROTECTED_MUT_DROP_CHUNK
    accel_in_valid = state == ACCEL_STREAM && chunk_index != 1;
`else
    accel_in_valid = state == ACCEL_STREAM;
`endif
    accel_in_data = input_buffer[chunk_index];
    accel_in_tag = active.tag;
    accel_out_ready = state == ACCEL_WAIT;
  end

  task automatic prepare_retire(
    input logic [3:0] status,
    input logic [31:0] fault_iova,
    input logic [2:0] fault_stage,
    input logic [6:0] vectors_done
  );
    begin
      retire_status <= status;
      retire_fault_iova <= fault_iova;
      retire_fault_stage <= fault_stage;
      retire_vectors_done <= vectors_done;
      state <= RETIRE;
    end
  endtask

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      submit_head <= '0;
      submit_tail <= '0;
      submit_count <= '0;
      completion_head <= '0;
      completion_tail <= '0;
      completion_count <= '0;
      submit_accepted <= 1'b0;
      submit_rejected <= 1'b0;
      active <= '0;
      chunk_index <= '0;
      vector_index <= '0;
      translated_addr <= '0;
      result_word <= '0;
      retire_status <= ST_OK;
      retire_fault_iova <= '0;
      retire_fault_stage <= FS_NONE;
      retire_vectors_done <= '0;
    end else begin
      submit_accepted <= 1'b0;
      submit_rejected <= 1'b0;

      if (completion_valid && completion_ready) begin
        completion_head <= completion_head + 1'b1;
      end

      if (submit_valid && submit_ready) begin
        if (submit_legal) begin
          submit_fifo[submit_tail] <= '{
            input_iova: submit_input_iova, output_iova: submit_output_iova,
            input_stride: submit_input_stride, output_stride: submit_output_stride,
            k: submit_k, batch: submit_batch, tag: submit_tag, asid: submit_asid,
            bank: submit_bank, bank_gen: submit_bank_generation, qos: submit_qos};
          submit_tail <= submit_tail + 1'b1;
          submit_accepted <= 1'b1;
        end else begin
          submit_rejected <= 1'b1;
        end
      end

      case (state)
        IDLE: if (submit_count != 0) begin
          active <= submit_fifo[submit_head];
          submit_head <= submit_head + 1'b1;
          chunk_index <= '0;
          vector_index <= '0;
          retire_status <= ST_OK;
          retire_fault_iova <= '0;
          retire_fault_stage <= FS_NONE;
          retire_vectors_done <= '0;
          state <= INPUT_XLATE_REQ;
        end
        INPUT_XLATE_REQ: if (xlate_req_valid && xlate_req_ready) state <= INPUT_XLATE_WAIT;
        INPUT_XLATE_WAIT: if (xlate_rsp_valid) begin
`ifdef PROTECTED_MUT_PERMISSION_BYPASS
          if (1'b0)
`else
          if (xlate_rsp_fault != 0)
`endif
            prepare_retire(ST_XLATE_READ, current_input_iova, FS_INPUT_XLATE, vector_index);
          else begin translated_addr <= xlate_rsp_paddr; state <= INPUT_MEM_REQ; end
        end
        INPUT_MEM_REQ: if (mem_req_valid && mem_req_ready) state <= INPUT_MEM_WAIT;
        INPUT_MEM_WAIT: if (mem_rsp_valid) begin
          if (mem_rsp_error)
            prepare_retire(ST_MEM_READ, current_input_iova, FS_INPUT_READ, vector_index);
          else begin
            input_buffer[chunk_index] <= mem_rsp_rdata;
            if (7'(chunk_index) + 7'd1 == active.k / 4) begin chunk_index <= '0; state <= ACCEL_CMD; end
            else begin chunk_index <= chunk_index + 1'b1; state <= INPUT_XLATE_REQ; end
          end
        end
        ACCEL_CMD: if (accel_cmd_valid && accel_cmd_ready) begin
          chunk_index <= '0;
          state <= ACCEL_STREAM;
        end
        ACCEL_STREAM: if (accel_in_valid && accel_in_ready) begin
          if (7'(chunk_index) + 7'd1 == active.k / 4) begin
            chunk_index <= '0;
            state <= ACCEL_WAIT;
          end else begin
            chunk_index <= chunk_index + 1'b1;
          end
        end
        ACCEL_WAIT: if (accel_out_valid) begin
          if (accel_out_tag != active.tag) begin
            prepare_retire(ST_ACCEL, current_output_iova, FS_ACCEL, vector_index);
          end else begin
            result_word <= accel_out_data;
            state <= OUTPUT_XLATE_REQ;
          end
        end
        OUTPUT_XLATE_REQ: if (xlate_req_valid && xlate_req_ready) state <= OUTPUT_XLATE_WAIT;
        OUTPUT_XLATE_WAIT: if (xlate_rsp_valid) begin
`ifdef PROTECTED_MUT_PERMISSION_BYPASS
          if (1'b0)
`else
          if (xlate_rsp_fault != 0)
`endif
            prepare_retire(ST_XLATE_WRITE, current_output_iova, FS_OUTPUT_XLATE, vector_index);
          else begin translated_addr <= xlate_rsp_paddr; state <= OUTPUT_MEM_REQ; end
        end
`ifdef PROTECTED_MUT_EARLY_COMPLETION
        OUTPUT_MEM_REQ: prepare_retire(ST_OK, 32'd0, FS_NONE, active.batch);
`else
        OUTPUT_MEM_REQ: if (mem_req_valid && mem_req_ready) state <= OUTPUT_MEM_WAIT;
`endif
        OUTPUT_MEM_WAIT: if (mem_rsp_valid) begin
          if (mem_rsp_error)
            prepare_retire(ST_MEM_WRITE, current_output_iova, FS_OUTPUT_WRITE, vector_index);
          else begin retire_vectors_done <= vector_index + 1'b1; state <= NEXT_VECTOR; end
        end
        NEXT_VECTOR: begin
          if (vector_index + 1 == active.batch)
            prepare_retire(ST_OK, 32'd0, FS_NONE, active.batch);
          else begin
            vector_index <= vector_index + 1'b1;
            chunk_index <= '0;
            state <= INPUT_XLATE_REQ;
          end
        end
        RETIRE: if (completion_count < (CW+1)'(COMPLETION_DEPTH)) begin
          completion_fifo[completion_tail] <= '{tag: active.tag, status: retire_status,
            asid: active.asid, fault_iova: retire_fault_iova,
            fault_stage: retire_fault_stage, vectors_done: retire_vectors_done};
          completion_tail <= completion_tail + 1'b1;
          state <= IDLE;
        end
        default: state <= IDLE;
      endcase

      submit_count <= submit_count_next;
      completion_count <= completion_count_next;
    end
  end

`ifndef SYNTHESIS
  a_completion_stable_when_blocked: assert property (@(posedge clk) disable iff (!rst_n)
    completion_valid && !completion_ready |=> $stable({completion_tag, completion_status,
      completion_asid, completion_fault_iova, completion_fault_stage, completion_vectors_done}));
  a_xlate_stable_when_blocked: assert property (@(posedge clk) disable iff (!rst_n)
    xlate_req_valid && !xlate_req_ready |=> $stable({xlate_req_iova, xlate_req_asid, xlate_req_write}));
  a_mem_stable_when_blocked: assert property (@(posedge clk) disable iff (!rst_n)
    mem_req_valid && !mem_req_ready |=> $stable({mem_req_write, mem_req_addr, mem_req_wdata,
      mem_req_wstrb, mem_req_qos}));
  a_stream_stable_when_blocked: assert property (@(posedge clk) disable iff (!rst_n)
    accel_in_valid && !accel_in_ready |=> $stable({accel_in_data, accel_in_tag}));
  a_irq_tracks_completion: assert property (@(posedge clk) disable iff (!rst_n)
    irq == completion_valid);
  a_no_success_before_all_vectors: assert property (@(posedge clk) disable iff (!rst_n)
    completion_valid && completion_status == ST_OK |-> completion_vectors_done != 0);
  a_submit_queue_bounded: assert property (@(posedge clk) disable iff (!rst_n)
    submit_count <= (QW+1)'(QUEUE_DEPTH));
  a_completion_queue_bounded: assert property (@(posedge clk) disable iff (!rst_n)
    completion_count <= (CW+1)'(COMPLETION_DEPTH));
  a_no_command_after_prefetch_fault: assert property (@(posedge clk) disable iff (!rst_n)
    state == RETIRE && (retire_fault_stage == FS_INPUT_XLATE || retire_fault_stage == FS_INPUT_READ) |-> !accel_cmd_valid);
  a_success_only_after_output_ack: assert property (@(posedge clk) disable iff (!rst_n)
    state == RETIRE && retire_status == ST_OK |-> retire_vectors_done == active.batch);
`endif
endmodule
