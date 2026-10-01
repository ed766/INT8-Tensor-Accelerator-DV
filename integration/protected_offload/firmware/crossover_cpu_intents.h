/* Directed architectural dependency chains. Inline assembly makes the
   dependent instructions observable even under -O2; the ISS checks semantics. */
static __attribute__((unused,noinline)) uint32_t intent_m_address(void) {
  volatile uint32_t word=0x5a19c3e7u;
  uint32_t address,loaded;
  __asm__ volatile("mul %0,%2,%3\n\tlw %1,0(%0)"
    : "=&r"(address),"=&r"(loaded)
    : "r"((uint32_t)(uintptr_t)&word),"r"(1u) : "memory");
  return loaded==0x5a19c3e7u;
}

static __attribute__((unused,noinline)) void intent_m_descriptor(uint32_t descriptor) {
  uint32_t computed;
  __asm__ volatile("mul %0,%1,%2\n\tsw %0,12(%3)"
    : "=&r"(computed) : "r"(descriptor),"r"(1u),"r"(0x40000000u) : "memory");
}

static __attribute__((unused,noinline)) uint32_t intent_load_m_store(void) {
  volatile uint32_t words[2]={19u,0u};
  uint32_t loaded,product;
  __asm__ volatile("lw %0,0(%2)\n\tmul %1,%0,%3\n\tsw %1,4(%2)"
    : "=&r"(loaded),"=&r"(product) : "r"(words),"r"(7u) : "memory");
  return words[1]==133u;
}

static __attribute__((unused,noinline)) uint32_t intent_m_branch(void) {
  uint32_t product,failed;
  __asm__ volatile("mul %0,%2,%3\n\tbne %0,%4,1f\n\tli %1,0\n\tj 2f\n"
                   "1:\n\tli %1,1\n2:"
    : "=&r"(product),"=&r"(failed) : "r"((uint32_t)-3),"r"(7u),"r"((uint32_t)-21));
  return failed==0;
}

static __attribute__((unused,noinline)) uint32_t intent_irq_divide(void) {
  uint32_t product,quotient;
  /* First retire a MUL while the K=64 DMA is active. Then place DIV at the
     measured completion edge so the same completion IRQ becomes pending
     during DIV. The trace checker requires both facts independently. */
  __asm__ volatile("mul %0,%2,%3\n"
                   ".rept 17\n nop\n .endr\n"
                   "div %1,%4,%5"
    : "=&r"(product),"=&r"(quotient)
    : "r"(21u),"r"(7u),"r"(93u),"r"(3u));
  return product==147u && quotient==31u;
}
