#include <stdint.h>

/* Independently constructed stimulus: output-major configuration, descriptor
 * staging before memory setup, repeated jobs, and a leaf assembly IRQ handler.
 * No shared_offload.c functions or scenario-signature generator are used. */
static void write_reg(uint32_t address,uint32_t data){
  *(volatile uint32_t *)(uintptr_t)address=data;
}
static uint32_t read_reg(uint32_t address){
  return *(volatile uint32_t *)(uintptr_t)address;
}
volatile uint32_t independent_irq_seen,independent_irq_result;
__attribute__((naked,aligned(4))) static void irq_handler(void){
  __asm__ volatile(
    "addi sp,sp,-16; sw t0,0(sp); sw t1,4(sp); sw t2,8(sp);"
    "li t0,0x40000000; lw t1,32(t0); la t2,independent_irq_result; sw t1,0(t2);"
    "li t1,1; sw t1,44(t0); la t2,independent_irq_seen; sw t1,0(t2);"
    "li t0,0x4000200c; li t1,2; sw t1,0(t0);"
    "lw t0,0(sp); lw t1,4(sp); lw t2,8(sp); addi sp,sp,16; mret");
}
static void maintenance(uint32_t command){
  write_reg(0x40002100u,command);write_reg(0x40002104u,1u);
  __asm__ volatile("fence":::"memory");
}
int main(void){
  uint32_t ok=1,expected_status=0;
  write_reg(0x4000000cu,(TEST_BATCH<<7)|TEST_K);
  write_reg(0x40000008u,(4u<<16)|64u);
  write_reg(0x40000004u,0x80004000u);
  write_reg(0x40000000u,0x80001000u);
  write_reg(0x40000014u,TEST_QOS);
  for(uint32_t output=0;output<4;output++){
    write_reg(0x40001004u,output);
    for(uint32_t kind=0;kind<4;kind++){
      write_reg(0x40001000u,kind);
      for(uint32_t index=0;index<(kind==0?TEST_K:1u);index++){
        write_reg(0x40001008u,index);
        write_reg(0x4000100cu,(kind==0||kind==2)?1u:0u);
        write_reg(0x40001014u,1u);
      }
    }
  }
  write_reg(0x40001010u,7u);
  for(uint32_t vector=0;vector<TEST_BATCH;vector++){
    write_reg(0x10004000u+4u*vector,0u);
    for(uint32_t offset=0;offset<TEST_K;offset+=4)
      write_reg(0x10001000u+64u*vector+offset,0x01010101u);
  }
  write_reg(0x30001010u,0x040010cfu);
  write_reg(0x30001004u,0x040004cfu);
  write_reg(0x30000800u,0x0c000401u);
#ifdef TEST_PARTIAL_OUTPUT_RETRY
  write_reg(0x40000008u,(4096u<<16)|64u);
  write_reg(0x30001014u,0x080000cfu);
  write_reg(0x10008000u,0u);
  expected_status=5;
#endif
#ifdef TEST_INPUT_PTE_FAULT
  write_reg(0x30001004u,0u);expected_status=2;
#endif
#ifdef TEST_READ_PERMISSION_DENIAL
  write_reg(0x30001004u,0x040004c9u);expected_status=2;
#endif
#ifdef TEST_OUTPUT_PTE_FAULT
  write_reg(0x30001010u,0u);expected_status=3;
#endif
#ifdef TEST_OUTPUT_PERMISSION_FAULT
  write_reg(0x30001010u,0x040010c3u);expected_status=3;
#endif
#ifdef TEST_INPUT_BUS_ERROR
  write_reg(0x30001004u,0x080004cfu);expected_status=4;
#endif
  if(TEST_CACHE)maintenance(0u);
  if(TEST_IRQ){
    uintptr_t handler=(uintptr_t)irq_handler;
    __asm__ volatile("csrw mtvec,%0"::"r"(handler));
    write_reg(0x40002008u,2u);
    __asm__ volatile("li t0,0x800; csrs mie,t0; csrsi mstatus,8":::"t0");
  }
  for(uint32_t job=0;job<2;job++){
    independent_irq_seen=0;
    uint32_t tag=0x35u+job;
#ifdef TEST_PARTIAL_OUTPUT_RETRY
    tag=0x35u;
#endif
    write_reg(0x40000010u,(7u<<17)|(TEST_ASID<<8)|tag);
#ifdef TEST_INDEPENDENT_PUBLISH_POP
    if(job==0){
      write_reg(0x40000018u,1u);
      write_reg(0x40000010u,(7u<<17)|(TEST_ASID<<8)|0x36u);
      write_reg(0x40000018u,1u);
    }
#else
    write_reg(0x40000018u,1u);
#endif
    uint32_t result;
    if(TEST_IRQ){
      while(!independent_irq_seen){
#ifdef TEST_M_DEPENDENCY
        uint32_t result;
        __asm__ volatile("li t0,0x1234567; li t1,37; div %0,t0,t1":"=r"(result)::"t0","t1");
#else
        __asm__ volatile("nop");
#endif
      }
      result=independent_irq_result;
    }else{
      while((read_reg(0x4000001cu)&4u)==0u){
#ifdef TEST_M_DEPENDENCY
        uint32_t result;
        __asm__ volatile("li t0,0x1234567; li t1,37; rem %0,t0,t1; remu %0,t0,t1; div %0,t0,t1":"=&r"(result)::"t0","t1");
#endif
      }
      result=read_reg(0x40000020u);
      if((read_reg(0x40000028u)&255u)!=tag)ok=0;
      write_reg(0x4000002cu,1u);
    }
    if((result&15u)!=expected_status||((result>>4)&255u)!=TEST_ASID||
       ((result>>12)&127u)!=(expected_status==5u?1u:expected_status?0u:TEST_BATCH))ok=0;
    if(TEST_CACHE)maintenance(1u);
#ifdef TEST_PARTIAL_OUTPUT_RETRY
    if(read_reg(0x10004000u)!=TEST_K*0x01010101u)ok=0;
    if(read_reg(0x10008000u)!=(job==0?0u:TEST_K*0x01010101u))ok=0;
    if(job==0){
      write_reg(0x30001014u,0x040020cfu);
      write_reg(0x40002200u,(TEST_ASID<<8)|1u);
      while(read_reg(0x40002204u)&1u){}
      expected_status=0;
    }
#else
    for(uint32_t vector=0;vector<TEST_BATCH;vector++)
      if(read_reg(0x10004000u+4u*vector)!=(expected_status?0u:TEST_K*0x01010101u))ok=0;
#endif
  }
  write_reg(0x40001ff0u,ok?0x600d5000u:0xdead5000u);
  write_reg(0x40001ff4u,1u);
  for(;;)__asm__ volatile("nop");
}
