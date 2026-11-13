/* Verification firmware sequences. Shared data/configuration use real MMIO. */
static volatile uint32_t stateful_faults, stateful_irq_sources;

static void stateful_timer_clear(void){
  MMIO(0x4000230cu)=0xffffffffu;MMIO(0x40002308u)=0xffffffffu;
}

static void stateful_trap(uint32_t cause){
  if(cause==0x80000007u){
#if TEST_STATEFUL_CASE == 83
    uint32_t value,address=0x1000c000u;
#ifdef TEST_HANDLER_OWNED_LINE
    address=0x10001000u;
#endif
    __asm__ volatile("lw %0,0(%1)\n mul %0,%0,%2\n sw %0,4(%1)"
        :"=&r"(value):"r"(address),"r"(3u):"memory");
    if(value!=39u)stateful_faults++;
#endif
    stateful_timer_clear();timer_seen++;return;
  }
  if(cause==0x8000000bu){
    uint32_t raw=MMIO(0x40002000u);
    stateful_irq_sources|=raw;
    if(raw&1u){chip_irq_status=CHIP(0x3c);chip_irq_words=CHIP(0x40);CHIP(0x44)=1;CHIP(0x1c)=1;chip_irq_seen=1;}
    if((raw&2u)&&(DMA(28)&4u)){irq_completion=DMA(32);irq_tag=DMA(40)&255u;DMA(44)=1;irq_seen=1;}
    MMIO(0x4000200cu)=raw;
    return;
  }
  if(cause==5u||cause==7u){
    uint32_t pc;__asm__ volatile("csrr %0,mepc":"=r"(pc));
    pc+=4u;__asm__ volatile("csrw mepc,%0"::"r"(pc));stateful_faults++;return;
  }
  MMIO(0x40001ff0u)=0xdead5100u|cause;MMIO(0x40001ff4u)=1;
  for(;;)__asm__ volatile("nop");
}

static uint32_t stateful_m(void){
  uint32_t result, lhs=0xfffedcbbu,rhs=0x23457u;
  __asm__ volatile("div %0,%1,%2":"=r"(result):"r"(lhs),"r"(rhs));
  return result==0u;
}

static uint32_t stateful_m_matrix(void){
  uint32_t a=0xfffffff9u,b=3u,result,ok=1;
#define CHECK_M(op,expected) do{__asm__ volatile(op " %0,%1,%2":"=r"(result):"r"(a),"r"(b));if(result!=(expected))ok=0;}while(0)
  CHECK_M("mul",0xffffffebu);CHECK_M("mulh",0xffffffffu);
  CHECK_M("mulhsu",0xffffffffu);CHECK_M("mulhu",2u);
  CHECK_M("div",0xfffffffeu);CHECK_M("divu",0x55555553u);
  CHECK_M("rem",0xffffffffu);CHECK_M("remu",0u);
  a=0x80000000u;b=0xffffffffu;CHECK_M("div",0x80000000u);CHECK_M("rem",0u);
  b=0;CHECK_M("div",0xffffffffu);CHECK_M("divu",0xffffffffu);
  CHECK_M("rem",0x80000000u);CHECK_M("remu",0x80000000u);
#undef CHECK_M
  return ok;
}

static void stateful_after_submit(volatile uint32_t *ok){
#if TEST_STATEFUL_CASE >= 1 && TEST_STATEFUL_CASE <= 3
  if(TEST_STATEFUL_CASE==2)__asm__ volatile("csrci mstatus,8" ::: "memory");
  uint32_t now=MMIO(0x40002300u);
  MMIO(0x4000230cu)=0xffffffffu;MMIO(0x40002308u)=now+(TEST_STATEFUL_CASE==1?220u:40u);MMIO(0x4000230cu)=0;
  __asm__ volatile("li t0,0x80; csrs mie,t0" ::: "t0","memory");
  if(TEST_STATEFUL_CASE==1){
    uint32_t before=stateful_faults,sentinel=0x62f19a37u,address=0x40002030u;
    __asm__ volatile("lw %0,0(%1)":"+r"(sentinel):"r"(address):"memory");
    if(sentinel!=0x62f19a37u||stateful_faults!=before+1u)*ok=0;
  }
  if(TEST_STATEFUL_CASE==3)__asm__ volatile("wfi" ::: "memory");
  /* Keep arithmetic live through delayed device completion, not just timer entry. */
  for(uint32_t i=0;i<(TEST_STATEFUL_CASE==2?16u:128u);i++)if(!stateful_m())*ok=0;
  if(TEST_STATEFUL_CASE==2){
    uint32_t pending;__asm__ volatile("csrr %0,mip":"=r"(pending));
    if((pending&0x880u)!=0x880u||irq_seen||timer_seen)*ok=0;
    __asm__ volatile("csrsi mstatus,8" ::: "memory");
  }
#elif TEST_STATEFUL_CASE == 10
  for(uint32_t i=0;i<32;i++)if(!stateful_m())*ok=0;
#elif TEST_STATEFUL_CASE == 78
  if(!stateful_m_matrix())*ok=0;
#elif TEST_STATEFUL_CASE == 83
  uint32_t now=MMIO(0x40002300u);
  MMIO(0x4000230cu)=0xffffffffu;MMIO(0x40002308u)=now+80u;MMIO(0x4000230cu)=0;
  __asm__ volatile("li t0,0x80;csrs mie,t0;csrsi mstatus,8" ::: "t0","memory");
  for(uint32_t n=0;n<16;n++)if(!stateful_m())*ok=0;
  if(timer_seen!=1u||stateful_faults||MMIO(0x1000c004u)!=39u)*ok=0;
#elif TEST_STATEFUL_CASE == 84
  __asm__ volatile("csrci mstatus,8" ::: "memory");
  uint32_t now=MMIO(0x40002300u);
  MMIO(0x4000230cu)=0xffffffffu;MMIO(0x40002308u)=now+40u;MMIO(0x4000230cu)=0;
  __asm__ volatile("li t0,0x80;csrs mie,t0" ::: "t0","memory");
  while((DMA(28)&4u)==0u){}
  uint32_t pending;do{__asm__ volatile("csrr %0,mip":"=r"(pending));}while((pending&0x880u)!=0x880u);
  uint32_t value=7u,address=0x40002030u,before=stateful_faults;
  __asm__ volatile("mul %0,%0,%2\n lw %0,0(%1)":"+r"(value):"r"(address),"r"(3u):"memory");
  if(value!=21u||stateful_faults!=before+1u||timer_seen||irq_seen)*ok=0;
  __asm__ volatile("csrsi mstatus,8" ::: "memory");
#endif
}

static void stateful_invalidate(void){
  MMIO(0x40002200u)=3u;while(MMIO(0x40002204u)&1u){}
}

static void stateful_stage(uint32_t tag,uint32_t input,uint32_t output,uint32_t k,uint32_t batch,uint32_t stride,uint32_t bank){
  DMA(0)=input;DMA(4)=output;DMA(8)=(stride<<16)|64u;DMA(12)=(batch<<7)|k;
  uint32_t gen=(CFG(16)>>(bank*8u))&255u;
  DMA(16)=(gen<<17)|(bank<<16)|(TEST_ASID<<8)|tag;DMA(20)=TEST_QOS;DMA(24)=1;
}

static uint32_t stateful_finish(uint32_t tag,uint32_t status,uint32_t count){
  while((DMA(28)&4u)==0u){}
  uint32_t result=DMA(32),meta=DMA(40);
  (void)DMA(36); /* Sample precise fault-address metadata before consumption. */
  uint32_t ok=(result&15u)==status&&((result>>12)&127u)==count&&(meta&255u)==tag;
  DMA(44)=1;return ok;
}

static void stateful_bank(uint32_t bank,uint32_t k){
  for(uint32_t o=0;o<4;o++){
    for(uint32_t i=0;i<k;i++)cfg(0,(bank<<2)|o,i,1);
    cfg(1,(bank<<2)|o,0,0);cfg(2,(bank<<2)|o,0,1);cfg(3,(bank<<2)|o,0,0);
  }
}

static uint32_t stateful_expected(const int8_t *a,const int8_t *w,int32_t bias,
    int32_t az,int32_t wz,int32_t oz,int32_t mult,uint32_t shift,uint32_t relu){
  uint32_t wrapped=(uint32_t)bias;
  for(uint32_t i=0;i<4;i++)wrapped+=(uint32_t)(((int32_t)a[i]-az)*((int32_t)w[i]-wz));
  int64_t value=(int64_t)(int32_t)wrapped*mult;
  if(shift){int64_t magnitude=value<0?-value:value;magnitude=(magnitude+((int64_t)1<<(shift-1)))>>shift;value=value<0?-magnitude:magnitude;}
  value+=oz;if(relu&&value<0)value=0;
  if(value>127)value=127;if(value< -128)value= -128;
  return (uint32_t)value&255u;
}

static void stateful_tail(uint32_t *ok){
  if(TEST_STATEFUL_CASE<=10){
    if(TEST_STATEFUL_CASE<=3&&(!timer_seen||!irq_seen||(stateful_irq_sources&2u)==0u))*ok=0;
    return;
  }
  /* Scratch regions do not replace the baseline application's buffers. */
  MMIO(0x30001018u)=0x040018cfu;MMIO(0x30001024u)=0x040024cfu;
  for(uint32_t i=0;i<256;i+=4)MMIO(0x10006000u+i)=0x01010101u;
  if(TEST_CACHE){MMIO(0x40002100u)=0;MMIO(0x40002104u)=1;__asm__ volatile("fence" ::: "memory");}
#if TEST_STATEFUL_CASE == 20
  stateful_bank(1,4);CFG(16)=0xffffu;
  for(uint32_t job=0;job<260;job++){
    uint32_t bank=job&1u;
    if((job&31u)==0u)CFG(16)=((job>>5)&255u)*0x101u;
    stateful_stage(job&255u,0x80006000u,0x80009000u,4,1,4,bank);
    if(!stateful_finish(job&255u,0,1)||MMIO(0x10009000u)!=0x04040404u)*ok=0;
  }
#elif TEST_STATEFUL_CASE == 21
  stateful_bank(1,64);CFG(16)=0xffffu;
  for(uint32_t round=0;round<3;round++){
    for(uint32_t j=0;j<4;j++)stateful_stage(j,0x80006000u,0x80009000u+j*4u,64,1,4,j&1u);
    uint32_t faults=stateful_faults;CFG(16)=0;
    if(stateful_faults!=faults+1u||CFG(16)!=0xffffu)*ok=0;
    for(uint32_t j=0;j<4;j++)if(!stateful_finish(j,0,1))*ok=0;
  }
  CFG(16)=0;
  if(CFG(16)!=0u)*ok=0;
#elif TEST_STATEFUL_CASE == 30
  for(uint32_t page=0;page<12;page++)MMIO(0x30001040u+page*4u)=0x040018cfu;
  stateful_invalidate();
  for(uint32_t visit=0;visit<24;visit++){
    stateful_stage(visit,0x80010000u+(visit%12u)*4096u,0x80009000u,4,1,4,0);
    if(!stateful_finish(visit,0,1)||MMIO(0x10009000u)!=0x04040404u)*ok=0;
  }
#elif TEST_STATEFUL_CASE == 31
  MMIO(0x30001024u)=0x040024c3u;stateful_invalidate();MMIO(0x10009000u)=0x01010101u;
  stateful_stage(1,0x80009000u,0x80006000u,4,1,4,0);if(!stateful_finish(1,0,1))*ok=0;
  stateful_stage(2,0x80006000u,0x80009000u,4,1,4,0);if(!stateful_finish(2,3,0))*ok=0;
  MMIO(0x30001024u)=0x040024cfu;
  stateful_stage(3,0x80006000u,0x80009000u,4,1,4,0);if(!stateful_finish(3,3,0))*ok=0;
  stateful_invalidate();
  stateful_stage(4,0x80006000u,0x80009000u,4,1,4,0);if(!stateful_finish(4,0,1))*ok=0;
#elif TEST_STATEFUL_CASE == 32
  MMIO(0x30001080u)=0x080000cfu;MMIO(0x30001084u)=0x080004cfu;MMIO(0x30001088u)=0x040030cfu;
  MMIO(0x1000a000u)=0x55555555u;MMIO(0x1000b000u)=0x55555555u;MMIO(0x1000c000u)=0x55555555u;
  for(uint32_t attempt=0;attempt<3;attempt++){
    stateful_invalidate();stateful_stage(0xfe,0x80006000u,0x80020000u,4,3,4096,0);
    if(!stateful_finish(0xfe,attempt<2?5u:0u,attempt<2?attempt:3u))*ok=0;
    if(attempt==0&&MMIO(0x1000a000u)!=0x55555555u)*ok=0;
    if(attempt==1&&(MMIO(0x1000a000u)!=0x04040404u||MMIO(0x1000b000u)!=0x55555555u))*ok=0;
    if(attempt==0)MMIO(0x30001080u)=0x040028cfu;
    if(attempt==1)MMIO(0x30001084u)=0x04002ccfu;
  }
  if(MMIO(0x1000a000u)!=0x04040404u||MMIO(0x1000b000u)!=0x04040404u||MMIO(0x1000c000u)!=0x04040404u)*ok=0;
#elif TEST_STATEFUL_CASE == 40 || TEST_STATEFUL_CASE == 41
  if(TEST_STATEFUL_CASE==41){
    if(stateful_faults!=1u||(MMIO(0x40002108u)&4u)==0u)*ok=0;
    MMIO(0x40002104u)=1;if(MMIO(0x40002108u)&4u)*ok=0;
  }
  MMIO(0x1000c000u)=13u;
  MMIO(0x40002100u)=0;MMIO(0x40002104u)=1;
  MMIO(0x40002100u)=1;MMIO(0x40002104u)=1;__asm__ volatile("fence" ::: "memory");
  stateful_stage(0xaa,0x80006000u,0x80009000u,64,4,4,0);
  uint32_t value;uintptr_t source=0x1000c000u,dest=0x1000c004u;
  __asm__ volatile("lw %0,0(%1)\n mul %0,%0,%3\n sw %0,0(%2)":"=&r"(value):"r"(source),"r"(dest),"r"(3u):"memory");
  if(value!=39u||MMIO(0x1000c004u)!=39u)*ok=0;
  if(!stateful_finish(0xaa,0,4))*ok=0;
  MMIO(0x40002100u)=1;MMIO(0x40002104u)=1;__asm__ volatile("fence" ::: "memory");
  for(uint32_t v=0;v<4;v++)if(MMIO(0x10009000u+v*4u)!=0x40404040u)*ok=0;
#elif TEST_STATEFUL_CASE == 92
  for(uint32_t job=0;job<4;job++)if(!stateful_finish(0xe8u+job,0,1))*ok=0;
#elif TEST_STATEFUL_CASE == 98
  for(uint32_t failing=0;failing<3;failing++){
    for(uint32_t page=0;page<3;page++){
      MMIO(0x30001080u+page*4u)=(0x040028cfu+(page<<10));
      MMIO(0x1000a000u+page*4096u)=0x55555555u;
    }
    MMIO(0x30001080u+failing*4u)=0x080000cfu;
    stateful_invalidate();stateful_stage(0xfd,0x80006000u,0x80020000u,4,3,4096,0);
    if(!stateful_finish(0xfd,5,failing))*ok=0;
    for(uint32_t page=0;page<3;page++)if(MMIO(0x1000a000u+page*4096u)!=(page<failing?0x04040404u:0x55555555u))*ok=0;
    MMIO(0x30001080u+failing*4u)=0x040028cfu+(failing<<10);
    stateful_invalidate();stateful_stage(0xfd,0x80006000u,0x80020000u,4,3,4096,0);
    if(!stateful_finish(0xfd,0,3))*ok=0;
    for(uint32_t page=0;page<3;page++)if(MMIO(0x1000a000u+page*4096u)!=0x04040404u)*ok=0;
  }
#elif TEST_STATEFUL_CASE == 99
  for(uint32_t fault=0;fault<3;fault++){
    MMIO(0x30001018u)=fault==0?0x04001849u:(fault==1?0x080000cfu:0x040018cfu);
    MMIO(0x30001024u)=fault==2?0x040024c3u:0x040024cfu;
    stateful_invalidate();stateful_stage(0xfb,0x80006000u,0x80009000u,4,2,4,0);
    if(!stateful_finish(0xfb,fault==0?2u:(fault==1?4u:3u),0))*ok=0;
    MMIO(0x30001018u)=0x040018cfu;
    MMIO(0x30001024u)=0x040024cfu;
    stateful_invalidate();stateful_stage(0xfb,0x80006000u,0x80009000u,4,2,4,0);
    if(!stateful_finish(0xfb,0,2))*ok=0;
  }
#elif TEST_STATEFUL_CASE == 95
  stateful_bank(1,4);
  MMIO(0x30001024u)=0x040024c3u;
  MMIO(0x10009000u)=0x03030303u;stateful_invalidate();
  stateful_stage(0xf7,0x80006000u,0x80009000u,4,1,4,1);
  if(!stateful_finish(0xf7,3,0))*ok=0;
  stateful_stage(0xf8,0x80009000u,0x80006000u,4,1,4,1);
  if(!stateful_finish(0xf8,0,1))*ok=0;
  stateful_stage(0xf9,0x80006000u,0x80009000u,4,1,4,1);
  if(!stateful_finish(0xf9,3,0))*ok=0;
  MMIO(0x30001024u)=0x040024cfu;stateful_invalidate();
  stateful_stage(0xf9,0x80006000u,0x80009000u,4,1,4,1);
  if(!stateful_finish(0xf9,0,1))*ok=0;
#elif TEST_STATEFUL_CASE == 96 || TEST_STATEFUL_CASE == 97
  MMIO(0x30001020u)=0x040018cfu;stateful_invalidate();
  stateful_stage(0xfa,0x80008000u,0x80009000u,4,1,4,0);
  while((DMA(28)&2u)==0u){}
#if TEST_STATEFUL_CASE == 97
  (void)MMIO(0x10006004u);
#else
  if(MMIO(0x10006040u)!=0x01010101u)*ok=0;
  if(!stateful_finish(0xfa,0,1))*ok=0;
#endif
#elif TEST_STATEFUL_CASE == 93
  /* Both ways in final set, then a third tag forces dirty eviction. */
  MMIO(0x100007e0u)=0x01010101u;
  MMIO(0x100017e0u)=0x02020202u;
  (void)MMIO(0x100027e0u);
  MMIO(0x40002100u)=0u;MMIO(0x40002104u)=1u;
  MMIO(0x40002100u)=1u;MMIO(0x40002104u)=1u;
  if(MMIO(0x100007e0u)!=0x01010101u||MMIO(0x100017e0u)!=0x02020202u)*ok=0;
  MMIO(0x30001018u)=0x040000cfu;MMIO(0x3000101cu)=0x040004cfu;
  MMIO(0x30001020u)=0x040000cfu;stateful_invalidate();
  stateful_stage(0xee,0x800067e0u,0x80009000u,4,1,4,0);
  if(!stateful_finish(0xee,0,1))*ok=0;
  stateful_stage(0xef,0x800087e0u,0x80009020u,4,1,4,0);
  if(!stateful_finish(0xef,0,1))*ok=0;
  MMIO(0x40002100u)=1u;MMIO(0x40002104u)=1u;
  if(MMIO(0x10009000u)!=0x04040404u||MMIO(0x10009020u)!=0x04040404u)*ok=0;
#elif TEST_STATEFUL_CASE == 50 || TEST_STATEFUL_CASE == 94
  for(uint32_t j=0;j<4;j++){
    stateful_stage(j,0x80006000u,0x80009000u+j*4u,4,1,4,0);
    while(((DMA(28)>>7)&7u)<j+1u){(void)MMIO(0x1000c000u);}
  }
  stateful_stage(4,0x80006000u,0x80009010u,4,1,4,0);
  for(uint32_t n=0;n<64;n++)if(!stateful_m())*ok=0;
  if(((DMA(28)>>7)&7u)!=4u||(DMA(28)&2u)==0u)*ok=0;
#if TEST_STATEFUL_CASE == 94
  uint32_t generation=CFG(16),before=stateful_faults;
  CFG(16)=generation^1u;
  if(stateful_faults!=before+1u||CFG(16)!=generation)*ok=0;
#endif
  for(uint32_t j=0;j<5;j++)if(!stateful_finish(j,0,1))*ok=0;
#elif TEST_STATEFUL_CASE >= 60 && TEST_STATEFUL_CASE <= 63
  int8_t a[4]={1,-1,0,2},w[4]={1,1,1,1};
  int32_t az=0,wz=0,oz=0;uint32_t shift=1,relu=0;
  if(TEST_STATEFUL_CASE==61){a[0]=-128;a[1]=127;a[2]=-128;a[3]=127;w[0]=-128;w[1]=127;w[2]=-128;w[3]=127;shift=0;}
  if(TEST_STATEFUL_CASE==62){az=3;wz=-2;oz=4;relu=1;}
  if(TEST_STATEFUL_CASE==63){shift=0;}
  uint32_t input=0,expected=0;
  for(uint32_t i=0;i<4;i++)input|=(uint32_t)(uint8_t)a[i]<<(i*8u);
  MMIO(0x10006000u)=input;
  for(uint32_t o=0;o<4;o++){
    int32_t bias=TEST_STATEFUL_CASE==63?(int32_t)0x7fffffffu:(int32_t)o-3;
    int8_t wo[4];for(uint32_t i=0;i<4;i++){wo[i]=(o&1u)?(int8_t)-w[i]:w[i];cfg(0,o,i,(uint8_t)wo[i]);}
    cfg(1,o,0,(uint32_t)bias);cfg(2,o,0,1u|(shift<<16));
    cfg(3,o,0,relu|((uint32_t)(uint8_t)az<<8)|((uint32_t)(uint8_t)wz<<16)|((uint32_t)(uint8_t)oz<<24));
    expected|=stateful_expected(a,wo,bias,az,wz,oz,1,shift,relu)<<(o*8u);
  }
  uint32_t timer_before=timer_seen,now=MMIO(0x40002300u);
  MMIO(0x4000230cu)=0xffffffffu;MMIO(0x40002308u)=now+180u;MMIO(0x4000230cu)=0;
  __asm__ volatile("li t0,0x80; csrs mie,t0; csrsi mstatus,8" ::: "t0","memory");
  stateful_stage(0xaa,0x80006000u,0x80009000u,4,1,4,0);
  for(uint32_t n=0;n<8;n++)if(!stateful_m())*ok=0;
  if(!stateful_finish(0xaa,0,1)||MMIO(0x10009000u)!=expected)*ok=0;
  if(timer_seen!=timer_before+1u)*ok=0;
#elif TEST_STATEFUL_CASE == 70
  uint32_t before=stateful_faults,sentinel=0x1234abcdu,address=0x40001018u;
  __asm__ volatile("lw %0,0(%1)":"+r"(sentinel):"r"(address):"memory");
  address=0x40000034u;
  __asm__ volatile("lw %0,0(%1)":"+r"(sentinel):"r"(address):"memory");
  if(stateful_faults!=before+2u||sentinel!=0x1234abcdu)*ok=0;
  if(MMIO(0x40002004u)!=0||MMIO(0x4000200cu)!=0)*ok=0;
  DMA(36)=0xffffffffu;if(DMA(36)!=0)*ok=0;
  DMA(48)=0;DMA(48)=1;
#elif TEST_STATEFUL_CASE == 71 || TEST_STATEFUL_CASE == 72
  MMIO(0x30001018u)=TEST_STATEFUL_CASE==71?0x04001849u:0x080004cfu;
  stateful_invalidate();stateful_stage(0xab,0x80006000u,0x80009000u,4,1,4,0);
  while((DMA(28)&4u)==0u){}
  if(DMA(36)!=0x80006000u||((DMA(40)>>8)&7u)!=(TEST_STATEFUL_CASE==71?1u:2u))*ok=0;
  if(!stateful_finish(0xab,TEST_STATEFUL_CASE==71?2u:4u,0))*ok=0;
  MMIO(0x30001018u)=0x040018cfu;stateful_invalidate();
  stateful_stage(0xab,0x80006000u,0x80009000u,4,1,4,0);
  if(!stateful_finish(0xab,0,1)||MMIO(0x10009000u)!=0x04040404u)*ok=0;
#elif TEST_STATEFUL_CASE == 73
  DMA(0)=0x80006000u;DMA(4)=0x80009000u;DMA(8)=0x40040u;DMA(12)=132u;
  DMA(16)=(6u<<17)|(TEST_ASID<<8)|0xabu;DMA(24)=1;
  if((DMA(28)&8u)==0u||(DMA(28)&4u)!=0u)*ok=0;
  DMA(48)=0;if((DMA(28)&8u)==0u)*ok=0;
  DMA(48)=1;if(DMA(28)&8u)*ok=0;
  stateful_stage(0xab,0x80006000u,0x80009000u,4,1,4,0);
  if(!stateful_finish(0xab,0,1))*ok=0;
#elif TEST_STATEFUL_CASE == 74
  for(uint32_t job=0;job<6;job++)stateful_stage(job,0x80006000u,0x80009000u+4u*job,64,1,4,0);
  if((DMA(28)&8u)==0)*ok=0;
  while(((DMA(28)>>7)&7u)!=4u){}
  if(!stateful_m_matrix())*ok=0;
  for(uint32_t job=0;job<5;job++)if(!stateful_finish(job,0,1))*ok=0;
  DMA(48)=1;if(DMA(28)&8u)*ok=0;
#elif TEST_STATEFUL_CASE == 75
  for(uint32_t job=0;job<2;job++){
    stateful_stage(job,0x80006000u,0x80009000u+job*4u,4,1,4,0);
    if(!stateful_finish(job,0,1))*ok=0;
  }
#elif TEST_STATEFUL_CASE == 76
  MMIO(0x30001080u)=0x040028cfu;MMIO(0x30001084u)=0x04002ccfu;MMIO(0x30001088u)=0x080000cfu;
  for(uint32_t attempt=0;attempt<2;attempt++){
    stateful_invalidate();stateful_stage(0xfd,0x80006000u,0x80020000u,4,3,4096,0);
    if(!stateful_finish(0xfd,attempt?0u:5u,attempt?3u:2u))*ok=0;
    if(MMIO(0x1000a000u)!=0x04040404u||MMIO(0x1000b000u)!=0x04040404u)*ok=0;
    MMIO(0x30001088u)=0x040030cfu;
  }
  if(MMIO(0x1000c000u)!=0x04040404u)*ok=0;
#elif TEST_STATEFUL_CASE == 77
  /* Reserved mailbox words acknowledge but must not change result/done. */
  uint32_t result=MMIO(0x40001ff0u);
  MMIO(0x40001fe8u)=0x13579bdfu;MMIO(0x40001ff8u)=0x2468ace1u;
  if(MMIO(0x40001ff0u)!=result)*ok=0;
  stateful_stage(0xac,0x80006000u,0x80009000u,4,1,4,0);
  if(!stateful_finish(0xac,0,1)||MMIO(0x10009000u)!=0x04040404u)*ok=0;
#elif TEST_STATEFUL_CASE == 80
  /* Seeded firmware owns both input buffers, both parameter banks and tags. */
  uint32_t rng=STATEFUL_RANDOM_SEED,expected[2];int8_t weights[TEST_K];
  for(uint32_t i=0;i<TEST_K;i++){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;weights[i]=(int8_t)(rng>>24);}
  for(uint32_t bank=0;bank<2;bank++)for(uint32_t o=0;o<4;o++){
    for(uint32_t i=0;i<TEST_K;i++)cfg(0,(bank<<2)|o,i,(uint8_t)weights[i]);
    cfg(1,(bank<<2)|o,0,(uint32_t)((int32_t)o-64));cfg(2,(bank<<2)|o,0,(bank+1u)|(7u<<16));cfg(3,(bank<<2)|o,0,0);
  }
  MMIO(0x3000101cu)=0x04001ccfu;
  for(uint32_t round=0;round<4;round++){
    for(uint32_t job=0;job<2;job++){
      uint32_t base=0x10006000u+job*4096u,accum[4]={0xffffffc0u,0xffffffc1u,0xffffffc2u,0xffffffc3u};
      for(uint32_t i=0;i<TEST_K;i+=4){uint32_t word=0;
        for(uint32_t lane=0;lane<4;lane++){
          rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;int8_t value=(int8_t)(rng>>24);word|=(uint32_t)(uint8_t)value<<(lane*8u);
          for(uint32_t o=0;o<4;o++)accum[o]+=(uint32_t)((int32_t)value*(int32_t)weights[i+lane]);
        }MMIO(base+i)=word;
      }
      expected[job]=0;
      for(uint32_t o=0;o<4;o++){
        int64_t v=(int64_t)(int32_t)accum[o]*(job+1u);int64_t mag=v<0?-v:v;mag=(mag+64)>>7;v=v<0?-mag:mag;
        if(v>127)v=127;if(v< -128)v= -128;expected[job]|=((uint32_t)v&255u)<<(o*8u);
      }
    }
    if(TEST_CACHE){MMIO(0x40002100u)=0;MMIO(0x40002104u)=1;__asm__ volatile("fence" ::: "memory");}
    for(uint32_t job=0;job<2;job++)stateful_stage((round*2u+job+STATEFUL_RANDOM_SEED)&255u,0x80006000u+job*4096u,0x80009000u+job*4u,TEST_K,1,4,job);
    uint32_t seen=timer_seen,now=MMIO(0x40002300u);MMIO(0x4000230cu)=0xffffffffu;MMIO(0x40002308u)=now+80;MMIO(0x4000230cu)=0;
    __asm__ volatile("li t0,0x80;csrs mie,t0;csrsi mstatus,8" ::: "t0","memory");
    if(!stateful_m_matrix())*ok=0;
    if(timer_seen!=seen+1u)*ok=0;
    for(uint32_t job=0;job<2;job++)if(!stateful_finish((round*2u+job+STATEFUL_RANDOM_SEED)&255u,0,1))*ok=0;
    if(TEST_CACHE){MMIO(0x40002100u)=1;MMIO(0x40002104u)=1;__asm__ volatile("fence" ::: "memory");}
    for(uint32_t job=0;job<2;job++)if(MMIO(0x10009000u+job*4u)!=expected[job])*ok=0;
  }
#elif TEST_STATEFUL_CASE == 81
  stateful_bank(1,4);
  for(uint32_t round=0;round<96;round++){
    uint32_t generation=(250u+round*3u)&255u;
    CFG(16)=generation*0x101u;
    for(uint32_t job=0;job<4;job++)stateful_stage((round*4u+job)&255u,0x80006000u,0x80009000u+job*32u,4,1,4,job&1u);
    while(((DMA(28)>>7)&7u)!=4u){}
    if(!stateful_m_matrix())*ok=0;
    for(uint32_t job=0;job<4;job++){
      uint32_t result=DMA(32),fault=DMA(36),meta=DMA(40);
      for(uint32_t read=0;read<3;read++){
        if(DMA(32)!=result||DMA(36)!=fault||DMA(40)!=meta)*ok=0;
      }
      if(!stateful_finish((round*4u+job)&255u,0,1)||MMIO(0x10009000u+job*32u)!=0x04040404u)*ok=0;
    }
  }
#elif TEST_STATEFUL_CASE == 86
  stateful_bank(1,4);
  MMIO(0x3000101cu)=0x04001ccfu;
  for(uint32_t i=0;i<4;i++)MMIO(0x10007000u+i*4u)=0x02020202u;
  for(uint32_t job=0;job<4;job++)stateful_stage(0xe0u+job,0x80006000u,0x80009000u+job*32u,4,1,4,job&1u);
  MMIO(0x40002200u)=1u|(TEST_ASID<<8);
  if((MMIO(0x40002204u)&1u)==0u)*ok=0;
  for(uint32_t job=0;job<4;job++){
    if(!stateful_finish(0xe0u+job,0,1)||MMIO(0x10009000u+job*32u)!=0x04040404u)*ok=0;
  }
  while(MMIO(0x40002204u)&1u){}
  MMIO(0x30001018u)=0x04001ccfu;stateful_invalidate();
  stateful_stage(0xe0,0x80006000u,0x80009000u,4,1,4,0);
  if(!stateful_finish(0xe0,0,1)||MMIO(0x10009000u)!=0x08080808u)*ok=0;
#elif TEST_STATEFUL_CASE == 89 || TEST_STATEFUL_CASE == 90
  MMIO(0x30001018u)=0x040018cfu;
  for(uint32_t word=0;word<4;word++){
    MMIO(0x10006000u+word*4u)=0x01010101u;
    MMIO(0x10007000u+word*4u)=0x02020202u;
  }
  MMIO(0x40002100u)=2u;MMIO(0x40002104u)=1u;
  stateful_invalidate();
  stateful_stage(0xec,0x80006000u,0x80009000u,4,1,4,0);
  if(!stateful_finish(0xec,0,1))*ok=0;
  MMIO(0x30001018u)=0x04001ccfu;
  stateful_stage(0xed,0x80006000u,0x80009020u,4,1,4,0);
  while((DMA(28)&2u)==0u){}
#if TEST_STATEFUL_CASE == 90
  /* Expected-negative: the stale TLB still assigns page A to the device. */
  (void)MMIO(0x10006000u);
#else
  if(MMIO(0x10007000u)!=0x02020202u)*ok=0;
  if(!stateful_finish(0xed,0,1))*ok=0;
  MMIO(0x40002100u)=1u;MMIO(0x40002104u)=1u;
  if(MMIO(0x10009020u)!=0x04040404u)*ok=0;
#endif
#elif TEST_STATEFUL_CASE == 87
  for(uint32_t attempt=0;attempt<4;attempt++){
    if(attempt==0)stateful_invalidate();
    if(attempt==1)MMIO(0x30001018u)=0x04001849u;
    if(attempt==2)stateful_invalidate();
    if(attempt==3){MMIO(0x30001018u)=0x040018cfu;stateful_invalidate();}
    stateful_stage(0xeb,0x80006000u,0x80009000u,4,1,4,0);
    if(!stateful_finish(0xeb,attempt==2?2u:0u,attempt==2?0u:1u))*ok=0;
  }
#elif TEST_STATEFUL_CASE == 85
  __asm__ volatile("csrci mstatus,8" ::: "memory");
  stateful_stage(0xf0,0x80006000u,0x80009000u,4,1,4,0);
  while((DMA(28)&4u)==0u){}
  stateful_stage(0xf1,0x80006000u,0x80009020u,4,1,4,0);
  for(uint32_t n=0;n<32;n++)if(!stateful_m())*ok=0;
  if(!stateful_finish(0xf0,0,1)||!stateful_finish(0xf1,0,1))*ok=0;
  MMIO(0x4000200cu)=2u;
  if(MMIO(0x10009000u)!=0x04040404u||MMIO(0x10009020u)!=0x04040404u)*ok=0;
#elif TEST_STATEFUL_CASE == 82
  for(uint32_t attempt=0;attempt<4;attempt++){
    MMIO(0x30001018u)=attempt==0?0x04001849u:(attempt==2?0x080004cfu:0x040018cfu);
    MMIO(0x30001080u)=0x040028cfu;MMIO(0x30001084u)=attempt==1?0x080000cfu:0x04002ccfu;MMIO(0x30001088u)=0x040030cfu;
    for(uint32_t page=0;page<3;page++)MMIO(0x1000a000u+page*4096u)=0x55555555u;
    stateful_invalidate();stateful_stage(0xfc,0x80006000u,0x80020000u,4,3,4096,0);
    uint32_t status=attempt==0?2u:(attempt==1?5u:(attempt==2?4u:0u));
    uint32_t prefix=attempt==1?1u:(attempt==3?3u:0u);
    while((DMA(28)&4u)==0u){}
    uint32_t fault=DMA(36),stage=(DMA(40)>>8)&7u;
    if(attempt<3&&(fault!=(attempt==1?0x80021000u:0x80006000u)||stage!=(attempt==0?1u:(attempt==1?4u:2u))))*ok=0;
    if(!stateful_finish(0xfc,status,prefix))*ok=0;
    for(uint32_t page=0;page<3;page++)if(MMIO(0x1000a000u+page*4096u)!=(page<prefix?0x04040404u:0x55555555u))*ok=0;
  }
#endif
}
