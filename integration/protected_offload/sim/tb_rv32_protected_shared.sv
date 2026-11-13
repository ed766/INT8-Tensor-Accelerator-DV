`timescale 1ns/1ps
module tb_rv32_protected_shared #(parameter bit USE_CACHE=0,parameter bit CPU_ENABLE_M=0,parameter bit CPU_ENABLE_TRAPS=1,parameter bit ENABLE_CHIPLET=0,parameter int COMPLETION_POP_WAIT_CYCLES=0);
 logic clk=0,rst_n=0,firmware_done,commit_valid,irq,chip_active_debug,chip_link_debug;logic[2:0]chip_state_debug,chip_submit_debug,chip_comp_debug;logic[8:0]chip_send_debug,chip_recv_debug;logic[31:0]firmware_result,commit_pc,cycles,benchmark_cycles;logic recovery_snapshot_valid=0;logic[31:0]recovery_snapshot_addr=0;logic[63:0]recovery_snapshot_data=0;logic recovery_snapshot_sent=0;logic reset_trigger_pending=0;string reset_phase="none";always #5 clk=~clk;
 rv32_protected_shared_top #(.USE_CACHE(USE_CACHE),.CPU_ENABLE_M(CPU_ENABLE_M),.CPU_ENABLE_TRAPS(CPU_ENABLE_TRAPS),.ENABLE_CHIPLET(ENABLE_CHIPLET),.COMPLETION_POP_WAIT_CYCLES(COMPLETION_POP_WAIT_CYCLES)) dut(.*);integer commits=0;
 integer prolonged_wait_cycles=0;
 logic prior_reset_release=0;
 always @(posedge clk) begin
   if(rst_n && !prior_reset_release)
     a_no_stale_muldiv_result_after_reset: assert(!dut.cpu.muldiv_rsp_valid)
       else $fatal(1,"a_no_stale_muldiv_result_after_reset");
   prior_reset_release<=rst_n;
 end
 always @(posedge clk) begin
   if(!rst_n || !dut.psel || !dut.penable || dut.pready)prolonged_wait_cycles<=0;
   else prolonged_wait_cycles<=prolonged_wait_cycles+1;
 end
 always @(posedge clk) begin
   if(rst_n && !reset_issued && reset_at<0 && reset_phase!="none") begin
     case(reset_phase)
       "ptw_req": if(dut.ptw_req_valid&&dut.ptw_req_ready)reset_trigger_pending<=1;
       "metadata_status": if(dut.psel&&dut.penable&&dut.pready&&!dut.pwrite&&dut.paddr==32'h4000_0020)reset_trigger_pending<=1;
       "metadata_address": if(dut.psel&&dut.penable&&dut.pready&&!dut.pwrite&&dut.paddr==32'h4000_0024)reset_trigger_pending<=1;
       "metadata_stage": if(dut.psel&&dut.penable&&dut.pready&&!dut.pwrite&&dut.paddr==32'h4000_0028)reset_trigger_pending<=1;
       "publication": if(dut.completion_published)reset_trigger_pending<=1;
       "dma_b_wait": if(dut.crossover_observer.mem_pending&&!dut.mem_req_valid&&!dut.mem_rsp_valid&&dut.svc.dma.state==dut.svc.dma.OUTPUT_MEM_WAIT)reset_trigger_pending<=1;
       "mem_req": if(dut.mem_req_valid&&dut.mem_req_ready)reset_trigger_pending<=1;
       "accepted_output_write": if(dut.s_awvalid[1]&&dut.s_awready[1])reset_trigger_pending<=1;
      // Response/completion reset points are handled at the falling edge
      // before the next rising-edge handshake, not one cycle after drain.
      "mem_rsp": ;
       "mdiv_result": ;
       "apb_wait": if(dut.psel&&dut.penable&&!dut.pready)reset_trigger_pending<=1;
       "mdiv_busy": if(dut.cpu.muldiv_active_q)reset_trigger_pending<=1;
       "m_dma_early", "m_dma_middle", "m_dma_finalize": ;
       "m_dma_response": ;
       "multiple_owners": ;
       "before_pop": ;
       // Target WREADY is delayed for this test so the address handshake
       // leaves an observable ownership window before the first data beat.
       "host_w_wait": if((|(dut.m_awvalid & dut.m_awready)) &&
                         !(|(dut.m_wvalid & dut.m_wready)))reset_trigger_pending<=1;
       "completion": if(dut.svc.completion_valid&&!dut.svc.completion_ready)reset_trigger_pending<=1;
       "completion_irq": if(dut.svc.completion_valid&&dut.irq_pending[1])reset_trigger_pending<=1;
       "maintenance_invalidation": if(dut.maint_busy)reset_trigger_pending<=1;
       "prolonged_backpressure": if(prolonged_wait_cycles>=128&&dut.crossover_observer.host_aw_pending)reset_trigger_pending<=1;
       "combined_busy": if(ENABLE_CHIPLET && dut.chip_busy && dut.svc.dma.busy)reset_trigger_pending<=1;
       default: $fatal(1,"unsupported RESET_PHASE=%s",reset_phase);
     endcase
   end
 end
 always @(negedge clk) if(rst_n && !reset_issued &&
     (reset_trigger_pending ||
      (reset_phase=="mem_rsp"&&dut.mem_rsp_valid&&dut.mem_rsp_ready) ||
      (reset_phase=="before_pop"&&dut.dma_sel&&dut.penable&&dut.pwrite&&dut.paddr==32'h4000_002c&&dut.svc.completion_valid) ||
      (reset_phase=="mdiv_result"&&dut.cpu.muldiv_rsp_valid&&dut.cpu.muldiv_rsp_ready) ||
      (reset_phase=="m_dma_early"&&dut.svc.dma.busy&&dut.cpu.muldiv_active_q&&dut.cpu.u_muldiv.state_q==1&&dut.cpu.u_muldiv.iteration_q==2) ||
      (reset_phase=="m_dma_middle"&&dut.svc.dma.busy&&dut.cpu.muldiv_active_q&&dut.cpu.u_muldiv.state_q==1&&dut.cpu.u_muldiv.iteration_q==16) ||
      (reset_phase=="m_dma_finalize"&&dut.svc.dma.busy&&dut.cpu.muldiv_active_q&&dut.cpu.u_muldiv.state_q==2) ||
      (reset_phase=="m_dma_response"&&dut.svc.dma.busy&&dut.cpu.muldiv_rsp_valid) ||
      (reset_phase=="multiple_owners"&&dut.svc.dma.busy&&dut.cpu.muldiv_active_q&&dut.cpu.u_muldiv.iteration_q>=2&&dut.crossover_observer.mem_pending&&dut.svc.completion_valid&&dut.irq_pending[1]) ||
      (reset_phase=="completion"&&dut.svc.completion_valid&&!dut.svc.completion_ready))) begin
   rst_n=0;reset_issued=1;
 end
 always @(posedge clk) begin
   recovery_snapshot_valid<=0;
   if(rst_n && expected_partial_retry!=0 && !recovery_snapshot_sent &&
      dut.svc.completion_valid && dut.svc.completion_ready &&
      dut.svc.completion_status!=0 && dut.svc.completion_vectors_done==1) begin
     recovery_snapshot_addr<=32'h10004000;
     recovery_snapshot_data<=dut.mem1.memory[13'h800];
     recovery_snapshot_valid<=1;
     recovery_snapshot_sent<=1;
   end
 end
 integer expected_k=4,expected_batch=1,expected_buffer_offset=0,reset_at=-1,expected_fault=0,expected_partial_retry=0,expected_double_submit=0;logic reset_issued;
 integer completion_publish_count=0;
 always @(posedge clk) if(rst_n && expected_double_submit!=0 && dut.completion_published) begin
   if(completion_publish_count==0 && (dut.completion_publish_tag!=8'h35 || dut.completion_publish_status!=0))
     $fatal(1,"first queued completion identity/status mismatch");
   if(completion_publish_count==1 && (dut.completion_publish_tag!=8'h36 || dut.completion_publish_status!=0))
     $fatal(1,"second queued completion identity/status mismatch");
   if(completion_publish_count>=2)$fatal(1,"duplicate queued completion publication");
   completion_publish_count<=completion_publish_count+1;
 end
 always_ff@(posedge clk)if(commit_valid)commits<=commits+1;
 always_ff@(posedge clk)if(ENABLE_CHIPLET&&dut.chip_sel&&dut.penable)$display("CHIP_APB|addr=%08x|write=%0b|data=%08x|rdata=%08x",dut.paddr,dut.pwrite,dut.pwdata,dut.chip_rdata);
`ifdef TEST_MLP_DEMO
 int contenders, overlap, dma_wait, contender_wait, max_dma_wait, max_contender_wait;
 logic [3:0] observed_dma_qos, observed_peer_qos;
 always @(posedge clk) if (rst_n) begin
   if (dut.s_arvalid[1] && dut.s_arvalid[3]) overlap <= overlap + 1;
   if (dut.s_arvalid[1]) begin
     observed_dma_qos <= dut.s_arqos[1];
     if (dut.s_arready[1]) dma_wait <= 0;
     else begin
       dma_wait <= dma_wait + 1;
       if (dma_wait >= max_dma_wait) max_dma_wait <= dma_wait + 1;
     end
   end
   if (dut.cached_host.contender_selected) begin
     observed_peer_qos <= dut.s_arqos[3];
     if (dut.s_arready[3]) begin
       contenders <= contenders + 1;
       contender_wait <= 0;
     end else begin
       contender_wait <= contender_wait + 1;
       if (contender_wait >= max_contender_wait) max_contender_wait <= contender_wait + 1;
     end
   end
 end
`endif
 initial begin
   reset_issued=0;void'($value$plusargs("EXPECT_K=%d",expected_k));void'($value$plusargs("EXPECT_BATCH=%d",expected_batch));void'($value$plusargs("EXPECT_FAULT=%d",expected_fault));void'($value$plusargs("EXPECT_PARTIAL_RETRY=%d",expected_partial_retry));void'($value$plusargs("EXPECT_DOUBLE_SUBMIT=%d",expected_double_submit));void'($value$plusargs("RESET_AT=%d",reset_at));void'($value$plusargs("RESET_PHASE=%s",reset_phase));
   void'($value$plusargs("BUFFER_OFFSET=%d",expected_buffer_offset));
   // Make the backing-store startup contract explicit rather than relying on
   // simulator-specific initialization of unpacked arrays.
   for (int word_index = 0; word_index < 8192; word_index++) begin
     dut.mem1.memory[word_index] = '0;
     dut.mem2.memory[word_index] = '0;
     dut.mem3.memory[word_index] = '0;
   end
   repeat(5)@(posedge clk);rst_n=1;
   fork
     begin : reset_driver
       integer reset_index;
       if(reset_at>=0) begin
         for(reset_index=0;reset_index<reset_at;reset_index=reset_index+1) @(posedge clk);
         rst_n=0;
         reset_issued=1;
         for(reset_index=0;reset_index<3;reset_index=reset_index+1) @(negedge clk);
         rst_n=1;
       end else if(reset_phase!="none") begin
         wait(reset_issued);
         for(reset_index=0;reset_index<3;reset_index=reset_index+1) @(negedge clk);
         rst_n=1;
       end
     end
   join_none
   repeat(400000)begin @(posedge clk);if(firmware_done)begin
   if(firmware_result!==32'h600d5000)$fatal(1,"firmware result %08x",firmware_result);
`ifdef TEST_MLP_DEMO
   $display("MLP_AXI|contenders=%0d|overlap=%0d|dma_wait=%0d|contender_wait=%0d|qos=%0d|peer_qos=%0d",
            contenders, overlap, max_dma_wait, max_contender_wait, observed_dma_qos, observed_peer_qos);
`else
   if(expected_double_submit!=0 && completion_publish_count!=2)$fatal(1,"expected two tagged completion publications, saw %0d",completion_publish_count);
   if(((expected_buffer_offset&4)!=0 ? dut.mem1.memory[(32'h1000+expected_buffer_offset)>>3][63:32] : dut.mem1.memory[(32'h1000+expected_buffer_offset)>>3][31:0])!==32'h01010101)$fatal(1,"input memory wrong at buffer offset %0d",expected_buffer_offset);
   for(int v=0;v<expected_batch;v++)begin int output_byte_addr,wi,expected_output_k;logic[31:0]actual;output_byte_addr=(expected_partial_retry!=0&&v!=0)?32'h8000:(32'h4000+expected_buffer_offset+v*4);wi=output_byte_addr>>3;expected_output_k=(expected_double_submit!=0)?4:expected_k;if(output_byte_addr[2])actual=dut.mem1.memory[wi][63:32];else actual=dut.mem1.memory[wi][31:0];if(actual!==((expected_fault!=0)?32'h0:((expected_output_k&255)*32'h01010101)))$fatal(1,"output memory v=%0d got=%08x",v,actual);end
   if(expected_double_submit!=0 && dut.mem1.memory[13'h800][63:32]!==((expected_k&255)*32'h01010101))$fatal(1,"second descriptor output got=%08x",dut.mem1.memory[13'h800][63:32]);
   if(((expected_fault!=0)&&dut.perf_tlb_misses<1)||((expected_fault==0)&&(dut.perf_tlb_misses<2||dut.perf_walk_reads<4)))$fatal(1,"page walk missing");
`endif
   $display("PROTECTED_SHARED|status=PASS|commits=%0d|cycles=%0d|benchmark_cycles=%0d|k=%0d|batch=%0d|cache=%0d|rv32m=%0d|reset=%0d|host=1|dma=1|ptw=1|fabric=1",commits,cycles,benchmark_cycles,expected_k,expected_batch,USE_CACHE,CPU_ENABLE_M,reset_issued);$finish;end end
   if (ENABLE_CHIPLET)
     $fatal(1,"timeout pc=%08x mcause=%08x mtval=%08x paddr=%08x psel=%0b penable=%0b chip_sel=%0b instr=%08x commits=%0d chip_active=%0b chip_state=%0d chip_submit=%0d chip_comp=%0d chip_send=%0d chip_recv=%0d chip_link=%0b",
            commit_pc,dut.cpu.mcause_q,dut.cpu.mtval_q,dut.paddr,dut.psel,dut.penable,dut.chip_sel,dut.instr,commits,
            chip_active_debug,chip_state_debug,chip_submit_debug,chip_comp_debug,
            chip_send_debug,chip_recv_debug,chip_link_debug);
   else
     $fatal(1,"timeout pc=%08x mcause=%08x mtval=%08x paddr=%08x psel=%0b penable=%0b instr=%08x commits=%0d",commit_pc,dut.cpu.mcause_q,dut.cpu.mtval_q,dut.paddr,dut.psel,dut.penable,dut.instr,commits);
 end
endmodule
