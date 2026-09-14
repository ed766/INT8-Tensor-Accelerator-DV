#include <stdint.h>
#include "protected_offload_address_map.h"

#define MMIO32(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define CSR(o) MMIO32(DMA_CSR_BASE + (o))
#ifndef WORKFLOW
#define WORKFLOW 0
#endif

enum { ST_OK=0, ST_XLATE_READ=2, ST_XLATE_WRITE=3, ST_MEM_READ=4, ST_MEM_WRITE=5 };

static void submit(uint32_t k,uint32_t batch,uint32_t asid,uint32_t qos) {
  CSR(0x000)=SHARED_IOVA_BASE+0x1000u;
  CSR(0x004)=SHARED_IOVA_BASE+0x4000u;
  CSR(0x008)=(4u<<16)|64u;
  CSR(0x00c)=(batch<<7)|k;
  CSR(0x010)=(7u<<17)|(asid<<8)|(0x35u+WORKFLOW);
  CSR(0x014)=qos;
  CSR(0x018)=1;
}

int main(void) {
  const uint32_t k_table[8]={4,8,16,32,64,16,32,8};
  const uint32_t batch_table[8]={1,2,4,8,1,16,2,4};
  const uint32_t asid_table[8]={1,1,17,17,127,127,255,255};
  uint32_t k=k_table[WORKFLOW&7],batch=batch_table[WORKFLOW&7];
  submit(k,batch,asid_table[WORKFLOW&7],(WORKFLOW*2u)&15u);
  while((CSR(0x01c)&0x4u)==0u) { __asm__ volatile("nop"); }
  uint32_t completion=CSR(0x020);
  uint32_t status=completion&15u;
  uint32_t vectors=(completion>>12)&127u;
  uint32_t tag=CSR(0x028)&255u;
  uint32_t result=(status==ST_OK&&vectors==batch&&tag==(0x35u+WORKFLOW))?0x600d0000u|WORKFLOW:0xdead0000u|status;
  CSR(0x02c)=1;
  MMIO32(RESULT_MAILBOX_BASE)=result;
  MMIO32(RESULT_MAILBOX_BASE+4u)=1;
  for(;;) __asm__ volatile("nop");
}
