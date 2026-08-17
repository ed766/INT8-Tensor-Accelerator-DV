#include <stdint.h>

uint32_t __mulsi3(uint32_t a, uint32_t b) {
  uint32_t value = 0;
  while (b) {
    if (b & 1u) value += a;
    a <<= 1; b >>= 1;
  }
  return value;
}

uint64_t __muldi3(uint64_t a, uint64_t b) {
  uint64_t value = 0;
  while (b) {
    if (b & 1u) value += a;
    a <<= 1; b >>= 1;
  }
  return value;
}

uint64_t __ashldi3(uint64_t value, int shift) {
  while (shift-- > 0) value <<= 1;
  return value;
}

int64_t __ashrdi3(int64_t value, int shift) {
  while (shift-- > 0) value >>= 1;
  return value;
}

uint64_t __lshrdi3(uint64_t value, int shift) {
  while (shift-- > 0) value >>= 1;
  return value;
}
