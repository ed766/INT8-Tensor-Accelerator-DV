#include <stdint.h>
#define MMIO(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define DMA(o) MMIO(0x40000000u+(o))
#define CFG(o) MMIO(0x40001000u+(o))
#define CHIP(o) MMIO(0x50000000u+(o))
#ifndef TEST_K
#define TEST_K 4u
#endif
#ifndef TEST_BATCH
#define TEST_BATCH 1u
#endif
#ifndef TEST_ASID
#define TEST_ASID 1u
#endif
#ifndef TEST_QOS
#define TEST_QOS 8u
#endif
#ifndef TEST_IRQ
#define TEST_IRQ 0
#endif
#ifndef TEST_CACHE
#define TEST_CACHE 0
#endif
static volatile uint32_t irq_seen,irq_completion,irq_tag;
static inline uint32_t cycle32(void){uint32_t v;__asm__ volatile("csrr %0,mcycle":"=r"(v));return v;}
void __attribute__((interrupt("machine"))) trap_handler(void){
  irq_completion=DMA(32);irq_tag=DMA(40)&255u;DMA(44)=1;MMIO(0x4000200cu)=2;irq_seen=1;
}
static void cfg(uint32_t kind,uint32_t out,uint32_t index,uint32_t data){CFG(0)=kind;CFG(4)=out;CFG(8)=index;CFG(12)=data;CFG(20)=1;}
int main(void){
  uint32_t benchmark_start=cycle32();
  volatile uint32_t arithmetic_seed=TEST_K+TEST_BATCH+TEST_ASID;
  uint32_t arithmetic_check=(arithmetic_seed*7u)/(TEST_BATCH?TEST_BATCH:1u);
  if(arithmetic_check==0xffffffffu)return 1;
  MMIO(0x30000800u)=0x0c000401u;
  MMIO(0x30001004u)=0x040004cfu;
  MMIO(0x30001010u)=0x040010cfu;
  for(uint32_t v=0;v<TEST_BATCH;v++){for(uint32_t i=0;i<TEST_K;i+=4)MMIO(0x10001000u+v*64u+i)=0x01010101u;MMIO(0x10004000u+v*4u)=0;}
  for(uint32_t o=0;o<4;o++){for(uint32_t i=0;i<TEST_K;i++)cfg(0,o,i,1);cfg(1,o,0,0);cfg(2,o,0,1);cfg(3,o,0,0);}
  CFG(16)=7;
#ifdef TEST_COMBINED_HOST
  for(volatile uint32_t wake=0;wake<64;wake++)__asm__ volatile("nop");
  for(uint32_t i=0;i<4;i++){
    CHIP(0x20)=i;CHIP(0x24)=0;CHIP(0x28)=0x11111111u+i;CHIP(0x2c)=0x22222222u+i;CHIP(0x58)=3;
    for(volatile uint32_t settle=0;settle<8;settle++)__asm__ volatile("nop");
  }
  CHIP(0x08)=0;CHIP(0x0c)=32;CHIP(0x10)=4;CHIP(0x14)=0x123;CHIP(0x00)=1;
#endif
#ifdef TEST_WARM
  benchmark_start=cycle32();
#endif
#if !defined(NEG_SKIP_FLUSH)
  if(TEST_CACHE){MMIO(0x40002100u)=0;MMIO(0x40002104u)=1;__asm__ volatile("fence");}
#endif
  DMA(0)=0x80001000u;DMA(4)=0x80004000u;DMA(8)=(4u<<16)|64u;DMA(12)=(TEST_BATCH<<7)|TEST_K;
  if(TEST_IRQ){uintptr_t v=(uintptr_t)trap_handler;__asm__ volatile("csrw mtvec,%0"::"r"(v));MMIO(0x40002008u)=2;__asm__ volatile("li t0,0x800; csrs mie,t0; csrsi mstatus,8":::"t0");}
  DMA(16)=(7u<<17)|(TEST_ASID<<8)|0x35u;DMA(20)=TEST_QOS;DMA(24)=1;
#ifdef NEG_ACCESS_DURING
  (void)MMIO(0x10001000u);
#endif
  if(TEST_IRQ){while(!irq_seen)__asm__ volatile("wfi");}else while((DMA(28)&4u)==0u){}
  uint32_t c=TEST_IRQ?irq_completion:DMA(32),tag=TEST_IRQ?irq_tag:(DMA(40)&255u),ok=((c&15u)==0u)&&(((c>>12)&127u)==TEST_BATCH)&&(tag==0x35u);
#ifdef NEG_LATE_DIRTY
  MMIO(0x10004000u)=0x99999999u;MMIO(0x40002100u)=0;MMIO(0x40002104u)=1;
#endif
#if !defined(NEG_SKIP_INVALIDATE)
  if(TEST_CACHE){MMIO(0x40002100u)=1;MMIO(0x40002104u)=1;__asm__ volatile("fence");}
#endif
  uint32_t expected=(TEST_K&255u)*0x01010101u;for(uint32_t v=0;v<TEST_BATCH;v++)if(MMIO(0x10004000u+v*4u)!=expected)ok=0;
#ifdef TEST_COMBINED_HOST
  while(CHIP(0x38)==0u){}
  if((CHIP(0x3c)&15u)!=0u||CHIP(0x40)!=4u)ok=0;
  CHIP(0x44)=1;
#endif
  if(!TEST_IRQ)DMA(44)=1;MMIO(0x40001fe0u)=cycle32()-benchmark_start;MMIO(0x40001ff0u)=ok?0x600d5000u:0xdead5000u;MMIO(0x40001ff4u)=1;
  for(;;)__asm__ volatile("nop");
}
