# L10 case `zifencei` — the Zifencei extension the design DECLARES
# (declaration.json isa_extensions = ["I","Zifencei"]).
#
# Stores a new instruction over an instruction that is about to be executed,
# executes FENCE.I, then jumps to the patched site. The instruction word is
# NOT hand-encoded: the assembler encodes it at `insn_template` and the
# firmware copies that word. No expected value appears in this file; the
# golden comes from spike.
    .option nopic
    .option norvc
    .include "common.inc"
    .section .text.init,"ax",@progbits
    .globl _start
_start:
    PROLOGUE

    # x28 must end up holding what the PATCHED instruction writes, not what
    # the original one writes.
    li    x28, 0
    lui   x5, %hi(patch_site)
    addi  x5, x5, %lo(patch_site)
    lui   x6, %hi(insn_template)
    addi  x6, x6, %lo(insn_template)
    lw    x7, 0(x6)
    sw    x7, 0(x5)
    fence.i
    jal   x1, patch_site
    ACC   x28

    # read the patched word back as data too, so the store itself is checked
    lw    x7, 0(x5)
    ACC   x7

    EPILOGUE

patch_site:
    addi  x28, x0, 0x111      # overwritten before it is ever executed
    jalr  x0, 0(x1)

    .section .data
    .align 2
insn_template:
    addi  x28, x0, 0x2A5      # assembled by GAS, consumed as DATA
    TAIL_DATA
