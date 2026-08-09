# rv32i_fw.S - RV32I(+Zifencei) exercise firmware for the subservient SoC.
#
# The DUT declares ISA = I + Zifencei (with_csr=0, with_c=0, with_mdu=0), so
# this program uses ONLY base-integer instructions plus fence.i.
#
# Memory map (read out of the DUT RTL, not out of any oracle):
#   servile_mux.v  : adr[31:30] == 00 -> shared SRAM ; != 00 -> extension bus
#   subservient.v  : memsize = 1024 bytes, reset_pc = 0x00000000
#   subservient_gpio.v : the only extension-bus target (no address decode)
#
# The program folds the architectural result of ~90 instructions into a
# 32-bit signature, serialises the signature MSB-first over the GPIO port,
# then stores it to SRAM and signals HTIF tohost.
#
# NOTHING in this file encodes an expected value. Every expected value comes
# from spike (the RISC-V reference ISA simulator) run on this same ELF.

    .option nopic
    .option norvc
    .section .text.init,"ax",@progbits
    .globl _start

    # x8  (s0) = signature accumulator
    # x3  (gp) = 0x40000000  GPIO / extension-bus address
    # x4  (tp) = 0x00000380  SRAM scratch base

.macro ACC reg
    slli  x31, x8, 1
    add   x8, x31, \reg
.endm

_start:
    li    x8, 0
    lui   x3, 0x40000
    lui   x4, %hi(scratch)
    addi  x4, x4, %lo(scratch)

# ---------------- 1. ALU register-register ----------------
    li    x5, 0x12345678
    li    x6, 0x0F0F0F0F
    add   x7, x5, x6
    ACC   x7
    sub   x7, x5, x6
    ACC   x7
    and   x7, x5, x6
    ACC   x7
    or    x7, x5, x6
    ACC   x7
    xor   x7, x5, x6
    ACC   x7
    sll   x7, x5, x6
    ACC   x7
    srl   x7, x5, x6
    ACC   x7
    sra   x7, x5, x6
    ACC   x7
    slt   x7, x5, x6
    ACC   x7
    sltu  x7, x5, x6
    ACC   x7

# negative operands exercise sra / slt / sltu differently
    li    x5, -1234567
    li    x6, 19
    add   x7, x5, x6
    ACC   x7
    sub   x7, x5, x6
    ACC   x7
    sra   x7, x5, x6
    ACC   x7
    srl   x7, x5, x6
    ACC   x7
    sll   x7, x5, x6
    ACC   x7
    slt   x7, x5, x6
    ACC   x7
    sltu  x7, x5, x6
    ACC   x7

# ---------------- 2. ALU register-immediate ----------------
    li    x5, 0x0BADF00D
    addi  x7, x5, -2047
    ACC   x7
    andi  x7, x5, 0x5A5
    ACC   x7
    ori   x7, x5, 0x2AA
    ACC   x7
    xori  x7, x5, -1
    ACC   x7
    slti  x7, x5, 100
    ACC   x7
    sltiu x7, x5, 100
    ACC   x7
    slli  x7, x5, 13
    ACC   x7
    srli  x7, x5, 7
    ACC   x7
    srai  x7, x5, 7
    ACC   x7
    lui   x7, 0xDEADB
    ACC   x7
    auipc x20, 0x0
    auipc x7, 0x1
    sub   x7, x7, x20        # PC-relative: identical in any link base
    ACC   x7

# ---------------- 3. loads and stores ----------------
    li    x5, 0x89ABCDEF
    sw    x5, 0(x4)
    lw    x7, 0(x4)
    ACC   x7
    lh    x7, 0(x4)
    ACC   x7
    lhu   x7, 0(x4)
    ACC   x7
    lh    x7, 2(x4)
    ACC   x7
    lhu   x7, 2(x4)
    ACC   x7
    lb    x7, 0(x4)
    ACC   x7
    lbu   x7, 0(x4)
    ACC   x7
    lb    x7, 3(x4)
    ACC   x7
    lbu   x7, 3(x4)
    ACC   x7

    li    x5, 0x77
    sb    x5, 5(x4)
    li    x5, 0x8001
    sh    x5, 6(x4)
    lw    x7, 4(x4)
    ACC   x7
    li    x5, 0x11223344
    sw    x5, 8(x4)
    lbu   x7, 8(x4)
    ACC   x7
    lbu   x7, 11(x4)
    ACC   x7

# ---------------- 4. branches ----------------
    li    x5, 5
    li    x6, -5
    li    x9, 0

    beq   x5, x5, 1f
    addi  x9, x9, 1          # must NOT execute
1:  addi  x9, x9, 2
    bne   x5, x6, 2f
    addi  x9, x9, 4          # must NOT execute
2:  addi  x9, x9, 8
    blt   x6, x5, 3f
    addi  x9, x9, 16         # must NOT execute
3:  addi  x9, x9, 32
    bge   x5, x6, 4f
    addi  x9, x9, 64         # must NOT execute
4:  addi  x9, x9, 128
    bltu  x5, x6, 5f         # unsigned: 5 < 0xFFFFFFFB -> taken
    addi  x9, x9, 256        # must NOT execute
5:  addi  x9, x9, 512
    bgeu  x6, x5, 6f         # unsigned: 0xFFFFFFFB >= 5 -> taken
    addi  x9, x9, 1024       # must NOT execute
6:  addi  x9, x9, 2000
    beq   x5, x6, 7f         # NOT taken
    addi  x9, x9, 1500
7:  bne   x5, x5, 8f         # NOT taken
    addi  x9, x9, 1234
8:  ACC   x9

# ---------------- 5. jal / jalr ----------------
    auipc x20, 0x0
    jal   x1, subr
    sub   x21, x1, x20       # PC-relative link offset, not the absolute link
    ACC   x21
    ACC   x10                # subroutine result

# ---------------- 6. fence.i (Zifencei) ----------------
    fence.i
    li    x7, 0x5EED
    ACC   x7

# ---------------- 7. serialise signature MSB-first over GPIO ----------------
    addi  x10, x8, 0
    li    x11, 32
ser_loop:
    addi  x11, x11, -1
    srl   x12, x10, x11
    andi  x12, x12, 1
    sw    x12, 0(x3)
    bne   x11, x0, ser_loop

# ---------------- 8. commit signature to SRAM, then HTIF exit -------------
    sw    x8, 32(x4)
    li    x13, 1
    lui   x14, %hi(tohost)
    addi  x14, x14, %lo(tohost)
    sw    x13, 0(x14)
    sw    x0, 4(x14)
halt:
    jal   x0, halt

# ---- subroutine, returned from with jalr ----
subr:
    li    x10, 0x1000
    addi  x10, x10, 0x123
    jalr  x0, 0(x1)

    .section .data
    .align 2
scratch:
    .space 64

    .section .htif,"aw",@progbits
    .align 3
    .globl tohost
tohost:
    .dword 0
    .globl fromhost
fromhost:
    .dword 0
