//      // verilator_coverage annotation
        /*
         * serv_decode.v : SERV module decoding instruction word into control signals
         *
         * SPDX-FileCopyrightText: 2018 Olof Kindgren <olof@award-winning.me>
         * SPDX-License-Identifier: ISC
         */
        `default_nettype none
        module serv_decode
          #(parameter [0:0] PRE_REGISTER = 1,
            parameter [0:0] MDU = 0)
          (
 200008    input wire        clk,
           //Input
 000288    input wire [31:2] i_wb_rdt,
 003476    input wire        i_wb_en,
           //To state
 000578    output reg       o_sh_right,
 001156    output reg       o_bne_or_bge,
 000289    output reg       o_cond_branch,
%000000    output reg       o_e_op,
 001447    output reg       o_ebreak,
 001156    output reg       o_branch_op,
 001159    output reg       o_shift_op,
 001447    output reg       o_rd_op,
 001160    output reg       o_two_stage_op,
 000292    output reg       o_dbus_en,
           //MDU
%000000    output reg       o_mdu_op,
           //Extension
 000288    output reg [2:0] o_ext_funct3,
           //To bufreg
 001157    output reg       o_bufreg_rs1_en,
 001160    output reg       o_bufreg_imm_en,
 001156    output reg       o_bufreg_clr_lsb,
 000289    output reg       o_bufreg_sh_signed,
           //To ctrl
 000288    output reg       o_ctrl_jal_or_jalr,
%000000    output reg       o_ctrl_utype,
%000001    output reg       o_ctrl_pc_rel,
%000000    output reg       o_ctrl_mret,
           //To alu
 001156    output reg       o_alu_sub,
 000288    output reg [1:0] o_alu_bool_op,
 000579    output reg       o_alu_cmp_eq,
 000289    output reg       o_alu_cmp_sig,
 000578    output reg [2:0] o_alu_rd_sel,
           //To mem IF
 000579    output reg       o_mem_signed,
 000288    output reg       o_mem_word,
 001156    output reg       o_mem_half,
 001158    output reg       o_mem_cmd,
           //To CSR
%000000    output reg       o_csr_en,
 001157    output reg [1:0] o_csr_addr,
%000000    output reg       o_csr_mstatus_en,
%000000    output reg       o_csr_mie_en,
%000000    output reg       o_csr_mcause_en,
 000288    output reg [1:0] o_csr_source,
 000578    output reg       o_csr_d_sel,
%000000    output reg       o_csr_imm_en,
 001156    output reg       o_mtval_pc,
           //To top
 000289    output reg [3:0] o_immdec_ctrl,
%000001    output reg [3:0] o_immdec_en,
 001158    output reg       o_op_b_source,
           //To RF IF
 001448    output reg       o_rd_mem_en,
%000000    output reg       o_rd_csr_en,
 001159    output reg       o_rd_alu_en);
        
 000288    reg [4:0] opcode;
 000288    reg [2:0] funct3;
 001447    reg        op20;
 001159    reg        op21;
 001449    reg        op22;
 000291    reg        op26;
        
 000291    reg       imm25;
 000289    reg       imm30;
        
%000000    wire co_mdu_op     = MDU & (opcode == 5'b01100) & imm25;
        
 001160    wire co_two_stage_op =
        	~opcode[2] | (funct3[0] & ~funct3[1] & ~opcode[0] & ~opcode[4]) |
        	(funct3[1] & ~funct3[2] & ~opcode[0] & ~opcode[4]) | co_mdu_op;
 001159    wire co_shift_op = (opcode[2] & ~funct3[1]) & !co_mdu_op;
 001156    wire co_branch_op = opcode[4];
 000292    wire co_dbus_en    = ~opcode[2] & ~opcode[4];
 001156    wire co_mtval_pc   = opcode[4];
 000288    wire co_mem_word   = funct3[1];
 001159    wire co_rd_alu_en  = !opcode[0] & opcode[2] & !opcode[4] & !co_mdu_op;
 001448    wire co_rd_mem_en  = (!opcode[2] & !opcode[0]) | co_mdu_op;
 000288    wire [2:0] co_ext_funct3 = funct3;
        
           //jal,branch =     imm
           //jalr       = rs1+imm
           //mem        = rs1+imm
           //shift      = rs1
 001157    wire co_bufreg_rs1_en = !opcode[4] | (!opcode[1] & opcode[0]);
 001160    wire co_bufreg_imm_en = !opcode[2];
        
           //Clear LSB of immediate for BRANCH and JAL ops
           //True for BRANCH and JAL
           //False for JALR/LOAD/STORE/OP/OPIMM?
 001156    wire co_bufreg_clr_lsb = opcode[4] & ((opcode[1:0] == 2'b00) | (opcode[1:0] == 2'b11));
        
           //Conditional branch
           //True for BRANCH
           //False for JAL/JALR
 000289    wire co_cond_branch = !opcode[0];
        
%000000    wire co_ctrl_utype       = !opcode[4] & opcode[2] & opcode[0];
 000288    wire co_ctrl_jal_or_jalr = opcode[4] & opcode[0];
        
           //PC-relative operations
           //True for jal, b* auipc, ebreak
           //False for jalr, lui
%000001    wire co_ctrl_pc_rel = (opcode[2:0] == 3'b000)  |
                                  (opcode[1:0] == 2'b11)  |
                                  (opcode[4] & opcode[2]) & op20|
                                  (opcode[4:3] == 2'b00);
           //Write to RD
           //True for OP-IMM, AUIPC, OP, LUI, SYSTEM, JALR, JAL, LOAD
           //False for STORE, BRANCH, MISC-MEM
 001447    wire co_rd_op = (opcode[2] |
                             (!opcode[2] & opcode[4] & opcode[0]) |
                             (!opcode[2] & !opcode[3] & !opcode[0]));
        
           //
           //funct3
           //
        
 000578    wire co_sh_right   = funct3[2];
 001156    wire co_bne_or_bge = funct3[0];
        
           //Matches system ops except ecall/ebreak/mret
%000000    wire csr_op = opcode[4] & opcode[2] & (|funct3);
        
        
           //op20
 001447    wire co_ebreak = op20;
        
        
           //opcode & funct3 & op21
        
%000000    wire co_ctrl_mret = opcode[4] & opcode[2] & op21 & !(|funct3);
           //Matches system opcodes except CSR accesses (funct3 == 0)
           //and mret (!op21)
%000000    wire co_e_op = opcode[4] & opcode[2] & !op21 & !(|funct3);
        
           //opcode & funct3 & imm30
        
 000289    wire co_bufreg_sh_signed = imm30;
        
           /*
            True for sub, b*, slt*
            False for add*
            op    opcode f3  i30
            b*    11000  xxx x   t
            addi  00100  000 x   f
            slt*  0x100  01x x   t
            add   01100  000 0   f
            sub   01100  000 1   t
            */
 001156    wire co_alu_sub = funct3[1] | funct3[0] | (opcode[3] & imm30) | opcode[4];
        
           /*
            Bits 26, 22, 21 and 20 are enough to uniquely identify the eight supported CSR regs
            mtvec, mscratch, mepc and mtval are stored externally (normally in the RF) and are
            treated differently from mstatus, mie and mcause which are stored in serv_csr.
        
            The former get a 2-bit address as seen below while the latter get a
            one-hot enable signal each.
        
            Hex|2 222|Reg     |csr
            adr|6 210|name    |addr
            ---|-----|--------|----
            300|0_000|mstatus | xx
            304|0_100|mie     | xx
            305|0_101|mtvec   | 01
            340|1_000|mscratch| 00
            341|1_001|mepc    | 10
            342|1_010|mcause  | xx
            343|1_011|mtval   | 11
        
            */
        
           //true  for mtvec,mscratch,mepc and mtval
           //false for mstatus, mie, mcause
 000291    wire csr_valid = op20 | (op26 & !op21);
        
%000000    wire co_rd_csr_en = csr_op;
        
%000000    wire co_csr_en         = csr_op & csr_valid;
%000000    wire co_csr_mstatus_en = csr_op & !op26 & !op22 & !op20;
%000000    wire co_csr_mie_en     = csr_op & !op26 &  op22 & !op20;
%000000    wire co_csr_mcause_en  = csr_op         &  op21 & !op20;
        
 000288    wire [1:0] co_csr_source = funct3[1:0];
 000578    wire co_csr_d_sel = funct3[2];
%000000    wire co_csr_imm_en = opcode[4] & opcode[2] & funct3[2];
 001157    wire [1:0] co_csr_addr = {op26 & op20, !op26 | op21};
        
 000579    wire co_alu_cmp_eq = funct3[2:1] == 2'b00;
        
 000289    wire co_alu_cmp_sig = ~((funct3[0] & funct3[1]) | (funct3[1] & funct3[2]));
        
 001158    wire co_mem_cmd  = opcode[3];
 000579    wire co_mem_signed = ~funct3[2];
 001156    wire co_mem_half   = funct3[0];
        
 000288    wire [1:0] co_alu_bool_op = funct3[1:0];
        
 000289    wire [3:0] co_immdec_ctrl;
           //True for S (STORE) or B (BRANCH) type instructions
           //False for J type instructions
           assign co_immdec_ctrl[0] = opcode[3:0] == 4'b1000;
           //True for OP-IMM, LOAD, STORE, JALR  (I S)
           //False for LUI, AUIPC, JAL           (U J)
           assign co_immdec_ctrl[1] = (opcode[1:0] == 2'b00) | (opcode[2:1] == 2'b00);
           assign co_immdec_ctrl[2] = opcode[4] & !opcode[0];
           assign co_immdec_ctrl[3] = opcode[4];
        
%000001    wire [3:0] co_immdec_en;
           assign co_immdec_en[3] = opcode[4] | opcode[3] | opcode[2] | !opcode[0];                 //B I J S U
           assign co_immdec_en[2] = (opcode[4] & opcode[2]) | !opcode[3] | opcode[0];               //  I J   U
           assign co_immdec_en[1] = (opcode[2:1] == 2'b01) | (opcode[2] & opcode[0]) | co_csr_imm_en;//    J   U
           assign co_immdec_en[0] = ~co_rd_op;                                                       //B     S
        
 000578    wire [2:0] co_alu_rd_sel;
           assign co_alu_rd_sel[0] = (funct3 == 3'b000); // Add/sub
           assign co_alu_rd_sel[1] = (funct3[2:1] == 2'b01); //SLT*
           assign co_alu_rd_sel[2] = funct3[2]; //Bool
        
           //0 (OP_B_SOURCE_IMM) when OPIMM
           //1 (OP_B_SOURCE_RS2) when BRANCH or OP
 001158    wire co_op_b_source = opcode[3];
        
           generate
              if (PRE_REGISTER) begin : gen_pre_register
        
 100003          always @(posedge clk) begin
 001738             if (i_wb_en) begin
 001738                funct3 <= i_wb_rdt[14:12];
 001738                imm30  <= i_wb_rdt[30];
 001738                imm25  <= i_wb_rdt[25];
 001738                opcode <= i_wb_rdt[6:2];
 001738                op20   <= i_wb_rdt[20];
 001738                op21   <= i_wb_rdt[21];
 001738                op22   <= i_wb_rdt[22];
 001738                op26   <= i_wb_rdt[26];
                    end
                 end
        
%000001          always @(*) begin
%000001             o_sh_right         = co_sh_right;
%000001             o_bne_or_bge       = co_bne_or_bge;
%000001             o_cond_branch      = co_cond_branch;
%000001             o_dbus_en          = co_dbus_en;
%000001             o_mtval_pc         = co_mtval_pc;
%000001 	    o_two_stage_op     = co_two_stage_op;
%000001             o_e_op             = co_e_op;
%000001             o_ebreak           = co_ebreak;
%000001             o_branch_op        = co_branch_op;
%000001             o_shift_op         = co_shift_op;
%000001             o_rd_op            = co_rd_op;
%000001             o_mdu_op           = co_mdu_op;
%000001             o_ext_funct3       = co_ext_funct3;
%000001             o_bufreg_rs1_en    = co_bufreg_rs1_en;
%000001             o_bufreg_imm_en    = co_bufreg_imm_en;
%000001             o_bufreg_clr_lsb   = co_bufreg_clr_lsb;
%000001             o_bufreg_sh_signed = co_bufreg_sh_signed;
%000001             o_ctrl_jal_or_jalr = co_ctrl_jal_or_jalr;
%000001             o_ctrl_utype       = co_ctrl_utype;
%000001             o_ctrl_pc_rel      = co_ctrl_pc_rel;
%000001             o_ctrl_mret        = co_ctrl_mret;
%000001             o_alu_sub          = co_alu_sub;
%000001             o_alu_bool_op      = co_alu_bool_op;
%000001             o_alu_cmp_eq       = co_alu_cmp_eq;
%000001             o_alu_cmp_sig      = co_alu_cmp_sig;
%000001             o_alu_rd_sel       = co_alu_rd_sel;
%000001             o_mem_signed       = co_mem_signed;
%000001             o_mem_word         = co_mem_word;
%000001             o_mem_half         = co_mem_half;
%000001             o_mem_cmd          = co_mem_cmd;
%000001             o_csr_en           = co_csr_en;
%000001             o_csr_addr         = co_csr_addr;
%000001             o_csr_mstatus_en   = co_csr_mstatus_en;
%000001             o_csr_mie_en       = co_csr_mie_en;
%000001             o_csr_mcause_en    = co_csr_mcause_en;
%000001             o_csr_source       = co_csr_source;
%000001             o_csr_d_sel        = co_csr_d_sel;
%000001             o_csr_imm_en       = co_csr_imm_en;
%000001             o_immdec_ctrl      = co_immdec_ctrl;
%000001             o_immdec_en        = co_immdec_en;
%000001             o_op_b_source      = co_op_b_source;
%000001             o_rd_csr_en        = co_rd_csr_en;
%000001             o_rd_alu_en        = co_rd_alu_en;
%000001             o_rd_mem_en        = co_rd_mem_en;
                 end
        
              end else begin : gen_post_register
        
                 always @(*) begin
                    funct3  = i_wb_rdt[14:12];
                    imm30   = i_wb_rdt[30];
                    imm25   = i_wb_rdt[25];
                    opcode  = i_wb_rdt[6:2];
                    op20    = i_wb_rdt[20];
                    op21    = i_wb_rdt[21];
                    op22    = i_wb_rdt[22];
                    op26    = i_wb_rdt[26];
                 end
        
                 always @(posedge clk) begin
                    if (i_wb_en) begin
                       o_sh_right         <= co_sh_right;
                       o_bne_or_bge       <= co_bne_or_bge;
                       o_cond_branch      <= co_cond_branch;
                       o_e_op             <= co_e_op;
                       o_ebreak           <= co_ebreak;
                       o_two_stage_op     <= co_two_stage_op;
                       o_dbus_en          <= co_dbus_en;
                       o_mtval_pc         <= co_mtval_pc;
                       o_branch_op        <= co_branch_op;
                       o_shift_op         <= co_shift_op;
                       o_rd_op            <= co_rd_op;
                       o_mdu_op           <= co_mdu_op;
                       o_ext_funct3       <= co_ext_funct3;
                       o_bufreg_rs1_en    <= co_bufreg_rs1_en;
                       o_bufreg_imm_en    <= co_bufreg_imm_en;
                       o_bufreg_clr_lsb   <= co_bufreg_clr_lsb;
                       o_bufreg_sh_signed <= co_bufreg_sh_signed;
                       o_ctrl_jal_or_jalr <= co_ctrl_jal_or_jalr;
                       o_ctrl_utype       <= co_ctrl_utype;
                       o_ctrl_pc_rel      <= co_ctrl_pc_rel;
                       o_ctrl_mret        <= co_ctrl_mret;
                       o_alu_sub          <= co_alu_sub;
                       o_alu_bool_op      <= co_alu_bool_op;
                       o_alu_cmp_eq       <= co_alu_cmp_eq;
                       o_alu_cmp_sig      <= co_alu_cmp_sig;
                       o_alu_rd_sel       <= co_alu_rd_sel;
                       o_mem_signed       <= co_mem_signed;
                       o_mem_word         <= co_mem_word;
                       o_mem_half         <= co_mem_half;
                       o_mem_cmd          <= co_mem_cmd;
                       o_csr_en           <= co_csr_en;
                       o_csr_addr         <= co_csr_addr;
                       o_csr_mstatus_en   <= co_csr_mstatus_en;
                       o_csr_mie_en       <= co_csr_mie_en;
                       o_csr_mcause_en    <= co_csr_mcause_en;
                       o_csr_source       <= co_csr_source;
                       o_csr_d_sel        <= co_csr_d_sel;
                       o_csr_imm_en       <= co_csr_imm_en;
                       o_immdec_ctrl      <= co_immdec_ctrl;
                       o_immdec_en        <= co_immdec_en;
                       o_op_b_source      <= co_op_b_source;
                       o_rd_csr_en        <= co_rd_csr_en;
                       o_rd_alu_en        <= co_rd_alu_en;
                       o_rd_mem_en        <= co_rd_mem_en;
                    end
                 end
        
              end
           endgenerate
        
        endmodule
        
