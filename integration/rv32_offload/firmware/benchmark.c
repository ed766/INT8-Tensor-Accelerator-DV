#include <stdint.h>
#include "benchmark_data.h"

#define MMIO32(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define AXIL_BASE 0x40000000u
#define IN_DATA   0x40000100u
#define IN_TAG    0x40000104u
#define IN_PUSH   0x40000108u
#define OUT_DATA  0x40000120u
#define OUT_TAG   0x40000124u
#define OUT_STAT  0x40000128u
#define OUT_POP   0x4000012cu
#define MARK_SCALAR_START 0x40000180u
#define MARK_CALIBRATE    0x40000174u
#define MARK_SCALAR_END   0x40000184u
#define MARK_ACCEL_START  0x40000188u
#define MARK_ACCEL_END    0x4000018cu
#define MARK_CONFIG_START 0x40000190u
#define MARK_CONFIG_END   0x40000194u
#define MARK_STREAM_START 0x40000198u
#define MARK_STREAM_END   0x4000019cu
#define MARK_POLL_START   0x400001a0u
#define MARK_POLL_END     0x400001a4u
#define MARK_OUTPUT_START 0x400001a8u
#define MARK_OUTPUT_END   0x400001acu
#define STATS     0x400001c0u
#define RESULT    0x400001f0u
#define DONE      0x400001f4u

static inline uint32_t cycle32(void) {
  uint32_t value;
  __asm__ volatile ("csrr %0, mcycle" : "=r"(value));
  return value;
}

static inline uint32_t instret32(void) {
  uint32_t value;
  __asm__ volatile ("csrr %0, minstret" : "=r"(value));
  return value;
}

static void axil_write(uint32_t offset, uint32_t value) { MMIO32(AXIL_BASE + offset) = value; }
static uint32_t axil_read(uint32_t offset) { return MMIO32(AXIL_BASE + offset); }

static int8_t requant(uint32_t acc_bits, int16_t multiplier, uint8_t shift,
                      int8_t output_zero, uint8_t relu) {
  int32_t acc = (int32_t)acc_bits;
  int64_t product = (int64_t)acc * (int64_t)multiplier;
  uint64_t magnitude = product < 0 ? (uint64_t)(-product) : (uint64_t)product;
  uint64_t rounded = shift == 0 ? magnitude : magnitude + (1ull << (shift - 1));
  int64_t scaled = shift == 0 ? product :
      (product < 0 ? -(int64_t)(rounded >> shift) : (int64_t)(rounded >> shift));
  scaled += output_zero;
#ifdef RV32_BENCH_MUT_SCALAR_ROUND
  scaled += 1;
#endif
  if (relu && scaled < 0) scaled = 0;
  if (scaled > 127) return 127;
  if (scaled < -128) return -128;
  return (int8_t)scaled;
}

static void scalar_layer(unsigned sample, int8_t output[4]) {
  for (unsigned o = 0; o < 4; ++o) {
    uint32_t acc = (uint32_t)biases[o];
    for (unsigned k = 0; k < BENCH_K; ++k) {
      int32_t xd = (int32_t)inputs[sample][k] - INPUT_ZERO;
      int32_t wd = (int32_t)weights[o][k] - weight_zero[o];
      acc += (uint32_t)(xd * wd);
    }
    output[o] = requant(acc, multipliers[o], shifts[o], output_zero[o], (RELU_MASK >> o) & 1u);
  }
}

static void configure(void) {
  MMIO32(MARK_CONFIG_START)=1;
  for (unsigned o = 0; o < 4; ++o) {
    for (unsigned k = 0; k < BENCH_K; ++k) {
      axil_write(0x00, (k << 6) | (o << 4));
      axil_write(0x04, (uint8_t)weights[o][k]);
    }
    axil_write(0x00, (o << 4) | 1u); axil_write(0x04, (uint32_t)biases[o]);
    axil_write(0x00, (o << 4) | 2u);
    axil_write(0x04, (uint16_t)multipliers[o] | ((uint32_t)shifts[o] << 16));
    axil_write(0x00, (o << 4) | 3u);
    axil_write(0x04, (((uint32_t)(uint8_t)output_zero[o]) << 24) |
      (((uint32_t)(uint8_t)weight_zero[o]) << 16) |
      (((uint32_t)(uint8_t)INPUT_ZERO) << 8) | ((RELU_MASK >> o) & 1u));
  }
  MMIO32(MARK_CONFIG_END)=1;
}

static uint32_t run_accel(unsigned sample) {
  uint8_t tag = (uint8_t)(sample + 1u);
  MMIO32(MARK_STREAM_START)=1;
  axil_write(0x08, ((uint32_t)tag << 8) | (BENCH_K << 1));
  MMIO32(IN_TAG) = tag;
  for (unsigned k = 0; k < BENCH_K; k += 4) {
    uint32_t word = 0;
    for (unsigned lane = 0; lane < 4; ++lane)
      word |= (uint32_t)(uint8_t)inputs[sample][k + lane] << (lane * 8);
    MMIO32(IN_DATA) = word; MMIO32(IN_PUSH) = 1;
  }
  MMIO32(MARK_STREAM_END)=1; MMIO32(MARK_POLL_START)=1;
  while ((MMIO32(OUT_STAT) & 1u) == 0) { }
  MMIO32(MARK_POLL_END)=1; MMIO32(MARK_OUTPUT_START)=1;
  if ((uint8_t)MMIO32(OUT_TAG) != tag) return 0xffffffffu;
  uint32_t result = MMIO32(OUT_DATA); MMIO32(OUT_POP) = 1;
  MMIO32(MARK_OUTPUT_END)=1;
  return result;
}

static uint32_t counter_overhead(void) {
  // The marker APB path is deterministic. Thirty-two consecutive deltas are
  // sampled in hardware; the final value equals their median when all match.
  for (unsigned i=0;i<33;++i) MMIO32(MARK_CALIBRATE)=i;
  return MMIO32(MARK_CALIBRATE);
}

volatile uint32_t benchmark_stats[12];

int main(void) {
  int8_t scalar[4];
  uint32_t overhead = counter_overhead();
  uint32_t scalar_i0=instret32(), scalar_c0=cycle32(); MMIO32(MARK_SCALAR_START)=1;
  for (unsigned sample=0; sample<BENCH_BATCH; ++sample) {
    scalar_layer(sample, scalar);
    for (unsigned o=0;o<4;++o) if (scalar[o] != expected[sample][o]) { MMIO32(RESULT)=0xdead0100u+sample;MMIO32(DONE)=1;return 1; }
  }
  MMIO32(MARK_SCALAR_END)=1; uint32_t scalar_c1=cycle32(), scalar_i1=instret32();
#if !BENCH_COLD
  configure();
#endif
  axil_write(0x44,1);
  uint32_t accel_i0=instret32(), accel_c0=cycle32(); MMIO32(MARK_ACCEL_START)=1;
#if BENCH_COLD
  configure();
#endif
  for (unsigned sample=0; sample<BENCH_BATCH; ++sample) {
    uint32_t got=run_accel(sample), want=0;
    for(unsigned o=0;o<4;++o) want|=(uint32_t)(uint8_t)expected[sample][o]<<(8*o);
#ifdef RV32_BENCH_MUT_CORRUPT_RESULT
    got ^= 1u;
#endif
    if(got!=want){MMIO32(RESULT)=0xdead0200u+sample;MMIO32(DONE)=1;return 2;}
  }
  MMIO32(MARK_ACCEL_END)=1; uint32_t accel_c1=cycle32(), accel_i1=instret32();
  benchmark_stats[0]=scalar_c1-scalar_c0; benchmark_stats[1]=accel_c1-accel_c0;
  benchmark_stats[2]=scalar_i1-scalar_i0; benchmark_stats[3]=accel_i1-accel_i0;
  benchmark_stats[4]=overhead; benchmark_stats[5]=axil_read(0x2c);
  benchmark_stats[6]=axil_read(0x30); benchmark_stats[7]=axil_read(0x34);
  benchmark_stats[8]=axil_read(0x38); benchmark_stats[9]=axil_read(0x10);
  benchmark_stats[10]=axil_read(0x14); benchmark_stats[11]=axil_read(0x18);
  for (unsigned i=5;i<12;++i) MMIO32(STATS + 4u*i)=benchmark_stats[i];
  MMIO32(RESULT)=0x600d0000u | (BENCH_K & 0xffu); MMIO32(DONE)=1;
  return 0;
}
