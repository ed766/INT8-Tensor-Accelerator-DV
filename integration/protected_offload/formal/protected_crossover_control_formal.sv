module protected_crossover_control_formal;
  (* gclk *) logic clk;
  logic [1:0] reset_count = 0;
  wire rst_n = reset_count[1];
  always @(posedge clk) if (!reset_count[1]) reset_count <= reset_count + 1'b1;

  logic submit_valid, submit_bank;
  wire block_submissions;
  logic [31:0] submit_input_iova, submit_output_iova;
  logic [15:0] submit_input_stride, submit_output_stride;
  logic [6:0] submit_k, submit_batch;
  logic [7:0] submit_tag, submit_asid, submit_bank_generation;
  logic [3:0] submit_qos;
  logic [1:0][7:0] bank_generation;
  logic xlate_req_ready;
  wire xlate_rsp_valid;
  logic xlate_pending;
  wire [31:0] xlate_rsp_paddr;
  logic [1:0] xlate_rsp_fault;
  logic mem_req_ready, mem_rsp_error;
  wire mem_rsp_valid;
  logic mem_pending;
  logic [31:0] mem_rsp_rdata;
  logic accel_cmd_ready, accel_in_ready;
  wire accel_out_valid;
  logic [31:0] accel_out_data;
  wire [7:0] accel_out_tag;
  logic completion_ready;
  logic submitted=0;
  assign submit_valid=!submitted;
  assign submit_input_iova=32'h0000_1000;
  assign submit_output_iova=32'h0000_2000;
  assign submit_input_stride=16'd4;
  assign submit_output_stride=16'd4;
  assign submit_k=7'd4;
  assign submit_batch=7'd1;
  assign submit_tag=8'd1;
  assign submit_asid=8'd1;
  assign submit_bank=1'b0;
  assign submit_bank_generation=8'd0;
  assign submit_qos=4'd8;
  assign bank_generation=16'd0;
  assign xlate_req_ready=1'b1;
  assign xlate_rsp_paddr=32'h0000_1000;
  assign xlate_rsp_fault=2'd0;
  assign mem_req_ready=1'b1;
  assign mem_rsp_error=1'b0;
  assign mem_rsp_rdata=32'd0;
  assign accel_cmd_ready=1'b1;
  assign accel_in_ready=1'b1;
  assign accel_out_valid=1'b1;
  assign accel_out_tag=8'd1;
  assign accel_out_data=32'd0;
  assign completion_ready=1'b0;
  always @(posedge clk) begin
    if (!rst_n) begin
      submitted<=0;
    end else begin
      if (submit_valid&&submit_ready&&!submit_rejected) submitted<=1;
    end
  end

  wire submit_ready, submit_accepted, submit_rejected;
  wire [4:0] formal_state;
  wire xlate_req_valid, xlate_req_write, xlate_rsp_ready;
  wire [31:0] xlate_req_iova;
  wire [7:0] xlate_req_asid;
  wire mem_req_valid, mem_req_write;
  wire [31:0] mem_req_addr, mem_req_wdata;
  wire [3:0] mem_req_wstrb, mem_req_qos;
  wire mem_rsp_ready, accel_cmd_valid, accel_cmd_bank;
  wire [6:0] accel_cmd_k;
  wire [7:0] accel_cmd_tag;
  wire accel_in_valid, accel_out_ready;
  wire [31:0] accel_in_data;
  wire [7:0] accel_in_tag;
  wire completion_valid, completion_published, irq, busy;
  wire [7:0] completion_tag, completion_asid, completion_publish_tag, completion_publish_asid;
  wire [3:0] completion_status, completion_publish_status;
  wire [31:0] completion_fault_iova;
  wire [2:0] completion_fault_stage, completion_publish_fault_stage;
  wire [6:0] completion_vectors_done, completion_publish_vectors_done;
  wire [2:0] submit_occupancy, completion_occupancy;
  wire [1:0] bank_referenced;
  wire [4:0] owned_valid;
  wire [4:0][31:0] owned_start, owned_end, owned_input_start, owned_input_end,
                   owned_output_start, owned_output_end;

  (* anyseq *) logic inv_psel, inv_penable, inv_pwrite;
  (* anyseq *) logic [7:0] inv_paddr;
  (* anyseq *) logic [31:0] inv_pwdata;
  wire [31:0] inv_prdata;
  wire inv_pready, inv_pslverr, inv_valid, inv_all;
  wire [7:0] inv_asid;
  wire inv_translation_idle = !(formal_state == 5'd1 || formal_state == 5'd2 ||
                                formal_state == 5'd8 || formal_state == 5'd9);

  protected_tlb_control_apb inv_dut (
    .clk, .rst_n, .paddr(inv_paddr), .psel(inv_psel), .penable(inv_penable),
    .pwrite(inv_pwrite), .pwdata(inv_pwdata), .prdata(inv_prdata),
    .pready(inv_pready), .pslverr(inv_pslverr),
    .translation_idle(inv_translation_idle), .service_busy(busy),
    .submit_occupancy, .completion_occupancy, .inv_valid, .inv_all,
    .inv_asid, .block_submissions
  );

  protected_offload_dma #(.QUEUE_DEPTH(4), .COMPLETION_DEPTH(4), .MAX_K(16)) dut (.*);

  // Model a one-cycle-latency target from the actual request handshake. The
  // response cannot appear before acceptance and remains asserted until the
  // DMA consumes it.
  assign xlate_rsp_valid = xlate_pending;
  assign mem_rsp_valid = mem_pending;
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      xlate_pending <= 1'b0;
      mem_pending <= 1'b0;
    end else begin
      if (xlate_req_valid && xlate_req_ready) xlate_pending <= 1'b1;
      if (xlate_rsp_valid && xlate_rsp_ready) xlate_pending <= 1'b0;
      if (mem_req_valid && mem_req_ready) mem_pending <= 1'b1;
      if (mem_rsp_valid && mem_rsp_ready) mem_pending <= 1'b0;
    end
  end

  (* anyseq *) logic chiplet_dma_event, accelerator_event, device_fault_event;
  (* anyseq *) logic [5:0] paddr;
  (* anyseq *) logic psel, penable, pwrite;
  (* anyseq *) logic [31:0] pwdata;
  wire [31:0] prdata;
  wire pready, pslverr, irq_ext;
  wire [2:0] raw_status, pending_status, enable_mask;
  protected_irq_aggregator irq_dut(.*);

  logic past_valid = 0, write_inflight = 0;
  logic [2:0] irq_events_now, irq_ack_now;
  assign irq_events_now={device_fault_event,accelerator_event,chiplet_dma_event};
  assign irq_ack_now=(psel&&penable&&pwrite&&paddr==6'h0c)?pwdata[2:0]:3'b000;
  always @(posedge clk) begin
    past_valid <= 1'b1;
    if(!rst_n) write_inflight<=0;
    else begin
      if(mem_req_valid&&mem_req_ready&&mem_req_write)write_inflight<=1;
      if(mem_rsp_valid&&mem_rsp_ready&&write_inflight)write_inflight<=0;
    end
    if (rst_n) begin
      // These assertions bind the crossover contract to the real DMA and IRQ
      // RTL rather than a duplicate software state model.
      assert(!block_submissions || !submit_ready);
      assert(!inv_valid || (inv_translation_idle && !busy &&
             submit_occupancy == 0 && completion_occupancy == 0));
      assert(!(busy || submit_occupancy != 0) || (bank_referenced != 0));
      assert(!completion_published || completion_publish_status != 0 ||
             completion_publish_vectors_done != 0);
      assert(!completion_published || completion_publish_status != 0 || !write_inflight);
      assert(irq_ext == |(raw_status & enable_mask));
      if(past_valid&&$past(rst_n)&&|( $past(irq_events_now & irq_ack_now) ))
        assert((raw_status & $past(irq_events_now & irq_ack_now)) ==
               $past(irq_events_now & irq_ack_now));
      if (past_valid && !$past(rst_n)) begin
        assert(!busy && submit_occupancy == 0 && completion_occupancy == 0);
        assert(bank_referenced == 0 && !completion_valid && !xlate_req_valid && !mem_req_valid);
      end
      cover(submit_accepted);
      cover(bank_referenced != 0);
      cover(formal_state == 5'd2);
      cover(formal_state == 5'd3);
      cover(formal_state == 5'd4);
      cover(formal_state == 5'd5);
      cover(formal_state == 5'd6);
      cover(formal_state == 5'd7);
      cover(formal_state == 5'd8);
      cover(formal_state == 5'd9);
      cover(formal_state == 5'd10);
      cover(formal_state == 5'd11);
      cover(formal_state == 5'd12);
      cover(formal_state == 5'd13);
      cover(inv_dut.pending && block_submissions && !submit_ready);
      cover(inv_valid);
      cover(completion_published && completion_publish_status == 0);
      cover(block_submissions && submit_valid && !submit_ready);
      cover((chiplet_dma_event || accelerator_event || device_fault_event) &&
            psel && penable && pwrite && paddr == 6'h0c && pwdata[2:0] != 0);
    end
    cover(rst_n && busy && dut.state != 5'd0);
  end
endmodule
