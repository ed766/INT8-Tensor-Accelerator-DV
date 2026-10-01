// Reduced queues, implemented DMA datapath/control, legal one-cycle responders.
// Tags are restricted to two identities; data correctness is checked elsewhere.
module protected_lifetime_reset_formal;
  (* gclk *) logic clk;
  (* anyseq *) logic rst_n, submit_valid, tag_select, completion_ready;
  logic past_valid=0;
  wire [7:0] submit_tag={7'b0,tag_select};
  wire submit_ready,submit_accepted,submit_rejected;
  wire xlate_req_valid,xlate_req_write,xlate_rsp_ready;
  wire [31:0] xlate_req_iova;
  wire [7:0] xlate_req_asid;
  logic xlate_pending,mem_pending,output_pending;
  wire mem_req_valid,mem_req_write,mem_rsp_ready;
  wire [31:0] mem_req_addr,mem_req_wdata;
  wire [3:0] mem_req_wstrb,mem_req_qos;
  wire accel_cmd_valid,accel_cmd_bank,accel_in_valid,accel_out_ready;
  wire [6:0] accel_cmd_k;
  wire [7:0] accel_cmd_tag,accel_in_tag;
  wire [31:0] accel_in_data;
  logic [7:0] output_tag;
  wire completion_valid,completion_published,irq,busy;
  wire [7:0] completion_tag,completion_asid,completion_publish_tag,completion_publish_asid;
  wire [3:0] completion_status,completion_publish_status;
  wire [31:0] completion_fault_iova;
  wire [2:0] completion_fault_stage,completion_publish_fault_stage;
  wire [6:0] completion_vectors_done,completion_publish_vectors_done;
  wire [2:0] submit_occupancy,completion_occupancy;
  wire [1:0] bank_referenced;
  wire [2:0] owned_valid;
  wire [2:0][31:0] owned_start,owned_end,owned_input_start,owned_input_end,
                    owned_output_start,owned_output_end;
  wire [4:0] formal_state;
  protected_offload_dma #(.QUEUE_DEPTH(2),.COMPLETION_DEPTH(2),.MAX_K(4)) dut (
    .clk,.rst_n,.submit_valid,.submit_ready,.submit_accepted,.submit_rejected,
    .submit_input_iova(32'h1000),.submit_output_iova(32'h2000),
    .submit_input_stride(16'd4),.submit_output_stride(16'd4),
    .submit_k(7'd4),.submit_batch(7'd1),.submit_tag,.submit_asid(8'd1),
    .submit_bank(1'b0),.submit_bank_generation(8'd0),.submit_qos(4'd0),
    .bank_generation(16'd0),.block_submissions(1'b0),
    .xlate_req_valid,.xlate_req_ready(1'b1),.xlate_req_write,.xlate_req_iova,.xlate_req_asid,
    .xlate_rsp_valid(xlate_pending),.xlate_rsp_ready,.xlate_rsp_paddr(32'h1000),.xlate_rsp_fault(2'd0),
    .mem_req_valid,.mem_req_ready(1'b1),.mem_req_write,.mem_req_addr,.mem_req_wdata,.mem_req_wstrb,.mem_req_qos,
    .mem_rsp_valid(mem_pending),.mem_rsp_ready,.mem_rsp_rdata(32'd0),.mem_rsp_error(1'b0),
    .accel_cmd_valid,.accel_cmd_ready(1'b1),.accel_cmd_k,.accel_cmd_tag,.accel_cmd_bank,
    .accel_in_valid,.accel_in_ready(1'b1),.accel_in_data,.accel_in_tag,
    .accel_out_valid(output_pending),.accel_out_ready,.accel_out_tag(output_tag),.accel_out_data(32'd0),
    .completion_valid,.completion_ready,.completion_tag,.completion_asid,.completion_status,
    .completion_fault_iova,.completion_fault_stage,.completion_vectors_done,
    .completion_published,.completion_publish_tag,.completion_publish_asid,
    .completion_publish_status,.completion_publish_fault_stage,.completion_publish_vectors_done,
    .submit_occupancy,.completion_occupancy,.bank_referenced,.owned_valid,.owned_start,.owned_end,
    .owned_input_start,.owned_input_end,.owned_output_start,.owned_output_end,.irq,.busy,.formal_state
  );
  logic [1:0] live_tags;
  logic accepted_tag;
  logic saw_owned_reset=0, saw_publication=0, saw_consumption=0;
  always @(posedge clk) begin
    past_valid<=1;
    if(!past_valid) assume(!rst_n);
    if(!rst_n) begin
      xlate_pending<=0;mem_pending<=0;output_pending<=0;output_tag<=0;
      live_tags<=0;accepted_tag<=0;
      if(past_valid && $past(rst_n) && $past(busy)) saw_owned_reset<=1;
    end else begin
      accepted_tag<=tag_select;
      if(xlate_req_valid)xlate_pending<=1;
      if(xlate_pending&&xlate_rsp_ready)xlate_pending<=0;
      if(mem_req_valid)mem_pending<=1;
      if(mem_pending&&mem_rsp_ready)mem_pending<=0;
      if(accel_in_valid)begin output_pending<=1;output_tag<=accel_in_tag;end
      if(output_pending&&accel_out_ready)output_pending<=0;
      if(submit_accepted)begin
        assert(!live_tags[accepted_tag]);
        live_tags[accepted_tag]<=1;
      end
      if(completion_valid)begin
        assert(completion_tag<2);
        assert(live_tags[completion_tag[0]]);
      end
      if(completion_valid&&completion_ready)begin
        live_tags[completion_tag[0]]<=0;
        saw_consumption<=1;
      end
      if(completion_published)saw_publication<=1;
      if(past_valid&&!$past(rst_n))begin
        assert(!submit_accepted&&!submit_rejected);
        assert(!busy&&!completion_valid&&!completion_published);
        assert(submit_occupancy==0&&completion_occupancy==0&&bank_referenced==0);
        assert(!mem_req_valid&&!xlate_req_valid&&!accel_cmd_valid&&!accel_in_valid);
      end
      cover(submit_rejected && |live_tags);
      cover(completion_valid&&!completion_ready);
      cover(saw_consumption&&submit_accepted);
      cover(saw_owned_reset&&!busy&&!completion_valid);
      cover(saw_owned_reset&&completion_valid);
      cover(saw_publication&&saw_consumption);
    end
  end
endmodule
