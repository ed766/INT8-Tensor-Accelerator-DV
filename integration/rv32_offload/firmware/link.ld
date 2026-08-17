OUTPUT_ARCH(riscv)
ENTRY(_start)
PHDRS { text PT_LOAD FLAGS(5); rodata PT_LOAD FLAGS(4); data PT_LOAD FLAGS(6); }
SECTIONS {
  . = 0x00000000;
  .text : { KEEP(*(.text.start)) *(.text .text.*) } :text
  . = 0x00002000;
  .rodata : { *(.rodata .rodata.*) } :rodata
  . = ALIGN(4);
  .data : { *(.data .data.*) } :data
  . = ALIGN(4); __bss_start = .;
  .bss : { *(.bss .bss.*) *(COMMON) } :data
  __bss_end = .;
  __stack_top = 0x00003f00;
}
