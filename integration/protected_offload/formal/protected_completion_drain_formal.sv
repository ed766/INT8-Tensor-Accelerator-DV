module protected_completion_drain_formal;
  (* gclk *) logic clk;
  logic [1:0] reset_count = 0;
  wire rst_n = reset_count[1];
  always @(posedge clk) if (!reset_count[1]) reset_count <= reset_count + 1'b1;

  logic submitted = 0;
  wire submit_valid = !submitted;
  wire submit_ready, submit_accepted, submit_rejected;
  wire block_submissions = 1'b0;
  wire [1:0][7:0] bank_generation = '0;
  wire [3:0] submit_qos = 4'd8;
  wire [31:0] submit_input_iova = 32'h1000, submit_output_iova = 32'h2000;
  wire [15:0] submit_input_stride = 16'd4, submit_output_stride = 16'd4;
  wire [6:0] submit_k = 7'd4, submit_batch = 7'd1;
  wire [7:0] submit_tag = 8'd1, submit_asid = 8'd1, submit_bank_generation = 8'd0;
  wire submit_bank = 1'b0;
  wire xlate_req_valid, xlate_req_write, xlate_rsp_ready;
  wire [31:0] xlate_req_iova;
  wire [7:0] xlate_req_asid;
  wire xlate_req_ready = 1'b1;
  logic xlate_pending;
  wire xlate_rsp_valid = xlate_pending;
  wire [31:0] xlate_rsp_paddr = xlate_req_iova;
  wire [1:0] xlate_rsp_fault = '0;
  wire mem_req_valid, mem_req_write, mem_rsp_ready;
  wire [31:0] mem_req_addr, mem_req_wdata;
  wire [3:0] mem_req_wstrb, mem_req_qos;
  wire mem_req_ready = 1'b1;
  logic mem_pending, mem_pending_write;
  wire mem_rsp_valid = mem_pending;
  wire [31:0] mem_rsp_rdata = 32'h12345678;
  wire mem_rsp_error = 1'b0;
  wire accel_cmd_valid, accel_cmd_bank, accel_in_valid, accel_out_ready;
  wire [6:0] accel_cmd_k;
  wire [7:0] accel_cmd_tag, accel_in_tag;
  wire [31:0] accel_in_data;
  wire accel_cmd_ready = 1'b1, accel_in_ready = 1'b1;
  wire accel_out_valid = 1'b1;
  wire [31:0] accel_out_data = 32'hcafef00d;
  wire [7:0] accel_out_tag = 8'd1;
  wire completion_valid, completion_published, irq, busy;
  wire completion_ready = 1'b0;
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
  wire [4:0] formal_state;

  protected_offload_dma #(.QUEUE_DEPTH(4), .COMPLETION_DEPTH(4), .MAX_K(16)) dut (.*);

  logic write_accepted, write_response_seen;
  logic past_valid = 0;
  always @(posedge clk) begin
    past_valid <= 1'b1;
    if (!rst_n) begin
      submitted <= 1'b0;
      xlate_pending <= 1'b0;
      mem_pending <= 1'b0;
      mem_pending_write <= 1'b0;
      write_accepted <= 1'b0;
      write_response_seen <= 1'b0;
    end else begin
      cover(submit_accepted);
      cover(busy);
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
      if (submit_valid && submit_ready && !submit_rejected) submitted <= 1'b1;
      if (xlate_req_valid && xlate_req_ready) xlate_pending <= 1'b1;
      if (xlate_rsp_valid && xlate_rsp_ready) xlate_pending <= 1'b0;
      if (mem_req_valid && mem_req_ready) begin
        mem_pending <= 1'b1;
        mem_pending_write <= mem_req_write;
        if (mem_req_write) write_accepted <= 1'b1;
      end
      if (mem_rsp_valid && mem_rsp_ready) begin
        mem_pending <= 1'b0;
        if (mem_pending_write) write_response_seen <= 1'b1;
      end
      if (completion_published && completion_publish_status == 0)
        assert(write_accepted && write_response_seen);
      if (completion_published && completion_publish_status == 0)
        assert(completion_publish_vectors_done == 1);
      cover(completion_published && completion_publish_status == 0 && write_response_seen);
      cover(mem_req_valid && mem_req_ready && mem_req_write);
      cover(mem_rsp_valid && mem_rsp_ready && mem_pending_write);
    end
  end
endmodule
