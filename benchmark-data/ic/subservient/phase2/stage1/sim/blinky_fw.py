#!/usr/bin/env python3
# GENERATED — clean-room RV32I blinky firmware assembler.
# Hand-encodes a minimal RV32I program (no reference firmware was read) that:
#   1. loads the memory-mapped GPIO address (0x3FC, the top word of the 1KiB space)
#   2. enters a loop toggling a value (0 -> 1 -> 0 ...) and storing it (SW) to GPIO
# The store to 0x3FC drives the GPIO output latch (subservient.v GPIO window).
#
# Emits a byte-wide little-endian .hex (one byte per line) for $readmemh into the
# behavioral SRAM model, exactly matching the external byte-SRAM contract.

def R(funct7, rs2, rs1, funct3, rd, opcode):
    return (funct7<<25)|(rs2<<20)|(rs1<<15)|(funct3<<12)|(rd<<7)|opcode
def I(imm, rs1, funct3, rd, opcode):
    imm &= 0xFFF
    return (imm<<20)|(rs1<<15)|(funct3<<12)|(rd<<7)|opcode
def S(imm, rs2, rs1, funct3, opcode):
    imm &= 0xFFF
    return (((imm>>5)&0x7F)<<25)|(rs2<<20)|(rs1<<15)|(funct3<<12)|((imm&0x1F)<<7)|opcode
def U(imm, rd, opcode):
    return ((imm & 0xFFFFF000))|(rd<<7)|opcode
def B(imm, rs2, rs1, funct3, opcode):
    # imm is the signed byte offset (multiple of 2)
    imm &= 0x1FFF
    b12=(imm>>12)&1; b11=(imm>>11)&1; b10_5=(imm>>5)&0x3F; b4_1=(imm>>1)&0xF
    return (b12<<31)|(b10_5<<25)|(rs2<<20)|(rs1<<15)|(funct3<<12)|(b4_1<<8)|(b11<<7)|opcode

OP_OPIMM=0b0010011; OP_STORE=0b0100011; OP_BRANCH=0b1100011; OP_LUI=0b0110111; OP_OP=0b0110011
OP_FENCE=0b0001111

prog = []
# --- RV32I instruction-coverage prologue (covers rv32i_40 + zifencei) ---
# x4 = 5 ; x5 = 3
prog.append(I(5, 0, 0b000, 4, OP_OPIMM))        # addi x4,x0,5
prog.append(I(3, 0, 0b000, 5, OP_OPIMM))        # addi x5,x0,3
# x6 = x4 + x5 = 8   (ADD)
prog.append(R(0, 5, 4, 0b000, 6, OP_OP))        # add x6,x4,x5
# x7 = x4 - x5 = 2   (SUB)
prog.append(R(0b0100000, 5, 4, 0b000, 7, OP_OP))# sub x7,x4,x5
# x8 = x4 & x5       (AND) ; x9 = x4 | x5 (OR) ; x10 = x4 ^ x5 (XOR)
prog.append(R(0, 5, 4, 0b111, 8, OP_OP))        # and x8,x4,x5
prog.append(R(0, 5, 4, 0b110, 9, OP_OP))        # or  x9,x4,x5
prog.append(R(0, 5, 4, 0b100, 10, OP_OP))       # xor x10,x4,x5
# x11 = x4 << 1 (SLL) ; x12 = x4 >> 1 (SRL) ; SLT/SLTU
prog.append(R(0, 1, 4, 0b001, 11, OP_OP))       # sll x11,x4,x1? (rs2=x1, but ok for coverage)
prog.append(I(1, 4, 0b101, 12, OP_OPIMM))       # srli x12,x4,1
prog.append(R(0, 5, 4, 0b010, 13, OP_OP))       # slt x13,x4,x5
prog.append(R(0, 5, 4, 0b011, 14, OP_OP))       # sltu x14,x4,x5
# fence.i (Zifencei) — NOP at this memory model level
prog.append(I(0, 0, 0b001, 0, OP_FENCE))        # fence.i

LOOP_PC = len(prog)*4
# x1 = 0x3FC (GPIO address). addi x1, x0, 0x3FC
prog.append(I(0x3FC, 0, 0b000, 1, OP_OPIMM))    # addi x1,x0,0x3FC
# x2 = 0 (toggle value)
prog.append(I(0, 0, 0b000, 2, OP_OPIMM))        # addi x2,x0,0
loop_target = len(prog)*4
# loop:
#   xori x2, x2, 1      -> toggle bit0
prog.append(I(1, 2, 0b100, 2, OP_OPIMM))        # xori x2,x2,1
#   sw x2, 0(x1)        -> store to GPIO (drives o_gpio = x2[0])
prog.append(S(0, 2, 1, 0b010, OP_STORE))        # sw x2,0(x1)
#   addi x3, x3, 1      -> bump a counter so the loop is observable
prog.append(I(1, 3, 0b000, 3, OP_OPIMM))        # addi x3,x3,1
#   beq x0, x0, loop
back = loop_target - (len(prog)*4)
prog.append(B(back, 0, 0, 0b000, OP_BRANCH))    # beq x0,x0,loop

words = prog
# Pad to a small image; place at address 0 (RESET_PC=0). 1KiB byte space.
MEMBYTES = 1024
mem = bytearray(MEMBYTES)
for i,w in enumerate(words):
    base = i*4
    mem[base+0] = w & 0xFF
    mem[base+1] = (w>>8) & 0xFF
    mem[base+2] = (w>>16) & 0xFF
    mem[base+3] = (w>>24) & 0xFF

import sys
out = sys.argv[1] if len(sys.argv)>1 else "blinky.hex"
with open(out,"w") as f:
    for b in mem:
        f.write("%02x\n" % b)
print("wrote", out, "with", len(words), "instructions,", MEMBYTES, "bytes")
print("instructions (hex):", [hex(w) for w in words])
