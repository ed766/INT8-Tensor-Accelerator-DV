#include <stdint.h>
#define MMIO(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define DMA(o) MMIO(0x40000000u+(o))
#define CFG(o) MMIO(0x40001000u+(o))
#define CHIP(o) MMIO(0x50000000u+(o))
#ifdef TEST_CACHE_BOUNDARY
#define INPUT_PA 0x1000101cu
#define OUTPUT_PA 0x1000401cu
#define INPUT_IOVA 0x8000101cu
#define OUTPUT_IOVA 0x8000401cu
#else
#define INPUT_PA 0x10001000u
#define OUTPUT_PA 0x10004000u
#define INPUT_IOVA 0x80001000u
#define OUTPUT_IOVA 0x80004000u
#endif
#if defined(TEST_CHIPLET_SLEEP_DURING) || defined(TEST_CHIPLET_PARITY_FAULT)
#define CHIPLET_WORDS 8u
#else
#define CHIPLET_WORDS 4u
#endif
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
#ifndef TEST_SCENARIO_ID
#define TEST_SCENARIO_ID 0
#endif
#ifndef TEST_COMPLETION_POP_DELAY
#define TEST_COMPLETION_POP_DELAY 0u
#endif
#ifndef TEST_COVERAGE_EDGES
#define TEST_COVERAGE_EDGES 0
#endif
#ifdef TEST_M_DEPENDENCY
#include "crossover_cpu_intents.h"
#endif
static volatile uint32_t irq_seen,irq_completion,irq_tag,trap_seen;
#ifdef TEST_ACCESS_LEGALITY
static volatile uint32_t access_trap_causes;
#endif
static volatile uint32_t timer_seen,interrupt_order;
static volatile uint32_t chip_irq_seen,chip_irq_status,chip_irq_words;
static volatile uint32_t scenario_activation;
#ifdef TEST_STATEFUL_CASE
static void stateful_trap(uint32_t cause);
#endif
#ifdef TEST_M_SWEEP
extern uint32_t m_sweep_probe(void);
#endif
#if TEST_SCENARIO_ID != 0
extern uint32_t crossover_scenario_program(void);
#endif
#ifdef TEST_CPU_STREAM
extern uint32_t generated_cpu_stream_abi_probe(void);
volatile uint32_t cpu_stream_signature;
#endif
static inline uint32_t cycle32(void){uint32_t v;__asm__ volatile("csrr %0,mcycle":"=r"(v));return v;}
static __attribute__((unused)) void wait_for_device_irq(void){
  /* Avoid a lost wakeup if the handler sets irq_seen between a C load and
     the branch to WFI. With MIE cleared, WFI still resumes for an enabled
     pending interrupt; re-enabling MIE then services it architecturally. */
  for(;;){
    __asm__ volatile("csrci mstatus,8" ::: "memory");
    if(irq_seen){__asm__ volatile("csrsi mstatus,8" ::: "memory");break;}
    __asm__ volatile("wfi" ::: "memory");
    __asm__ volatile("csrsi mstatus,8" ::: "memory");
    if(irq_seen)break;
  }
}
#ifdef TEST_M_DEPENDENCY
#ifdef TEST_LIVE_M_OPCODE
static __attribute__((noinline)) uint32_t live_opcode_probe(void){
  uint32_t result;
  const uint32_t a=0xfffedcbbu,b=0x23457u;
#if TEST_LIVE_M_OPCODE == 0
  __asm__ volatile("mul %0,%1,%2":"=r"(result):"r"(a),"r"(b));
  return result==0x7de8ff8du;
#elif TEST_LIVE_M_OPCODE == 1
  __asm__ volatile("mulh %0,%1,%2":"=r"(result):"r"(a),"r"(b));
  return result==0xfffffffdu;
#elif TEST_LIVE_M_OPCODE == 2
  __asm__ volatile("mulhsu %0,%1,%2":"=r"(result):"r"(a),"r"(b));
  return result==0xfffffffdu;
#elif TEST_LIVE_M_OPCODE == 3
  __asm__ volatile("mulhu %0,%1,%2":"=r"(result):"r"(a),"r"(b));
  return result==0x23454u;
#elif TEST_LIVE_M_OPCODE == 4
  __asm__ volatile("div %0,%1,%2":"=r"(result):"r"(a),"r"(b));
  return result==0u;
#elif TEST_LIVE_M_OPCODE == 5
  __asm__ volatile("divu %0,%1,%2":"=r"(result):"r"(a),"r"(b));
  return result==0x7420u;
#elif TEST_LIVE_M_OPCODE == 6
  __asm__ volatile("rem %0,%1,%2":"=r"(result):"r"(a),"r"(b));
  return result==a;
#else
  __asm__ volatile("remu %0,%1,%2":"=r"(result):"r"(a),"r"(b));
  return result==0xe5dbu;
#endif
}
#endif
// Keep an architectural M dependency in the firmware path.  It is deliberately
// runtime-valued and noinline so retirement traces, rather than ELF metadata,
// prove that the RV32IM integration actually exercised MUL and DIV.
static __attribute__((noinline)) uint32_t m_dependency_probe(uint32_t lhs,uint32_t rhs){
  uint32_t product,quotient;
  __asm__ volatile("mul %0,%1,%2":"=r"(product):"r"(lhs),"r"(rhs));
  __asm__ volatile("div %0,%1,%2":"=r"(quotient):"r"(product),"r"(rhs));
  return quotient;
}
/* Hand-authored RV32M operations provide a second construction path beside
   the generated streams. The fixed operands make all eight architectural
   results independently checkable while DMA remains active. */
static __attribute__((noinline)) uint32_t m_all_opcode_probe(void){
  const uint32_t a=(uint32_t)-0x12345;
  const uint32_t b=0x23457u;
  uint32_t mul,mulh,mulhsu,mulhu,div,divu,rem,remu;
  __asm__ volatile(
    "mul   %0,%8,%9\n"
    "mulh  %1,%8,%9\n"
    "mulhsu %2,%8,%9\n"
    "mulhu %3,%8,%9\n"
    "div   %4,%8,%9\n"
    "divu  %5,%8,%9\n"
    "rem   %6,%8,%9\n"
    "remu  %7,%8,%9\n"
    : "=&r"(mul),"=&r"(mulh),"=&r"(mulhsu),"=&r"(mulhu),
      "=&r"(div),"=&r"(divu),"=&r"(rem),"=&r"(remu)
    : "r"(a),"r"(b));
  return mul==0x7de8ff8du && mulh==0xfffffffdu &&
         mulhsu==0xfffffffdu && mulhu==0x00023454u && div==0u &&
         divu==0x00007420u && rem==0xfffedcbbu && remu==0x0000e5dbu;
}
#endif
void __attribute__((interrupt("machine"))) trap_handler(void){
  trap_seen++;
#ifdef TEST_STATEFUL_CASE
  uint32_t stateful_cause;__asm__ volatile("csrr %0,mcause":"=r"(stateful_cause));
  stateful_trap(stateful_cause);return;
#endif
#ifdef TEST_ACCESS_LEGALITY
  uint32_t access_cause;
  __asm__ volatile("csrr %0,mcause":"=r"(access_cause));
  access_trap_causes=(access_trap_causes<<4)|(access_cause&15u);
#endif
#ifdef TEST_TIMER_DEVICE_PRIORITY
  uint32_t cause;
  __asm__ volatile("csrr %0,mcause":"=r"(cause));
  interrupt_order=(interrupt_order<<4)|(cause&15u);
  if(cause==0x80000007u){
    MMIO(0x4000230cu)=0xffffffffu;MMIO(0x40002308u)=0xffffffffu;
    timer_seen++;
    return;
  }
#endif
#if defined(TEST_REFERENCED_BANK) || defined(TEST_MAINT_ERROR_RECOVERY) || defined(TEST_ACCESS_LEGALITY) || defined(TEST_REGION_BOUNDARIES) || TEST_COVERAGE_EDGES
  /* These selected APB failures are intentional probes. Advance past each
     faulting instruction so the independent result checks can complete. */
  uint32_t fault_pc;
  uint32_t fault_cause;__asm__ volatile("csrr %0,mcause":"=r"(fault_cause));
  if((fault_cause&0x80000000u)==0u){
    __asm__ volatile("csrr %0,mepc" : "=r"(fault_pc));
    fault_pc += 4u;
    __asm__ volatile("csrw mepc,%0" :: "r"(fault_pc));
  }
#endif
#if TEST_IRQ
#ifdef TEST_IRQ_BOTH_SOURCES
  if((MMIO(0x40002000u)&1u)!=0u){
    chip_irq_status=CHIP(0x3c);chip_irq_words=CHIP(0x40);
    CHIP(0x44)=1;CHIP(0x1c)=1;chip_irq_seen=1;
  }
#endif
  irq_completion=DMA(32);irq_tag=DMA(40)&255u;DMA(44)=1;MMIO(0x4000200cu)=2;irq_seen=1;
#ifdef TEST_IRQ_BOTH_SOURCES
  MMIO(0x4000200cu)=3;
#endif
#endif
}
static void cfg(uint32_t kind,uint32_t out,uint32_t index,uint32_t data){CFG(0)=kind;CFG(4)=out;CFG(8)=index;CFG(12)=data;CFG(20)=1;}
#if defined(TEST_ASID_ISOLATION) || defined(TEST_REMAP_INVALIDATION)
static uint32_t asid_job(uint32_t tag,uint32_t asid){
  DMA(16)=(7u<<17)|(asid<<8)|tag;DMA(24)=1;
  while((DMA(28)&4u)==0u){}
  uint32_t c=DMA(32),observed_tag=DMA(40)&255u;
  uint32_t pass=(c&15u)==0u&&((c>>4)&255u)==asid&&
                ((c>>12)&127u)==1u&&observed_tag==tag;
  DMA(44)=1;
  return pass;
}
#endif
#ifdef TEST_CACHED_PERMISSION_TRANSITIONS
static uint32_t permission_job(uint32_t tag,uint32_t input,uint32_t output,uint32_t status){
  DMA(0)=input;DMA(4)=output;DMA(8)=(4u<<16)|64u;DMA(12)=(1u<<7)|4u;
  DMA(16)=(7u<<17)|(TEST_ASID<<8)|tag;DMA(20)=TEST_QOS;DMA(24)=1;
  while((DMA(28)&4u)==0u){}
  uint32_t result=DMA(32),observed_tag=DMA(40)&255u;
  uint32_t pass=(result&15u)==status&&observed_tag==tag&&
                ((result>>12)&127u)==(status==0u?1u:0u);
  DMA(44)=1;
  return pass;
}
static void permission_invalidate(void){
  MMIO(0x40002200u)=(TEST_ASID<<8)|1u;
  while((MMIO(0x40002204u)&1u)!=0u){}
}
#endif
#ifdef TEST_STATEFUL_CASE
#include "stateful_sequences.h"
#endif
int main(void){
#ifdef TEST_STATEFUL_CASE
  {uintptr_t handler=(uintptr_t)trap_handler;__asm__ volatile("csrw mtvec,%0"::"r"(handler));}
#endif
#ifdef TEST_MAINT_ERROR_RECOVERY
  {uintptr_t v=(uintptr_t)trap_handler;__asm__ volatile("csrw mtvec,%0"::"r"(v));}
#endif
#if TEST_COVERAGE_EDGES
  {uintptr_t v=(uintptr_t)trap_handler;__asm__ volatile("csrw mtvec,%0"::"r"(v));}
  (void)MMIO(0x40002000u); /* IRQ raw status */
  (void)MMIO(0x40002004u); /* IRQ pending status */
  (void)MMIO(0x4000200cu); /* IRQ acknowledgement register read path */
  (void)CFG(16);           /* configuration generation */
  (void)MMIO(0x40002300u); /* mtime */
  (void)MMIO(0x40002304u); /* mtime high */
  (void)MMIO(0x40002308u); /* mtimecmp */
  (void)MMIO(0x40002108u); /* maintenance status */
  (void)MMIO(0x40002030u); /* invalid IRQ offset: precise trap */
  (void)CFG(0x34u);         /* invalid config read: precise trap */
  CFG(0x34u)=0x12345678u;  /* invalid config write: no CSR mutation */
  (void)DMA(0x34u);         /* invalid DMA read: precise trap */
  DMA(0x34u)=0x87654321u;  /* invalid DMA write: no CSR mutation */
  MMIO(0x4000210cu)=0u;    /* invalid maintenance offset: precise trap */
  (void)MMIO(0x40002310u); /* timer range error: precise trap */
#endif
  uint32_t benchmark_start=cycle32();
  volatile uint32_t overlap_ok=1;
#ifdef TEST_REGION_BOUNDARIES
  {uintptr_t handler=(uintptr_t)trap_handler;
   __asm__ volatile("csrw mtvec,%0"::"r"(handler));}
  const uint32_t edges[]={0x10000000u,0x1000fffcu,0x30000000u,0x3000fffcu};
  for(uint32_t i=0;i<4;i++){
    uint32_t value=0x619ac357u^edges[i];
    MMIO(edges[i])=value;
    if(MMIO(edges[i])!=value)overlap_ok=0;
  }
  (void)MMIO(0x10010000u);MMIO(0x10010000u)=0xdeadbeefu;
  (void)MMIO(0x20010000u);MMIO(0x20010000u)=0xdeadbeefu;
  (void)MMIO(0x20000000u);(void)MMIO(0x2000fffcu);
  if(trap_seen!=6u)overlap_ok=0;
#endif
#ifdef TEST_ACCESS_LEGALITY
  {uintptr_t handler=(uintptr_t)trap_handler;
   __asm__ volatile("csrw mtvec,%0"::"r"(handler));}
  /* Assembly preserves the exact access widths and avoids undefined C
     misaligned dereferences. Trapping loads must leave the sentinel intact. */
  uint32_t probe=0x619ac357u, address=INPUT_PA;
  __asm__ volatile("lb %0,0(%1)":"+r"(probe):"r"(address):"memory");
  if(probe!=0x619ac357u)overlap_ok=0;
  __asm__ volatile("sb %0,0(%1)"::"r"(probe),"r"(address):"memory");
  address=INPUT_PA+1u;
  __asm__ volatile("lw %0,0(%1)":"+r"(probe):"r"(address):"memory");
  if(probe!=0x619ac357u)overlap_ok=0;
  __asm__ volatile("sw %0,0(%1)"::"r"(probe),"r"(address):"memory");
  if(trap_seen!=4u||access_trap_causes!=0x5746u)overlap_ok=0;
#endif
#if defined(TEST_M_DEPENDENCY) && !TEST_IRQ
  volatile uint32_t m_lhs=19u,m_rhs=7u;
  if(m_dependency_probe(m_lhs,m_rhs)!=19u)return 1;
#endif
  volatile uint32_t arithmetic_seed=TEST_K+TEST_BATCH+TEST_ASID;
  uint32_t arithmetic_check=(arithmetic_seed*7u)/(TEST_BATCH?TEST_BATCH:1u);
  if(arithmetic_check==0xffffffffu)return 1;
  MMIO(0x30000800u)=0x0c000401u;
  MMIO(0x30001004u)=0x040004cfu;
  MMIO(0x30001010u)=0x040010cfu;
#if defined(TEST_ASID_ISOLATION) || defined(TEST_REMAP_INVALIDATION)
  MMIO(0x10002000u)=0x02020202u;
#endif
#ifdef TEST_CACHED_PERMISSION_TRANSITIONS
  MMIO(0x30001018u)=0x040018cfu;MMIO(0x10006000u)=0u;
#endif
#ifdef TEST_INPUT_PTE_FAULT
  MMIO(0x30001004u)=0u;
#endif
#ifdef TEST_READ_PERMISSION_DENIAL
  /* Valid execute-only leaf: read denied, not an invalid/missing mapping. */
  MMIO(0x30001004u)=0x040004c9u;
#endif
#ifdef TEST_INPUT_BUS_ERROR
  /* Keep translation legal but route payload reads to the error target. */
  MMIO(0x30001004u)=0x080004cfu;
#endif
#ifdef TEST_OUTPUT_PTE_FAULT
  MMIO(0x30001010u)=0u;
#endif
#ifdef TEST_OUTPUT_PERMISSION_FAULT
  /* Valid/readable leaf with write permission deliberately removed. */
  MMIO(0x30001010u)=0x040010c3u;
#endif
#ifdef TEST_WRITE_PERMISSION_DENIAL
  MMIO(0x30001010u)=0x040010c3u;
#endif
#ifdef TEST_PARTIAL_OUTPUT_RETRY
  /* Vector zero remains writable; vector one maps to the error target. */
  MMIO(0x30001014u)=0x080000cfu;
#endif
  for(uint32_t v=0;v<TEST_BATCH;v++){
    for(uint32_t i=0;i<TEST_K;i+=4)MMIO(INPUT_PA+v*64u+i)=0x01010101u;
#ifdef TEST_PARTIAL_OUTPUT_RETRY
    MMIO(v ? 0x10008000u : 0x10004000u)=0;
#else
    MMIO(OUTPUT_PA+v*4u)=0;
#endif
  }
#ifdef TEST_COMPLETION_PUBLISH_POP
  MMIO(0x10004004u)=0;
#endif
#ifdef TEST_UNRELATED_ACCESS_DURING
  MMIO(0x10008000u)=0x5a5aa5a5u;
#endif
#ifdef TEST_CACHE_BOUNDARY
  /* Padding belongs to the same cache lines as the input/output allocation.
     Preserve these words across cleaning, DMA, and invalidation. */
  MMIO(INPUT_PA-4u)=0x62f19a37u;MMIO(OUTPUT_PA-4u)=0x85c3d2e1u;
#endif
  for(uint32_t o=0;o<4;o++){for(uint32_t i=0;i<TEST_K;i++)cfg(0,o,i,1);cfg(1,o,0,0);cfg(2,o,0,1);cfg(3,o,0,0);}
  CFG(16)=7;
#ifdef TEST_COMBINED_HOST
  for(volatile uint32_t wake=0;wake<64;wake++)__asm__ volatile("nop");
  for(uint32_t i=0;i<CHIPLET_WORDS;i++){
    CHIP(0x20)=32u+i;CHIP(0x24)=1;
    CHIP(0x28)=0xaaaa0000u+i;CHIP(0x2c)=0x55550000u+i;CHIP(0x58)=3;
    for(volatile uint32_t settle=0;settle<8;settle++)__asm__ volatile("nop");
  }
  for(uint32_t i=0;i<
#ifdef TEST_CHIPLET_PARITY_FAULT
      8u
#else
      4u
#endif
      ;i++){
    CHIP(0x20)=i;CHIP(0x24)=0;
#if defined(TEST_STATEFUL_CASE) && (TEST_STATEFUL_CASE == 51 || TEST_STATEFUL_CASE == 88 || TEST_STATEFUL_CASE == 92)
    CHIP(0x28)=(i&1u)?0xffffffffu:0u;
    CHIP(0x2c)=(i&2u)?0x7ffffffeu:0x80000001u;
#else
    CHIP(0x28)=0x11111111u+i;CHIP(0x2c)=0x22222222u+i;
#endif
    CHIP(0x58)=3;
    for(volatile uint32_t settle=0;settle<8;settle++)__asm__ volatile("nop");
  }
#ifdef TEST_CHIPLET_PARITY_FAULT
  CHIP(0x7c)=4u;
  CHIP(0x80)=5u; /* Fault the first word of the second complete FLIT. */
  /* The injection-done bit is a one-cycle pulse. APB polling can miss it;
     wait past the bounded local injection operation and check rejection. */
  for(volatile uint32_t inject_wait=0;inject_wait<8;inject_wait++)__asm__ volatile("nop");
  if((CHIP(0x84)&4u)!=0u)return 1;
#endif
  CHIP(0x08)=0;CHIP(0x0c)=32;
#if defined(TEST_CHIPLET_SLEEP_DURING) || defined(TEST_CHIPLET_PARITY_FAULT)
  CHIP(0x10)=8;
#else
  CHIP(0x10)=4;
#endif
  CHIP(0x14)=0x123;
#ifdef TEST_IRQ_BOTH_SOURCES
  CHIP(0x18)=1;
#endif
#endif
#ifdef TEST_WARM
  benchmark_start=cycle32();
#endif
#if !defined(NEG_SKIP_FLUSH)
  if(TEST_CACHE){
    MMIO(0x40002100u)=0;MMIO(0x40002104u)=1;
#ifdef TEST_MAINT_ERROR_RECOVERY
    if(trap_seen!=1u||(MMIO(0x40002108u)&4u)==0u)overlap_ok=0;
    MMIO(0x40002104u)=1;
    if((MMIO(0x40002108u)&4u)!=0u)overlap_ok=0;
#endif
    __asm__ volatile("fence");
  }
#endif
  DMA(0)=INPUT_IOVA;DMA(4)=OUTPUT_IOVA;
#ifdef TEST_PARTIAL_OUTPUT_RETRY
  DMA(8)=(4096u<<16)|64u;
#else
  DMA(8)=(4u<<16)|64u;
#endif
#if TEST_SCENARIO_ID == 2
  intent_m_descriptor((TEST_BATCH<<7)|TEST_K);
#else
  DMA(12)=(TEST_BATCH<<7)|
#ifdef TEST_COMPLETION_PUBLISH_POP
      4u;
#else
      TEST_K;
#endif
#endif
#ifdef TEST_REFERENCED_BANK
  {uintptr_t v=(uintptr_t)trap_handler;__asm__ volatile("csrw mtvec,%0"::"r"(v));}
#endif
  if(TEST_IRQ){uintptr_t v=(uintptr_t)trap_handler;__asm__ volatile("csrw mtvec,%0"::"r"(v));
#if !defined(TEST_IRQ_PENDING_ENABLE) && !defined(TEST_IRQ_BOTH_SOURCES)
    MMIO(0x40002008u)=2;
#endif
    __asm__ volatile("li t0,0x800; csrs mie,t0":::"t0");
#if !defined(TEST_TIMER_DEVICE_PRIORITY) && !defined(TEST_IRQ_BOTH_SOURCES)
    __asm__ volatile("csrsi mstatus,8");
#endif
  }
#ifdef TEST_RESET_COMPLETION_IRQ
  MMIO(0x40002008u)=2u;
#endif
#if defined(TEST_STATEFUL_CASE) && TEST_STATEFUL_CASE == 83
  MMIO(0x1000c000u)=13u;
#endif
DMA(16)=(7u<<17)|(TEST_ASID<<8)|0x35u;DMA(20)=TEST_QOS;DMA(24)=1;
#ifdef TEST_STATEFUL_CASE
  stateful_after_submit(&overlap_ok);
#endif
#if defined(TEST_M_SWEEP) && (TEST_M_SWEEP_CONTEXT == 0 || TEST_M_SWEEP_CONTEXT == 4)
  if(!m_sweep_probe())overlap_ok=0;
#endif
#ifdef TEST_IRQ_WFI
  wait_for_device_irq();
#endif
#ifdef TEST_REFERENCED_BANK
  /* Probe while the first descriptor still owns the programmed generation. */
  CFG(16)=8;
#endif
#ifdef TEST_INACTIVE_BANK_ROLLOVER
  /* Atomic generation writes must preserve bank 0's live generation while
     allowing the unreferenced byte to wrap from 255 to zero. */
  CFG(16)=0xff07u;
  if(CFG(16)!=0xff07u)overlap_ok=0;
  CFG(0)=0;CFG(4)=4;CFG(8)=0;CFG(12)=0x5au;CFG(20)=1;
  CFG(16)=0x0007u;
  if(CFG(16)!=0x0007u)overlap_ok=0;
#endif
#if TEST_SCENARIO_ID == 8
  /* A real host-side read of initialized page-table SRAM exercises the read
     direction of the APB-to-AXI bridge while the accelerator is active. */
  if (MMIO(0x30000800u) != 0x0c000401u) overlap_ok=0;
#endif
#if TEST_SCENARIO_ID == 5 && defined(TEST_M_DEPENDENCY)
  /* Start the long-latency DIV near the completion window. K=4 on this row
     makes the device interrupt arrive during, rather than before, the op. */
  if (!intent_irq_divide()) overlap_ok=0;
#endif
#ifdef TEST_IRQ_DELAY_M
  if(!intent_irq_divide())overlap_ok=0;
#endif
#if TEST_SCENARIO_ID != 0 && !defined(TEST_COMBINED_HOST)
  /* Execute the row's generated test program after the descriptor doorbell.
     Its unique local-RAM read/modify/write signature is checked against its
     generated source and the family-specific integration witness. */
#if TEST_IRQ && TEST_SCENARIO_ID != 5 && !defined(TEST_TIMER_DEVICE_PRIORITY)
  /* Keep the independent per-row instruction witness atomic with respect to
     the device IRQ; the pending event is serviced immediately after it. */
  __asm__ volatile("csrci mstatus,8" ::: "memory");
#endif
  scenario_activation = crossover_scenario_program();
#if TEST_IRQ && TEST_SCENARIO_ID != 5 && !defined(TEST_TIMER_DEVICE_PRIORITY)
  __asm__ volatile("csrsi mstatus,8" ::: "memory");
#endif
  if (scenario_activation != (0x43520000u | TEST_SCENARIO_ID)) overlap_ok=0;
#endif
#ifdef TEST_IRQ_PENDING_ENABLE
  while((DMA(28)&4u)==0u){}
  if((MMIO(0x40002000u)&2u)==0u || MMIO(0x40002004u)!=0u || irq_seen)overlap_ok=0;
  MMIO(0x40002008u)=2u;
#endif
#ifdef TEST_TIMER_DEVICE_PRIORITY
  while((DMA(28)&4u)==0u){}
  MMIO(0x4000230cu)=0u;MMIO(0x40002308u)=0u;
  uint32_t pending;
  __asm__ volatile("csrr %0,mip":"=r"(pending));
  if((pending&0x880u)!=0x880u)overlap_ok=0;
  __asm__ volatile("li t0,0x880; csrs mie,t0; csrsi mstatus,8":::"t0","memory");
#endif
#ifdef TEST_COMPLETION_PUBLISH_POP
  /* Queue a second independently tagged descriptor so the first completion
     can be consumed while the second reaches completion publication. */
#ifdef TEST_COMPLETION_PUBLISH_POP_ALT
  /* Alternate legal CSR staging order: payload fields are written in reverse
     order, but the doorbell remains the commit point for the descriptor. */
  DMA(16)=(7u<<17)|(TEST_ASID<<8)|0x36u;
  DMA(12)=(1u<<7)|TEST_K;
  DMA(8)=(4u<<16)|64u;
  DMA(4)=0x80004004u;DMA(0)=0x80001000u;
  DMA(20)=TEST_QOS;DMA(24)=1;
#else
  DMA(0)=0x80001000u;DMA(4)=0x80004004u;
  DMA(8)=(4u<<16)|64u;DMA(12)=(1u<<7)|TEST_K;
  DMA(16)=(7u<<17)|(TEST_ASID<<8)|0x36u;DMA(20)=TEST_QOS;DMA(24)=1;
#endif
#endif
#ifdef TEST_COMPLETION_FIFO_PRESSURE
  /* Publish four unread completions, then leave a fifth job stalled at
     retirement. Distinct tags keep tag-rejection separate from FIFO pressure. */
  for(uint32_t job=1;job<5;job++){
    while(((DMA(28)>>7)&7u)<job){}
    DMA(16)=(7u<<17)|(TEST_ASID<<8)|(0x35u+job);DMA(24)=1;
  }
  for(volatile uint32_t hold=0;hold<1024;hold++)__asm__ volatile("nop");
#if defined(TEST_M_SWEEP) && TEST_M_SWEEP_CONTEXT == 3
  if(!m_sweep_probe())overlap_ok=0;
#endif
#ifdef TEST_M_DEPENDENCY
  if(!m_all_opcode_probe())overlap_ok=0;
#endif
  uint32_t pressure_front=DMA(32),pressure_tag=DMA(40);
  for(uint32_t repeat=0;repeat<8;repeat++){
    uint32_t state=DMA(28);
    if(((state>>7)&7u)!=4u || (state&2u)==0u ||
       DMA(32)!=pressure_front || DMA(40)!=pressure_tag)overlap_ok=0;
  }
#endif
#ifdef TEST_SUBMIT_FIFO_PRESSURE
  while((DMA(28)&2u)==0u){}
  for(uint32_t job=1;job<5;job++){
    DMA(16)=(7u<<17)|(TEST_ASID<<8)|(0x35u+job);DMA(24)=1;
  }
  uint32_t full_submit=DMA(28);
  if(((full_submit>>4)&7u)!=4u || (full_submit&1u)!=0u)overlap_ok=0;
  DMA(16)=(7u<<17)|(TEST_ASID<<8)|0x3au;DMA(24)=1;
  if((DMA(28)&8u)==0u)overlap_ok=0;
#endif
#ifdef TEST_DUPLICATE_TAG
  /* A duplicate live tag is rejected as an APB store fault. The machine
     doorbell itself is accepted; firmware observes the sticky rejection
     bit in the DMA status register while the original work remains live. */
  DMA(24)=1;
  if((DMA(28)&8u)==0u)overlap_ok=0;
#endif
#ifdef TEST_DUPLICATE_UNREAD_TAG
  /* Hardware execution has ended, but the unread FIFO record still owns
     its software tag. Do not consume it before attempting the duplicate. */
  while((DMA(28)&4u)==0u){}
  if((DMA(40)&255u)!=0x35u)overlap_ok=0;
  DMA(24)=1;
  if((DMA(28)&8u)==0u || (DMA(40)&255u)!=0x35u)overlap_ok=0;
#endif
#ifdef TEST_CPU_STREAM
  /* The generated I/M stream executes after the descriptor is accepted so
     every retirement is checked inside a real DMA lifetime. */
  cpu_stream_signature=generated_cpu_stream_abi_probe();
  if(cpu_stream_signature!=1u)overlap_ok=0;
#endif
#ifdef TEST_UNRELATED_ACCESS_DURING
  /* This shared-memory line is deliberately outside both descriptor spans.
     A correct ownership checker permits it while the DMA owns its buffers. */
  if(MMIO(0x10008000u)!=0x5a5aa5a5u)overlap_ok=0;
#endif
#ifdef TEST_COMBINED_HOST
  /* Align AES with the first accelerator command: longer K values spend more
     time in the DMA read phase after the doorbell. */
  if(TEST_K>4)__asm__ volatile(".rept 7\n nop\n .endr" ::: "memory");
CHIP(0x00)=1;
#if defined(TEST_M_SWEEP) && TEST_M_SWEEP_CONTEXT == 1
  if(!m_sweep_probe())overlap_ok=0;
#endif
#ifdef TEST_LIVE_M_OPCODE
  if(!live_opcode_probe())overlap_ok=0;
#endif
#if TEST_SCENARIO_ID != 0
  /* Combined-service rows launch the scenario microprogram after AES starts,
     preserving the alignment window while still exercising RV32 during the
     actual AES/INT8 overlap interval. */
  scenario_activation = crossover_scenario_program();
  if (scenario_activation != (0x43520000u | TEST_SCENARIO_ID)) overlap_ok=0;
#endif
#ifdef TEST_CHIPLET_SLEEP_DURING
  /* Exercise the integrated chiplet's real SLEEP path while its AES DMA is
     in flight, then resume before firmware checks the returned data. */
  CHIP(0xf0)=2;
#if defined(TEST_STATEFUL_CASE) && (TEST_STATEFUL_CASE == 51 || TEST_STATEFUL_CASE == 88)
  if(!stateful_m())overlap_ok=0;
#endif
#if defined(TEST_M_SWEEP) && TEST_M_SWEEP_CONTEXT == 2
  if(!m_sweep_probe())overlap_ok=0;
#endif
#ifdef TEST_LIVE_M_POWER
  if(!m_all_opcode_probe())overlap_ok=0;
#endif
  for(volatile uint32_t sleep_wait=0;sleep_wait<
#if defined(TEST_STATEFUL_CASE) && TEST_STATEFUL_CASE == 88
      128u
#else
      24u
#endif
      ;sleep_wait++)__asm__ volatile("nop");
#if TEST_STATEFUL_CASE == 92
  for(uint32_t job=0;job<4;job++)
    stateful_stage(0xe8u+job,INPUT_IOVA,OUTPUT_IOVA+128u+job*32u,TEST_K,1,TEST_K,0);
  while(((DMA(28)>>7)&7u)!=4u){}
  for(uint32_t probe=0;probe<16;probe++)if(!stateful_m())overlap_ok=0;
#endif
  CHIP(0xf0)=0;
#endif
#endif
#ifdef TEST_M_DEPENDENCY
#ifdef TEST_LIVE_M_IRQ
  while(!irq_seen){
    if(m_dependency_probe(93u,3u)!=93u)overlap_ok=0;
  }
#endif
  #if TEST_SCENARIO_ID == 1
  if(!intent_m_address())overlap_ok=0;
  #elif TEST_SCENARIO_ID == 3
  if(!intent_load_m_store())overlap_ok=0;
  #elif TEST_SCENARIO_ID == 4
  if(!intent_m_branch())overlap_ok=0;
  #elif TEST_SCENARIO_ID == 5
  /* The DIV probe ran immediately after doorbell above, for IRQ phasing. */
  #endif
  if(!m_all_opcode_probe())overlap_ok=0;
  /* Exercise RV32M while the accepted descriptor is alive, not only in the
     preamble.  The observer/coverage lane requires this real overlap window. */
  for (volatile uint32_t m_iter = 0; m_iter < 4; m_iter++) {
    if (m_dependency_probe(31u + m_iter, 3u) != (31u + m_iter)) overlap_ok = 0;
  }
#endif
#ifdef TEST_IRQ_BOTH_SOURCES
  while((MMIO(0x40002000u)&3u)!=3u){}
  MMIO(0x40002008u)=3u;
  __asm__ volatile("csrsi mstatus,8" ::: "memory");
#endif
#ifdef NEG_ACCESS_DURING
  (void)MMIO(INPUT_PA
#ifdef TEST_CACHE_BOUNDARY
             -4u
#endif
             );
#endif
#ifdef TEST_LIVE_M_IRQ
  while(!irq_seen){
    if(m_dependency_probe(93u,3u)!=93u)overlap_ok=0;
  }
#endif
  if(TEST_IRQ){wait_for_device_irq();}else while((DMA(28)&4u)==0u){}
#ifdef TEST_TIMER_DEVICE_PRIORITY
  while(!timer_seen){}
  if(timer_seen!=1u||interrupt_order!=0xb7u)overlap_ok=0;
#endif
#ifdef TEST_IRQ_ACK_COLLISION
  /* The reactive CSR waits until the second real completion publication.
     A new pending event must survive the acknowledgement on that edge. */
  MMIO(0x4000200cu)=2u;
  if((MMIO(0x40002000u)&2u)==0u)overlap_ok=0;
#endif
#if TEST_STATEFUL_CASE == 91
  if(DMA(36)!=0u)overlap_ok=0;
#endif
  uint32_t c=TEST_IRQ?irq_completion:DMA(32),tag=TEST_IRQ?irq_tag:
#ifdef TEST_COMPLETION_PUBLISH_POP
      0x35u,
#else
      (DMA(40)&255u),
#endif
      ok=overlap_ok&&((c&15u)==0u)&&(((c>>12)&127u)==TEST_BATCH)&&(tag==0x35u);
#ifdef TEST_ASID_ISOLATION
  DMA(44)=1;
  MMIO(0x30001004u)=0x040008cfu;
  /* ASID 2 must walk the new PTE rather than borrowing ASID 1's entry. */
  ok=asid_job(0x36u,2u)&&ok;
  if(MMIO(OUTPUT_PA)!=0x08080808u)ok=0;
  /* Without invalidation, ASID 1 retains its original physical mapping. */
  ok=asid_job(0x37u,1u)&&ok;
  if(MMIO(OUTPUT_PA)!=0x04040404u)ok=0;
#endif
#ifdef TEST_REMAP_INVALIDATION
  DMA(44)=1;
  MMIO(0x30001004u)=0x040008cfu;
  ok=asid_job(0x36u,1u)&&ok;
  if(MMIO(OUTPUT_PA)!=0x04040404u)ok=0;
  MMIO(0x40002200u)=0x101u;
  while((MMIO(0x40002204u)&1u)!=0u){}
  ok=asid_job(0x37u,1u)&&ok;
  if(MMIO(OUTPUT_PA)!=0x08080808u)ok=0;
  MMIO(0x30001004u)=0x040004cfu;
  ok=asid_job(0x38u,1u)&&ok;
  if(MMIO(OUTPUT_PA)!=0x08080808u)ok=0;
  MMIO(0x40002200u)=3u;
  while((MMIO(0x40002204u)&1u)!=0u){}
  ok=asid_job(0x39u,1u)&&ok;
  if(MMIO(OUTPUT_PA)!=0x04040404u)ok=0;
#endif
#ifdef TEST_CACHED_PERMISSION_TRANSITIONS
  DMA(44)=1;
  MMIO(0x30001010u)=0x040010c3u;
  /* Warm writable TLB state stays writable until invalidation. */
  ok=permission_job(0x36u,INPUT_IOVA,OUTPUT_IOVA,0u)&&ok;
  permission_invalidate();
  /* Read through the readonly leaf to install a cached permission denial. */
  ok=permission_job(0x37u,OUTPUT_IOVA,0x80006000u,0u)&&ok;
  if(MMIO(0x10006000u)!=0x10101010u)ok=0;
  ok=permission_job(0x38u,INPUT_IOVA,OUTPUT_IOVA,3u)&&ok;
  if(MMIO(OUTPUT_PA)!=0x04040404u)ok=0;
  MMIO(0x30001010u)=0x040010cfu;
  /* Updating SRAM is insufficient: a cached readonly entry still denies. */
  ok=permission_job(0x39u,INPUT_IOVA,OUTPUT_IOVA,3u)&&ok;
  permission_invalidate();
  ok=permission_job(0x3au,INPUT_IOVA,OUTPUT_IOVA,0u)&&ok;
#endif
#if defined(TEST_COMPLETION_FIFO_PRESSURE) || defined(TEST_SUBMIT_FIFO_PRESSURE)
  for(uint32_t job=0;job<5;job++){
    while((DMA(28)&4u)==0u){}
    uint32_t entry=DMA(32),entry_tag=DMA(40)&255u;
    if((entry&15u)!=0u||((entry>>12)&127u)!=1u||entry_tag!=0x35u+job)ok=0;
    DMA(44)=1;
  }
  if(((DMA(28)>>7)&7u)!=0u)ok=0;
#endif
#if TEST_COVERAGE_EDGES
  ok=ok&&(trap_seen==7u);
#endif
#ifdef TEST_COMPLETION_PUBLISH_POP
  /* Delay is in architectural NOPs, not simulator cycles. It aligns the
     second descriptor's measured publication with the first APB completion
     pop; the trace-derived cross checker remains the acceptance oracle. */
  for(uint32_t align=0;align<TEST_COMPLETION_POP_DELAY;align++)
    __asm__ volatile("nop" ::: "memory");
  DMA(44)=1;
  while((DMA(28)&4u)==0u){}
  uint32_t c2=DMA(32),tag2=DMA(40)&255u;
  ok=ok&&((c2&15u)==0u)&&(((c2>>12)&127u)==1u)&&(tag2==0x36u);
  DMA(44)=1;
  if(MMIO(0x10004004u)!=((TEST_K&255u)*0x01010101u))ok=0;
#ifdef TEST_IRQ_ACK_COLLISION
  MMIO(0x4000200cu)=2u;
#endif
#endif
#if defined(TEST_INPUT_PTE_FAULT) || defined(TEST_OUTPUT_PTE_FAULT) || defined(TEST_OUTPUT_PERMISSION_FAULT) || defined(TEST_INPUT_BUS_ERROR) || defined(TEST_READ_PERMISSION_DENIAL) || defined(TEST_WRITE_PERMISSION_DENIAL)
  ok=((c&15u)!=0u)&&(tag==0x35u);
#endif
#if defined(TEST_READ_PERMISSION_DENIAL) || defined(TEST_WRITE_PERMISSION_DENIAL)
  ok=ok&&((c&15u)==
#ifdef TEST_READ_PERMISSION_DENIAL
     2u)&&(((DMA(40)>>8)&7u)==1u)&&(DMA(36)==INPUT_IOVA)&&
#else
     3u)&&(((DMA(40)>>8)&7u)==3u)&&(DMA(36)==OUTPUT_IOVA)&&
#endif
     (((c>>12)&127u)==0u);
#endif
#ifdef TEST_INPUT_BUS_ERROR
  ok=ok&&((c&15u)==4u)&&(((c>>12)&127u)==0u)&&
     (DMA(36)==0x80001000u)&&(((DMA(40)>>8)&7u)==2u);
#endif
#ifdef TEST_PARTIAL_OUTPUT_RETRY
  /* The first vector committed before the second output translation fault. */
  ok=((c&15u)!=0u)&&(((c>>12)&127u)==1u)&&(tag==0x35u);
  DMA(44)=1;                         /* Completion consumption permits tag reuse. */
  MMIO(0x30001014u)=0x040020cfu;     /* Repair vector-one physical mapping. */
  MMIO(0x40002200u)=(TEST_ASID<<8)|1u; /* Targeted invalidate after the service drains. */
  while((MMIO(0x40002204u)&1u)!=0u){}
  DMA(24)=1;                         /* Same descriptor/tag is now a legal retry. */
  while((DMA(28)&4u)==0u){}
  c=DMA(32);tag=DMA(40)&255u;
  ok=ok&&((c&15u)==0u)&&(((c>>12)&127u)==TEST_BATCH)&&(tag==0x35u);
#endif
#ifdef NEG_LATE_DIRTY
  MMIO(0x10004000u)=0x99999999u;MMIO(0x40002100u)=0;MMIO(0x40002104u)=1;
#endif
#if !defined(NEG_SKIP_INVALIDATE)
  if(TEST_CACHE){MMIO(0x40002100u)=1;MMIO(0x40002104u)=1;__asm__ volatile("fence");}
#endif
  uint32_t expected=(TEST_K&255u)*0x01010101u;
  for(uint32_t v=0;v<TEST_BATCH;v++) {
#if defined(TEST_INPUT_PTE_FAULT) || defined(TEST_OUTPUT_PTE_FAULT) || defined(TEST_OUTPUT_PERMISSION_FAULT) || defined(TEST_INPUT_BUS_ERROR) || defined(TEST_READ_PERMISSION_DENIAL) || defined(TEST_WRITE_PERMISSION_DENIAL)
    if(MMIO(OUTPUT_PA+v*4u)!=0u)ok=0;
#else
#ifdef TEST_PARTIAL_OUTPUT_RETRY
    if(MMIO(v ? 0x10008000u : 0x10004000u)!=expected)ok=0;
#else
    if(MMIO(OUTPUT_PA+v*4u)!=
#ifdef TEST_COMPLETION_PUBLISH_POP
       (4u*0x01010101u)
#else
       expected
#endif
       )ok=0;
#endif
#endif
  }
#ifdef TEST_CACHE_BOUNDARY
  if(MMIO(INPUT_PA-4u)!=0x62f19a37u||MMIO(OUTPUT_PA-4u)!=0x85c3d2e1u)ok=0;
#endif
#ifdef TEST_COMBINED_HOST
#ifdef TEST_IRQ_BOTH_SOURCES
  if(!chip_irq_seen||(chip_irq_status&15u)!=0u||chip_irq_words!=CHIPLET_WORDS)ok=0;
#else
  while(CHIP(0x38)==0u){}
#ifdef TEST_CHIPLET_PARITY_FAULT
  /* The first FLIT may reach AES, but its return has not retired to the
     destination when the second FLIT's source parity check aborts DMA. */
  if((CHIP(0x3c)&15u)!=6u || CHIP(0x40)!=0u)ok=0;
#else
  if((CHIP(0x3c)&15u)!=0u||CHIP(0x40)!=(
#ifdef TEST_CHIPLET_SLEEP_DURING
      8u
#else
      4u
#endif
      ))ok=0;
#endif
  CHIP(0x44)=1;
#endif
  /* The DMA completion can precede the return-link monitor update by a few
     link pipeline cycles. Let the real return stream drain before reporting
     firmware completion; the observer checks the returned AES words. */
  for(volatile uint32_t drain=0;drain<128;drain++)__asm__ volatile("nop");
  /* Read actual destination SRAM through its maintenance port. The host
     checker independently compares these retirement values with AES. */
  for(uint32_t i=0;i<CHIPLET_WORDS;i++){
    CHIP(0x20)=32u+i;CHIP(0x24)=1;CHIP(0x58)=1;
    for(volatile uint32_t settle=0;settle<8;settle++)__asm__ volatile("nop");
    uint32_t low=CHIP(0x28),high=CHIP(0x2c);
#ifdef TEST_CHIPLET_PARITY_FAULT
    if(low!=0xaaaa0000u+i||high!=0x55550000u+i)ok=0;
#else
    (void)low;(void)high;
#endif
  }
#endif
#if !TEST_IRQ && !defined(TEST_COMPLETION_PUBLISH_POP) && !defined(TEST_COMPLETION_FIFO_PRESSURE) && !defined(TEST_SUBMIT_FIFO_PRESSURE) && !defined(TEST_CACHED_PERMISSION_TRANSITIONS) && !defined(TEST_ASID_ISOLATION) && !defined(TEST_REMAP_INVALIDATION)
  DMA(44)=1;
#endif
#ifdef TEST_STATEFUL_CASE
  stateful_tail(&ok);
#endif
  MMIO(0x40001fe0u)=cycle32()-benchmark_start;MMIO(0x40001ff0u)=ok?0x600d5000u:0xdead5000u;MMIO(0x40001ff4u)=1;
  for(;;)__asm__ volatile("nop");
}
