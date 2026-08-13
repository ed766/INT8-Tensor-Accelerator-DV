module int8_control_formal;
  (* gclk *) logic clk;
  logic [1:0] reset_count = 0;
  wire rst_n = reset_count[1];
  always @(posedge clk) if (!rst_n) reset_count <= reset_count + 1'b1;

  (* anyseq *) logic cmd_valid, cmd_bank, out_ready;
  (* anyseq *) logic [3:0] cmd_k;
  (* anyseq *) logic [7:0] cmd_tag;
  (* anyseq *) logic in_valid;
  (* anyseq *) logic [15:0] in_data;
  logic [7:0] in_tag;
  logic cfg_valid=0,cfg_bank=0; logic [2:0] cfg_kind=0; logic cfg_output=0;
  logic [2:0] cfg_index=0; logic [31:0] cfg_data=0;
  wire cfg_ready,cmd_ready,cmd_error,in_ready,out_valid;
  wire [15:0] out_data; wire [7:0] out_tag;
  wire [31:0] perf_accepted,perf_completed,perf_input_chunks,perf_output_stalls,perf_bank_swaps;
  logic [7:0] expected_tag;
  always @(posedge clk) if (!rst_n) expected_tag<=0; else if(cmd_valid&&cmd_ready&&cmd_k>=2&&cmd_k<=8&&cmd_k[0]==0) expected_tag<=cmd_tag;
  always_comb in_tag=expected_tag;

  int8_tensor_accel #(.LANES(2),.OUTPUTS(2),.MAX_K(8),.FIFO_DEPTH(2)) dut(.*);

  logic past_valid=0;
  always @(posedge clk) begin
    past_valid<=1;
    if(past_valid&&rst_n&&$past(rst_n)) begin
      if($past(cmd_valid&&!cmd_ready)) assume(cmd_valid&&$stable(cmd_k)&&$stable(cmd_bank)&&$stable(cmd_tag));
      if($past(in_valid&&!in_ready)) assume(in_valid&&$stable(in_data));
      assert(perf_completed<=perf_accepted);
      assert((perf_accepted-perf_completed)<=3);
      if($past(out_valid&&!out_ready)) assert(out_valid&&$stable(out_data)&&$stable(out_tag));
      if($past(cmd_valid&&cmd_ready&&(cmd_k<2||cmd_k>8||cmd_k[0]))) begin
        assert(cmd_error); assert(perf_accepted==$past(perf_accepted));
      end
      if(in_ready) assert(perf_accepted>perf_completed);
      if(perf_completed!=$past(perf_completed)) assert($past(out_valid&&out_ready));
      cover((perf_accepted-perf_completed)>=2);
      cover(cmd_error);
      cover(perf_bank_swaps!=0);
    end
  end
endmodule
