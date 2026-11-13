#include <stdint.h>
#include "mlp_vectors.h"

#define REG(address) (*(volatile uint32_t *)(uintptr_t)(address))
#define DMA(offset) REG(0x40000000u + (offset))
#define CFG(offset) REG(0x40001000u + (offset))
#define INPUT 0x1000101cu
#define HIDDEN 0x1000401cu
#define OUTPUT 0x1000601cu
#define GUARD 0xa53c79e1u

static uint32_t cycle(void) {
    uint32_t value;
    __asm__ volatile("csrr %0,mcycle" : "=r"(value));
    return value;
}

static void maintain(uint32_t command) {
    REG(0x40002100u) = command;
    REG(0x40002104u) = 1;
    __asm__ volatile("fence" ::: "memory");
}

static void configure(unsigned bank, unsigned kind, unsigned output,
                      unsigned index, uint32_t value) {
    CFG(0) = kind;
    CFG(4) = (bank << 2) | output;
    CFG(8) = index;
    CFG(12) = value;
    CFG(20) = 1;
}

static void load_layer(unsigned bank, unsigned k, const int8_t *weights,
                       const int32_t *bias, unsigned shift) {
    for (unsigned o = 0; o < 4; ++o) {
        for (unsigned i = 0; i < k; ++i)
            configure(bank, 0, o, i, (uint8_t)weights[o * k + i]);
        configure(bank, 1, o, 0, bias[o]);
        configure(bank, 2, o, 0, (shift << 16) | 1u);
        configure(bank, 3, o, 0, bank == 0);
    }
}

static unsigned offload(unsigned bank, unsigned k, uint32_t input, uint32_t output,
                        unsigned expected_fault) {
    const unsigned tag = 0x61u + bank;
    DMA(0) = input + 0x70000000u;
    DMA(4) = output + 0x70000000u;
    DMA(8) = (4u << 16) | k;
    DMA(12) = (SAMPLES << 7) | k;
    DMA(16) = ((7u + bank) << 17) | (bank << 16) | (1u << 8) | tag;
    DMA(20) = DMA_QOS;
    DMA(24) = 1;
    while ((DMA(28) & 4u) == 0) {}
    unsigned status = DMA(32), metadata = DMA(40), fault_address = DMA(36);
    DMA(44) = 1;
    if (expected_fault)
        return (status & 15u) == 5 && ((status >> 12) & 127u) == 2 &&
               (metadata & 255u) == tag && ((metadata >> 8) & 7u) == 4 &&
               fault_address == output + 0x70000008u;
    return (status & 15u) == 0 && ((status >> 12) & 127u) == SAMPLES &&
           (metadata & 255u) == tag;
}

static void scalar(unsigned bank, unsigned k, uint32_t input, uint32_t output,
                   const int8_t *weights, const int32_t *bias, unsigned shift) {
    for (unsigned v = 0; v < SAMPLES; ++v) {
        int32_t sum[4] = {bias[0], bias[1], bias[2], bias[3]};
        for (unsigned i = 0; i < k; i += 4) {
            uint32_t word = REG(input + v * k + i);
            for (unsigned lane = 0; lane < 4; ++lane)
                for (unsigned o = 0; o < 4; ++o)
                    sum[o] += (int8_t)(word >> (8 * lane)) * weights[o * k + i + lane];
        }
        uint32_t packed = 0;
        for (unsigned o = 0; o < 4; ++o) {
            int32_t magnitude = sum[o] < 0 ? -sum[o] : sum[o];
            if (shift) magnitude = (magnitude + (1 << (shift - 1))) >> shift;
            int32_t value = sum[o] < 0 ? -magnitude : magnitude;
            int32_t minimum = bank == 0 ? 0 : -128;
            if (value < minimum) value = minimum;
            if (value > 127) value = 127;
            packed |= (uint32_t)(uint8_t)value << (8 * o);
        }
        REG(output + v * 4) = packed;
    }
}

int main(void) {
    const uint32_t start = cycle();
    unsigned ok = 1;
    REG(0x30000800u) = 0x0c000401u;
    REG(0x30001004u) = 0x040004cfu;
    REG(0x30001010u) = 0x040010cfu;
    REG(0x30001018u) = 0x040018cfu;
    for (unsigned i = 0; i < SAMPLES * 4; ++i) REG(INPUT + 4 * i) = inputs[i];
    for (unsigned i = 0; i < SAMPLES; ++i) {
        REG(HIDDEN + 4 * i) = GUARD;
        REG(OUTPUT + 4 * i) = GUARD;
    }
    REG(HIDDEN - 4) = REG(HIDDEN + SAMPLES * 4) = GUARD;
    REG(OUTPUT - 4) = REG(OUTPUT + SAMPLES * 4) = GUARD;

    if (SCALAR) {
        scalar(0, 16, INPUT, HIDDEN, w1, b1, SHIFT1);
        scalar(1, 4, HIDDEN, OUTPUT, w2, b2, SHIFT2);
        maintain(0);
    } else {
        load_layer(0, 16, w1, b1, SHIFT1);
        load_layer(1, 4, w2, b2, SHIFT2);
        CFG(16) = 0x0807u;
        maintain(0);
        ok &= offload(0, 16, INPUT, HIDDEN, 0);
#if RETRY
        ok &= offload(1, 4, HIDDEN, OUTPUT, 1);
        maintain(1);
        ok &= REG(OUTPUT) == expected_output[0];
        ok &= REG(OUTPUT + 4) == expected_output[1];
        for (unsigned i = 2; i < SAMPLES; ++i)
            ok &= REG(OUTPUT + 4 * i) == GUARD;
#endif
        ok &= offload(1, 4, HIDDEN, OUTPUT, 0);
        maintain(1);
    }
    const uint32_t elapsed = cycle() - start;
    for (unsigned i = 0; i < SAMPLES; ++i) {
        ok &= REG(HIDDEN + i * 4) == expected_hidden[i];
        ok &= REG(OUTPUT + i * 4) == expected_output[i];
    }
    ok &= REG(HIDDEN - 4) == GUARD && REG(HIDDEN + SAMPLES * 4) == GUARD;
    ok &= REG(OUTPUT - 4) == GUARD && REG(OUTPUT + SAMPLES * 4) == GUARD;
    REG(0x40001fe0u) = elapsed;
    REG(0x40001ff0u) = ok ? 0x600d5000u : 0xdead5000u;
    REG(0x40001ff4u) = 1;
    return 0;
}
