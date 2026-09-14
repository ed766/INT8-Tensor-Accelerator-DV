module protected_queue_count_formal;
  (* anyconst *) logic [2:0] count;
  (* anyconst *) logic push,pop;
  wire [2:0] next_count;
  protected_queue_count_next #(.WIDTH(3)) dut(.*);
  always @* begin
    assume(count<=4);
    assume(!push||count<4||pop);
    assume(!pop||count>0||push);
    assert(next_count<=4);
    if(push&&pop)assert(next_count==count);
    if(push&&!pop)assert(next_count==count+1);
    if(!push&&pop)assert(next_count==count-1);
    cover(count==4&&pop&&push);
  end
endmodule
