//      // verilator_coverage annotation
        /*
         * serv_top.v : SERV toplevel
         *
         * SPDX-FileCopyrightText: 2018 Olof Kindgren <olof@award-winning.me>
         * SPDX-License-Identifier: ISC
         */
        `default_nettype none
        
        module serv_top
          #(parameter	    WITH_CSR = 1,
            parameter	    W = 1,
            parameter	    B = W-1,
            parameter	    PRE_REGISTER = 1,
            parameter	    RESET_STRATEGY = "MINI",
            parameter	    RESET_PC = 32'd0,
            parameter [0:0] DEBUG = 1'b0,
            parameter [0:0] MDU = 1'b0,
            parameter [0:0] COMPRESSED=0,
            parameter [0:0] ALIGN = COMPRESSED)
           (
 200008    input wire 		      clk,
%000002    input wire 		      i_rst,
%000000    input wire 		      i_timer_irq,
        `ifdef RISCV_FORMAL
           output wire 		      rvfi_valid,
           output wire [63:0] 	      rvfi_order,
           output wire [31:0] 	      rvfi_insn,
           output wire 		      rvfi_trap,
           output wire 		      rvfi_halt,
           output wire 		      rvfi_intr,
           output wire [1:0] 	      rvfi_mode,
           output wire [1:0] 	      rvfi_ixl,
           output wire [4:0] 	      rvfi_rs1_addr,
           output wire [4:0] 	      rvfi_rs2_addr,
           output wire [31:0] 	      rvfi_rs1_rdata,
           output wire [31:0] 	      rvfi_rs2_rdata,
           output wire [4:0] 	      rvfi_rd_addr,
           output wire [31:0] 	      rvfi_rd_wdata,
           output wire [31:0] 	      rvfi_pc_rdata,
           output wire [31:0] 	      rvfi_pc_wdata,
           output wire [31:0] 	      rvfi_mem_addr,
           output wire [3:0] 	      rvfi_mem_rmask,
           output wire [3:0] 	      rvfi_mem_wmask,
           output wire [31:0] 	      rvfi_mem_rdata,
           output wire [31:0] 	      rvfi_mem_wdata,
        `endif
           //RF Interface
 003476    output wire 		      o_rf_rreq,
 001734    output wire 		      o_rf_wreq,
 005210    input wire 		      i_rf_ready,
%000000    output wire [4+WITH_CSR:0] o_wreg0,
%000001    output wire [4+WITH_CSR:0] o_wreg1,
 001741    output wire 		      o_wen0,
%000000    output wire 		      o_wen1,
 004058    output wire [B:0] o_wdata0,
 000868    output wire [B:0] o_wdata1,
%000000    output wire [4+WITH_CSR:0] o_rreg0,
%000000    output wire [4+WITH_CSR:0] o_rreg1,
 002462    input wire  [B:0] i_rdata0,
 000146    input wire  [B:0] i_rdata1,
        
 004632    output wire [31:0] 	      o_ibus_adr,
 003476    output wire 		      o_ibus_cyc,
 000288    input wire [31:0] 	      i_ibus_rdt,
 003476    input wire 		      i_ibus_ack,
 001733    output wire [31:0] 	      o_dbus_adr,
 001887    output wire [31:0] 	      o_dbus_dat,
 001157    output wire [3:0] 	      o_dbus_sel,
 001158    output wire 		      o_dbus_we ,
 000290    output wire 		      o_dbus_cyc,
 000288    input wire [31:0] 	      i_dbus_rdt,
 000290    input wire 		      i_dbus_ack,
           //Extension
 000288    output wire [ 2:0] o_ext_funct3,
%000000    input  wire        i_ext_ready,
%000000    input wire  [31:0] i_ext_rd,
 001733    output wire [31:0] o_ext_rs1,
 001887    output wire [31:0] o_ext_rs2,
           //MDU
%000000    output wire        o_mdu_valid);
        
 000291    wire [4:0]    rd_addr;
 000288    wire [4:0]    rs1_addr;
 001447    wire [4:0]    rs2_addr;
        
 000289    wire [3:0] 	 immdec_ctrl;
%000001    wire [3:0] 	immdec_en;
        
 000578    wire          sh_right;
 001156    wire 	 bne_or_bge;
 000289    wire 	 cond_branch;
 001160    wire 	 two_stage_op;
%000000    wire 	 e_op;
 001447    wire 	 ebreak;
 001156    wire 	 branch_op;
 001159    wire 	 shift_op;
 001447    wire 	 rd_op;
%000000    wire   mdu_op;
        
 001159    wire 	 rd_alu_en;
%000000    wire 	 rd_csr_en;
 001448    wire 	 rd_mem_en;
 000576    wire [B:0]    ctrl_rd;
 006942    wire [B:0]    alu_rd;
 015637    wire [B:0]    mem_rd;
%000000    wire [B:0]    csr_rd;
 001156    wire 	 mtval_pc;
        
 003475    wire          ctrl_pc_en;
 001156    wire          jump;
 000288    wire          jal_or_jalr;
%000000    wire          utype;
%000000    wire 	 mret;
 002605    wire [B:0]    imm;
%000000    wire 	 trap;
%000001    wire 	 pc_rel;
%000000    wire          iscomp;
        
 002894    wire          init;
 003765    wire          cnt_en;
 005210    wire 	 cnt0to3;
 005209    wire 	 cnt12to31;
 005210    wire          cnt0;
 005210    wire          cnt1;
 005210    wire          cnt2;
 005210    wire          cnt3;
 005210    wire          cnt7;
 005210    wire          cnt11;
 005210    wire          cnt12;
        
 005208    wire 	 cnt_done;
        
 001734    wire 	 bufreg_en;
 000289    wire          bufreg_sh_signed;
 001157    wire 	 bufreg_rs1_en;
 001160    wire 	 bufreg_imm_en;
 001156    wire 	 bufreg_clr_lsb;
 003466    wire [B:0]    bufreg_q;
 040089    wire [B:0]    bufreg2_q;
 000288    wire [31:0] dbus_rdt;
 000290    wire        dbus_ack;
        
 001156    wire          alu_sub;
 000288    wire [1:0] 	 alu_bool_op;
 000579    wire          alu_cmp_eq;
 000289    wire          alu_cmp_sig;
 002750    wire          alu_cmp;
 000578    wire [2:0]    alu_rd_sel;
        
 002462    wire [B:0]    rs1;
 000146    wire [B:0]    rs2;
 001447    wire          rd_en;
        
 001887    wire [B:0]    op_b;
 001158    wire          op_b_sel;
        
 000579    wire          mem_signed;
 000288    wire          mem_word;
 001156    wire          mem_half;
 005208    wire [1:0] 	 mem_bytecnt;
 002753    wire 	 sh_done;
        
 002600    wire 	 mem_misalign;
        
 008966    wire [B:0]    bad_pc;
        
%000000    wire 	 csr_mstatus_en;
%000000    wire 	 csr_mie_en;
%000000    wire 	 csr_mcause_en;
 000288    wire [1:0]	 csr_source;
 000578    wire	[B:0]	 csr_imm;
 000578    wire 	 csr_d_sel;
%000000    wire 	 csr_en;
 001157    wire [1:0] 	 csr_addr;
 000146    wire [B:0]    csr_pc;
%000000    wire 	 csr_imm_en;
 000868    wire [B:0]    csr_in;
%000000    wire [B:0]    rf_csr_out;
 000292    wire 	 dbus_en;
        
%000000    wire 	 new_irq;
        
 001733    wire [1:0]   lsb;
        
 000288    wire [31:0] i_wb_rdt;
        
 004632    wire [31:0] wb_ibus_adr;
 003476    wire        wb_ibus_cyc;
 000288    wire [31:0] wb_ibus_rdt;
 003476    wire        wb_ibus_ack;
        
           generate
              if (ALIGN) begin : gen_align
                 serv_aligner  align
                   (
                    .clk(clk),
                    .rst(i_rst),
                    // serv_rf_top
                    .i_ibus_adr(wb_ibus_adr),
                    .i_ibus_cyc(wb_ibus_cyc),
                    .o_ibus_rdt(wb_ibus_rdt),
                    .o_ibus_ack(wb_ibus_ack),
                    // servant_arbiter
                    .o_wb_ibus_adr(o_ibus_adr),
                    .o_wb_ibus_cyc(o_ibus_cyc),
                    .i_wb_ibus_rdt(i_ibus_rdt),
                    .i_wb_ibus_ack(i_ibus_ack));
              end else begin : gen_no_align
                 assign  o_ibus_adr  = wb_ibus_adr;
                 assign  o_ibus_cyc  = wb_ibus_cyc;
                 assign  wb_ibus_rdt = i_ibus_rdt;
                 assign  wb_ibus_ack = i_ibus_ack;
                end
           endgenerate
        
           generate
              if (COMPRESSED) begin : gen_compressed
                 serv_compdec compdec
                   (
                    .i_clk(clk),
                    .i_instr(wb_ibus_rdt),
                    .i_ack(wb_ibus_ack),
                    .o_instr(i_wb_rdt),
                    .o_iscomp(iscomp));
              end else begin : gen_no_compressed
                 assign i_wb_rdt =  wb_ibus_rdt;
                 assign iscomp   =  1'b0;
              end
           endgenerate
        
           serv_state
             #(.RESET_STRATEGY (RESET_STRATEGY),
               .WITH_CSR (WITH_CSR[0:0]),
               .MDU(MDU),
               .ALIGN(ALIGN),
               .W(W))
           state
             (
              .i_clk (clk),
              .i_rst          (i_rst),
              //State
              .i_new_irq      (new_irq),
              .i_alu_cmp      (alu_cmp),
              .o_init         (init),
              .o_cnt_en       (cnt_en),
              .o_cnt0to3      (cnt0to3),
              .o_cnt12to31    (cnt12to31),
              .o_cnt0         (cnt0),
              .o_cnt1         (cnt1),
              .o_cnt2         (cnt2),
              .o_cnt3         (cnt3),
              .o_cnt7         (cnt7),
              .o_cnt11        (cnt11),
              .o_cnt12        (cnt12),
              .o_cnt_done     (cnt_done),
              .o_bufreg_en    (bufreg_en),
              .o_ctrl_pc_en   (ctrl_pc_en),
              .o_ctrl_jump    (jump),
              .o_ctrl_trap    (trap),
              .i_ctrl_misalign(lsb[1]),
              .i_sh_done      (sh_done),
              .o_mem_bytecnt  (mem_bytecnt),
              .i_mem_misalign (mem_misalign),
              //Control
              .i_bne_or_bge   (bne_or_bge),
              .i_cond_branch  (cond_branch),
              .i_dbus_en      (dbus_en),
              .i_two_stage_op (two_stage_op),
              .i_branch_op    (branch_op),
              .i_shift_op     (shift_op),
              .i_sh_right     (sh_right),
              .i_alu_rd_sel1  (alu_rd_sel[1]),
              .i_rd_alu_en    (rd_alu_en),
              .i_e_op         (e_op),
              .i_rd_op        (rd_op),
              //MDU
              .i_mdu_op       (mdu_op),
              .o_mdu_valid    (o_mdu_valid),
              //Extension
              .i_mdu_ready    (i_ext_ready),
              //External
              .o_dbus_cyc     (o_dbus_cyc),
              .i_dbus_ack     (i_dbus_ack),
              .o_ibus_cyc     (wb_ibus_cyc),
              .i_ibus_ack     (wb_ibus_ack),
              //RF Interface
              .o_rf_rreq      (o_rf_rreq),
              .o_rf_wreq      (o_rf_wreq),
              .i_rf_ready     (i_rf_ready),
              .o_rf_rd_en     (rd_en));
        
           serv_decode
             #(.PRE_REGISTER (PRE_REGISTER),
               .MDU(MDU))
           decode
             (
              .clk (clk),
              //Input
              .i_wb_rdt           (i_wb_rdt[31:2]),
              .i_wb_en            (wb_ibus_ack),
              //To state
              .o_bne_or_bge       (bne_or_bge),
              .o_cond_branch      (cond_branch),
              .o_dbus_en          (dbus_en),
              .o_e_op             (e_op),
              .o_ebreak           (ebreak),
              .o_branch_op        (branch_op),
              .o_shift_op         (shift_op),
              .o_rd_op            (rd_op),
              .o_sh_right         (sh_right),
              .o_mdu_op           (mdu_op),
              .o_two_stage_op     (two_stage_op),
              //Extension
              .o_ext_funct3       (o_ext_funct3),
        
              //To bufreg
              .o_bufreg_rs1_en    (bufreg_rs1_en),
              .o_bufreg_imm_en    (bufreg_imm_en),
              .o_bufreg_clr_lsb   (bufreg_clr_lsb),
              .o_bufreg_sh_signed (bufreg_sh_signed),
              //To bufreg2
              .o_op_b_source      (op_b_sel),
              //To ctrl
              .o_ctrl_jal_or_jalr (jal_or_jalr),
              .o_ctrl_utype       (utype),
              .o_ctrl_pc_rel      (pc_rel),
              .o_ctrl_mret        (mret),
              //To alu
              .o_alu_sub          (alu_sub),
              .o_alu_bool_op      (alu_bool_op),
              .o_alu_cmp_eq       (alu_cmp_eq),
              .o_alu_cmp_sig      (alu_cmp_sig),
              .o_alu_rd_sel       (alu_rd_sel),
              //To mem IF
              .o_mem_cmd          (o_dbus_we),
              .o_mem_signed       (mem_signed),
              .o_mem_word         (mem_word),
              .o_mem_half         (mem_half),
              //To CSR
              .o_csr_en           (csr_en),
              .o_csr_addr         (csr_addr),
              .o_csr_mstatus_en   (csr_mstatus_en),
              .o_csr_mie_en       (csr_mie_en),
              .o_csr_mcause_en    (csr_mcause_en),
              .o_csr_source       (csr_source),
              .o_csr_d_sel        (csr_d_sel),
              .o_csr_imm_en       (csr_imm_en),
              .o_mtval_pc         (mtval_pc      ),
              //To top
              .o_immdec_ctrl      (immdec_ctrl),
              .o_immdec_en        (immdec_en),
              //To RF IF
              .o_rd_mem_en        (rd_mem_en),
              .o_rd_csr_en        (rd_csr_en),
              .o_rd_alu_en        (rd_alu_en));
        
           serv_immdec #(.W (W)) immdec
             (
              .i_clk        (clk),
              //State
              .i_cnt_en     (cnt_en),
              .i_cnt_done   (cnt_done),
              //Control
              .i_immdec_en        (immdec_en),
              .i_csr_imm_en (csr_imm_en),
              .i_ctrl       (immdec_ctrl),
              .o_rd_addr    (rd_addr),
              .o_rs1_addr   (rs1_addr),
              .o_rs2_addr   (rs2_addr),
              //Data
              .o_csr_imm    (csr_imm),
              .o_imm        (imm),
              //External
              .i_wb_en      (wb_ibus_ack),
              .i_wb_rdt     (i_wb_rdt[31:7]));
        
           serv_bufreg
              #(.MDU(MDU),
        	.W(W))
           bufreg
             (
              .i_clk    (clk),
              //State
              .i_cnt0   (cnt0),
              .i_cnt1   (cnt1),
              .i_cnt_done (cnt_done),
              .i_en     (bufreg_en),
              .i_init   (init),
              .i_mdu_op (mdu_op),
              .o_lsb    (lsb),
              //Control
              .i_sh_signed (bufreg_sh_signed),
              .i_rs1_en    (bufreg_rs1_en),
              .i_imm_en    (bufreg_imm_en),
              .i_clr_lsb   (bufreg_clr_lsb),
              .i_shift_op   (shift_op),
              .i_right_shift_op (sh_right),
              .i_shamt (o_dbus_dat[26:24]),
              //Data
              .i_rs1    (rs1),
              .i_imm    (imm),
              .o_q      (bufreg_q),
              //External
              .o_dbus_adr (o_dbus_adr),
              .o_ext_rs1  (o_ext_rs1));
        
           serv_bufreg2 #(.W(W)) bufreg2
             (
              .i_clk        (clk),
              //State
              .i_en         (cnt_en),
              .i_init       (init),
              .i_cnt7       (cnt7),
              .i_cnt_done   (cnt_done),
              .i_sh_right   (sh_right),
              .i_lsb        (lsb),
              .i_bytecnt    (mem_bytecnt),
              .o_sh_done    (sh_done),
              //Control
              .i_op_b_sel   (op_b_sel),
              .i_shift_op   (shift_op),
              //Data
              .i_rs2        (rs2),
              .i_imm        (imm),
              .o_op_b       (op_b),
              .o_q          (bufreg2_q),
              //External
              .o_dat        (o_dbus_dat),
              .i_load       (dbus_ack),
              .i_dat        (dbus_rdt));
        
           serv_ctrl
             #(.RESET_PC (RESET_PC),
               .RESET_STRATEGY (RESET_STRATEGY),
               .WITH_CSR (WITH_CSR),
               .W (W))
           ctrl
             (
              .clk        (clk),
              .i_rst      (i_rst),
              //State
              .i_pc_en    (ctrl_pc_en),
              .i_cnt12to31 (cnt12to31),
              .i_cnt0     (cnt0),
              .i_cnt1     (cnt1),
              .i_cnt2     (cnt2),
              //Control
              .i_jump     (jump),
              .i_jal_or_jalr (jal_or_jalr),
              .i_utype    (utype),
              .i_pc_rel   (pc_rel),
              .i_trap     (trap | mret),
              .i_iscomp    (iscomp),
              //Data
              .i_imm      (imm),
              .i_buf      (bufreg_q),
              .i_csr_pc   (csr_pc),
              .o_rd       (ctrl_rd),
              .o_bad_pc   (bad_pc),
              //External
              .o_ibus_adr (wb_ibus_adr));
        
           serv_alu #(.W (W)) alu
             (
              .clk        (clk),
              //State
              .i_en       (cnt_en),
              .i_cnt0     (cnt0),
              .o_cmp      (alu_cmp),
              //Control
              .i_sub      (alu_sub),
              .i_bool_op  (alu_bool_op),
              .i_cmp_eq   (alu_cmp_eq),
              .i_cmp_sig  (alu_cmp_sig),
              .i_rd_sel   (alu_rd_sel),
              //Data
              .i_rs1      (rs1),
              .i_op_b     (op_b),
              .i_buf      (bufreg_q),
              .o_rd       (alu_rd));
        
           serv_rf_if
             #(.WITH_CSR (WITH_CSR), .W(W))
           rf_if
             (//RF interface
              .i_cnt_en    (cnt_en),
              .o_wreg0     (o_wreg0),
              .o_wreg1     (o_wreg1),
              .o_wen0      (o_wen0),
              .o_wen1      (o_wen1),
              .o_wdata0    (o_wdata0),
              .o_wdata1    (o_wdata1),
              .o_rreg0     (o_rreg0),
              .o_rreg1     (o_rreg1),
              .i_rdata0    (i_rdata0),
              .i_rdata1    (i_rdata1),
        
              //Trap interface
              .i_trap      (trap),
              .i_mret      (mret),
              .i_mepc      (wb_ibus_adr[B:0]),
              .i_mtval_pc  (mtval_pc),
              .i_bufreg_q  (bufreg_q),
              .i_bad_pc    (bad_pc),
              .o_csr_pc    (csr_pc),
              //CSR write port
              .i_csr_en    (csr_en),
              .i_csr_addr  (csr_addr),
              .i_csr       (csr_in),
              //RD write port
              .i_rd_wen    (rd_en),
              .i_rd_waddr  (rd_addr),
              .i_ctrl_rd   (ctrl_rd),
              .i_alu_rd    (alu_rd),
              .i_rd_alu_en (rd_alu_en),
              .i_csr_rd    (csr_rd),
              .i_rd_csr_en (rd_csr_en),
              .i_mem_rd    (mem_rd),
              .i_rd_mem_en (rd_mem_en),
        
              //RS1 read port
              .i_rs1_raddr (rs1_addr),
              .o_rs1       (rs1),
              //RS2 read port
              .i_rs2_raddr (rs2_addr),
              .o_rs2       (rs2),
        
              //CSR read port
              .o_csr       (rf_csr_out));
        
           serv_mem_if
             #(.WITH_CSR (WITH_CSR[0:0]),
               .W (W))
           mem_if
             (
              .i_clk        (clk),
              //State
              .i_bytecnt    (mem_bytecnt),
              .i_lsb        (lsb),
              .o_misalign   (mem_misalign),
              //Control
              .i_mdu_op     (mdu_op),
              .i_signed     (mem_signed),
              .i_word       (mem_word),
              .i_half       (mem_half),
              //Data
              .i_bufreg2_q  (bufreg2_q),
              .o_rd         (mem_rd),
              //External interface
              .o_wb_sel     (o_dbus_sel));
        
           generate
              if (|WITH_CSR) begin : gen_csr
        	 serv_csr
        	   #(.RESET_STRATEGY (RESET_STRATEGY),
        	     .W(W))
        	 csr
        	   (
        	    .i_clk        (clk),
        	    .i_rst        (i_rst),
        	    //State
        	    .i_trig_irq   (wb_ibus_ack),
        	    .i_en         (cnt_en),
        	    .i_cnt0to3    (cnt0to3),
        	    .i_cnt3       (cnt3),
        	    .i_cnt7       (cnt7),
        	    .i_cnt11      (cnt11),
        	    .i_cnt12      (cnt12),
        	    .i_cnt_done   (cnt_done),
        	    .i_mem_op     (!mtval_pc),
        	    .i_mtip       (i_timer_irq),
        	    .i_trap       (trap),
        	    .o_new_irq    (new_irq),
        	    //Control
        	    .i_e_op       (e_op),
        	    .i_ebreak     (ebreak),
        	    .i_mem_cmd    (o_dbus_we),
        	    .i_mstatus_en (csr_mstatus_en),
        	    .i_mie_en     (csr_mie_en    ),
        	    .i_mcause_en  (csr_mcause_en ),
        	    .i_csr_source (csr_source),
        	    .i_mret       (mret),
        	    .i_csr_d_sel  (csr_d_sel),
        	    //Data
        	    .i_rf_csr_out (rf_csr_out),
        	    .o_csr_in     (csr_in),
        	    .i_csr_imm    (csr_imm),
        	    .i_rs1        (rs1),
        	    .o_q          (csr_rd));
              end else begin : gen_no_csr
        	 assign csr_in = {W{1'b0}};
        	 assign csr_rd = {W{1'b0}};
        	 assign new_irq = 1'b0;
              end
           endgenerate
        
           generate
              if (DEBUG) begin : gen_debug
        	 serv_debug #(.W (W), .RESET_PC (RESET_PC)) debug
        	   (
        `ifdef RISCV_FORMAL
        	    .rvfi_valid     (rvfi_valid    ),
        	    .rvfi_order     (rvfi_order    ),
        	    .rvfi_insn      (rvfi_insn     ),
        	    .rvfi_trap      (rvfi_trap     ),
        	    .rvfi_halt      (rvfi_halt     ),
        	    .rvfi_intr      (rvfi_intr     ),
        	    .rvfi_mode      (rvfi_mode     ),
        	    .rvfi_ixl       (rvfi_ixl      ),
        	    .rvfi_rs1_addr  (rvfi_rs1_addr ),
        	    .rvfi_rs2_addr  (rvfi_rs2_addr ),
        	    .rvfi_rs1_rdata (rvfi_rs1_rdata),
        	    .rvfi_rs2_rdata (rvfi_rs2_rdata),
        	    .rvfi_rd_addr   (rvfi_rd_addr  ),
        	    .rvfi_rd_wdata  (rvfi_rd_wdata ),
        	    .rvfi_pc_rdata  (rvfi_pc_rdata ),
        	    .rvfi_pc_wdata  (rvfi_pc_wdata ),
        	    .rvfi_mem_addr  (rvfi_mem_addr ),
        	    .rvfi_mem_rmask (rvfi_mem_rmask),
        	    .rvfi_mem_wmask (rvfi_mem_wmask),
        	    .rvfi_mem_rdata (rvfi_mem_rdata),
        	    .rvfi_mem_wdata (rvfi_mem_wdata),
        	    .i_dbus_adr     (o_dbus_adr),
        	    .i_dbus_dat     (o_dbus_dat),
        	    .i_dbus_sel     (o_dbus_sel),
        	    .i_dbus_we      (o_dbus_we ),
        	    .i_dbus_rdt     (i_dbus_rdt),
        	    .i_dbus_ack     (i_dbus_ack),
        	    .i_ctrl_pc_en   (ctrl_pc_en),
        	    .rs1            (rs1),
        	    .rs2            (rs2),
        	    .rs1_addr       (rs1_addr),
        	    .rs2_addr       (rs2_addr),
        	    .immdec_en      (immdec_en),
        	    .rd_en          (rd_en),
        	    .trap           (trap),
        	    .i_rf_ready     (i_rf_ready),
        	    .i_ibus_cyc     (o_ibus_cyc),
        	    .two_stage_op   (two_stage_op),
        	    .init           (init),
        	    .i_ibus_adr     (o_ibus_adr),
        `endif
        	    .i_clk            (clk),
        	    .i_rst            (i_rst),
        	    .i_ibus_rdt       (i_ibus_rdt),
        	    .i_ibus_ack       (i_ibus_ack),
        	    .i_rd_addr        (rd_addr       ),
        	    .i_cnt_en         (cnt_en        ),
        	    .i_csr_in         (csr_in        ),
        	    .i_csr_mstatus_en (csr_mstatus_en),
        	    .i_csr_mie_en     (csr_mie_en    ),
        	    .i_csr_mcause_en  (csr_mcause_en ),
        	    .i_csr_en         (csr_en        ),
        	    .i_csr_addr       (csr_addr),
        	    .i_wen0           (o_wen0),
        	    .i_wdata0         (o_wdata0),
        	    .i_cnt_done       (cnt_done));
              end
           endgenerate
        
        
        generate
          if (MDU) begin: gen_mdu
            assign dbus_rdt = i_ext_ready ? i_ext_rd:i_dbus_rdt;
            assign dbus_ack = i_dbus_ack | i_ext_ready;
          end else begin : gen_no_mdu
            assign dbus_rdt = i_dbus_rdt;
            assign dbus_ack = i_dbus_ack;
          end
          assign o_ext_rs2 = o_dbus_dat;
        endgenerate
        
        endmodule
        `default_nettype wire
        
