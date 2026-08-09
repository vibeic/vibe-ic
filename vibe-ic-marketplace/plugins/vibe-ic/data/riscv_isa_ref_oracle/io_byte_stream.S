# L10 case `hello_hex` — firmware emits a message over the GPIO pin.
# Serialises the bytes of the string at `msg` MSB-first, 8 bits per byte.
# The bit sequence is NOT written here; it comes from spike.
    .option nopic
    .option norvc
    .include "common.inc"
    .section .text.init,"ax",@progbits
    .globl _start
_start:
    PROLOGUE
    lui   x5, %hi(msg)
    addi  x5, x5, %lo(msg)
next_byte:
    lbu   x6, 0(x5)
    beq   x6, x0, msg_done
    ACC   x6
    li    x7, 8
next_bit:
    addi  x7, x7, -1
    srl   x9, x6, x7
    andi  x9, x9, 1
    sw    x9, 0(x3)
    bne   x7, x0, next_bit
    addi  x5, x5, 1
    jal   x0, next_byte
msg_done:
    EPILOGUE_NOSER

    .section .data
    .align 2
msg:
    .asciz "hello"
    TAIL_DATA
