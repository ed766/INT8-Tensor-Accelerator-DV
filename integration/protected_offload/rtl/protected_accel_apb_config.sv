`timescale 1ns/1ps
module protected_accel_apb_config (
  input logic clk,input logic rst_n,input logic[11:0]paddr,
  input logic psel,input logic penable,input logic pwrite,input logic[31:0]pwdata,
  output logic[31:0]prdata,output logic pready,output logic pslverr,
  output logic cfg_valid,input logic cfg_ready,input logic cfg_reject,input logic[1:0]generation_referenced,output logic[2:0]cfg_kind,
  output logic cfg_bank,output logic[1:0]cfg_output,output logic[5:0]cfg_index,
  output logic[31:0]cfg_data,output logic[1:0][7:0]bank_generation
);
  logic access,commit;
  assign access=psel&&penable;
  logic generation_write;
  logic write_reject;
  logic [1:0] generation_changed_referenced;
  assign commit=access&&pwrite&&paddr==12'h014;
  assign generation_write=access&&pwrite&&paddr==12'h010;
  // The generation register updates both banks atomically. Protect each byte
  // independently so selecting an unreferenced bank cannot rewrite a live one.
  assign generation_changed_referenced = {
    generation_referenced[1] && (pwdata[15:8] != bank_generation[1]),
    generation_referenced[0] && (pwdata[7:0] != bank_generation[0])
  };
`ifdef PROTECTED_MUT_BANK_REFERENCE_BYPASS
  assign write_reject=(commit && cfg_reject);
`else
  assign write_reject=(commit && cfg_reject) || (generation_write && (|generation_changed_referenced));
`endif
  // A referenced bank is an architectural rejection, not an indefinite APB
  // wait.  Firmware can therefore observe and recover from a bank conflict.
  assign cfg_valid=commit&&!cfg_reject;
  assign pready=access&&(!commit||cfg_ready||write_reject);
  always_comb begin
    pslverr=write_reject;prdata='0;
    if(access)case(paddr)
      12'h000:prdata={29'd0,cfg_kind};
      12'h004:prdata={29'd0,cfg_bank,cfg_output};
      12'h008:prdata={26'd0,cfg_index};
      12'h00c:prdata=cfg_data;
      12'h010:prdata={16'd0,bank_generation[1],bank_generation[0]};
      12'h014:prdata='0;
      default:pslverr=1'b1;
    endcase
  end
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin cfg_kind<=0;cfg_bank<=0;cfg_output<=0;cfg_index<=0;cfg_data<=0;bank_generation<='{default:'0};end
    else if(access&&pwrite&&pready&&!pslverr)case(paddr)
      12'h000:cfg_kind<=pwdata[2:0];
      12'h004:begin cfg_output<=pwdata[1:0];cfg_bank<=pwdata[2];end
      12'h008:cfg_index<=pwdata[5:0];
      12'h00c:cfg_data<=pwdata;
      12'h010:begin bank_generation[0]<=pwdata[7:0];bank_generation[1]<=pwdata[15:8];end
      default:begin end
    endcase
  end
`ifndef SYNTHESIS
  a_cfg_stable_while_waiting:assert property(@(posedge clk)disable iff(!rst_n)cfg_valid&&!cfg_ready|=>$stable({cfg_kind,cfg_bank,cfg_output,cfg_index,cfg_data}));
  a_cfg_only_on_commit:assert property(@(posedge clk)disable iff(!rst_n)cfg_valid|->access&&pwrite&&paddr==12'h014);
  a_referenced_bank_has_no_commit:assert property(@(posedge clk)disable iff(!rst_n)cfg_reject|->!cfg_valid);
  a_referenced_generation_write_rejected:assert property(@(posedge clk)disable iff(!rst_n)
    generation_write && (|generation_changed_referenced) |-> pslverr);
`endif
endmodule
