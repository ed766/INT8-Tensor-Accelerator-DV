`timescale 1ns/1ps
module protected_queue_count_next #(
  parameter int WIDTH=3
) (
  input logic [WIDTH-1:0] count,
  input logic push,
  input logic pop,
  output logic [WIDTH-1:0] next_count
);
  always_comb begin
    next_count=count;
    case({push,pop})
      2'b10:next_count=count+1'b1;
      2'b01:next_count=count-1'b1;
      default:next_count=count;
    endcase
  end
endmodule
