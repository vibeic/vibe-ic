# L10 case `blinky_hex` — "GPIO output toggles regularly".
# Drives the GPIO pin through 16 alternating levels with a fixed delay between
# them. The expected sequence is NOT written here; it comes from spike.
    .option nopic
    .option norvc
    .include "common.inc"
    .section .text.init,"ax",@progbits
    .globl _start
_start:
    PROLOGUE
    li    x5, 0                # level
    li    x6, 16               # number of toggles
blink:
    sw    x5, 0(x3)
    ACC   x5
    xori  x5, x5, 1
    li    x7, 8
delay:
    addi  x7, x7, -1
    bne   x7, x0, delay
    addi  x6, x6, -1
    bne   x6, x0, blink
    EPILOGUE_NOSER
    TAIL_DATA
