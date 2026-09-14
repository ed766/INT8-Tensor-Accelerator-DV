package protected_offload_addr_pkg;
  localparam logic [31:0] DMA_CSR_BASE = 32'h40000000;
  localparam logic [31:0] DMA_CSR_SIZE = 32'h00001000;
  localparam logic [31:0] ACCEL_CFG_BASE = 32'h40001000;
  localparam logic [31:0] ACCEL_CFG_SIZE = 32'h00001000;
  localparam logic [31:0] SHARED_IOVA_BASE = 32'h80000000;
  localparam logic [31:0] SHARED_IOVA_SIZE = 32'h00010000;
  localparam logic [31:0] SHARED_PHYS_BASE = 32'h10000000;
  localparam logic [31:0] SHARED_PHYS_SIZE = 32'h00010000;
  localparam logic [31:0] PAGE_TABLE_BASE = 32'h30000000;
  localparam logic [31:0] PAGE_TABLE_SIZE = 32'h00010000;
  localparam logic [31:0] RESULT_MAILBOX_BASE = 32'h40001ff0;
  localparam logic [31:0] RESULT_MAILBOX_SIZE = 32'h00000010;
endpackage
