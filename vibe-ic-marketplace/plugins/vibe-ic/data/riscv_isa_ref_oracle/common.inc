# -- shared prologue/epilogue for every subservient firmware case ----------
# Register convention used by all cases:
#   x8  signature accumulator
#   x3  0x40000000  extension bus (GPIO) address  [servile_mux: adr[31:30]!=0]
#   x4  scratch base in SRAM
# Addresses are materialised with explicit lui %hi / addi %lo so that the
# DUT link (base 0) and the spike link (base 0x80000000) assemble to the SAME
# instruction sequence, differing only in the lui immediate.

.macro ACC reg
    slli  x31, x8, 1
    add   x8, x31, \reg
.endm

.macro PROLOGUE
    li    x8, 0
    lui   x3, 0x40000
    lui   x4, %hi(scratch)
    addi  x4, x4, %lo(scratch)
.endm

# Serialise x8 MSB-first over the GPIO pin, commit it to SRAM, signal HTIF.
.macro EPILOGUE
    addi  x10, x8, 0
    li    x11, 32
9990:
    addi  x11, x11, -1
    srl   x12, x10, x11
    andi  x12, x12, 1
    sw    x12, 0(x3)
    bne   x11, x0, 9990b
    HALT_SEQ
.endm

# Commit + halt only, for cases whose observable is the GPIO traffic itself.
.macro EPILOGUE_NOSER
    HALT_SEQ
.endm

.macro HALT_SEQ
    sw    x8, 32(x4)
    lui   x14, %hi(tohost)
    addi  x14, x14, %lo(tohost)
    li    x13, 1
    sw    x13, 0(x14)
    sw    x0, 4(x14)
9991:
    jal   x0, 9991b
.endm

.macro TAIL_DATA
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
.endm
