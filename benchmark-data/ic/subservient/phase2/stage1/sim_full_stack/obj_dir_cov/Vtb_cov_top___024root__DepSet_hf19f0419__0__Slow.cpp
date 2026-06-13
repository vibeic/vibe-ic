// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_cov_top.h for the primary calling header

#include "Vtb_cov_top__pch.h"
#include "Vtb_cov_top__Syms.h"
#include "Vtb_cov_top___024root.h"

VL_ATTR_COLD void Vtb_cov_top___024root___eval_static__TOP(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_static__TOP\n"); );
    // Body
    vlSelf->tb_cov_top__DOT__init = 0U;
    ++(vlSymsp->__Vcoverage[32]);
}

VL_ATTR_COLD void Vtb_cov_top___024root___eval_initial__TOP(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_initial__TOP\n"); );
    // Body
    if ((1U & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr)) {
        ++(vlSymsp->__Vcoverage[142]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = (0xfffffffeU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr);
    }
    ++(vlSymsp->__Vcoverage[508]);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT__sim_ack = 0U;
    ++(vlSymsp->__Vcoverage[327]);
    ++(vlSymsp->__Vcoverage[605]);
    ++(vlSymsp->__Vcoverage[606]);
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_cov_top___024root___dump_triggers__stl(Vtb_cov_top___024root* vlSelf);
#endif  // VL_DEBUG

VL_ATTR_COLD void Vtb_cov_top___024root___eval_triggers__stl(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_triggers__stl\n"); );
    // Body
    vlSelf->__VstlTriggered.set(0U, (IData)(vlSelf->__VstlFirstIteration));
#ifdef VL_DEBUG
    if (VL_UNLIKELY(vlSymsp->_vm_contextp__->debug())) {
        Vtb_cov_top___024root___dump_triggers__stl(vlSelf);
    }
#endif
}

VL_ATTR_COLD void Vtb_cov_top___024root___stl_sequent__TOP__0(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___stl_sequent__TOP__0\n"); );
    // Init
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__wb_ext_stb;
    tb_cov_top__DOT__dut__DOT__wb_ext_stb = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_stb;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_stb = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_ack;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_ack = 0;
    CData/*5:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0 = 0;
    CData/*5:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1 = 0;
    CData/*5:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1 = 0;
    CData/*5:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg = 0;
    CData/*5:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_rd;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_rd = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_rd;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_rd = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_rd;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_rd = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12to31;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12to31 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt11;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt11 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_q;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_q = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rd_en;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rd_en = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_misalign;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_misalign = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bad_pc;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bad_pc = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_csr_out;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_csr_out = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vcellinp__ctrl__i_trap;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vcellinp__ctrl__i_trap = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_two_stage_op;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_two_stage_op = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_dbus_en;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_dbus_en = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_mem_en;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_mem_en = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_rs1_en;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_rs1_en = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_clr_lsb;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_clr_lsb = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_utype;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_utype = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_jal_or_jalr;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_jal_or_jalr = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_pc_rel;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_pc_rel = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_op;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_op = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_op;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_op = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_valid;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_valid = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_en;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_en = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_imm_en;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_imm_en = 0;
    CData/*1:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_addr;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_addr = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_cmp_sig;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_cmp_sig = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hb268fff8__0;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hb268fff8__0 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h95a35778__0;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h95a35778__0 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h9b5de16a__0;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h9b5de16a__0 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hcceddd3e__0;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hcceddd3e__0 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__clr_lsb;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__clr_lsb = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____VdfgTmp_h117d0fd5__0;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____VdfgTmp_h117d0fd5__0 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____VdfgTmp_h2e57f98f__0;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____VdfgTmp_h2e57f98f__0 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__byte_valid;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__byte_valid = 0;
    CData/*7:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__plus_4;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__plus_4 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_a;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_a = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_b;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_b = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_add;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_add = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_slt;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_slt = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__rs1_sx;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__rs1_sx = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__op_b_sx;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__op_b_sx = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_b;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_b = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_lt;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_lt = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_eq;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_eq = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_bool;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_bool = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT__rd_wen;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT__rd_wen = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____VdfgTmp_h61d8868c__0;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____VdfgTmp_h61d8868c__0 = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus = 0;
    // Body
    if (((IData)(vlSelf->clk) ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__clk))) {
        ++(vlSymsp->__Vcoverage[0]);
        vlSelf->tb_cov_top__DOT____Vtogcov__clk = vlSelf->clk;
    }
    if (((IData)(vlSelf->rst_in) ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__rst_in))) {
        ++(vlSymsp->__Vcoverage[1]);
        vlSelf->tb_cov_top__DOT____Vtogcov__rst_in 
            = vlSelf->rst_in;
    }
    if (((IData)(vlSelf->gpio_o) ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__gpio_o))) {
        ++(vlSymsp->__Vcoverage[2]);
        vlSelf->tb_cov_top__DOT____Vtogcov__gpio_o 
            = vlSelf->gpio_o;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_we) 
         ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__swe))) {
        ++(vlSymsp->__Vcoverage[29]);
        vlSelf->tb_cov_top__DOT____Vtogcov__swe = vlSelf->tb_cov_top__DOT__dut__DOT__br_we;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc) 
         ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__scyc))) {
        ++(vlSymsp->__Vcoverage[30]);
        vlSelf->tb_cov_top__DOT____Vtogcov__scyc = vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__init) ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__init))) {
        ++(vlSymsp->__Vcoverage[31]);
        vlSelf->tb_cov_top__DOT____Vtogcov__init = vlSelf->tb_cov_top__DOT__init;
    }
    if (((6U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_ack))) {
        ++(vlSymsp->__Vcoverage[141]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_ack 
            = (6U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate));
    }
    if ((1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                >> 3U) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_we)))) {
        ++(vlSymsp->__Vcoverage[173]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_we 
            = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                     >> 3U));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgate) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_ren))) {
        ++(vlSymsp->__Vcoverage[200]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_ren 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgate;
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rdata0)))) {
        ++(vlSymsp->__Vcoverage[318]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rdata0 
            = (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT__sim_ack) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT____Vtogcov__sim_ack))) {
        ++(vlSymsp->__Vcoverage[325]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT____Vtogcov__sim_ack 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT__sim_ack;
    }
    if (((0U != (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                 >> 0x1eU)) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT____Vtogcov__ext))) {
        ++(vlSymsp->__Vcoverage[326]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT____Vtogcov__ext 
            = (0U != (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                      >> 0x1eU));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgnt) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rgnt))) {
        ++(vlSymsp->__Vcoverage[331]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rgnt 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgnt;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rtrig1))) {
        ++(vlSymsp->__Vcoverage[337]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rtrig1 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen0_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wen0_r))) {
        ++(vlSymsp->__Vcoverage[347]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wen0_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen0_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen1_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wen1_r))) {
        ++(vlSymsp->__Vcoverage[348]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wen1_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen1_r;
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata0)))) {
        ++(vlSymsp->__Vcoverage[364]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata0 
            = ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata0)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0)));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata1))) {
        ++(vlSymsp->__Vcoverage[365]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata1 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata1;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreq_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreq_r))) {
        ++(vlSymsp->__Vcoverage[366]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreq_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreq_r;
    }
    if ((1U & ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cond_branch)))) {
        ++(vlSymsp->__Vcoverage[404]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cond_branch 
            = (1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ebreak))) {
        ++(vlSymsp->__Vcoverage[407]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ebreak 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20;
    }
    if ((IData)((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                  >> 4U) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__branch_op)))) {
        ++(vlSymsp->__Vcoverage[408]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__branch_op 
            = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                     >> 4U));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__jump) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__jump))) {
        ++(vlSymsp->__Vcoverage[419]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__jump 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__jump;
    }
    if (((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt_en))) {
        ++(vlSymsp->__Vcoverage[427]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt_en 
            = (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb));
    }
    if (((0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt0to3))) {
        ++(vlSymsp->__Vcoverage[428]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt0to3 
            = (0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm30) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_sh_signed))) {
        ++(vlSymsp->__Vcoverage[439]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_sh_signed 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm30;
    }
    if ((1U & ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                   >> 2U)) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_imm_en)))) {
        ++(vlSymsp->__Vcoverage[441]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_imm_en 
            = (1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                        >> 2U)));
    }
    if (((0U == (3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                       >> 1U))) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_cmp_eq))) {
        ++(vlSymsp->__Vcoverage[446]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_cmp_eq 
            = (0U == (3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                            >> 1U)));
    }
    if ((1U ^ (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                >> 2U) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_signed)))) {
        ++(vlSymsp->__Vcoverage[454]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_signed 
            = (1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                        >> 2U)));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__new_irq))) {
        ++(vlSymsp->__Vcoverage[470]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__new_irq 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__init_done) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__init_done))) {
        ++(vlSymsp->__Vcoverage[471]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__init_done 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__init_done;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_csr__DOT__misalign_trap_sync_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__misalign_trap_sync))) {
        ++(vlSymsp->__Vcoverage[472]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__misalign_trap_sync 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_csr__DOT__misalign_trap_sync_r;
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__o_cnt)))) {
        ++(vlSymsp->__Vcoverage[473]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__o_cnt 
            = ((6U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__o_cnt)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__ibus_cyc) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__ibus_cyc))) {
        ++(vlSymsp->__Vcoverage[478]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__ibus_cyc 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__ibus_cyc;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op21))) {
        ++(vlSymsp->__Vcoverage[500]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op21 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op22) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op22))) {
        ++(vlSymsp->__Vcoverage[501]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op22 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op22;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op26))) {
        ++(vlSymsp->__Vcoverage[502]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op26 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm25) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__imm25))) {
        ++(vlSymsp->__Vcoverage[503]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__imm25 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm25;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__c_r))) {
        ++(vlSymsp->__Vcoverage[529]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__c_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4_cy_r))) {
        ++(vlSymsp->__Vcoverage[596]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4_cy_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset_cy_r))) {
        ++(vlSymsp->__Vcoverage[599]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset_cy_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__cmp_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__cmp_r))) {
        ++(vlSymsp->__Vcoverage[617]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__cmp_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__cmp_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__add_cy_r))) {
        ++(vlSymsp->__Vcoverage[619]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__add_cy_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__signbit) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT____Vtogcov__signbit))) {
        ++(vlSymsp->__Vcoverage[634]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT____Vtogcov__signbit 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__signbit;
    }
    if ((1U ^ (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                >> 4U) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__i_mem_op)))) {
        ++(vlSymsp->__Vcoverage[639]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__i_mem_op 
            = (1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                        >> 4U)));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus_mie))) {
        ++(vlSymsp->__Vcoverage[640]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus_mie 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mpie) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus_mpie))) {
        ++(vlSymsp->__Vcoverage[641]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus_mpie 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mpie;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mie_mtie) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mie_mtie))) {
        ++(vlSymsp->__Vcoverage[642]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mie_mtie 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mie_mtie;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause31) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause31))) {
        ++(vlSymsp->__Vcoverage[643]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause31 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause31;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__timer_irq_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__timer_irq_r))) {
        ++(vlSymsp->__Vcoverage[649]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__timer_irq_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__timer_irq_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__regzero) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__regzero))) {
        ++(vlSymsp->__Vcoverage[674]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__regzero 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__regzero;
    }
    if ((1U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_rs1))) {
        ++(vlSymsp->__Vcoverage[320]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_rs1 
            = ((0xfffffffeU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_rs1) 
               | (1U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((2U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_rs1))) {
        ++(vlSymsp->__Vcoverage[321]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_rs1 
            = ((0xfffffffdU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_rs1) 
               | (2U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata0_r) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata0_r)))) {
        ++(vlSymsp->__Vcoverage[342]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata0_r 
            = ((2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata0_r)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata0_r)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata0_r) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata0_r)))) {
        ++(vlSymsp->__Vcoverage[343]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata0_r 
            = ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata0_r)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata0_r)));
    }
    if ((1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                >> 1U) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_bytecnt)))) {
        ++(vlSymsp->__Vcoverage[455]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_bytecnt 
            = ((2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_bytecnt)) 
               | (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                        >> 1U)));
    }
    if ((IData)((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                  >> 2U) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_bytecnt) 
                            >> 1U)))) {
        ++(vlSymsp->__Vcoverage[456]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_bytecnt 
            = ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_bytecnt)) 
               | (2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                        >> 1U)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__rdata) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__rdata)))) {
        ++(vlSymsp->__Vcoverage[669]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__rdata 
            = ((2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__rdata)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__rdata)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__rdata) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__rdata)))) {
        ++(vlSymsp->__Vcoverage[670]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__rdata 
            = ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__rdata)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__rdata)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__bstate)))) {
        ++(vlSymsp->__Vcoverage[201]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__bstate 
            = ((6U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__bstate)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__bstate)))) {
        ++(vlSymsp->__Vcoverage[202]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__bstate 
            = ((5U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__bstate)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__bstate)))) {
        ++(vlSymsp->__Vcoverage[203]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__bstate 
            = ((3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__bstate)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_op)))) {
        ++(vlSymsp->__Vcoverage[322]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_op 
            = ((6U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_op)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_op)))) {
        ++(vlSymsp->__Vcoverage[323]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_op 
            = ((5U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_op)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_op)))) {
        ++(vlSymsp->__Vcoverage[324]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_op 
            = ((3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_op)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata1_r) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata1_r)))) {
        ++(vlSymsp->__Vcoverage[344]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata1_r 
            = ((6U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata1_r)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata1_r)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata1_r) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata1_r)))) {
        ++(vlSymsp->__Vcoverage[345]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata1_r 
            = ((5U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata1_r)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata1_r)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata1_r) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata1_r)))) {
        ++(vlSymsp->__Vcoverage[346]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata1_r 
            = ((3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata1_r)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata1_r)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__opcode)))) {
        ++(vlSymsp->__Vcoverage[497]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__opcode 
            = ((0x1eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__opcode)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__opcode)))) {
        ++(vlSymsp->__Vcoverage[498]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__opcode 
            = ((0x1dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__opcode)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__opcode)))) {
        ++(vlSymsp->__Vcoverage[499]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__opcode 
            = ((0x1bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__opcode)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__i_shamt)))) {
        ++(vlSymsp->__Vcoverage[523]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__i_shamt 
            = ((6U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__i_shamt)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__i_shamt)))) {
        ++(vlSymsp->__Vcoverage[524]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__i_shamt 
            = ((5U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__i_shamt)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__i_shamt)))) {
        ++(vlSymsp->__Vcoverage[525]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__i_shamt 
            = ((3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__i_shamt)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi)));
    }
    if ((1U & ((0xfU & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                         - (IData)(4U)) >> 1U)) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt) 
                                                   >> 1U)))) {
        ++(vlSymsp->__Vcoverage[338]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt 
            = ((0x1dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt)) 
               | (2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                        - (IData)(4U))));
    }
    if ((1U & ((7U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                       - (IData)(4U)) >> 2U)) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt) 
                                                 >> 2U)))) {
        ++(vlSymsp->__Vcoverage[339]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt 
            = ((0x1bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt)) 
               | (4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                        - (IData)(4U))));
    }
    if ((1U & ((3U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                       - (IData)(4U)) >> 3U)) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt) 
                                                 >> 3U)))) {
        ++(vlSymsp->__Vcoverage[340]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt 
            = ((0x17U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt)) 
               | (8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                        - (IData)(4U))));
    }
    if ((1U & ((1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                       - (IData)(4U)) >> 4U)) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt) 
                                                 >> 4U)))) {
        ++(vlSymsp->__Vcoverage[341]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt 
            = ((0xfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt)) 
               | (0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                           - (IData)(4U))));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r)))) {
        ++(vlSymsp->__Vcoverage[474]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r 
            = ((0xeU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r)))) {
        ++(vlSymsp->__Vcoverage[475]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r 
            = ((0xdU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r)))) {
        ++(vlSymsp->__Vcoverage[476]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r 
            = ((0xbU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r)))) {
        ++(vlSymsp->__Vcoverage[477]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r 
            = ((7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0)))) {
        ++(vlSymsp->__Vcoverage[644]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0 
            = ((0xeU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0)))) {
        ++(vlSymsp->__Vcoverage[645]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0 
            = ((0xdU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0)))) {
        ++(vlSymsp->__Vcoverage[646]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0 
            = ((0xbU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0)))) {
        ++(vlSymsp->__Vcoverage[647]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0 
            = ((7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt)))) {
        ++(vlSymsp->__Vcoverage[332]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt 
            = ((0x1eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt)))) {
        ++(vlSymsp->__Vcoverage[333]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt 
            = ((0x1dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt)))) {
        ++(vlSymsp->__Vcoverage[334]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt 
            = ((0x1bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt)))) {
        ++(vlSymsp->__Vcoverage[335]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt 
            = ((0x17U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt)));
    }
    if ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt)))) {
        ++(vlSymsp->__Vcoverage[336]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt 
            = ((0xfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt)) 
               | (0x10U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr)))) {
        ++(vlSymsp->__Vcoverage[381]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr 
            = ((0x1eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr)))) {
        ++(vlSymsp->__Vcoverage[382]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr 
            = ((0x1dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr)))) {
        ++(vlSymsp->__Vcoverage[383]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr 
            = ((0x1bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr)))) {
        ++(vlSymsp->__Vcoverage[384]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr 
            = ((0x17U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7)));
    }
    if ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr)))) {
        ++(vlSymsp->__Vcoverage[385]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr 
            = ((0xfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr)) 
               | (0x10U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7)));
    }
    if ((1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                >> 4U) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr)))) {
        ++(vlSymsp->__Vcoverage[386]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr 
            = ((0x1eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr)) 
               | (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                        >> 4U)));
    }
    if ((1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                >> 5U) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr) 
                          >> 1U)))) {
        ++(vlSymsp->__Vcoverage[387]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr 
            = ((0x1dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr)) 
               | (2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                        >> 4U)));
    }
    if ((1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                >> 6U) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr) 
                          >> 2U)))) {
        ++(vlSymsp->__Vcoverage[388]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr 
            = ((0x1bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr)) 
               | (4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                        >> 4U)));
    }
    if ((1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                >> 7U) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr) 
                          >> 3U)))) {
        ++(vlSymsp->__Vcoverage[389]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr 
            = ((0x17U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr)) 
               | (8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                        >> 4U)));
    }
    if ((IData)((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                  >> 8U) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr) 
                            >> 4U)))) {
        ++(vlSymsp->__Vcoverage[390]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr 
            = ((0xfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr)) 
               | (0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                           >> 4U)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr)))) {
        ++(vlSymsp->__Vcoverage[391]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr 
            = ((0x1eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr)))) {
        ++(vlSymsp->__Vcoverage[392]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr 
            = ((0x1dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr)))) {
        ++(vlSymsp->__Vcoverage[393]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr 
            = ((0x1bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr)))) {
        ++(vlSymsp->__Vcoverage[394]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr 
            = ((0x17U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20)));
    }
    if ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr)))) {
        ++(vlSymsp->__Vcoverage[395]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr 
            = ((0xfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr)) 
               | (0x10U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi)))) {
        ++(vlSymsp->__Vcoverage[539]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi 
            = ((0xf7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi)));
    }
    if ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi)))) {
        ++(vlSymsp->__Vcoverage[540]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi 
            = ((0xefU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi)) 
               | (0x10U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi)));
    }
    if ((0x20U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi)))) {
        ++(vlSymsp->__Vcoverage[541]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi 
            = ((0xdfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi)) 
               | (0x20U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi)));
    }
    if ((0x40U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi)))) {
        ++(vlSymsp->__Vcoverage[542]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi 
            = ((0xbfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi)) 
               | (0x40U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi)));
    }
    if ((0x80U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi)))) {
        ++(vlSymsp->__Vcoverage[543]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi 
            = ((0x7fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi)) 
               | (0x80U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi)));
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt7 
        = ((1U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
              >> 3U));
    if ((1U & ((0x1fU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                         >> 4U)) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0)))) {
        ++(vlSymsp->__Vcoverage[305]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0 
            = ((0x3eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0)) 
               | (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                        >> 4U)));
    }
    if ((1U & ((0xfU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                        >> 5U)) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0) 
                                   >> 1U)))) {
        ++(vlSymsp->__Vcoverage[306]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0 
            = ((0x3dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0)) 
               | (2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                        >> 4U)));
    }
    if ((1U & ((7U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                      >> 6U)) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0) 
                                 >> 2U)))) {
        ++(vlSymsp->__Vcoverage[307]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0 
            = ((0x3bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0)) 
               | (4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                        >> 4U)));
    }
    if ((1U & ((3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                      >> 7U)) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0) 
                                 >> 3U)))) {
        ++(vlSymsp->__Vcoverage[308]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0 
            = ((0x37U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0)) 
               | (8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                        >> 4U)));
    }
    if ((1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                >> 8U) ^ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0) 
                          >> 4U)))) {
        ++(vlSymsp->__Vcoverage[309]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0 
            = ((0x2fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0)) 
               | (0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                           >> 4U)));
    }
    if ((0x20U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0))) {
        ++(vlSymsp->__Vcoverage[310]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0 
            = (0x1fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0));
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_wen = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1) 
                                                  & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen0_r)) 
                                                 | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                                                    & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen1_r)));
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)))) {
        ++(vlSymsp->__Vcoverage[13]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sw = ((0xfeU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)) 
                                                  | (1U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)))) {
        ++(vlSymsp->__Vcoverage[14]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sw = ((0xfdU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)) 
                                                  | (2U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)))) {
        ++(vlSymsp->__Vcoverage[15]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sw = ((0xfbU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)) 
                                                  | (4U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)))) {
        ++(vlSymsp->__Vcoverage[16]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sw = ((0xf7U 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)) 
                                                  | (8U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata)));
    }
    if ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)))) {
        ++(vlSymsp->__Vcoverage[17]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sw = ((0xefU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)) 
                                                  | (0x10U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata)));
    }
    if ((0x20U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)))) {
        ++(vlSymsp->__Vcoverage[18]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sw = ((0xdfU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)) 
                                                  | (0x20U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata)));
    }
    if ((0x40U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)))) {
        ++(vlSymsp->__Vcoverage[19]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sw = ((0xbfU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)) 
                                                  | (0x40U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata)));
    }
    if ((0x80U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)))) {
        ++(vlSymsp->__Vcoverage[20]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sw = ((0x7fU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sw)) 
                                                  | (0x80U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__sr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)))) {
        ++(vlSymsp->__Vcoverage[21]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sr = ((0xfeU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)) 
                                                  | (1U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__sr)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__sr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)))) {
        ++(vlSymsp->__Vcoverage[22]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sr = ((0xfdU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)) 
                                                  | (2U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__sr)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__sr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)))) {
        ++(vlSymsp->__Vcoverage[23]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sr = ((0xfbU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)) 
                                                  | (4U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__sr)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__sr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)))) {
        ++(vlSymsp->__Vcoverage[24]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sr = ((0xf7U 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)) 
                                                  | (8U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__sr)));
    }
    if ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__sr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)))) {
        ++(vlSymsp->__Vcoverage[25]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sr = ((0xefU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)) 
                                                  | (0x10U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__sr)));
    }
    if ((0x20U & ((IData)(vlSelf->tb_cov_top__DOT__sr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)))) {
        ++(vlSymsp->__Vcoverage[26]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sr = ((0xdfU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)) 
                                                  | (0x20U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__sr)));
    }
    if ((0x40U & ((IData)(vlSelf->tb_cov_top__DOT__sr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)))) {
        ++(vlSymsp->__Vcoverage[27]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sr = ((0xbfU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)) 
                                                  | (0x40U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__sr)));
    }
    if ((0x80U & ((IData)(vlSelf->tb_cov_top__DOT__sr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)))) {
        ++(vlSymsp->__Vcoverage[28]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sr = ((0x7fU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sr)) 
                                                  | (0x80U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__sr)));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)))) {
        ++(vlSymsp->__Vcoverage[3]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sa = ((0x3feU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)) 
                                                  | (1U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)))) {
        ++(vlSymsp->__Vcoverage[4]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sa = ((0x3fdU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)) 
                                                  | (2U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)))) {
        ++(vlSymsp->__Vcoverage[5]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sa = ((0x3fbU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)) 
                                                  | (4U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)))) {
        ++(vlSymsp->__Vcoverage[6]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sa = ((0x3f7U 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)) 
                                                  | (8U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)));
    }
    if ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)))) {
        ++(vlSymsp->__Vcoverage[7]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sa = ((0x3efU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)) 
                                                  | (0x10U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)));
    }
    if ((0x20U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)))) {
        ++(vlSymsp->__Vcoverage[8]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sa = ((0x3dfU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)) 
                                                  | (0x20U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)));
    }
    if ((0x40U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)))) {
        ++(vlSymsp->__Vcoverage[9]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sa = ((0x3bfU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)) 
                                                  | (0x40U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)));
    }
    if ((0x80U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)))) {
        ++(vlSymsp->__Vcoverage[10]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sa = ((0x37fU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)) 
                                                  | (0x80U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)));
    }
    if ((0x100U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr) 
                   ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)))) {
        ++(vlSymsp->__Vcoverage[11]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sa = ((0x2ffU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)) 
                                                  | (0x100U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)));
    }
    if ((0x200U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr) 
                   ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)))) {
        ++(vlSymsp->__Vcoverage[12]);
        vlSelf->tb_cov_top__DOT____Vtogcov__sa = ((0x1ffU 
                                                   & (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__sa)) 
                                                  | (0x200U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)));
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__byte_valid 
        = (1U & ((IData)((0U == (3U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data))) 
                 | ((IData)((0U == (6U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)))) 
                    | (((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                            >> 2U)) & (~ (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                                          >> 1U))) 
                       | (((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                               >> 2U)) & (~ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data)) 
                          | ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                                 >> 1U)) & (~ (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                                               >> 1U))))))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt1 
        = ((0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
              >> 1U));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_mem_en 
        = (IData)((0U == (5U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    if ((1U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[544]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfffffeU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (1U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((2U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[545]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfffffdU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (2U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((4U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[546]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfffffbU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (4U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((8U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[547]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfffff7U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (8U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x10U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[548]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xffffefU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x10U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x20U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[549]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xffffdfU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x20U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x40U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[550]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xffffbfU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x40U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x80U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[551]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xffff7fU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x80U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x100U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[552]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfffeffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x100U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x200U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[553]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfffdffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x200U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x400U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[554]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfffbffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x400U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x800U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[555]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfff7ffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x800U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x1000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[556]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xffefffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x1000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x2000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[557]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xffdfffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x2000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x4000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[558]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xffbfffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x4000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x8000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[559]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xff7fffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x8000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x10000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[560]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfeffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x10000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x20000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[561]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfdffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x20000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x40000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[562]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xfbffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x40000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x80000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[563]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xf7ffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x80000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x100000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[564]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xefffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x100000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x200000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[565]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xdfffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x200000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x400000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[566]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0xbfffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x400000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    if ((0x800000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo))) {
        ++(vlSymsp->__Vcoverage[567]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo 
            = ((0x7fffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo) 
               | (0x800000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo));
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_rs1_en 
        = (1U & ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                     >> 4U)) | (IData)((1U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel 
        = ((8U & (((3U == (3U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data)) 
                   << 3U) | (0xfffffff8U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                                             << 2U) 
                                            | (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                                                << 3U) 
                                               & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                                                  << 2U)))))) 
           | ((4U & (((2U == (3U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data)) 
                      << 2U) | (0xfffffffcU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                                               << 1U)))) 
              | ((2U & (((1U == (3U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data)) 
                         << 1U) | ((0xfffffffeU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)) 
                                   | (((~ (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                                           >> 1U)) 
                                       & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)) 
                                      << 1U)))) | (0U 
                                                   == 
                                                   (3U 
                                                    & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data)))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d 
        = (1U & ((4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))
                  ? ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                     >> 4U) : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0)));
    if ((4U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[143]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfffffffbU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (4U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((8U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[144]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfffffff7U & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (8U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x10U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[145]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffffffefU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x10U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x20U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[146]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffffffdfU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x20U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x40U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[147]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffffffbfU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x40U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x80U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[148]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffffff7fU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x80U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x100U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[149]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfffffeffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x100U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x200U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[150]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfffffdffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x200U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x400U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[151]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfffffbffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x400U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x800U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[152]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfffff7ffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x800U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x1000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[153]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffffefffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x1000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x2000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[154]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffffdfffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x2000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x4000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[155]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffffbfffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x4000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x8000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[156]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffff7fffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x8000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x10000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[157]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfffeffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x10000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x20000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[158]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfffdffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x20000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x40000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[159]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfffbffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x40000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x80000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[160]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfff7ffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x80000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x100000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[161]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffefffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x100000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x200000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[162]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffdfffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x200000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x400000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[163]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xffbfffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x400000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x800000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[164]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xff7fffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x800000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x1000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[165]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfeffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x1000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x2000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[166]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfdffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x2000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x4000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[167]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xfbffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x4000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x8000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[168]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xf7ffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x8000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x10000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[169]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xefffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x10000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x20000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[170]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xdfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x20000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((0x40000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr))) {
        ++(vlSymsp->__Vcoverage[171]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0xbfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x40000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if (((vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
          ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
         >> 0x1fU)) {
        ++(vlSymsp->__Vcoverage[172]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr 
            = ((0x7fffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr) 
               | (0x80000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    }
    if ((1U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[109]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffffffeU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (1U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((2U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[110]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffffffdU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (2U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((4U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[111]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffffffbU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (4U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((8U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[112]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffffff7U & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (8U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x10U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[113]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffffffefU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x10U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x20U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[114]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffffffdfU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x20U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x40U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[115]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffffffbfU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x40U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x80U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[116]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffffff7fU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x80U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x100U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[117]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffffeffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x100U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x200U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[118]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffffdffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x200U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x400U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[119]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffffbffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x400U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x800U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[120]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffff7ffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x800U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x1000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[121]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffffefffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x1000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x2000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[122]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffffdfffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x2000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x4000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[123]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffffbfffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x4000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x8000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[124]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffff7fffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x8000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x10000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[125]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffeffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x10000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x20000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[126]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffdffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x20000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x40000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[127]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfffbffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x40000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x80000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[128]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfff7ffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x80000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x100000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[129]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffefffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x100000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x200000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[130]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffdfffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x200000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x400000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[131]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xffbfffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x400000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x800000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[132]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xff7fffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x800000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x1000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[133]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfeffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x1000000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x2000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[134]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfdffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x2000000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x4000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[135]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xfbffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x4000000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x8000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[136]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xf7ffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x8000000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x10000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[137]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xefffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x10000000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x20000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[138]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xdfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x20000000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((0x40000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt))) {
        ++(vlSymsp->__Vcoverage[139]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0xbfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x40000000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if (((vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
          ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
         >> 0x1fU)) {
        ++(vlSymsp->__Vcoverage[140]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt 
            = ((0x7fffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt) 
               | (0x80000000U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm));
    }
    if ((1U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[217]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffffffeU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (1U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((2U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[218]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffffffdU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (2U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((4U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[219]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffffffbU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (4U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((8U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[220]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffffff7U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (8U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x10U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[221]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffffffefU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x10U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x20U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[222]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffffffdfU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x20U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x40U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[223]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffffffbfU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x40U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x80U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[224]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffffff7fU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x80U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x100U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[225]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffffeffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x100U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x200U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[226]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffffdffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x200U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x400U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[227]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffffbffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x400U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x800U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[228]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffff7ffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x800U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x1000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[229]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffffefffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x1000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x2000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[230]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffffdfffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x2000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x4000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[231]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffffbfffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x4000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x8000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[232]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffff7fffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x8000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x10000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[233]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffeffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x10000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x20000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[234]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffdffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x20000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x40000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[235]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfffbffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x40000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x80000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[236]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfff7ffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x80000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x100000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[237]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffefffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x100000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x200000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[238]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffdfffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x200000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x400000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[239]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xffbfffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x400000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x800000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[240]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xff7fffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x800000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x1000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[241]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfeffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x1000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x2000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[242]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfdffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x2000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x4000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[243]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xfbffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x4000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x8000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[244]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xf7ffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x8000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x10000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[245]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xefffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x10000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x20000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[246]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xdfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x20000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if ((0x40000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr))) {
        ++(vlSymsp->__Vcoverage[247]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0xbfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x40000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    if (((vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
          ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
         >> 0x1fU)) {
        ++(vlSymsp->__Vcoverage[248]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr 
            = ((0x7fffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr) 
               | (0x80000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr));
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_clr_lsb 
        = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
            >> 4U) & ((0U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))) 
                      | (3U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid 
        = (1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                  >> 1U) | ((0U == (3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                                          >> 1U))) 
                            | ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                                   >> 2U)) & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2_q 
        = (((3U == (3U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data)) 
            & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi)) 
           | (((2U == (3U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data)) 
               & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                  >> 0x10U)) | (((1U == (3U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data)) 
                                 & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                                    >> 8U)) | ((0U 
                                                == 
                                                (3U 
                                                 & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data)) 
                                               & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_alu_en 
        = (IData)((4U == (0x15U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____VdfgTmp_hb0ab83f8__0 
        = ((~ (IData)((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)))) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__init_done));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__plus_4 
        = ((0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
              >> 2U));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt3 
        = ((0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
              >> 3U));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt11 
        = ((2U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
              >> 3U));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12 
        = ((3U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel 
        = ((4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)) 
           | (((1U == (3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                             >> 1U))) << 1U) | (0U 
                                                == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_dbus_en 
        = (IData)((0U == (0x14U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_misalign 
        = (1U & ((vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                  & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                     | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                        >> 1U))) | ((vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)) 
                                    >> 1U)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_jal_or_jalr 
        = (IData)((0x11U == (0x11U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12to31 
        = (IData)((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                    >> 2U) | (3U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_cmp_sig 
        = (1U & (~ (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                     & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                        >> 1U)) | (IData)((6U == (6U 
                                                  & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)))))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h95a35778__0 
        = (IData)((5U == (5U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_sub 
        = (1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                  >> 1U) | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                            | ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                                 >> 3U) & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm30)) 
                               | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                                  >> 4U)))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0 
        = ((0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_addr 
        = ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20) 
             & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26)) 
            << 1U) | (1U & ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26)) 
                            | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op 
        = (1U & ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                     >> 1U)) & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                                >> 2U)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_valid 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20) 
           | ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21)) 
              & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hb268fff8__0 
        = (IData)((0U == (0x11U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata = (
                                                   (~ 
                                                    (- (IData)((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__regzero)))) 
                                                   & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__rdata));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl 
        = ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                  >> 1U)) | (((IData)((0x10U == (0x11U 
                                                 & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)))) 
                              << 2U) | ((((0U == (3U 
                                                  & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))) 
                                          | (0U == 
                                             (3U & 
                                              ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                                               >> 1U)))) 
                                         << 1U) | (8U 
                                                   == 
                                                   (0xfU 
                                                    & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
        = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
            << 0x18U) | vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
        = ((0U != (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                   >> 0x1eU)) ? 0U : vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm);
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb 
        = ((~ (IData)(vlSelf->rst_in)) & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__ibus_cyc));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done 
        = ((7U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
              >> 3U));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h9b5de16a__0 
        = (IData)((0x14U == (0x14U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt7) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt7))) {
        ++(vlSymsp->__Vcoverage[434]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt7 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt7;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_wen) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wen))) {
        ++(vlSymsp->__Vcoverage[187]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wen 
            = vlSelf->tb_cov_top__DOT__dut__DOT__rf_wen;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_wdata = (3U 
                                                   & ((1U 
                                                       & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt))
                                                       ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata1_r)
                                                       : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata0_r)));
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_wdata) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wdata)))) {
        ++(vlSymsp->__Vcoverage[185]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wdata 
            = ((2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wdata)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_wdata)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_wdata) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wdata)))) {
        ++(vlSymsp->__Vcoverage[186]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wdata 
            = ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wdata)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_wdata)));
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__byte_valid) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__byte_valid))) {
        ++(vlSymsp->__Vcoverage[568]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__byte_valid 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__byte_valid;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt1))) {
        ++(vlSymsp->__Vcoverage[431]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt1 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt1;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_mem_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_mem_en))) {
        ++(vlSymsp->__Vcoverage[413]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_mem_en 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_mem_en;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_rs1_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_rs1_en))) {
        ++(vlSymsp->__Vcoverage[440]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_rs1_en 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_rs1_en;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____VdfgTmp_h117d0fd5__0 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0) 
           & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_rs1_en));
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel)))) {
        ++(vlSymsp->__Vcoverage[103]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel 
            = ((0xeU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel)))) {
        ++(vlSymsp->__Vcoverage[104]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel 
            = ((0xdU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel)))) {
        ++(vlSymsp->__Vcoverage[105]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel 
            = ((0xbU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel)))) {
        ++(vlSymsp->__Vcoverage[106]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel 
            = ((7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel)));
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__d))) {
        ++(vlSymsp->__Vcoverage[650]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__d 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_clr_lsb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_clr_lsb))) {
        ++(vlSymsp->__Vcoverage[442]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_clr_lsb 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_clr_lsb;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT____Vtogcov__dat_valid))) {
        ++(vlSymsp->__Vcoverage[635]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT____Vtogcov__dat_valid 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2_q) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg2_q))) {
        ++(vlSymsp->__Vcoverage[444]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg2_q 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2_q;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2_q) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__o_q))) {
        ++(vlSymsp->__Vcoverage[538]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__o_q 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2_q;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_rd 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid)
            ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2_q)
            : ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__signbit) 
               & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                     >> 2U))));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_alu_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_alu_en))) {
        ++(vlSymsp->__Vcoverage[411]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_alu_en 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_alu_en;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__plus_4) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt2))) {
        ++(vlSymsp->__Vcoverage[432]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt2 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__plus_4;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__plus_4) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__plus_4))) {
        ++(vlSymsp->__Vcoverage[600]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__plus_4 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__plus_4;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy 
        = (1U & (((1U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr) 
                  + ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__plus_4) 
                     + (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy_r))) 
                 >> 1U));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4 
        = (1U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                 + ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__plus_4) 
                    + (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy_r))));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt3) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt3))) {
        ++(vlSymsp->__Vcoverage[433]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt3 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt3;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt11) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt11))) {
        ++(vlSymsp->__Vcoverage[435]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt11 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt11;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt12))) {
        ++(vlSymsp->__Vcoverage[436]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt12 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus 
        = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt3) 
            & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie)) 
           | ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt11) 
              | (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12)));
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd_sel)))) {
        ++(vlSymsp->__Vcoverage[449]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd_sel 
            = ((6U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd_sel)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd_sel)))) {
        ++(vlSymsp->__Vcoverage[450]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd_sel 
            = ((5U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd_sel)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd_sel)))) {
        ++(vlSymsp->__Vcoverage[451]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd_sel 
            = ((3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd_sel)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel)));
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_dbus_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__dbus_en))) {
        ++(vlSymsp->__Vcoverage[469]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__dbus_en 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_dbus_en;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_misalign) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_misalign))) {
        ++(vlSymsp->__Vcoverage[458]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_misalign 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_misalign;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_stb 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____VdfgTmp_hb0ab83f8__0) 
           & ((~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_misalign)) 
              & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_dbus_en)));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_jal_or_jalr) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__jal_or_jalr))) {
        ++(vlSymsp->__Vcoverage[420]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__jal_or_jalr 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_jal_or_jalr;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_op 
        = (1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                  >> 2U) | ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_jal_or_jalr) 
                            | (IData)((0U == (9U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)))))));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12to31) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt12to31))) {
        ++(vlSymsp->__Vcoverage[429]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt12to31 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12to31;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_cmp_sig) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_cmp_sig))) {
        ++(vlSymsp->__Vcoverage[447]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_cmp_sig 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_cmp_sig;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__rs1_sx 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_cmp_sig) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_utype 
        = ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
               >> 4U)) & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h95a35778__0));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_sub) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_sub))) {
        ++(vlSymsp->__Vcoverage[445]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_sub 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_sub;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt0))) {
        ++(vlSymsp->__Vcoverage[430]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt0 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__clr_lsb 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_clr_lsb) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_slt 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__cmp_r) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0));
    if ((1U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_addr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_addr)))) {
        ++(vlSymsp->__Vcoverage[464]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_addr 
            = ((2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_addr)) 
               | (1U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_addr)));
    }
    if ((2U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_addr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_addr)))) {
        ++(vlSymsp->__Vcoverage[465]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_addr 
            = ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_addr)) 
               | (2U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_addr)));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__shift_op))) {
        ++(vlSymsp->__Vcoverage[409]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__shift_op 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_valid) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__csr_valid))) {
        ++(vlSymsp->__Vcoverage[504]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__csr_valid 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_valid;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_two_stage_op 
        = (1U & ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                     >> 2U)) | ((IData)(((1U == (3U 
                                                 & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))) 
                                         & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hb268fff8__0))) 
                                | (IData)(((2U == (6U 
                                                   & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))) 
                                           & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hb268fff8__0))))));
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_rdata)))) {
        ++(vlSymsp->__Vcoverage[198]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_rdata 
            = ((2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_rdata)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_rdata)))) {
        ++(vlSymsp->__Vcoverage[199]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_rdata 
            = ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_rdata)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata)));
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1 
        = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1)
                  ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata)
                  : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata1)));
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl)))) {
        ++(vlSymsp->__Vcoverage[396]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl 
            = ((0xeU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl)))) {
        ++(vlSymsp->__Vcoverage[397]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl 
            = ((0xdU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl)))) {
        ++(vlSymsp->__Vcoverage[398]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl 
            = ((0xbU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl)))) {
        ++(vlSymsp->__Vcoverage[399]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl 
            = ((7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl)));
    }
    if ((1U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[71]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffffffeU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (1U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((2U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[72]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffffffdU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (2U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((4U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[73]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffffffbU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (4U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((8U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[74]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffffff7U & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (8U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x10U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[75]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffffffefU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x10U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x20U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[76]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffffffdfU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x20U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x40U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[77]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffffffbfU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x40U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x80U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[78]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffffff7fU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x80U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x100U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[79]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffffeffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x100U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x200U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[80]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffffdffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x200U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x400U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[81]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffffbffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x400U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x800U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[82]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffff7ffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x800U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x1000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[83]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffffefffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x1000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x2000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[84]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffffdfffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x2000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x4000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[85]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffffbfffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x4000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x8000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[86]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffff7fffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x8000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x10000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[87]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffeffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x10000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x20000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[88]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffdffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x20000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x40000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[89]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfffbffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x40000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x80000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[90]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfff7ffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x80000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x100000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[91]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffefffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x100000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x200000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[92]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffdfffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x200000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x400000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[93]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xffbfffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x400000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x800000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[94]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xff7fffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x800000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x1000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[95]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfeffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x1000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x2000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[96]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfdffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x2000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x4000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[97]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xfbffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x4000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x8000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[98]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xf7ffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x8000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x10000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[99]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xefffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x10000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x20000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[100]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xdfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x20000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((0x40000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat))) {
        ++(vlSymsp->__Vcoverage[101]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0xbfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x40000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if (((vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
          ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
         >> 0x1fU)) {
        ++(vlSymsp->__Vcoverage[102]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat 
            = ((0x7fffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat) 
               | (0x80000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat));
    }
    if ((1U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[252]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffffffeU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (1U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((2U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[253]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffffffdU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (2U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((4U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[254]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffffffbU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (4U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((8U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[255]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffffff7U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (8U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x10U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[256]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffffffefU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x10U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x20U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[257]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffffffdfU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x20U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x40U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[258]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffffffbfU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x40U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x80U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[259]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffffff7fU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x80U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x100U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[260]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffffeffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x100U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x200U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[261]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffffdffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x200U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x400U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[262]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffffbffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x400U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x800U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[263]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffff7ffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x800U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x1000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[264]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffffefffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x1000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x2000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[265]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffffdfffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x2000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x4000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[266]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffffbfffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x4000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x8000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[267]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffff7fffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x8000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x10000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[268]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffeffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x10000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x20000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[269]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffdffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x20000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x40000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[270]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfffbffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x40000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x80000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[271]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfff7ffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x80000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x100000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[272]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffefffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x100000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x200000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[273]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffdfffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x200000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x400000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[274]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xffbfffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x400000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x800000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[275]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xff7fffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x800000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x1000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[276]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfeffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x1000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x2000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[277]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfdffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x2000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x4000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[278]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xfbffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x4000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x8000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[279]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xf7ffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x8000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x10000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[280]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xefffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x10000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x20000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[281]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xdfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x20000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if ((0x40000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt))) {
        ++(vlSymsp->__Vcoverage[282]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0xbfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x40000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if (((vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
          ^ vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
         >> 0x1fU)) {
        ++(vlSymsp->__Vcoverage[283]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt 
            = ((0x7fffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt) 
               | (0x80000000U & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt));
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_stb))) {
        ++(vlSymsp->__Vcoverage[249]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_stb 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we = 
        (1U & ((~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb)) 
               & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                  >> 3U)));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb) 
           & (6U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_ack 
        = ((~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb)) 
           & (6U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)));
    vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr = 
        ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb)
          ? vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr
          : (0xfffffffcU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt_done))) {
        ++(vlSymsp->__Vcoverage[437]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt_done 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause 
        = (1U & ((0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt))
                  ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0)
                  : ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done) 
                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause31))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_pc_rel 
        = ((0U == (7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))) 
           | ((3U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))) 
              | (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h9b5de16a__0) 
                  & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20)) 
                 | (0U == (3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                                 >> 3U))))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_mret 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h9b5de16a__0) 
           & ((~ (IData)((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)))) 
              & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_op 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h9b5de16a__0) 
           & (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_imm_en 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h9b5de16a__0) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
              >> 2U));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_e_op 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h9b5de16a__0) 
           & ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21)) 
              & (~ (IData)((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))))));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_rd) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_rd))) {
        ++(vlSymsp->__Vcoverage[416]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_rd 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_rd;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_rd) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__i_mem_rd))) {
        ++(vlSymsp->__Vcoverage[632]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__i_mem_rd 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_rd;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4_cy))) {
        ++(vlSymsp->__Vcoverage[595]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4_cy 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4))) {
        ++(vlSymsp->__Vcoverage[594]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus))) {
        ++(vlSymsp->__Vcoverage[651]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_stb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_stb))) {
        ++(vlSymsp->__Vcoverage[251]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_stb 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_stb;
    }
    tb_cov_top__DOT__dut__DOT__wb_ext_stb = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_stb) 
                                             & (0U 
                                                != 
                                                (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                                                 >> 0x1eU)));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_stb 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_stb) 
           & (0U == (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                     >> 0x1eU)));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_op) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_op))) {
        ++(vlSymsp->__Vcoverage[410]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_op 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_op;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__rs1_sx) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__rs1_sx))) {
        ++(vlSymsp->__Vcoverage[620]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__rs1_sx 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__rs1_sx;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_utype) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__utype))) {
        ++(vlSymsp->__Vcoverage[421]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__utype 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_utype;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__clr_lsb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__clr_lsb))) {
        ++(vlSymsp->__Vcoverage[530]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__clr_lsb 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__clr_lsb;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_slt) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_slt))) {
        ++(vlSymsp->__Vcoverage[616]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_slt 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_slt;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_two_stage_op) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__two_stage_op))) {
        ++(vlSymsp->__Vcoverage[405]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__two_stage_op 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_two_stage_op;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init 
        = ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq) 
               | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__init_done))) 
           & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_two_stage_op));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rdata1))) {
        ++(vlSymsp->__Vcoverage[319]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rdata1 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__o_rdata1))) {
        ++(vlSymsp->__Vcoverage[330]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__o_rdata1 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_we))) {
        ++(vlSymsp->__Vcoverage[107]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_we 
            = vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_ack))) {
        ++(vlSymsp->__Vcoverage[250]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_ack 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_ack) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dmem_ack))) {
        ++(vlSymsp->__Vcoverage[286]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dmem_ack 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_ack;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_ack) 
           | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT__sim_ack));
    if ((1U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[39]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffffffeU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (1U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((2U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[40]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffffffdU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (2U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((4U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[41]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffffffbU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (4U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((8U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
               ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[42]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffffff7U & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (8U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x10U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[43]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffffffefU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x10U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x20U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[44]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffffffdfU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x20U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x40U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[45]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffffffbfU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x40U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x80U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                  ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[46]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffffff7fU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x80U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x100U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[47]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffffeffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x100U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x200U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[48]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffffdffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x200U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x400U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[49]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffffbffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x400U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x800U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                   ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[50]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffff7ffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x800U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x1000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[51]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffffefffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x1000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x2000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[52]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffffdfffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x2000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x4000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[53]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffffbfffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x4000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x8000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                    ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[54]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffff7fffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x8000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x10000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[55]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffeffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x10000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x20000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[56]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffdffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x20000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x40000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[57]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfffbffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x40000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x80000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                     ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[58]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfff7ffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x80000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x100000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[59]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffefffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x100000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x200000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[60]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffdfffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x200000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x400000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[61]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xffbfffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x400000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x800000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                      ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[62]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xff7fffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x800000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x1000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[63]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfeffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x1000000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x2000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[64]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfdffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x2000000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x4000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[65]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xfbffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x4000000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x8000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                       ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[66]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xf7ffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x8000000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x10000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[67]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xefffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x10000000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x20000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[68]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xdfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x20000000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if ((0x40000000U & (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
                        ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr))) {
        ++(vlSymsp->__Vcoverage[69]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0xbfffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x40000000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if (((vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr 
          ^ vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
         >> 0x1fU)) {
        ++(vlSymsp->__Vcoverage[70]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr 
            = ((0x7fffffffU & vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr) 
               | (0x80000000U & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause))) {
        ++(vlSymsp->__Vcoverage[648]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_pc_rel) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__pc_rel))) {
        ++(vlSymsp->__Vcoverage[425]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__pc_rel 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_pc_rel;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_a 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_pc_rel) 
           & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr);
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_mret) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mret))) {
        ++(vlSymsp->__Vcoverage[422]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mret 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_mret;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_op) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_csr_en))) {
        ++(vlSymsp->__Vcoverage[412]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_csr_en 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_op;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mcause_en 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_op) 
           & ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20)) 
              & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hcceddd3e__0 
        = ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26)) 
           & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_op));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_en 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_op) 
           & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_valid));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_imm_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_imm_en))) {
        ++(vlSymsp->__Vcoverage[466]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_imm_en 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_imm_en;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en 
        = (((IData)((1U != (0x1dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)))) 
            << 3U) | ((((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h9b5de16a__0) 
                        | (8U != (9U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)))) 
                       << 2U) | ((((1U == (3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                                                 >> 1U))) 
                                   | ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h95a35778__0) 
                                      | (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_imm_en))) 
                                  << 1U) | (1U & (~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_op))))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__signbit 
        = ((~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_imm_en)) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm31));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_e_op) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__e_op))) {
        ++(vlSymsp->__Vcoverage[406]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__e_op 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_e_op;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_e_op) 
           | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq) 
              | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_csr__DOT__misalign_trap_sync_r)));
    if (((IData)(tb_cov_top__DOT__dut__DOT__wb_ext_stb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_stb))) {
        ++(vlSymsp->__Vcoverage[174]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_stb 
            = tb_cov_top__DOT__dut__DOT__wb_ext_stb;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_stb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dmem_stb))) {
        ++(vlSymsp->__Vcoverage[285]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dmem_stb 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_stb;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_stb = 
        ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_stb) 
         | (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__init))) {
        ++(vlSymsp->__Vcoverage[426]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__init 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_pc_en 
        = ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init)) 
           & (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__shift_en 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op)
            ? ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
               & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init) 
                  & (0U == (6U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)))))
            : ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
               & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__byte_valid)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rd_en 
        = ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init)) 
           & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_op));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__last_init 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_en 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op) 
           & ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init)) 
              | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done) 
                 & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                    >> 2U))));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_ack))) {
        ++(vlSymsp->__Vcoverage[284]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_ack 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_a) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__offset_a))) {
        ++(vlSymsp->__Vcoverage[602]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__offset_a 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_a;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mcause_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_mcause_en))) {
        ++(vlSymsp->__Vcoverage[462]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_mcause_en 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mcause_en;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mie_en 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hcceddd3e__0) 
           & ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20)) 
              & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op22)));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mstatus_en 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hcceddd3e__0) 
           & ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op22)) 
              & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20))));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_en))) {
        ++(vlSymsp->__Vcoverage[463]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_en 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_en;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_csr_out 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_en) 
           & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1));
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en)))) {
        ++(vlSymsp->__Vcoverage[400]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en 
            = ((0xeU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en)))) {
        ++(vlSymsp->__Vcoverage[401]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en 
            = ((0xdU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en)))) {
        ++(vlSymsp->__Vcoverage[402]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en 
            = ((0xbU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en)))) {
        ++(vlSymsp->__Vcoverage[403]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en 
            = ((7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en)));
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm 
        = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)
                  ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__signbit)
                  : ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl))
                      ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7)
                      : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20))));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__trap))) {
        ++(vlSymsp->__Vcoverage[424]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__trap 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wen1 
        = ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
           & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_en) 
              | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vcellinp__ctrl__i_trap 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_mret) 
           | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____VdfgTmp_h61d8868c__0 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
           | ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_en) 
              | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_mret)));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_stb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_stb))) {
        ++(vlSymsp->__Vcoverage[108]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_stb 
            = vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_stb;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_pc_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ctrl_pc_en))) {
        ++(vlSymsp->__Vcoverage[418]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ctrl_pc_en 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_pc_en;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__shift_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__shift_en))) {
        ++(vlSymsp->__Vcoverage[569]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__shift_en 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__shift_en;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rd_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_en))) {
        ++(vlSymsp->__Vcoverage[452]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_en 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rd_en;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT__rd_wen 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rd_en) 
           & (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7)));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__last_init) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__last_init))) {
        ++(vlSymsp->__Vcoverage[480]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__last_init 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__last_init;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_en))) {
        ++(vlSymsp->__Vcoverage[570]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_en 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_en;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mie_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_mie_en))) {
        ++(vlSymsp->__Vcoverage[461]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_mie_en 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mie_en;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mstatus_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_mstatus_en))) {
        ++(vlSymsp->__Vcoverage[460]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_mstatus_en 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mstatus_en;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_csr_out) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rf_csr_out))) {
        ++(vlSymsp->__Vcoverage[468]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rf_csr_out 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_csr_out;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_csr_out) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__o_csr))) {
        ++(vlSymsp->__Vcoverage[630]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__o_csr 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_csr_out;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd 
        = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mstatus_en) 
            & ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
               & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus))) 
           | ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_csr_out) 
              | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mcause_en) 
                 & ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
                    & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause)))));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__imm))) {
        ++(vlSymsp->__Vcoverage[423]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__imm 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT____Vtogcov__o_imm))) {
        ++(vlSymsp->__Vcoverage[509]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT____Vtogcov__o_imm 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____VdfgTmp_h2e57f98f__0 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm) 
           & ((~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__clr_lsb)) 
              & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                    >> 2U))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b 
        = ((8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))
            ? (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1)
            : (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wen1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wen1))) {
        ++(vlSymsp->__Vcoverage[302]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wen1 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wen1;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vcellinp__ctrl__i_trap) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__i_trap))) {
        ++(vlSymsp->__Vcoverage[591]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__i_trap 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vcellinp__ctrl__i_trap;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)
            ? 0x23U : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7));
    if ((1U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)))) {
        ++(vlSymsp->__Vcoverage[289]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0 
            = ((0x3eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)) 
               | (1U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0)));
    }
    if ((2U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)))) {
        ++(vlSymsp->__Vcoverage[290]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0 
            = ((0x3dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)) 
               | (2U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0)));
    }
    if ((4U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)))) {
        ++(vlSymsp->__Vcoverage[291]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0 
            = ((0x3bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)) 
               | (4U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0)));
    }
    if ((8U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)))) {
        ++(vlSymsp->__Vcoverage[292]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0 
            = ((0x37U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)) 
               | (8U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0)));
    }
    if ((0x10U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)))) {
        ++(vlSymsp->__Vcoverage[293]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0 
            = ((0x2fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)) 
               | (0x10U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0)));
    }
    if ((0x20U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)))) {
        ++(vlSymsp->__Vcoverage[294]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0 
            = ((0x1fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0)) 
               | (0x20U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0)));
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)
            ? 0x22U : (0x20U | (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_addr)));
    if ((1U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)))) {
        ++(vlSymsp->__Vcoverage[295]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1 
            = ((0x3eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)) 
               | (1U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1)));
    }
    if ((2U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)))) {
        ++(vlSymsp->__Vcoverage[296]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1 
            = ((0x3dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)) 
               | (2U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1)));
    }
    if ((4U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)))) {
        ++(vlSymsp->__Vcoverage[297]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1 
            = ((0x3bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)) 
               | (4U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1)));
    }
    if ((8U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)))) {
        ++(vlSymsp->__Vcoverage[298]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1 
            = ((0x37U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)) 
               | (8U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1)));
    }
    if ((0x10U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)))) {
        ++(vlSymsp->__Vcoverage[299]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1 
            = ((0x2fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)) 
               | (0x10U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1)));
    }
    if ((0x20U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)))) {
        ++(vlSymsp->__Vcoverage[300]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1 
            = ((0x1fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1)) 
               | (0x20U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1)));
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1 
        = (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____VdfgTmp_h61d8868c__0) 
            << 5U) | ((0x1cU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20) 
                                & ((- (IData)((1U & 
                                               (~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____VdfgTmp_h61d8868c__0))))) 
                                   << 2U))) | (3U & 
                                               ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
                                                | (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_mret) 
                                                    << 1U) 
                                                   | (((- (IData)((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_en))) 
                                                       & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_addr)) 
                                                      | ((- (IData)(
                                                                    (1U 
                                                                     & (~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____VdfgTmp_h61d8868c__0))))) 
                                                         & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20))))))));
    if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt))) {
        tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg1;
        tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1;
    } else {
        tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__wreg0;
        tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg 
            = (0x1fU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                        >> 4U));
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT__rd_wen) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__rd_wen))) {
        ++(vlSymsp->__Vcoverage[633]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__rd_wen 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT__rd_wen;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wen0 
        = ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
              | (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT__rd_wen)));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_rd))) {
        ++(vlSymsp->__Vcoverage[417]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_rd 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__i_csr_rd))) {
        ++(vlSymsp->__Vcoverage[631]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__i_csr_rd 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in 
        = ((1U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)))
            ? (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d)
            : ((2U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)))
                ? ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd) 
                   | (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d))
                : ((3U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)))
                    ? ((~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d)) 
                       & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd))
                    : ((0U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))) 
                       & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd)))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c 
        = (1U & (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____VdfgTmp_h117d0fd5__0) 
                  + ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____VdfgTmp_h2e57f98f__0) 
                     + (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c_r))) 
                 >> 1U));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__q 
        = (1U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____VdfgTmp_h117d0fd5__0) 
                 + ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____VdfgTmp_h2e57f98f__0) 
                    + (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c_r))));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__op_b))) {
        ++(vlSymsp->__Vcoverage[453]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__op_b 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__o_op_b))) {
        ++(vlSymsp->__Vcoverage[537]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__o_op_b 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_bool 
        = (1U & (((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)) 
                  & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b) 
                     ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0))) 
                 | (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                     >> 1U) & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b) 
                               & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0)))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__op_b_sx 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_cmp_sig) 
           & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_b 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b) 
           ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_sub));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next 
        = (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b) 
            << 7U) | ((0x40U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
                                >> 1U)) | (0x3fU & 
                                           ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
                                            - (IData)(1U)))));
    if ((1U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)))) {
        ++(vlSymsp->__Vcoverage[349]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg 
            = ((0x3eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)) 
               | (1U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg)));
    }
    if ((2U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)))) {
        ++(vlSymsp->__Vcoverage[350]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg 
            = ((0x3dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)) 
               | (2U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg)));
    }
    if ((4U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)))) {
        ++(vlSymsp->__Vcoverage[351]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg 
            = ((0x3bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)) 
               | (4U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg)));
    }
    if ((8U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)))) {
        ++(vlSymsp->__Vcoverage[352]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg 
            = ((0x37U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)) 
               | (8U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg)));
    }
    if ((0x10U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)))) {
        ++(vlSymsp->__Vcoverage[353]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg 
            = ((0x2fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)) 
               | (0x10U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg)));
    }
    if ((0x20U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)))) {
        ++(vlSymsp->__Vcoverage[354]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg 
            = ((0x1fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg)) 
               | (0x20U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg)));
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr = (
                                                   ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wreg) 
                                                    << 4U) 
                                                   | (0xfU 
                                                      & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                                                          - (IData)(4U)) 
                                                         >> 1U)));
    if ((1U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)))) {
        ++(vlSymsp->__Vcoverage[311]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1 
            = ((0x3eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)) 
               | (1U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1)));
    }
    if ((2U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)))) {
        ++(vlSymsp->__Vcoverage[312]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1 
            = ((0x3dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)) 
               | (2U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1)));
    }
    if ((4U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)))) {
        ++(vlSymsp->__Vcoverage[313]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1 
            = ((0x3bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)) 
               | (4U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1)));
    }
    if ((8U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)))) {
        ++(vlSymsp->__Vcoverage[314]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1 
            = ((0x37U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)) 
               | (8U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1)));
    }
    if ((0x10U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)))) {
        ++(vlSymsp->__Vcoverage[315]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1 
            = ((0x2fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)) 
               | (0x10U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1)));
    }
    if ((0x20U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)))) {
        ++(vlSymsp->__Vcoverage[316]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1 
            = ((0x1fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1)) 
               | (0x20U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rreg1)));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wen0) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wen0))) {
        ++(vlSymsp->__Vcoverage[301]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wen0 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wen0;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_in))) {
        ++(vlSymsp->__Vcoverage[467]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_in 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__i_csr))) {
        ++(vlSymsp->__Vcoverage[629]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__i_csr 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__c))) {
        ++(vlSymsp->__Vcoverage[527]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__c 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__q) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__q))) {
        ++(vlSymsp->__Vcoverage[528]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__q 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__q;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_bool) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_bool))) {
        ++(vlSymsp->__Vcoverage[625]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_bool 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_bool;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__op_b_sx) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__op_b_sx))) {
        ++(vlSymsp->__Vcoverage[621]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__op_b_sx 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__op_b_sx;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_b) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__add_b))) {
        ++(vlSymsp->__Vcoverage[622]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__add_b 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_b;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy 
        = (1U & (((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0)) 
                  + ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_b) 
                     + (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy_r))) 
                 >> 1U));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_add 
        = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0) 
                 + ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_b) 
                    + (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy_r))));
    if ((1U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)))) {
        ++(vlSymsp->__Vcoverage[571]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next 
            = ((0xfeU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)) 
               | (1U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next)));
    }
    if ((2U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)))) {
        ++(vlSymsp->__Vcoverage[572]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next 
            = ((0xfdU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)) 
               | (2U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next)));
    }
    if ((4U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)))) {
        ++(vlSymsp->__Vcoverage[573]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next 
            = ((0xfbU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)) 
               | (4U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next)));
    }
    if ((8U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)))) {
        ++(vlSymsp->__Vcoverage[574]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next 
            = ((0xf7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)) 
               | (8U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next)));
    }
    if ((0x10U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)))) {
        ++(vlSymsp->__Vcoverage[575]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next 
            = ((0xefU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)) 
               | (0x10U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next)));
    }
    if ((0x20U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)))) {
        ++(vlSymsp->__Vcoverage[576]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next 
            = ((0xdfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)) 
               | (0x20U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next)));
    }
    if ((0x40U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)))) {
        ++(vlSymsp->__Vcoverage[577]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next 
            = ((0xbfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)) 
               | (0x40U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next)));
    }
    if ((0x80U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)))) {
        ++(vlSymsp->__Vcoverage[578]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next 
            = ((0x7fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next)) 
               | (0x80U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next)));
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_en)
            ? (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_next)
            : (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__op_b) 
                << 7U) | (0x7fU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
                                   >> 1U))));
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)))) {
        ++(vlSymsp->__Vcoverage[175]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr 
            = ((0x3feU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)))) {
        ++(vlSymsp->__Vcoverage[176]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr 
            = ((0x3fdU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)))) {
        ++(vlSymsp->__Vcoverage[177]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr 
            = ((0x3fbU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)))) {
        ++(vlSymsp->__Vcoverage[178]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr 
            = ((0x3f7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr)));
    }
    if ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)))) {
        ++(vlSymsp->__Vcoverage[179]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr 
            = ((0x3efU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)) 
               | (0x10U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr)));
    }
    if ((0x20U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)))) {
        ++(vlSymsp->__Vcoverage[180]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr 
            = ((0x3dfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)) 
               | (0x20U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr)));
    }
    if ((0x40U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)))) {
        ++(vlSymsp->__Vcoverage[181]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr 
            = ((0x3bfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)) 
               | (0x40U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr)));
    }
    if ((0x80U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)))) {
        ++(vlSymsp->__Vcoverage[182]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr 
            = ((0x37fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)) 
               | (0x80U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr)));
    }
    if ((0x100U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr) 
                   ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)))) {
        ++(vlSymsp->__Vcoverage[183]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr 
            = ((0x2ffU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)) 
               | (0x100U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr)));
    }
    if ((0x200U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr) 
                   ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)))) {
        ++(vlSymsp->__Vcoverage[184]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr 
            = ((0x1ffU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr)) 
               | (0x200U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr)));
    }
    if ((1U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)))) {
        ++(vlSymsp->__Vcoverage[358]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg 
            = ((0x3eU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)) 
               | (1U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg)));
    }
    if ((2U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)))) {
        ++(vlSymsp->__Vcoverage[359]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg 
            = ((0x3dU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)) 
               | (2U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg)));
    }
    if ((4U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)))) {
        ++(vlSymsp->__Vcoverage[360]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg 
            = ((0x3bU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)) 
               | (4U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg)));
    }
    if ((8U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)))) {
        ++(vlSymsp->__Vcoverage[361]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg 
            = ((0x37U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)) 
               | (8U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg)));
    }
    if ((0x10U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)))) {
        ++(vlSymsp->__Vcoverage[362]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg 
            = ((0x2fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)) 
               | (0x10U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg)));
    }
    if ((0x20U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)))) {
        ++(vlSymsp->__Vcoverage[363]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg 
            = ((0x1fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg)) 
               | (0x20U & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg)));
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr = (
                                                   ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreg) 
                                                    << 4U) 
                                                   | (0xfU 
                                                      & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                                                         >> 1U)));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata1 
        = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)
                  ? vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr
                  : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in)));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wdata1))) {
        ++(vlSymsp->__Vcoverage[304]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wdata1 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata1;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__i_wdata1))) {
        ++(vlSymsp->__Vcoverage[329]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__i_wdata1 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata1;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__add_cy))) {
        ++(vlSymsp->__Vcoverage[618]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__add_cy 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_lt 
        = (1U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__rs1_sx) 
                 + ((~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__op_b_sx)) 
                    + (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy))));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_add) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_add))) {
        ++(vlSymsp->__Vcoverage[615]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_add 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_add;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_eq 
        = ((~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_add)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__cmp_r) 
              | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0)));
    if ((1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
                >> 5U) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__sh_done)))) {
        ++(vlSymsp->__Vcoverage[457]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__sh_done 
            = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
                     >> 5U));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)))) {
        ++(vlSymsp->__Vcoverage[579]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt 
            = ((0xfeU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)))) {
        ++(vlSymsp->__Vcoverage[580]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt 
            = ((0xfdU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)))) {
        ++(vlSymsp->__Vcoverage[581]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt 
            = ((0xfbU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)))) {
        ++(vlSymsp->__Vcoverage[582]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt 
            = ((0xf7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt)));
    }
    if ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)))) {
        ++(vlSymsp->__Vcoverage[583]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt 
            = ((0xefU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)) 
               | (0x10U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt)));
    }
    if ((0x40U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)))) {
        ++(vlSymsp->__Vcoverage[584]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt 
            = ((0xbfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)) 
               | (0x40U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt)));
    }
    if ((0x80U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)))) {
        ++(vlSymsp->__Vcoverage[585]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt 
            = ((0x7fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt)) 
               | (0x80U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt)));
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_en 
        = (((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
            & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init) 
               | (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
                   | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                      >> 4U)) & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_two_stage_op)))) 
           | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op) 
              & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__init_done) 
                 & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
                     >> 5U) | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                               >> 2U)))));
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)))) {
        ++(vlSymsp->__Vcoverage[188]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr 
            = ((0x3feU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr)));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)))) {
        ++(vlSymsp->__Vcoverage[189]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr 
            = ((0x3fdU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr)));
    }
    if ((4U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)))) {
        ++(vlSymsp->__Vcoverage[190]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr 
            = ((0x3fbU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)) 
               | (4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr)));
    }
    if ((8U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)))) {
        ++(vlSymsp->__Vcoverage[191]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr 
            = ((0x3f7U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)) 
               | (8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr)));
    }
    if ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)))) {
        ++(vlSymsp->__Vcoverage[192]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr 
            = ((0x3efU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)) 
               | (0x10U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr)));
    }
    if ((0x20U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)))) {
        ++(vlSymsp->__Vcoverage[193]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr 
            = ((0x3dfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)) 
               | (0x20U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr)));
    }
    if ((0x40U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)))) {
        ++(vlSymsp->__Vcoverage[194]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr 
            = ((0x3bfU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)) 
               | (0x40U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr)));
    }
    if ((0x80U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
                  ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)))) {
        ++(vlSymsp->__Vcoverage[195]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr 
            = ((0x37fU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)) 
               | (0x80U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr)));
    }
    if ((0x100U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
                   ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)))) {
        ++(vlSymsp->__Vcoverage[196]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr 
            = ((0x2ffU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)) 
               | (0x100U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr)));
    }
    if ((0x200U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
                   ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)))) {
        ++(vlSymsp->__Vcoverage[197]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr 
            = ((0x1ffU & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr)) 
               | (0x200U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr)));
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_lt) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_lt))) {
        ++(vlSymsp->__Vcoverage[623]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_lt 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_lt;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_eq) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_eq))) {
        ++(vlSymsp->__Vcoverage[624]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_eq 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_eq;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_cmp 
        = ((0U == (3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                         >> 1U))) ? (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_eq)
            : (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_lt));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_en))) {
        ++(vlSymsp->__Vcoverage[438]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_en 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_en;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_q 
        = (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_en));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_cmp) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_cmp))) {
        ++(vlSymsp->__Vcoverage[448]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_cmp 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_cmp;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__take_branch 
        = (IData)((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                    >> 4U) & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                              | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_cmp) 
                                 ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)))));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_q) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_q))) {
        ++(vlSymsp->__Vcoverage[443]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_q 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_q;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_q) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__o_q))) {
        ++(vlSymsp->__Vcoverage[526]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__o_q 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_q;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_rd 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_q) 
           | (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel) 
               & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_add)) 
              | ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel) 
                   >> 1U) & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_slt)) 
                 | (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel) 
                     >> 2U) & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_bool)))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_b 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_utype)
            ? ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12to31) 
               & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm))
            : (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_q));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__take_branch) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__take_branch))) {
        ++(vlSymsp->__Vcoverage[479]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__take_branch 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__take_branch;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__trap_pending 
        = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__take_branch) 
            & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
               >> 1U)) | ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_dbus_en) 
                          & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_misalign)));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_rd) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd))) {
        ++(vlSymsp->__Vcoverage[415]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_rd;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_rd) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__o_rd))) {
        ++(vlSymsp->__Vcoverage[614]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__o_rd 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_rd;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_b) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__offset_b))) {
        ++(vlSymsp->__Vcoverage[603]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__offset_b 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_b;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy 
        = (1U & (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_a) 
                  + ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_b) 
                     + (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy_r))) 
                 >> 1U));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset 
        = (1U & ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_a) 
                 + ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__offset_b) 
                    + (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy_r))));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__trap_pending) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__trap_pending))) {
        ++(vlSymsp->__Vcoverage[481]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__trap_pending 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__trap_pending;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
           | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__trap_pending) 
              & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__last_init)));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq 
        = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op) 
            & ((4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))
                ? (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
                    >> 5U) & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__last_init) 
                              | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____VdfgTmp_hb0ab83f8__0)))
                : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__last_init))) 
           | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack) 
              | ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                   >> 4U) & ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__trap_pending)) 
                             & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__last_init))) 
                 | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_alu_en) 
                    & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel) 
                        >> 1U) & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__last_init))))));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset_cy))) {
        ++(vlSymsp->__Vcoverage[598]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset_cy 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset))) {
        ++(vlSymsp->__Vcoverage[597]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bad_pc 
        = ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0)) 
           & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_rreq))) {
        ++(vlSymsp->__Vcoverage[288]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_rreq 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_wreq))) {
        ++(vlSymsp->__Vcoverage[287]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_wreq 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ready 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq) 
           | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgnt));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bad_pc) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bad_pc))) {
        ++(vlSymsp->__Vcoverage[459]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bad_pc 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bad_pc;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bad_pc) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__o_bad_pc))) {
        ++(vlSymsp->__Vcoverage[593]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__o_bad_pc 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bad_pc;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__new_pc 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vcellinp__ctrl__i_trap)
            ? ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0) 
                   | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt1))) 
               & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1))
            : ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__jump)
                ? (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bad_pc)
                : (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_rd 
        = (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_utype) 
            & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bad_pc)) 
           | ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4) 
              & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_jal_or_jalr)));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata0 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)
            ? ((0x10U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))
                ? (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bad_pc)
                : (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_q))
            : (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_rd) 
                & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_alu_en)) 
               | (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_rd) 
                   & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_op)) 
                  | (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_rd) 
                      & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_mem_en)) 
                     | (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_rd)))));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ready) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_ready))) {
        ++(vlSymsp->__Vcoverage[317]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_ready 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ready;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__new_pc) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__new_pc))) {
        ++(vlSymsp->__Vcoverage[601]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__new_pc 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__new_pc;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_rd) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ctrl_rd))) {
        ++(vlSymsp->__Vcoverage[414]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ctrl_rd 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_rd;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_rd) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__o_rd))) {
        ++(vlSymsp->__Vcoverage[592]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__o_rd 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_rd;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata0) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wdata0))) {
        ++(vlSymsp->__Vcoverage[303]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wdata0 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata0;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata0) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__i_wdata0))) {
        ++(vlSymsp->__Vcoverage[328]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__i_wdata0 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata0;
    }
}

VL_ATTR_COLD void Vtb_cov_top___024root___configure_coverage(Vtb_cov_top___024root* vlSelf, bool first) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___configure_coverage\n"); );
    // Body
    if (false && first) {}  // Prevent unused
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "tb_cov_top.v", 2, 30, ".tb_cov_top", "v_toggle/tb_cov_top", "clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[1]), first, "tb_cov_top.v", 2, 46, ".tb_cov_top", "v_toggle/tb_cov_top", "rst_in", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[2]), first, "tb_cov_top.v", 2, 66, ".tb_cov_top", "v_toggle/tb_cov_top", "gpio_o", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[3]), first, "tb_cov_top.v", 4, 15, ".tb_cov_top", "v_toggle/tb_cov_top", "sa[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[4]), first, "tb_cov_top.v", 4, 15, ".tb_cov_top", "v_toggle/tb_cov_top", "sa[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[5]), first, "tb_cov_top.v", 4, 15, ".tb_cov_top", "v_toggle/tb_cov_top", "sa[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[6]), first, "tb_cov_top.v", 4, 15, ".tb_cov_top", "v_toggle/tb_cov_top", "sa[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[7]), first, "tb_cov_top.v", 4, 15, ".tb_cov_top", "v_toggle/tb_cov_top", "sa[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[8]), first, "tb_cov_top.v", 4, 15, ".tb_cov_top", "v_toggle/tb_cov_top", "sa[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[9]), first, "tb_cov_top.v", 4, 15, ".tb_cov_top", "v_toggle/tb_cov_top", "sa[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[10]), first, "tb_cov_top.v", 4, 15, ".tb_cov_top", "v_toggle/tb_cov_top", "sa[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[11]), first, "tb_cov_top.v", 4, 15, ".tb_cov_top", "v_toggle/tb_cov_top", "sa[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[12]), first, "tb_cov_top.v", 4, 15, ".tb_cov_top", "v_toggle/tb_cov_top", "sa[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[13]), first, "tb_cov_top.v", 4, 30, ".tb_cov_top", "v_toggle/tb_cov_top", "sw[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[14]), first, "tb_cov_top.v", 4, 30, ".tb_cov_top", "v_toggle/tb_cov_top", "sw[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[15]), first, "tb_cov_top.v", 4, 30, ".tb_cov_top", "v_toggle/tb_cov_top", "sw[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[16]), first, "tb_cov_top.v", 4, 30, ".tb_cov_top", "v_toggle/tb_cov_top", "sw[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[17]), first, "tb_cov_top.v", 4, 30, ".tb_cov_top", "v_toggle/tb_cov_top", "sw[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[18]), first, "tb_cov_top.v", 4, 30, ".tb_cov_top", "v_toggle/tb_cov_top", "sw[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[19]), first, "tb_cov_top.v", 4, 30, ".tb_cov_top", "v_toggle/tb_cov_top", "sw[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[20]), first, "tb_cov_top.v", 4, 30, ".tb_cov_top", "v_toggle/tb_cov_top", "sw[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[21]), first, "tb_cov_top.v", 4, 44, ".tb_cov_top", "v_toggle/tb_cov_top", "sr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[22]), first, "tb_cov_top.v", 4, 44, ".tb_cov_top", "v_toggle/tb_cov_top", "sr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[23]), first, "tb_cov_top.v", 4, 44, ".tb_cov_top", "v_toggle/tb_cov_top", "sr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[24]), first, "tb_cov_top.v", 4, 44, ".tb_cov_top", "v_toggle/tb_cov_top", "sr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[25]), first, "tb_cov_top.v", 4, 44, ".tb_cov_top", "v_toggle/tb_cov_top", "sr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[26]), first, "tb_cov_top.v", 4, 44, ".tb_cov_top", "v_toggle/tb_cov_top", "sr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[27]), first, "tb_cov_top.v", 4, 44, ".tb_cov_top", "v_toggle/tb_cov_top", "sr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[28]), first, "tb_cov_top.v", 4, 44, ".tb_cov_top", "v_toggle/tb_cov_top", "sr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[29]), first, "tb_cov_top.v", 4, 53, ".tb_cov_top", "v_toggle/tb_cov_top", "swe", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[30]), first, "tb_cov_top.v", 4, 58, ".tb_cov_top", "v_toggle/tb_cov_top", "scyc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[31]), first, "tb_cov_top.v", 5, 48, ".tb_cov_top", "v_toggle/tb_cov_top", "init", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[32]), first, "tb_cov_top.v", 5, 53, ".tb_cov_top", "v_line/tb_cov_top", "block", "5");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[33]), first, "tb_cov_top.v", 7, 24, ".tb_cov_top", "v_line/tb_cov_top", "block", "7");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[34]), first, "tb_cov_top.v", 7, 7, ".tb_cov_top", "v_branch/tb_cov_top", "if", "7");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[35]), first, "tb_cov_top.v", 7, 8, ".tb_cov_top", "v_branch/tb_cov_top", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[36]), first, "tb_cov_top.v", 8, 7, ".tb_cov_top", "v_branch/tb_cov_top", "if", "8");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[37]), first, "tb_cov_top.v", 8, 8, ".tb_cov_top", "v_branch/tb_cov_top", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[38]), first, "tb_cov_top.v", 6, 4, ".tb_cov_top", "v_line/tb_cov_top", "block", "6,9");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/subservient.v", 49, 24, ".tb_cov_top.dut", "v_toggle/subservient", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[1]), first, "../rtl/subservient.v", 50, 24, ".tb_cov_top.dut", "v_toggle/subservient", "i_rst", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[3]), first, "../rtl/subservient.v", 53, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[4]), first, "../rtl/subservient.v", 53, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[5]), first, "../rtl/subservient.v", 53, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_addr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[6]), first, "../rtl/subservient.v", 53, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_addr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[7]), first, "../rtl/subservient.v", 53, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_addr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[8]), first, "../rtl/subservient.v", 53, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_addr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[9]), first, "../rtl/subservient.v", 53, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_addr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[10]), first, "../rtl/subservient.v", 53, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_addr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[11]), first, "../rtl/subservient.v", 53, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_addr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[12]), first, "../rtl/subservient.v", 53, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_addr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[13]), first, "../rtl/subservient.v", 54, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_wdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[14]), first, "../rtl/subservient.v", 54, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_wdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[15]), first, "../rtl/subservient.v", 54, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_wdata[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[16]), first, "../rtl/subservient.v", 54, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_wdata[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[17]), first, "../rtl/subservient.v", 54, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_wdata[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[18]), first, "../rtl/subservient.v", 54, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_wdata[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[19]), first, "../rtl/subservient.v", 54, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_wdata[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[20]), first, "../rtl/subservient.v", 54, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_wdata[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[21]), first, "../rtl/subservient.v", 55, 24, ".tb_cov_top.dut", "v_toggle/subservient", "i_sram_rdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[22]), first, "../rtl/subservient.v", 55, 24, ".tb_cov_top.dut", "v_toggle/subservient", "i_sram_rdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[23]), first, "../rtl/subservient.v", 55, 24, ".tb_cov_top.dut", "v_toggle/subservient", "i_sram_rdata[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[24]), first, "../rtl/subservient.v", 55, 24, ".tb_cov_top.dut", "v_toggle/subservient", "i_sram_rdata[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[25]), first, "../rtl/subservient.v", 55, 24, ".tb_cov_top.dut", "v_toggle/subservient", "i_sram_rdata[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[26]), first, "../rtl/subservient.v", 55, 24, ".tb_cov_top.dut", "v_toggle/subservient", "i_sram_rdata[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[27]), first, "../rtl/subservient.v", 55, 24, ".tb_cov_top.dut", "v_toggle/subservient", "i_sram_rdata[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[28]), first, "../rtl/subservient.v", 55, 24, ".tb_cov_top.dut", "v_toggle/subservient", "i_sram_rdata[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[29]), first, "../rtl/subservient.v", 56, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[30]), first, "../rtl/subservient.v", 57, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_sram_cyc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[2]), first, "../rtl/subservient.v", 60, 24, ".tb_cov_top.dut", "v_toggle/subservient", "o_gpio", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[39]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[40]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[41]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[42]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[43]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[44]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[45]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[46]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[47]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[48]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[49]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[50]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[51]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[52]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[53]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[54]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[55]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[56]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[57]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[58]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[59]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[60]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[61]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[62]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[63]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[64]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[65]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[66]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[67]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[68]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[69]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[70]), first, "../rtl/subservient.v", 67, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/subservient.v", 68, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/subservient.v", 69, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/subservient.v", 69, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/subservient.v", 69, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/subservient.v", 69, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[107]), first, "../rtl/subservient.v", 70, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[108]), first, "../rtl/subservient.v", 71, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/subservient.v", 72, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[141]), first, "../rtl/subservient.v", 73, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_mem_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/subservient.v", 76, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/subservient.v", 77, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/subservient.v", 78, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/subservient.v", 78, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/subservient.v", 78, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/subservient.v", 78, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/subservient.v", 79, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[174]), first, "../rtl/subservient.v", 80, 16, ".tb_cov_top.dut", "v_toggle/subservient", "wb_ext_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[175]), first, "../rtl/subservient.v", 85, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_waddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[176]), first, "../rtl/subservient.v", 85, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_waddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[177]), first, "../rtl/subservient.v", 85, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_waddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[178]), first, "../rtl/subservient.v", 85, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_waddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[179]), first, "../rtl/subservient.v", 85, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_waddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[180]), first, "../rtl/subservient.v", 85, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_waddr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[181]), first, "../rtl/subservient.v", 85, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_waddr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[182]), first, "../rtl/subservient.v", 85, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_waddr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[183]), first, "../rtl/subservient.v", 85, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_waddr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[184]), first, "../rtl/subservient.v", 85, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_waddr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[185]), first, "../rtl/subservient.v", 86, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_wdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[186]), first, "../rtl/subservient.v", 86, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_wdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[187]), first, "../rtl/subservient.v", 87, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_wen", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[188]), first, "../rtl/subservient.v", 88, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_raddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[189]), first, "../rtl/subservient.v", 88, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_raddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[190]), first, "../rtl/subservient.v", 88, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_raddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[191]), first, "../rtl/subservient.v", 88, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_raddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[192]), first, "../rtl/subservient.v", 88, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_raddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[193]), first, "../rtl/subservient.v", 88, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_raddr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[194]), first, "../rtl/subservient.v", 88, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_raddr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[195]), first, "../rtl/subservient.v", 88, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_raddr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[196]), first, "../rtl/subservient.v", 88, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_raddr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[197]), first, "../rtl/subservient.v", 88, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_raddr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[198]), first, "../rtl/subservient.v", 89, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_rdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[199]), first, "../rtl/subservient.v", 89, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_rdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[200]), first, "../rtl/subservient.v", 90, 24, ".tb_cov_top.dut", "v_toggle/subservient", "rf_ren", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[201]), first, "../rtl/subservient.v", 170, 15, ".tb_cov_top.dut", "v_toggle/subservient", "bstate[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[202]), first, "../rtl/subservient.v", 170, 15, ".tb_cov_top.dut", "v_toggle/subservient", "bstate[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[203]), first, "../rtl/subservient.v", 170, 15, ".tb_cov_top.dut", "v_toggle/subservient", "bstate[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[3]), first, "../rtl/subservient.v", 171, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[4]), first, "../rtl/subservient.v", 171, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[5]), first, "../rtl/subservient.v", 171, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_addr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[6]), first, "../rtl/subservient.v", 171, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_addr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[7]), first, "../rtl/subservient.v", 171, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_addr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[8]), first, "../rtl/subservient.v", 171, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_addr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[9]), first, "../rtl/subservient.v", 171, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_addr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[10]), first, "../rtl/subservient.v", 171, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_addr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[11]), first, "../rtl/subservient.v", 171, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_addr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[12]), first, "../rtl/subservient.v", 171, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_addr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[13]), first, "../rtl/subservient.v", 172, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_wdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[14]), first, "../rtl/subservient.v", 172, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_wdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[15]), first, "../rtl/subservient.v", 172, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_wdata[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[16]), first, "../rtl/subservient.v", 172, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_wdata[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[17]), first, "../rtl/subservient.v", 172, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_wdata[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[18]), first, "../rtl/subservient.v", 172, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_wdata[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[19]), first, "../rtl/subservient.v", 172, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_wdata[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[20]), first, "../rtl/subservient.v", 172, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_wdata[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[29]), first, "../rtl/subservient.v", 173, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[30]), first, "../rtl/subservient.v", 174, 15, ".tb_cov_top.dut", "v_toggle/subservient", "br_cyc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/subservient.v", 175, 15, ".tb_cov_top.dut", "v_toggle/subservient", "rdt_asm[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[39]), first, "../rtl/subservient.v", 180, 15, ".tb_cov_top.dut", "v_toggle/subservient", "word_base[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[40]), first, "../rtl/subservient.v", 180, 15, ".tb_cov_top.dut", "v_toggle/subservient", "word_base[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[41]), first, "../rtl/subservient.v", 180, 15, ".tb_cov_top.dut", "v_toggle/subservient", "word_base[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[42]), first, "../rtl/subservient.v", 180, 15, ".tb_cov_top.dut", "v_toggle/subservient", "word_base[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[43]), first, "../rtl/subservient.v", 180, 15, ".tb_cov_top.dut", "v_toggle/subservient", "word_base[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[44]), first, "../rtl/subservient.v", 180, 15, ".tb_cov_top.dut", "v_toggle/subservient", "word_base[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[45]), first, "../rtl/subservient.v", 180, 15, ".tb_cov_top.dut", "v_toggle/subservient", "word_base[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[46]), first, "../rtl/subservient.v", 180, 15, ".tb_cov_top.dut", "v_toggle/subservient", "word_base[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[47]), first, "../rtl/subservient.v", 180, 15, ".tb_cov_top.dut", "v_toggle/subservient", "word_base[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[48]), first, "../rtl/subservient.v", 180, 15, ".tb_cov_top.dut", "v_toggle/subservient", "word_base[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[204]), first, "../rtl/subservient.v", 195, 16, ".tb_cov_top.dut", "v_branch/subservient", "if", "195,197-201");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[205]), first, "../rtl/subservient.v", 195, 17, ".tb_cov_top.dut", "v_branch/subservient", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[206]), first, "../rtl/subservient.v", 192, 19, ".tb_cov_top.dut", "v_line/subservient", "case", "192-194");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[207]), first, "../rtl/subservient.v", 208, 17, ".tb_cov_top.dut", "v_line/subservient", "case", "208-213");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[208]), first, "../rtl/subservient.v", 215, 17, ".tb_cov_top.dut", "v_line/subservient", "case", "215-221");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[209]), first, "../rtl/subservient.v", 223, 17, ".tb_cov_top.dut", "v_line/subservient", "case", "223-229");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[210]), first, "../rtl/subservient.v", 231, 17, ".tb_cov_top.dut", "v_line/subservient", "case", "231-235");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[211]), first, "../rtl/subservient.v", 237, 17, ".tb_cov_top.dut", "v_line/subservient", "case", "237-241");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[212]), first, "../rtl/subservient.v", 243, 18, ".tb_cov_top.dut", "v_line/subservient", "case", "243-246");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[213]), first, "../rtl/subservient.v", 248, 13, ".tb_cov_top.dut", "v_line/subservient", "case", "248");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[214]), first, "../rtl/subservient.v", 183, 7, ".tb_cov_top.dut", "v_branch/subservient", "if", "183-189");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[215]), first, "../rtl/subservient.v", 183, 8, ".tb_cov_top.dut", "v_branch/subservient", "else", "190-191");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[216]), first, "../rtl/subservient.v", 182, 4, ".tb_cov_top.dut", "v_line/subservient", "block", "182");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/servile.v", 25, 22, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[1]), first, "../rtl/servile.v", 26, 22, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_rst", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 27, 22, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_timer_irq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[39]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[40]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[41]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[42]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[43]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[44]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[45]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[46]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[47]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[48]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[49]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[50]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[51]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[52]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[53]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[54]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[55]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[56]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[57]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[58]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[59]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[60]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[61]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[62]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[63]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[64]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[65]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[66]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[67]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[68]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[69]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[70]), first, "../rtl/servile.v", 30, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/servile.v", 31, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/servile.v", 32, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/servile.v", 32, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/servile.v", 32, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/servile.v", 32, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[107]), first, "../rtl/servile.v", 33, 23, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[108]), first, "../rtl/servile.v", 34, 23, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_mem_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/servile.v", 35, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[141]), first, "../rtl/servile.v", 36, 22, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_mem_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/servile.v", 39, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/servile.v", 40, 29, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/servile.v", 41, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/servile.v", 41, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/servile.v", 41, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/servile.v", 41, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/servile.v", 42, 23, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[174]), first, "../rtl/servile.v", 43, 23, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_wb_ext_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 44, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 45, 22, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_wb_ext_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[175]), first, "../rtl/servile.v", 48, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_waddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[176]), first, "../rtl/servile.v", 48, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_waddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[177]), first, "../rtl/servile.v", 48, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_waddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[178]), first, "../rtl/servile.v", 48, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_waddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[179]), first, "../rtl/servile.v", 48, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_waddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[180]), first, "../rtl/servile.v", 48, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_waddr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[181]), first, "../rtl/servile.v", 48, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_waddr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[182]), first, "../rtl/servile.v", 48, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_waddr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[183]), first, "../rtl/servile.v", 48, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_waddr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[184]), first, "../rtl/servile.v", 48, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_waddr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[185]), first, "../rtl/servile.v", 49, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_wdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[186]), first, "../rtl/servile.v", 49, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_wdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[187]), first, "../rtl/servile.v", 50, 23, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_wen", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[188]), first, "../rtl/servile.v", 51, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_raddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[189]), first, "../rtl/servile.v", 51, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_raddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[190]), first, "../rtl/servile.v", 51, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_raddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[191]), first, "../rtl/servile.v", 51, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_raddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[192]), first, "../rtl/servile.v", 51, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_raddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[193]), first, "../rtl/servile.v", 51, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_raddr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[194]), first, "../rtl/servile.v", 51, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_raddr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[195]), first, "../rtl/servile.v", 51, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_raddr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[196]), first, "../rtl/servile.v", 51, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_raddr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[197]), first, "../rtl/servile.v", 51, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_raddr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[198]), first, "../rtl/servile.v", 52, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_rf_rdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[199]), first, "../rtl/servile.v", 52, 31, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "i_rf_rdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[200]), first, "../rtl/servile.v", 53, 23, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "o_rf_ren", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[217]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[218]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[219]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[220]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[221]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[222]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[223]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[224]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[225]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[226]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[227]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[228]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[229]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[230]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[231]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[232]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[233]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[234]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[235]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[236]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[237]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[238]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[239]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[240]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[241]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[242]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[243]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[244]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[245]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[246]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[247]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[248]), first, "../rtl/servile.v", 57, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[249]), first, "../rtl/servile.v", 58, 10, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/servile.v", 59, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[250]), first, "../rtl/servile.v", 60, 10, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_ibus_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/servile.v", 62, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/servile.v", 63, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/servile.v", 64, 16, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/servile.v", 64, 16, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/servile.v", 64, 16, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/servile.v", 64, 16, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/servile.v", 65, 10, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[251]), first, "../rtl/servile.v", 66, 10, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[252]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[253]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[254]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[255]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[256]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[257]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[258]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[259]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[260]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[261]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[262]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[263]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[264]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[265]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[266]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[267]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[268]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[269]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[270]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[271]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[272]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[273]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[274]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[275]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[276]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[277]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[278]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[279]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[280]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[281]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[282]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[283]), first, "../rtl/servile.v", 67, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[284]), first, "../rtl/servile.v", 68, 10, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dbus_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/servile.v", 70, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/servile.v", 71, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/servile.v", 72, 16, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/servile.v", 72, 16, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/servile.v", 72, 16, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/servile.v", 72, 16, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/servile.v", 73, 10, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[285]), first, "../rtl/servile.v", 74, 10, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/servile.v", 75, 17, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[286]), first, "../rtl/servile.v", 76, 10, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wb_dmem_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[287]), first, "../rtl/servile.v", 78, 14, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rf_wreq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[288]), first, "../rtl/servile.v", 79, 14, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rf_rreq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[289]), first, "../rtl/servile.v", 80, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[290]), first, "../rtl/servile.v", 80, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg0[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[291]), first, "../rtl/servile.v", 80, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg0[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[292]), first, "../rtl/servile.v", 80, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg0[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[293]), first, "../rtl/servile.v", 80, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg0[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[294]), first, "../rtl/servile.v", 80, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg0[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[295]), first, "../rtl/servile.v", 81, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[296]), first, "../rtl/servile.v", 81, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[297]), first, "../rtl/servile.v", 81, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[298]), first, "../rtl/servile.v", 81, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[299]), first, "../rtl/servile.v", 81, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[300]), first, "../rtl/servile.v", 81, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wreg1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[301]), first, "../rtl/servile.v", 82, 14, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wen0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[302]), first, "../rtl/servile.v", 83, 14, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wen1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[303]), first, "../rtl/servile.v", 84, 19, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wdata0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[304]), first, "../rtl/servile.v", 85, 19, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "wdata1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[305]), first, "../rtl/servile.v", 86, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[306]), first, "../rtl/servile.v", 86, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg0[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[307]), first, "../rtl/servile.v", 86, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg0[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[308]), first, "../rtl/servile.v", 86, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg0[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[309]), first, "../rtl/servile.v", 86, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg0[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[310]), first, "../rtl/servile.v", 86, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg0[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[311]), first, "../rtl/servile.v", 87, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[312]), first, "../rtl/servile.v", 87, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[313]), first, "../rtl/servile.v", 87, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[314]), first, "../rtl/servile.v", 87, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[315]), first, "../rtl/servile.v", 87, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[316]), first, "../rtl/servile.v", 87, 28, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rreg1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[317]), first, "../rtl/servile.v", 88, 14, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rf_ready", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[318]), first, "../rtl/servile.v", 89, 19, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rdata0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[319]), first, "../rtl/servile.v", 90, 19, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "rdata1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[320]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[321]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/servile.v", 92, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs1[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/servile.v", 93, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rs2[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/servile.v", 94, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_op[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/servile.v", 94, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_op[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/servile.v", 94, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_op[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 95, 14, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_valid", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 96, 20, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_rd[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile.v", 97, 14, ".tb_cov_top.dut.u_servile", "v_toggle/servile__WCz1", "mdu_ready", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/servile_mux.v", 13, 23, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[1]), first, "../rtl/servile_mux.v", 14, 23, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_rst", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/servile_mux.v", 16, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/servile_mux.v", 17, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/servile_mux.v", 18, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/servile_mux.v", 18, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/servile_mux.v", 18, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/servile_mux.v", 18, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/servile_mux.v", 19, 23, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[251]), first, "../rtl/servile_mux.v", 20, 23, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_cpu_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[252]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[253]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[254]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[255]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[256]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[257]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[258]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[259]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[260]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[261]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[262]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[263]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[264]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[265]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[266]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[267]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[268]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[269]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[270]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[271]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[272]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[273]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[274]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[275]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[276]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[277]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[278]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[279]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[280]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[281]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[282]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[283]), first, "../rtl/servile_mux.v", 21, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[284]), first, "../rtl/servile_mux.v", 22, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_cpu_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/servile_mux.v", 24, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/servile_mux.v", 25, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/servile_mux.v", 26, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/servile_mux.v", 26, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/servile_mux.v", 26, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/servile_mux.v", 26, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/servile_mux.v", 27, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[285]), first, "../rtl/servile_mux.v", 28, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_mem_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/servile_mux.v", 29, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[286]), first, "../rtl/servile_mux.v", 30, 23, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_mem_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/servile_mux.v", 32, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/servile_mux.v", 33, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/servile_mux.v", 34, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/servile_mux.v", 34, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/servile_mux.v", 34, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/servile_mux.v", 34, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/servile_mux.v", 35, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[174]), first, "../rtl/servile_mux.v", 36, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "o_wb_ext_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 37, 24, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 38, 23, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "i_wb_ext_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 40, 17, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "sig_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_mux.v", 41, 17, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "halt_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[325]), first, "../rtl/servile_mux.v", 42, 16, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "sim_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[326]), first, "../rtl/servile_mux.v", 44, 17, ".tb_cov_top.dut.u_servile.mux", "v_toggle/servile_mux__Sz2", "ext", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[327]), first, "../rtl/servile_mux.v", 96, 3, ".tb_cov_top.dut.u_servile.mux", "v_line/servile_mux__Sz2", "block", "96");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/servile_arbiter.v", 11, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/servile_arbiter.v", 12, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/servile_arbiter.v", 13, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/servile_arbiter.v", 13, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/servile_arbiter.v", 13, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/servile_arbiter.v", 13, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/servile_arbiter.v", 14, 22, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[285]), first, "../rtl/servile_arbiter.v", 15, 22, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_dbus_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/servile_arbiter.v", 16, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[286]), first, "../rtl/servile_arbiter.v", 17, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_dbus_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[217]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[218]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[219]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[220]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[221]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[222]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[223]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[224]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[225]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[226]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[227]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[228]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[229]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[230]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[231]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[232]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[233]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[234]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[235]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[236]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[237]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[238]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[239]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[240]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[241]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[242]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[243]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[244]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[245]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[246]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[247]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[248]), first, "../rtl/servile_arbiter.v", 19, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[249]), first, "../rtl/servile_arbiter.v", 20, 22, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_cpu_ibus_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/servile_arbiter.v", 21, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[250]), first, "../rtl/servile_arbiter.v", 22, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_cpu_ibus_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[39]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[40]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[41]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[42]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[43]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[44]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[45]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[46]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[47]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[48]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[49]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[50]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[51]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[52]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[53]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[54]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[55]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[56]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[57]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[58]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[59]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[60]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[61]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[62]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[63]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[64]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[65]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[66]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[67]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[68]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[69]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[70]), first, "../rtl/servile_arbiter.v", 24, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/servile_arbiter.v", 25, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/servile_arbiter.v", 26, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/servile_arbiter.v", 26, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/servile_arbiter.v", 26, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/servile_arbiter.v", 26, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[107]), first, "../rtl/servile_arbiter.v", 27, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[108]), first, "../rtl/servile_arbiter.v", 28, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "o_wb_mem_stb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/servile_arbiter.v", 29, 23, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[141]), first, "../rtl/servile_arbiter.v", 30, 22, ".tb_cov_top.dut.u_servile.arbiter", "v_toggle/servile_arbiter", "i_wb_mem_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_rf_ram_if.v", 29, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[1]), first, "../rtl/serv_rf_ram_if.v", 30, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rst", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[287]), first, "../rtl/serv_rf_ram_if.v", 31, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[288]), first, "../rtl/serv_rf_ram_if.v", 32, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[317]), first, "../rtl/serv_rf_ram_if.v", 33, 20, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_ready", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[289]), first, "../rtl/serv_rf_ram_if.v", 34, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[290]), first, "../rtl/serv_rf_ram_if.v", 34, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg0[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[291]), first, "../rtl/serv_rf_ram_if.v", 34, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg0[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[292]), first, "../rtl/serv_rf_ram_if.v", 34, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg0[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[293]), first, "../rtl/serv_rf_ram_if.v", 34, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg0[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[294]), first, "../rtl/serv_rf_ram_if.v", 34, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg0[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[295]), first, "../rtl/serv_rf_ram_if.v", 35, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[296]), first, "../rtl/serv_rf_ram_if.v", 35, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[297]), first, "../rtl/serv_rf_ram_if.v", 35, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[298]), first, "../rtl/serv_rf_ram_if.v", 35, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[299]), first, "../rtl/serv_rf_ram_if.v", 35, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[300]), first, "../rtl/serv_rf_ram_if.v", 35, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wreg1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[301]), first, "../rtl/serv_rf_ram_if.v", 36, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wen0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[302]), first, "../rtl/serv_rf_ram_if.v", 37, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wen1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[328]), first, "../rtl/serv_rf_ram_if.v", 38, 24, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wdata0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[329]), first, "../rtl/serv_rf_ram_if.v", 39, 24, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_wdata1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[305]), first, "../rtl/serv_rf_ram_if.v", 40, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[306]), first, "../rtl/serv_rf_ram_if.v", 40, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg0[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[307]), first, "../rtl/serv_rf_ram_if.v", 40, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg0[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[308]), first, "../rtl/serv_rf_ram_if.v", 40, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg0[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[309]), first, "../rtl/serv_rf_ram_if.v", 40, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg0[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[310]), first, "../rtl/serv_rf_ram_if.v", 40, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg0[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[311]), first, "../rtl/serv_rf_ram_if.v", 41, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[312]), first, "../rtl/serv_rf_ram_if.v", 41, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[313]), first, "../rtl/serv_rf_ram_if.v", 41, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[314]), first, "../rtl/serv_rf_ram_if.v", 41, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[315]), first, "../rtl/serv_rf_ram_if.v", 41, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[316]), first, "../rtl/serv_rf_ram_if.v", 41, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rreg1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[318]), first, "../rtl/serv_rf_ram_if.v", 42, 25, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_rdata0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[330]), first, "../rtl/serv_rf_ram_if.v", 43, 25, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_rdata1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[175]), first, "../rtl/serv_rf_ram_if.v", 45, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_waddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[176]), first, "../rtl/serv_rf_ram_if.v", 45, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_waddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[177]), first, "../rtl/serv_rf_ram_if.v", 45, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_waddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[178]), first, "../rtl/serv_rf_ram_if.v", 45, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_waddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[179]), first, "../rtl/serv_rf_ram_if.v", 45, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_waddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[180]), first, "../rtl/serv_rf_ram_if.v", 45, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_waddr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[181]), first, "../rtl/serv_rf_ram_if.v", 45, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_waddr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[182]), first, "../rtl/serv_rf_ram_if.v", 45, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_waddr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[183]), first, "../rtl/serv_rf_ram_if.v", 45, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_waddr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[184]), first, "../rtl/serv_rf_ram_if.v", 45, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_waddr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[185]), first, "../rtl/serv_rf_ram_if.v", 46, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_wdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[186]), first, "../rtl/serv_rf_ram_if.v", 46, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_wdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[187]), first, "../rtl/serv_rf_ram_if.v", 47, 20, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_wen", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[188]), first, "../rtl/serv_rf_ram_if.v", 48, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_raddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[189]), first, "../rtl/serv_rf_ram_if.v", 48, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_raddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[190]), first, "../rtl/serv_rf_ram_if.v", 48, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_raddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[191]), first, "../rtl/serv_rf_ram_if.v", 48, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_raddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[192]), first, "../rtl/serv_rf_ram_if.v", 48, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_raddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[193]), first, "../rtl/serv_rf_ram_if.v", 48, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_raddr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[194]), first, "../rtl/serv_rf_ram_if.v", 48, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_raddr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[195]), first, "../rtl/serv_rf_ram_if.v", 48, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_raddr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[196]), first, "../rtl/serv_rf_ram_if.v", 48, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_raddr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[197]), first, "../rtl/serv_rf_ram_if.v", 48, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_raddr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[200]), first, "../rtl/serv_rf_ram_if.v", 49, 20, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "o_ren", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[198]), first, "../rtl/serv_rf_ram_if.v", 50, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[199]), first, "../rtl/serv_rf_ram_if.v", 50, 28, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "i_rdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[331]), first, "../rtl/serv_rf_ram_if.v", 56, 15, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rgnt", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[332]), first, "../rtl/serv_rf_ram_if.v", 58, 20, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rcnt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[333]), first, "../rtl/serv_rf_ram_if.v", 58, 20, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rcnt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[334]), first, "../rtl/serv_rf_ram_if.v", 58, 20, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rcnt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[335]), first, "../rtl/serv_rf_ram_if.v", 58, 20, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rcnt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[336]), first, "../rtl/serv_rf_ram_if.v", 58, 20, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rcnt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[337]), first, "../rtl/serv_rf_ram_if.v", 60, 12, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rtrig1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[332]), first, "../rtl/serv_rf_ram_if.v", 65, 24, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wcnt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[338]), first, "../rtl/serv_rf_ram_if.v", 65, 24, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wcnt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[339]), first, "../rtl/serv_rf_ram_if.v", 65, 24, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wcnt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[340]), first, "../rtl/serv_rf_ram_if.v", 65, 24, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wcnt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[341]), first, "../rtl/serv_rf_ram_if.v", 65, 24, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wcnt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[342]), first, "../rtl/serv_rf_ram_if.v", 67, 22, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wdata0_r[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[343]), first, "../rtl/serv_rf_ram_if.v", 67, 22, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wdata0_r[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[344]), first, "../rtl/serv_rf_ram_if.v", 68, 24, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wdata1_r[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[345]), first, "../rtl/serv_rf_ram_if.v", 68, 24, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wdata1_r[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[346]), first, "../rtl/serv_rf_ram_if.v", 68, 24, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wdata1_r[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[347]), first, "../rtl/serv_rf_ram_if.v", 70, 15, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wen0_r", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[348]), first, "../rtl/serv_rf_ram_if.v", 71, 15, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wen1_r", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[337]), first, "../rtl/serv_rf_ram_if.v", 72, 15, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wtrig0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[332]), first, "../rtl/serv_rf_ram_if.v", 73, 15, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wtrig1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[349]), first, "../rtl/serv_rf_ram_if.v", 90, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wreg[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[350]), first, "../rtl/serv_rf_ram_if.v", 90, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wreg[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[351]), first, "../rtl/serv_rf_ram_if.v", 90, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wreg[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[352]), first, "../rtl/serv_rf_ram_if.v", 90, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wreg[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[353]), first, "../rtl/serv_rf_ram_if.v", 90, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wreg[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[354]), first, "../rtl/serv_rf_ram_if.v", 90, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "wreg[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[355]), first, "../rtl/serv_rf_ram_if.v", 103, 7, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "if", "103-105");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[356]), first, "../rtl/serv_rf_ram_if.v", 103, 8, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[357]), first, "../rtl/serv_rf_ram_if.v", 102, 4, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_line/serv_rf_ram_if__W2_C4", "block", "102,108-109");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[332]), first, "../rtl/serv_rf_ram_if.v", 118, 12, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rtrig0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[358]), first, "../rtl/serv_rf_ram_if.v", 120, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rreg[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[359]), first, "../rtl/serv_rf_ram_if.v", 120, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rreg[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[360]), first, "../rtl/serv_rf_ram_if.v", 120, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rreg[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[361]), first, "../rtl/serv_rf_ram_if.v", 120, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rreg[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[362]), first, "../rtl/serv_rf_ram_if.v", 120, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rreg[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[363]), first, "../rtl/serv_rf_ram_if.v", 120, 19, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rreg[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[318]), first, "../rtl/serv_rf_ram_if.v", 128, 21, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rdata0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[364]), first, "../rtl/serv_rf_ram_if.v", 128, 21, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rdata0[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[365]), first, "../rtl/serv_rf_ram_if.v", 129, 23, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rdata1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[200]), first, "../rtl/serv_rf_ram_if.v", 131, 14, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rgate", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[366]), first, "../rtl/serv_rf_ram_if.v", 145, 15, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_toggle/serv_rf_ram_if__W2_C4", "rreq_r", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[367]), first, "../rtl/serv_rf_ram_if.v", 154, 31, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "if", "154");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[368]), first, "../rtl/serv_rf_ram_if.v", 154, 32, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[369]), first, "../rtl/serv_rf_ram_if.v", 154, 7, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_line/serv_rf_ram_if__W2_C4", "block", "154");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[370]), first, "../rtl/serv_rf_ram_if.v", 159, 7, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "if", "159-160");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[371]), first, "../rtl/serv_rf_ram_if.v", 159, 8, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[372]), first, "../rtl/serv_rf_ram_if.v", 164, 7, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "if", "164-165");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[373]), first, "../rtl/serv_rf_ram_if.v", 164, 8, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[374]), first, "../rtl/serv_rf_ram_if.v", 171, 7, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "if", "171-172");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[375]), first, "../rtl/serv_rf_ram_if.v", 171, 8, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[376]), first, "../rtl/serv_rf_ram_if.v", 175, 3, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "if", "175-179");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[377]), first, "../rtl/serv_rf_ram_if.v", 175, 4, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[378]), first, "../rtl/serv_rf_ram_if.v", 174, 7, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "if", "174");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[379]), first, "../rtl/serv_rf_ram_if.v", 174, 8, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_branch/serv_rf_ram_if__W2_C4", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[380]), first, "../rtl/serv_rf_ram_if.v", 158, 4, ".tb_cov_top.dut.u_servile.rf_ram_if", "v_line/serv_rf_ram_if__W2_C4", "block", "158,162-163,167-168,170");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_top.v", 21, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[1]), first, "../rtl/serv_top.v", 22, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_rst", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 23, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_timer_irq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[288]), first, "../rtl/serv_top.v", 48, 24, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rf_rreq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[287]), first, "../rtl/serv_top.v", 49, 24, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rf_wreq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[317]), first, "../rtl/serv_top.v", 50, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_rf_ready", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[289]), first, "../rtl/serv_top.v", 51, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[290]), first, "../rtl/serv_top.v", 51, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg0[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[291]), first, "../rtl/serv_top.v", 51, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg0[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[292]), first, "../rtl/serv_top.v", 51, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg0[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[293]), first, "../rtl/serv_top.v", 51, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg0[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[294]), first, "../rtl/serv_top.v", 51, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg0[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[295]), first, "../rtl/serv_top.v", 52, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[296]), first, "../rtl/serv_top.v", 52, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[297]), first, "../rtl/serv_top.v", 52, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[298]), first, "../rtl/serv_top.v", 52, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[299]), first, "../rtl/serv_top.v", 52, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[300]), first, "../rtl/serv_top.v", 52, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wreg1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[301]), first, "../rtl/serv_top.v", 53, 24, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wen0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[302]), first, "../rtl/serv_top.v", 54, 24, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wen1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[328]), first, "../rtl/serv_top.v", 55, 22, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wdata0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[329]), first, "../rtl/serv_top.v", 56, 22, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_wdata1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[305]), first, "../rtl/serv_top.v", 57, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[306]), first, "../rtl/serv_top.v", 57, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg0[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[307]), first, "../rtl/serv_top.v", 57, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg0[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[308]), first, "../rtl/serv_top.v", 57, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg0[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[309]), first, "../rtl/serv_top.v", 57, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg0[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[310]), first, "../rtl/serv_top.v", 57, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg0[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[311]), first, "../rtl/serv_top.v", 58, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[312]), first, "../rtl/serv_top.v", 58, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[313]), first, "../rtl/serv_top.v", 58, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[314]), first, "../rtl/serv_top.v", 58, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[315]), first, "../rtl/serv_top.v", 58, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[316]), first, "../rtl/serv_top.v", 58, 31, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_rreg1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[318]), first, "../rtl/serv_top.v", 59, 22, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_rdata0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[330]), first, "../rtl/serv_top.v", 60, 22, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_rdata1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[217]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[218]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[219]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[220]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[221]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[222]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[223]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[224]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[225]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[226]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[227]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[228]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[229]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[230]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[231]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[232]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[233]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[234]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[235]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[236]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[237]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[238]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[239]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[240]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[241]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[242]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[243]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[244]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[245]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[246]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[247]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[248]), first, "../rtl/serv_top.v", 62, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[249]), first, "../rtl/serv_top.v", 63, 24, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ibus_cyc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/serv_top.v", 64, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[250]), first, "../rtl/serv_top.v", 65, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ibus_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/serv_top.v", 66, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/serv_top.v", 67, 30, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/serv_top.v", 68, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/serv_top.v", 68, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/serv_top.v", 68, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/serv_top.v", 68, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/serv_top.v", 69, 24, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[251]), first, "../rtl/serv_top.v", 70, 24, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_dbus_cyc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[252]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[253]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[254]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[255]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[256]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[257]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[258]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[259]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[260]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[261]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[262]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[263]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[264]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[265]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[266]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[267]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[268]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[269]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[270]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[271]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[272]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[273]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[274]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[275]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[276]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[277]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[278]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[279]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[280]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[281]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[282]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[283]), first, "../rtl/serv_top.v", 71, 29, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[284]), first, "../rtl/serv_top.v", 72, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_dbus_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_top.v", 74, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_funct3[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_top.v", 74, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_funct3[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_top.v", 74, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_funct3[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 75, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_ready", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 76, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_ext_rd[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[320]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[321]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/serv_top.v", 77, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs1[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/serv_top.v", 78, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_ext_rs2[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 80, 23, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "o_mdu_valid", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[381]), first, "../rtl/serv_top.v", 82, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rd_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[382]), first, "../rtl/serv_top.v", 82, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rd_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[383]), first, "../rtl/serv_top.v", 82, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rd_addr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[384]), first, "../rtl/serv_top.v", 82, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rd_addr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[385]), first, "../rtl/serv_top.v", 82, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rd_addr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[386]), first, "../rtl/serv_top.v", 83, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs1_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[387]), first, "../rtl/serv_top.v", 83, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs1_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[388]), first, "../rtl/serv_top.v", 83, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs1_addr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[389]), first, "../rtl/serv_top.v", 83, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs1_addr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[390]), first, "../rtl/serv_top.v", 83, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs1_addr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[391]), first, "../rtl/serv_top.v", 84, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs2_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[392]), first, "../rtl/serv_top.v", 84, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs2_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[393]), first, "../rtl/serv_top.v", 84, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs2_addr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[394]), first, "../rtl/serv_top.v", 84, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs2_addr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[395]), first, "../rtl/serv_top.v", 84, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs2_addr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[396]), first, "../rtl/serv_top.v", 86, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "immdec_ctrl[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[397]), first, "../rtl/serv_top.v", 86, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "immdec_ctrl[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[398]), first, "../rtl/serv_top.v", 86, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "immdec_ctrl[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[399]), first, "../rtl/serv_top.v", 86, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "immdec_ctrl[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[400]), first, "../rtl/serv_top.v", 87, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "immdec_en[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[401]), first, "../rtl/serv_top.v", 87, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "immdec_en[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[402]), first, "../rtl/serv_top.v", 87, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "immdec_en[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[403]), first, "../rtl/serv_top.v", 87, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "immdec_en[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_top.v", 89, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "sh_right", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_top.v", 90, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "bne_or_bge", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[404]), first, "../rtl/serv_top.v", 91, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cond_branch", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[405]), first, "../rtl/serv_top.v", 92, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "two_stage_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[406]), first, "../rtl/serv_top.v", 93, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "e_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[407]), first, "../rtl/serv_top.v", 94, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "ebreak", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[408]), first, "../rtl/serv_top.v", 95, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "branch_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[409]), first, "../rtl/serv_top.v", 96, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "shift_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[410]), first, "../rtl/serv_top.v", 97, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rd_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 98, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "mdu_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[411]), first, "../rtl/serv_top.v", 100, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rd_alu_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[412]), first, "../rtl/serv_top.v", 101, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rd_csr_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[413]), first, "../rtl/serv_top.v", 102, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rd_mem_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[414]), first, "../rtl/serv_top.v", 103, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "ctrl_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[415]), first, "../rtl/serv_top.v", 104, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "alu_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[416]), first, "../rtl/serv_top.v", 105, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "mem_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[417]), first, "../rtl/serv_top.v", 106, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[408]), first, "../rtl/serv_top.v", 107, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "mtval_pc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[418]), first, "../rtl/serv_top.v", 109, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "ctrl_pc_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[419]), first, "../rtl/serv_top.v", 110, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "jump", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[420]), first, "../rtl/serv_top.v", 111, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "jal_or_jalr", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[421]), first, "../rtl/serv_top.v", 112, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "utype", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[422]), first, "../rtl/serv_top.v", 113, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "mret", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[423]), first, "../rtl/serv_top.v", 114, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "imm[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[424]), first, "../rtl/serv_top.v", 115, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "trap", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[425]), first, "../rtl/serv_top.v", 116, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "pc_rel", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_top.v", 117, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "iscomp", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[426]), first, "../rtl/serv_top.v", 119, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "init", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[427]), first, "../rtl/serv_top.v", 120, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[428]), first, "../rtl/serv_top.v", 121, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt0to3", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[429]), first, "../rtl/serv_top.v", 122, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt12to31", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[430]), first, "../rtl/serv_top.v", 123, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[431]), first, "../rtl/serv_top.v", 124, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[432]), first, "../rtl/serv_top.v", 125, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt2", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[433]), first, "../rtl/serv_top.v", 126, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt3", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[434]), first, "../rtl/serv_top.v", 127, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt7", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[435]), first, "../rtl/serv_top.v", 128, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt11", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[436]), first, "../rtl/serv_top.v", 129, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt12", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[437]), first, "../rtl/serv_top.v", 131, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "cnt_done", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[438]), first, "../rtl/serv_top.v", 133, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "bufreg_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[439]), first, "../rtl/serv_top.v", 134, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "bufreg_sh_signed", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[440]), first, "../rtl/serv_top.v", 135, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "bufreg_rs1_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[441]), first, "../rtl/serv_top.v", 136, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "bufreg_imm_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[442]), first, "../rtl/serv_top.v", 137, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "bufreg_clr_lsb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[443]), first, "../rtl/serv_top.v", 138, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "bufreg_q[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[444]), first, "../rtl/serv_top.v", 139, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "bufreg2_q[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[252]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[253]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[254]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[255]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[256]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[257]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[258]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[259]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[260]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[261]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[262]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[263]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[264]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[265]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[266]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[267]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[268]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[269]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[270]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[271]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[272]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[273]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[274]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[275]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[276]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[277]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[278]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[279]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[280]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[281]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[282]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[283]), first, "../rtl/serv_top.v", 140, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[284]), first, "../rtl/serv_top.v", 141, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[445]), first, "../rtl/serv_top.v", 143, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "alu_sub", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_top.v", 144, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "alu_bool_op[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_top.v", 144, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "alu_bool_op[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[446]), first, "../rtl/serv_top.v", 145, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "alu_cmp_eq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[447]), first, "../rtl/serv_top.v", 146, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "alu_cmp_sig", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[448]), first, "../rtl/serv_top.v", 147, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "alu_cmp", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[449]), first, "../rtl/serv_top.v", 148, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "alu_rd_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[450]), first, "../rtl/serv_top.v", 148, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "alu_rd_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[451]), first, "../rtl/serv_top.v", 148, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "alu_rd_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[318]), first, "../rtl/serv_top.v", 150, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[330]), first, "../rtl/serv_top.v", 151, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rs2[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[452]), first, "../rtl/serv_top.v", 152, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rd_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[453]), first, "../rtl/serv_top.v", 154, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "op_b[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/serv_top.v", 155, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "op_b_sel", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[454]), first, "../rtl/serv_top.v", 157, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "mem_signed", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_top.v", 158, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "mem_word", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_top.v", 159, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "mem_half", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[455]), first, "../rtl/serv_top.v", 160, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "mem_bytecnt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[456]), first, "../rtl/serv_top.v", 160, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "mem_bytecnt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[457]), first, "../rtl/serv_top.v", 161, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "sh_done", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[458]), first, "../rtl/serv_top.v", 163, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "mem_misalign", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[459]), first, "../rtl/serv_top.v", 165, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "bad_pc[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[460]), first, "../rtl/serv_top.v", 167, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_mstatus_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[461]), first, "../rtl/serv_top.v", 168, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_mie_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[462]), first, "../rtl/serv_top.v", 169, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_mcause_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_top.v", 170, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_source[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_top.v", 170, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_source[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[386]), first, "../rtl/serv_top.v", 171, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_imm[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_top.v", 172, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_d_sel", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[463]), first, "../rtl/serv_top.v", 173, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[464]), first, "../rtl/serv_top.v", 174, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[465]), first, "../rtl/serv_top.v", 174, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[330]), first, "../rtl/serv_top.v", 175, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_pc[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[466]), first, "../rtl/serv_top.v", 176, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_imm_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[467]), first, "../rtl/serv_top.v", 177, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "csr_in[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[468]), first, "../rtl/serv_top.v", 178, 18, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "rf_csr_out[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[469]), first, "../rtl/serv_top.v", 179, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "dbus_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[470]), first, "../rtl/serv_top.v", 181, 11, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "new_irq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[320]), first, "../rtl/serv_top.v", 183, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "lsb[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[321]), first, "../rtl/serv_top.v", 183, 17, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "lsb[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/serv_top.v", 185, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "i_wb_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[217]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[218]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[219]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[220]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[221]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[222]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[223]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[224]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[225]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[226]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[227]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[228]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[229]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[230]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[231]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[232]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[233]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[234]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[235]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[236]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[237]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[238]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[239]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[240]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[241]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[242]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[243]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[244]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[245]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[246]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[247]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[248]), first, "../rtl/serv_top.v", 187, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[249]), first, "../rtl/serv_top.v", 188, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_cyc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[109]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[110]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/serv_top.v", 189, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[250]), first, "../rtl/serv_top.v", 190, 16, ".tb_cov_top.dut.u_servile.cpu", "v_toggle/serv_top__Pz1_Dz2_Mz2_Cz2", "wb_ibus_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_state.v", 15, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[1]), first, "../rtl/serv_state.v", 16, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_rst", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[470]), first, "../rtl/serv_state.v", 18, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_new_irq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[448]), first, "../rtl/serv_state.v", 19, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_alu_cmp", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[426]), first, "../rtl/serv_state.v", 20, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_init", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[427]), first, "../rtl/serv_state.v", 21, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[428]), first, "../rtl/serv_state.v", 22, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt0to3", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[429]), first, "../rtl/serv_state.v", 23, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt12to31", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[430]), first, "../rtl/serv_state.v", 24, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[431]), first, "../rtl/serv_state.v", 25, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[432]), first, "../rtl/serv_state.v", 26, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt2", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[433]), first, "../rtl/serv_state.v", 27, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt3", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[434]), first, "../rtl/serv_state.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt7", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[435]), first, "../rtl/serv_state.v", 29, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt11", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[436]), first, "../rtl/serv_state.v", 30, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt12", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[437]), first, "../rtl/serv_state.v", 31, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt_done", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[438]), first, "../rtl/serv_state.v", 32, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_bufreg_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[418]), first, "../rtl/serv_state.v", 33, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_ctrl_pc_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[419]), first, "../rtl/serv_state.v", 34, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_ctrl_jump", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[424]), first, "../rtl/serv_state.v", 35, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_ctrl_trap", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[321]), first, "../rtl/serv_state.v", 36, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_ctrl_misalign", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[457]), first, "../rtl/serv_state.v", 37, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_sh_done", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[455]), first, "../rtl/serv_state.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_mem_bytecnt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[456]), first, "../rtl/serv_state.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_mem_bytecnt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[458]), first, "../rtl/serv_state.v", 39, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_mem_misalign", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_state.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_bne_or_bge", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[404]), first, "../rtl/serv_state.v", 42, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_cond_branch", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[469]), first, "../rtl/serv_state.v", 43, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_dbus_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[405]), first, "../rtl/serv_state.v", 44, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_two_stage_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[408]), first, "../rtl/serv_state.v", 45, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_branch_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[409]), first, "../rtl/serv_state.v", 46, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_shift_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_state.v", 47, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_sh_right", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[450]), first, "../rtl/serv_state.v", 48, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_alu_rd_sel1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[411]), first, "../rtl/serv_state.v", 49, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_rd_alu_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[406]), first, "../rtl/serv_state.v", 50, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_e_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[410]), first, "../rtl/serv_state.v", 51, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_rd_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_state.v", 53, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_mdu_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_state.v", 54, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_mdu_valid", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_state.v", 56, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_mdu_ready", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[251]), first, "../rtl/serv_state.v", 58, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_dbus_cyc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[284]), first, "../rtl/serv_state.v", 59, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_dbus_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[249]), first, "../rtl/serv_state.v", 60, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_ibus_cyc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[250]), first, "../rtl/serv_state.v", 61, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_ibus_ack", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[288]), first, "../rtl/serv_state.v", 63, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_rf_rreq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[287]), first, "../rtl/serv_state.v", 64, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_rf_wreq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[317]), first, "../rtl/serv_state.v", 65, 21, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "i_rf_ready", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[452]), first, "../rtl/serv_state.v", 66, 22, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_rf_rd_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[471]), first, "../rtl/serv_state.v", 68, 9, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "init_done", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[472]), first, "../rtl/serv_state.v", 69, 9, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "misalign_trap_sync", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[473]), first, "../rtl/serv_state.v", 71, 14, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[455]), first, "../rtl/serv_state.v", 71, 14, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[456]), first, "../rtl/serv_state.v", 71, 14, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "o_cnt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[474]), first, "../rtl/serv_state.v", 72, 15, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "cnt_r[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[475]), first, "../rtl/serv_state.v", 72, 15, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "cnt_r[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[476]), first, "../rtl/serv_state.v", 72, 15, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "cnt_r[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[477]), first, "../rtl/serv_state.v", 72, 15, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "cnt_r[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[478]), first, "../rtl/serv_state.v", 74, 14, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "ibus_cyc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[479]), first, "../rtl/serv_state.v", 96, 14, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "take_branch", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[480]), first, "../rtl/serv_state.v", 98, 9, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "last_init", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[481]), first, "../rtl/serv_state.v", 105, 9, ".tb_cov_top.dut.u_servile.cpu.state", "v_toggle/serv_state__Wz1_Mz2_Az2", "trap_pending", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[482]), first, "../rtl/serv_state.v", 157, 7, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "if", "157-158");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[483]), first, "../rtl/serv_state.v", 157, 8, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[484]), first, "../rtl/serv_state.v", 160, 7, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "if", "160-162");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[485]), first, "../rtl/serv_state.v", 160, 8, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[486]), first, "../rtl/serv_state.v", 166, 3, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "if", "166-168");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[487]), first, "../rtl/serv_state.v", 166, 4, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[488]), first, "../rtl/serv_state.v", 165, 7, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "if", "165");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[489]), first, "../rtl/serv_state.v", 165, 8, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[490]), first, "../rtl/serv_state.v", 147, 4, ".tb_cov_top.dut.u_servile.cpu.state", "v_line/serv_state__Wz1_Mz2_Az2", "block", "147");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[491]), first, "../rtl/serv_state.v", 201, 6, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "if", "201-203");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[492]), first, "../rtl/serv_state.v", 201, 7, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[493]), first, "../rtl/serv_state.v", 198, 3, ".tb_cov_top.dut.u_servile.cpu.state", "v_line/serv_state__Wz1_Mz2_Az2", "block", "198-200");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[494]), first, "../rtl/serv_state.v", 231, 6, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "if", "231-232");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[495]), first, "../rtl/serv_state.v", 231, 7, ".tb_cov_top.dut.u_servile.cpu.state", "v_branch/serv_state__Wz1_Mz2_Az2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[496]), first, "../rtl/serv_state.v", 230, 3, ".tb_cov_top.dut.u_servile.cpu.state", "v_line/serv_state__Wz1_Mz2_Az2", "block", "230");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_decode.v", 12, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[111]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[112]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[113]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[114]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[115]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/serv_decode.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[250]), first, "../rtl/serv_decode.v", 15, 22, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "i_wb_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_decode.v", 17, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_sh_right", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 18, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_bne_or_bge", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[404]), first, "../rtl/serv_decode.v", 19, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_cond_branch", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[406]), first, "../rtl/serv_decode.v", 20, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_e_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[407]), first, "../rtl/serv_decode.v", 21, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_ebreak", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[408]), first, "../rtl/serv_decode.v", 22, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_branch_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[409]), first, "../rtl/serv_decode.v", 23, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_shift_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[410]), first, "../rtl/serv_decode.v", 24, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_rd_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[405]), first, "../rtl/serv_decode.v", 25, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_two_stage_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[469]), first, "../rtl/serv_decode.v", 26, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_dbus_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_decode.v", 28, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_mdu_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 30, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_ext_funct3[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_decode.v", 30, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_ext_funct3[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_decode.v", 30, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_ext_funct3[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[440]), first, "../rtl/serv_decode.v", 32, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_bufreg_rs1_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[441]), first, "../rtl/serv_decode.v", 33, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_bufreg_imm_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[442]), first, "../rtl/serv_decode.v", 34, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_bufreg_clr_lsb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[439]), first, "../rtl/serv_decode.v", 35, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_bufreg_sh_signed", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[420]), first, "../rtl/serv_decode.v", 37, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_ctrl_jal_or_jalr", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[421]), first, "../rtl/serv_decode.v", 38, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_ctrl_utype", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[425]), first, "../rtl/serv_decode.v", 39, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_ctrl_pc_rel", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[422]), first, "../rtl/serv_decode.v", 40, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_ctrl_mret", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[445]), first, "../rtl/serv_decode.v", 42, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_alu_sub", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 43, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_alu_bool_op[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_decode.v", 43, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_alu_bool_op[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[446]), first, "../rtl/serv_decode.v", 44, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_alu_cmp_eq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[447]), first, "../rtl/serv_decode.v", 45, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_alu_cmp_sig", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[449]), first, "../rtl/serv_decode.v", 46, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_alu_rd_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[450]), first, "../rtl/serv_decode.v", 46, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_alu_rd_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[451]), first, "../rtl/serv_decode.v", 46, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_alu_rd_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[454]), first, "../rtl/serv_decode.v", 48, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_mem_signed", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_decode.v", 49, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_mem_word", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 50, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_mem_half", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/serv_decode.v", 51, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_mem_cmd", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[463]), first, "../rtl/serv_decode.v", 53, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_csr_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[464]), first, "../rtl/serv_decode.v", 54, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_csr_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[465]), first, "../rtl/serv_decode.v", 54, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_csr_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[460]), first, "../rtl/serv_decode.v", 55, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_csr_mstatus_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[461]), first, "../rtl/serv_decode.v", 56, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_csr_mie_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[462]), first, "../rtl/serv_decode.v", 57, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_csr_mcause_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 58, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_csr_source[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_decode.v", 58, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_csr_source[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_decode.v", 59, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_csr_d_sel", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[466]), first, "../rtl/serv_decode.v", 60, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_csr_imm_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[408]), first, "../rtl/serv_decode.v", 61, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_mtval_pc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[396]), first, "../rtl/serv_decode.v", 63, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_immdec_ctrl[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[397]), first, "../rtl/serv_decode.v", 63, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_immdec_ctrl[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[398]), first, "../rtl/serv_decode.v", 63, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_immdec_ctrl[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[399]), first, "../rtl/serv_decode.v", 63, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_immdec_ctrl[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[400]), first, "../rtl/serv_decode.v", 64, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_immdec_en[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[401]), first, "../rtl/serv_decode.v", 64, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_immdec_en[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[402]), first, "../rtl/serv_decode.v", 64, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_immdec_en[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[403]), first, "../rtl/serv_decode.v", 64, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_immdec_en[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/serv_decode.v", 65, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_op_b_source", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[413]), first, "../rtl/serv_decode.v", 67, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_rd_mem_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[412]), first, "../rtl/serv_decode.v", 68, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_rd_csr_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[411]), first, "../rtl/serv_decode.v", 69, 21, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "o_rd_alu_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[497]), first, "../rtl/serv_decode.v", 71, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "opcode[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[498]), first, "../rtl/serv_decode.v", 71, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "opcode[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[499]), first, "../rtl/serv_decode.v", 71, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "opcode[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/serv_decode.v", 71, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "opcode[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[408]), first, "../rtl/serv_decode.v", 71, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "opcode[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 72, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "funct3[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_decode.v", 72, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "funct3[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_decode.v", 72, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "funct3[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[407]), first, "../rtl/serv_decode.v", 73, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "op20", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[500]), first, "../rtl/serv_decode.v", 74, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "op21", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[501]), first, "../rtl/serv_decode.v", 75, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "op22", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[502]), first, "../rtl/serv_decode.v", 76, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "op26", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[503]), first, "../rtl/serv_decode.v", 78, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "imm25", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[439]), first, "../rtl/serv_decode.v", 79, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "imm30", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_decode.v", 81, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_mdu_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[405]), first, "../rtl/serv_decode.v", 83, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_two_stage_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[409]), first, "../rtl/serv_decode.v", 86, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_shift_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[408]), first, "../rtl/serv_decode.v", 87, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_branch_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[469]), first, "../rtl/serv_decode.v", 88, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_dbus_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[408]), first, "../rtl/serv_decode.v", 89, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_mtval_pc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_decode.v", 90, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_mem_word", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[411]), first, "../rtl/serv_decode.v", 91, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_rd_alu_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[413]), first, "../rtl/serv_decode.v", 92, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_rd_mem_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 93, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_ext_funct3[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_decode.v", 93, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_ext_funct3[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_decode.v", 93, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_ext_funct3[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[440]), first, "../rtl/serv_decode.v", 99, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_bufreg_rs1_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[441]), first, "../rtl/serv_decode.v", 100, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_bufreg_imm_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[442]), first, "../rtl/serv_decode.v", 105, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_bufreg_clr_lsb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[404]), first, "../rtl/serv_decode.v", 110, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_cond_branch", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[421]), first, "../rtl/serv_decode.v", 112, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_ctrl_utype", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[420]), first, "../rtl/serv_decode.v", 113, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_ctrl_jal_or_jalr", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[425]), first, "../rtl/serv_decode.v", 118, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_ctrl_pc_rel", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[410]), first, "../rtl/serv_decode.v", 125, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_rd_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_decode.v", 133, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_sh_right", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 134, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_bne_or_bge", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[412]), first, "../rtl/serv_decode.v", 137, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "csr_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[407]), first, "../rtl/serv_decode.v", 141, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_ebreak", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[422]), first, "../rtl/serv_decode.v", 146, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_ctrl_mret", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[406]), first, "../rtl/serv_decode.v", 149, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_e_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[439]), first, "../rtl/serv_decode.v", 153, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_bufreg_sh_signed", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[445]), first, "../rtl/serv_decode.v", 165, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_alu_sub", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[504]), first, "../rtl/serv_decode.v", 190, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "csr_valid", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[412]), first, "../rtl/serv_decode.v", 192, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_rd_csr_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[463]), first, "../rtl/serv_decode.v", 194, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_csr_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[460]), first, "../rtl/serv_decode.v", 195, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_csr_mstatus_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[461]), first, "../rtl/serv_decode.v", 196, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_csr_mie_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[462]), first, "../rtl/serv_decode.v", 197, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_csr_mcause_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 199, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_csr_source[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_decode.v", 199, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_csr_source[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_decode.v", 200, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_csr_d_sel", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[466]), first, "../rtl/serv_decode.v", 201, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_csr_imm_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[464]), first, "../rtl/serv_decode.v", 202, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_csr_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[465]), first, "../rtl/serv_decode.v", 202, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_csr_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[446]), first, "../rtl/serv_decode.v", 204, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_alu_cmp_eq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[447]), first, "../rtl/serv_decode.v", 206, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_alu_cmp_sig", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/serv_decode.v", 208, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_mem_cmd", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[454]), first, "../rtl/serv_decode.v", 209, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_mem_signed", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 210, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_mem_half", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_decode.v", 212, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_alu_bool_op[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_decode.v", 212, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_alu_bool_op[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[396]), first, "../rtl/serv_decode.v", 214, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_immdec_ctrl[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[397]), first, "../rtl/serv_decode.v", 214, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_immdec_ctrl[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[398]), first, "../rtl/serv_decode.v", 214, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_immdec_ctrl[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[399]), first, "../rtl/serv_decode.v", 214, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_immdec_ctrl[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[400]), first, "../rtl/serv_decode.v", 224, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_immdec_en[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[401]), first, "../rtl/serv_decode.v", 224, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_immdec_en[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[402]), first, "../rtl/serv_decode.v", 224, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_immdec_en[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[403]), first, "../rtl/serv_decode.v", 224, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_immdec_en[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[449]), first, "../rtl/serv_decode.v", 230, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_alu_rd_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[450]), first, "../rtl/serv_decode.v", 230, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_alu_rd_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[451]), first, "../rtl/serv_decode.v", 230, 15, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_alu_rd_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/serv_decode.v", 237, 9, ".tb_cov_top.dut.u_servile.cpu.decode", "v_toggle/serv_decode__Pz1_Mz2", "co_op_b_source", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[505]), first, "../rtl/serv_decode.v", 243, 13, ".tb_cov_top.dut.u_servile.cpu.decode", "v_branch/serv_decode__Pz1_Mz2", "if", "243-251");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[506]), first, "../rtl/serv_decode.v", 243, 14, ".tb_cov_top.dut.u_servile.cpu.decode", "v_branch/serv_decode__Pz1_Mz2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[507]), first, "../rtl/serv_decode.v", 242, 10, ".tb_cov_top.dut.u_servile.cpu.decode", "v_line/serv_decode__Pz1_Mz2", "block", "242");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[508]), first, "../rtl/serv_decode.v", 255, 10, ".tb_cov_top.dut.u_servile.cpu.decode", "v_line/serv_decode__Pz1_Mz2", "block", "255-299");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_immdec.v", 12, 21, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[427]), first, "../rtl/serv_immdec.v", 14, 21, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_cnt_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[437]), first, "../rtl/serv_immdec.v", 15, 21, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_cnt_done", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[400]), first, "../rtl/serv_immdec.v", 17, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_immdec_en[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[401]), first, "../rtl/serv_immdec.v", 17, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_immdec_en[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[402]), first, "../rtl/serv_immdec.v", 17, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_immdec_en[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[403]), first, "../rtl/serv_immdec.v", 17, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_immdec_en[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[466]), first, "../rtl/serv_immdec.v", 18, 21, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_csr_imm_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[396]), first, "../rtl/serv_immdec.v", 19, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_ctrl[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[397]), first, "../rtl/serv_immdec.v", 19, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_ctrl[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[398]), first, "../rtl/serv_immdec.v", 19, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_ctrl[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[399]), first, "../rtl/serv_immdec.v", 19, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_ctrl[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[381]), first, "../rtl/serv_immdec.v", 20, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rd_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[382]), first, "../rtl/serv_immdec.v", 20, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rd_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[383]), first, "../rtl/serv_immdec.v", 20, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rd_addr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[384]), first, "../rtl/serv_immdec.v", 20, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rd_addr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[385]), first, "../rtl/serv_immdec.v", 20, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rd_addr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[386]), first, "../rtl/serv_immdec.v", 21, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rs1_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[387]), first, "../rtl/serv_immdec.v", 21, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rs1_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[388]), first, "../rtl/serv_immdec.v", 21, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rs1_addr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[389]), first, "../rtl/serv_immdec.v", 21, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rs1_addr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[390]), first, "../rtl/serv_immdec.v", 21, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rs1_addr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[391]), first, "../rtl/serv_immdec.v", 22, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rs2_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[392]), first, "../rtl/serv_immdec.v", 22, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rs2_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[393]), first, "../rtl/serv_immdec.v", 22, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rs2_addr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[394]), first, "../rtl/serv_immdec.v", 22, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rs2_addr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[395]), first, "../rtl/serv_immdec.v", 22, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_rs2_addr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[386]), first, "../rtl/serv_immdec.v", 24, 24, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_csr_imm[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[509]), first, "../rtl/serv_immdec.v", 25, 24, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "o_imm[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[250]), first, "../rtl/serv_immdec.v", 27, 21, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[116]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[117]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[118]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[119]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[120]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[121]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[122]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[123]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[124]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[125]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[126]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[127]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[128]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[129]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[130]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[131]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[132]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[133]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[134]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[135]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[136]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[137]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[138]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[139]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[140]), first, "../rtl/serv_immdec.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_toggle/serv_immdec", "i_wb_rdt[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[510]), first, "../rtl/serv_immdec.v", 50, 6, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "if", "50,52");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[511]), first, "../rtl/serv_immdec.v", 50, 7, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[512]), first, "../rtl/serv_immdec.v", 54, 6, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "if", "54-55");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[513]), first, "../rtl/serv_immdec.v", 54, 7, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[514]), first, "../rtl/serv_immdec.v", 56, 6, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "if", "56-57");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[515]), first, "../rtl/serv_immdec.v", 56, 7, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[516]), first, "../rtl/serv_immdec.v", 59, 6, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "if", "59-60");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[517]), first, "../rtl/serv_immdec.v", 59, 7, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[518]), first, "../rtl/serv_immdec.v", 62, 6, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "if", "62-63");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[519]), first, "../rtl/serv_immdec.v", 62, 7, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[520]), first, "../rtl/serv_immdec.v", 65, 6, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "if", "65-66");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[521]), first, "../rtl/serv_immdec.v", 65, 7, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_branch/serv_immdec", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[522]), first, "../rtl/serv_immdec.v", 49, 3, ".tb_cov_top.dut.u_servile.cpu.immdec", "v_line/serv_immdec", "block", "49");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_bufreg.v", 12, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[430]), first, "../rtl/serv_bufreg.v", 14, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_cnt0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[431]), first, "../rtl/serv_bufreg.v", 15, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_cnt1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[437]), first, "../rtl/serv_bufreg.v", 16, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_cnt_done", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[438]), first, "../rtl/serv_bufreg.v", 17, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[426]), first, "../rtl/serv_bufreg.v", 18, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_init", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_bufreg.v", 19, 25, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_mdu_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[320]), first, "../rtl/serv_bufreg.v", 20, 25, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_lsb[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[321]), first, "../rtl/serv_bufreg.v", 20, 25, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_lsb[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[440]), first, "../rtl/serv_bufreg.v", 22, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_rs1_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[441]), first, "../rtl/serv_bufreg.v", 23, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_imm_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[442]), first, "../rtl/serv_bufreg.v", 24, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_clr_lsb", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[409]), first, "../rtl/serv_bufreg.v", 25, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_shift_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_bufreg.v", 26, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_right_shift_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[523]), first, "../rtl/serv_bufreg.v", 27, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_shamt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[524]), first, "../rtl/serv_bufreg.v", 27, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_shamt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[525]), first, "../rtl/serv_bufreg.v", 27, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_shamt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[439]), first, "../rtl/serv_bufreg.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_sh_signed", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[318]), first, "../rtl/serv_bufreg.v", 30, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_rs1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[509]), first, "../rtl/serv_bufreg.v", 31, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "i_imm[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[526]), first, "../rtl/serv_bufreg.v", 32, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_q[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/serv_bufreg.v", 34, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_dbus_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[320]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[321]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/serv_bufreg.v", 36, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "o_ext_rs1[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[527]), first, "../rtl/serv_bufreg.v", 38, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "c", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[528]), first, "../rtl/serv_bufreg.v", 39, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "q[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[529]), first, "../rtl/serv_bufreg.v", 40, 20, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "c_r[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[320]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[321]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[143]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[144]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[145]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[146]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[147]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[148]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[149]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[150]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[151]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[152]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[153]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[154]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[155]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[156]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[157]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[158]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[159]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[160]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[161]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[162]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[163]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[164]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[165]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[166]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[167]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[168]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[169]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[170]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[171]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[172]), first, "../rtl/serv_bufreg.v", 41, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "data[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[530]), first, "../rtl/serv_bufreg.v", 42, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_toggle/serv_bufreg__Mz2", "clr_lsb[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[531]), first, "../rtl/serv_bufreg.v", 54, 4, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_line/serv_bufreg__Mz2", "block", "54,56-57");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[532]), first, "../rtl/serv_bufreg.v", 63, 6, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_branch/serv_bufreg__Mz2", "if", "63-64");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[533]), first, "../rtl/serv_bufreg.v", 63, 7, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_branch/serv_bufreg__Mz2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[534]), first, "../rtl/serv_bufreg.v", 66, 6, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_branch/serv_bufreg__Mz2", "if", "66-67");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[535]), first, "../rtl/serv_bufreg.v", 66, 7, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_branch/serv_bufreg__Mz2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[536]), first, "../rtl/serv_bufreg.v", 62, 3, ".tb_cov_top.dut.u_servile.cpu.bufreg", "v_line/serv_bufreg__Mz2", "block", "62");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_bufreg2.v", 12, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[427]), first, "../rtl/serv_bufreg2.v", 14, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[426]), first, "../rtl/serv_bufreg2.v", 15, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_init", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[434]), first, "../rtl/serv_bufreg2.v", 16, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_cnt7", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[437]), first, "../rtl/serv_bufreg2.v", 17, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_cnt_done", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_bufreg2.v", 18, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_sh_right", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[320]), first, "../rtl/serv_bufreg2.v", 19, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_lsb[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[321]), first, "../rtl/serv_bufreg2.v", 19, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_lsb[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[455]), first, "../rtl/serv_bufreg2.v", 20, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_bytecnt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[456]), first, "../rtl/serv_bufreg2.v", 20, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_bytecnt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[457]), first, "../rtl/serv_bufreg2.v", 21, 22, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_sh_done", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/serv_bufreg2.v", 23, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_op_b_sel", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[409]), first, "../rtl/serv_bufreg2.v", 24, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_shift_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[330]), first, "../rtl/serv_bufreg2.v", 26, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_rs2[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[509]), first, "../rtl/serv_bufreg2.v", 27, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_imm[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[537]), first, "../rtl/serv_bufreg2.v", 28, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_op_b[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[538]), first, "../rtl/serv_bufreg2.v", 29, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_q[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[71]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[72]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[73]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[74]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[75]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[76]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[77]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[78]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[79]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[80]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[81]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[82]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[83]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[84]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[85]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[86]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[87]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[88]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[89]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[90]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[91]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[92]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[93]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[94]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[95]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[96]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[97]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[98]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[99]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[100]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[101]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[102]), first, "../rtl/serv_bufreg2.v", 31, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "o_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[284]), first, "../rtl/serv_bufreg2.v", 32, 21, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_load", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[252]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[253]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[254]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[255]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[256]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[257]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[258]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[259]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[260]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[261]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[262]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[263]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[264]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[265]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[266]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[267]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[268]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[269]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[270]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[271]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[272]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[273]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[274]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[275]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[276]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[277]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[278]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[279]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[280]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[281]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[282]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[283]), first, "../rtl/serv_bufreg2.v", 33, 23, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "i_dat[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[523]), first, "../rtl/serv_bufreg2.v", 36, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dhi[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[524]), first, "../rtl/serv_bufreg2.v", 36, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dhi[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[525]), first, "../rtl/serv_bufreg2.v", 36, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dhi[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[539]), first, "../rtl/serv_bufreg2.v", 36, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dhi[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[540]), first, "../rtl/serv_bufreg2.v", 36, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dhi[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[541]), first, "../rtl/serv_bufreg2.v", 36, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dhi[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[542]), first, "../rtl/serv_bufreg2.v", 36, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dhi[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[543]), first, "../rtl/serv_bufreg2.v", 36, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dhi[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[544]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[545]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[546]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[547]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[548]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[549]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[550]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[551]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[552]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[553]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[554]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[555]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[556]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[557]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[558]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[559]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[560]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[561]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[562]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[563]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[564]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[565]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[566]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[567]), first, "../rtl/serv_bufreg2.v", 37, 17, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dlo[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[568]), first, "../rtl/serv_bufreg2.v", 47, 9, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "byte_valid", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[569]), first, "../rtl/serv_bufreg2.v", 56, 11, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "shift_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[570]), first, "../rtl/serv_bufreg2.v", 58, 11, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "cnt_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[571]), first, "../rtl/serv_bufreg2.v", 73, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "cnt_next[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[572]), first, "../rtl/serv_bufreg2.v", 73, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "cnt_next[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[573]), first, "../rtl/serv_bufreg2.v", 73, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "cnt_next[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[574]), first, "../rtl/serv_bufreg2.v", 73, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "cnt_next[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[575]), first, "../rtl/serv_bufreg2.v", 73, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "cnt_next[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[576]), first, "../rtl/serv_bufreg2.v", 73, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "cnt_next[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[577]), first, "../rtl/serv_bufreg2.v", 73, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "cnt_next[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[578]), first, "../rtl/serv_bufreg2.v", 73, 16, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "cnt_next[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[579]), first, "../rtl/serv_bufreg2.v", 82, 15, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dat_shamt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[580]), first, "../rtl/serv_bufreg2.v", 82, 15, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dat_shamt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[581]), first, "../rtl/serv_bufreg2.v", 82, 15, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dat_shamt[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[582]), first, "../rtl/serv_bufreg2.v", 82, 15, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dat_shamt[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[583]), first, "../rtl/serv_bufreg2.v", 82, 15, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dat_shamt[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[457]), first, "../rtl/serv_bufreg2.v", 82, 15, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dat_shamt[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[584]), first, "../rtl/serv_bufreg2.v", 82, 15, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dat_shamt[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[585]), first, "../rtl/serv_bufreg2.v", 82, 15, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_toggle/serv_bufreg2", "dat_shamt[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[586]), first, "../rtl/serv_bufreg2.v", 99, 7, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_branch/serv_bufreg2", "if", "99-100");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[587]), first, "../rtl/serv_bufreg2.v", 99, 8, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_branch/serv_bufreg2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[588]), first, "../rtl/serv_bufreg2.v", 101, 7, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_branch/serv_bufreg2", "if", "101-102");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[589]), first, "../rtl/serv_bufreg2.v", 101, 8, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_branch/serv_bufreg2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[590]), first, "../rtl/serv_bufreg2.v", 98, 4, ".tb_cov_top.dut.u_servile.cpu.bufreg2", "v_line/serv_bufreg2", "block", "98");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_ctrl.v", 16, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[1]), first, "../rtl/serv_ctrl.v", 17, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_rst", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[418]), first, "../rtl/serv_ctrl.v", 19, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_pc_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[429]), first, "../rtl/serv_ctrl.v", 20, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_cnt12to31", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[430]), first, "../rtl/serv_ctrl.v", 21, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_cnt0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[431]), first, "../rtl/serv_ctrl.v", 22, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_cnt1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[432]), first, "../rtl/serv_ctrl.v", 23, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_cnt2", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[419]), first, "../rtl/serv_ctrl.v", 25, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_jump", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[420]), first, "../rtl/serv_ctrl.v", 26, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_jal_or_jalr", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[421]), first, "../rtl/serv_ctrl.v", 27, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_utype", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[425]), first, "../rtl/serv_ctrl.v", 28, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_pc_rel", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[591]), first, "../rtl/serv_ctrl.v", 29, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_trap", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_ctrl.v", 30, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_iscomp", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[509]), first, "../rtl/serv_ctrl.v", 32, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_imm[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[526]), first, "../rtl/serv_ctrl.v", 33, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_buf[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[330]), first, "../rtl/serv_ctrl.v", 34, 21, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "i_csr_pc[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[592]), first, "../rtl/serv_ctrl.v", 35, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[593]), first, "../rtl/serv_ctrl.v", 36, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_bad_pc[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[217]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[218]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[219]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[220]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[221]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[222]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[223]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[224]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[225]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[226]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[227]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[10]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[228]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[11]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[229]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[12]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[230]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[13]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[231]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[14]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[232]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[15]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[233]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[16]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[234]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[17]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[235]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[18]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[236]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[19]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[237]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[20]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[238]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[21]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[239]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[22]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[240]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[23]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[241]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[24]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[242]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[25]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[243]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[26]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[244]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[27]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[245]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[28]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[246]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[29]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[247]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[30]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[248]), first, "../rtl/serv_ctrl.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "o_ibus_adr[31]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[594]), first, "../rtl/serv_ctrl.v", 40, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "pc_plus_4[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[595]), first, "../rtl/serv_ctrl.v", 41, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "pc_plus_4_cy", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[596]), first, "../rtl/serv_ctrl.v", 42, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "pc_plus_4_cy_r", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[596]), first, "../rtl/serv_ctrl.v", 43, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "pc_plus_4_cy_r_w[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[597]), first, "../rtl/serv_ctrl.v", 44, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "pc_plus_offset[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[598]), first, "../rtl/serv_ctrl.v", 45, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "pc_plus_offset_cy", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[599]), first, "../rtl/serv_ctrl.v", 46, 14, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "pc_plus_offset_cy_r", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[599]), first, "../rtl/serv_ctrl.v", 47, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "pc_plus_offset_cy_r_w[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[593]), first, "../rtl/serv_ctrl.v", 48, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "pc_plus_offset_aligned[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[600]), first, "../rtl/serv_ctrl.v", 49, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "plus_4[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[217]), first, "../rtl/serv_ctrl.v", 51, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "pc[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[601]), first, "../rtl/serv_ctrl.v", 53, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "new_pc[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[602]), first, "../rtl/serv_ctrl.v", 55, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "offset_a[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[603]), first, "../rtl/serv_ctrl.v", 56, 15, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_toggle/serv_ctrl", "offset_b[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[604]), first, "../rtl/serv_ctrl.v", 101, 12, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_branch/serv_ctrl", "if", "101");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[605]), first, "../rtl/serv_ctrl.v", 101, 13, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_branch/serv_ctrl", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[606]), first, "../rtl/serv_ctrl.v", 101, 4, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_line/serv_ctrl", "block", "101");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[607]), first, "../rtl/serv_ctrl.v", 108, 3, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_branch/serv_ctrl", "if", "108-109");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[608]), first, "../rtl/serv_ctrl.v", 108, 4, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_branch/serv_ctrl", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[609]), first, "../rtl/serv_ctrl.v", 111, 3, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_branch/serv_ctrl", "if", "111-112");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[610]), first, "../rtl/serv_ctrl.v", 111, 4, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_branch/serv_ctrl", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[611]), first, "../rtl/serv_ctrl.v", 107, 7, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_branch/serv_ctrl", "if", "107");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[612]), first, "../rtl/serv_ctrl.v", 107, 8, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_branch/serv_ctrl", "else", "110");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[613]), first, "../rtl/serv_ctrl.v", 103, 4, ".tb_cov_top.dut.u_servile.cpu.ctrl", "v_line/serv_ctrl", "block", "103-105");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_alu.v", 14, 20, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[427]), first, "../rtl/serv_alu.v", 16, 20, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[430]), first, "../rtl/serv_alu.v", 17, 20, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_cnt0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[448]), first, "../rtl/serv_alu.v", 18, 21, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "o_cmp", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[445]), first, "../rtl/serv_alu.v", 20, 20, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_sub", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_alu.v", 21, 21, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_bool_op[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_alu.v", 21, 21, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_bool_op[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[446]), first, "../rtl/serv_alu.v", 22, 20, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_cmp_eq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[447]), first, "../rtl/serv_alu.v", 23, 20, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_cmp_sig", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[449]), first, "../rtl/serv_alu.v", 24, 21, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_rd_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[450]), first, "../rtl/serv_alu.v", 24, 21, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_rd_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[451]), first, "../rtl/serv_alu.v", 24, 21, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_rd_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[318]), first, "../rtl/serv_alu.v", 26, 22, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_rs1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[537]), first, "../rtl/serv_alu.v", 27, 22, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_op_b[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[526]), first, "../rtl/serv_alu.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "i_buf[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[614]), first, "../rtl/serv_alu.v", 29, 22, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "o_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[615]), first, "../rtl/serv_alu.v", 31, 16, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "result_add[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[616]), first, "../rtl/serv_alu.v", 32, 16, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "result_slt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[617]), first, "../rtl/serv_alu.v", 34, 16, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "cmp_r", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[618]), first, "../rtl/serv_alu.v", 36, 16, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "add_cy", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[619]), first, "../rtl/serv_alu.v", 37, 16, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "add_cy_r[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[620]), first, "../rtl/serv_alu.v", 40, 9, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "rs1_sx", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[621]), first, "../rtl/serv_alu.v", 41, 9, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "op_b_sx", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[622]), first, "../rtl/serv_alu.v", 43, 15, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "add_b[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[623]), first, "../rtl/serv_alu.v", 47, 9, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "result_lt", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[624]), first, "../rtl/serv_alu.v", 49, 9, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "result_eq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[625]), first, "../rtl/serv_alu.v", 65, 15, ".tb_cov_top.dut.u_servile.cpu.alu", "v_toggle/serv_alu", "result_bool[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[626]), first, "../rtl/serv_alu.v", 83, 7, ".tb_cov_top.dut.u_servile.cpu.alu", "v_branch/serv_alu", "if", "83-84");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[627]), first, "../rtl/serv_alu.v", 83, 8, ".tb_cov_top.dut.u_servile.cpu.alu", "v_branch/serv_alu", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[628]), first, "../rtl/serv_alu.v", 79, 4, ".tb_cov_top.dut.u_servile.cpu.alu", "v_line/serv_alu", "block", "79-81");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[427]), first, "../rtl/serv_rf_if.v", 14, 23, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_cnt_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[289]), first, "../rtl/serv_rf_if.v", 15, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[290]), first, "../rtl/serv_rf_if.v", 15, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg0[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[291]), first, "../rtl/serv_rf_if.v", 15, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg0[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[292]), first, "../rtl/serv_rf_if.v", 15, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg0[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[293]), first, "../rtl/serv_rf_if.v", 15, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg0[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[294]), first, "../rtl/serv_rf_if.v", 15, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg0[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[295]), first, "../rtl/serv_rf_if.v", 16, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[296]), first, "../rtl/serv_rf_if.v", 16, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[297]), first, "../rtl/serv_rf_if.v", 16, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[298]), first, "../rtl/serv_rf_if.v", 16, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[299]), first, "../rtl/serv_rf_if.v", 16, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[300]), first, "../rtl/serv_rf_if.v", 16, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wreg1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[301]), first, "../rtl/serv_rf_if.v", 17, 24, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wen0", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[302]), first, "../rtl/serv_rf_if.v", 18, 24, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wen1", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[328]), first, "../rtl/serv_rf_if.v", 19, 23, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wdata0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[329]), first, "../rtl/serv_rf_if.v", 20, 23, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_wdata1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[305]), first, "../rtl/serv_rf_if.v", 21, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[306]), first, "../rtl/serv_rf_if.v", 21, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg0[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[307]), first, "../rtl/serv_rf_if.v", 21, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg0[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[308]), first, "../rtl/serv_rf_if.v", 21, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg0[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[309]), first, "../rtl/serv_rf_if.v", 21, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg0[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[310]), first, "../rtl/serv_rf_if.v", 21, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg0[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[311]), first, "../rtl/serv_rf_if.v", 22, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[312]), first, "../rtl/serv_rf_if.v", 22, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg1[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[313]), first, "../rtl/serv_rf_if.v", 22, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg1[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[314]), first, "../rtl/serv_rf_if.v", 22, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg1[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[315]), first, "../rtl/serv_rf_if.v", 22, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg1[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[316]), first, "../rtl/serv_rf_if.v", 22, 31, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rreg1[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[318]), first, "../rtl/serv_rf_if.v", 23, 22, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rdata0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[330]), first, "../rtl/serv_rf_if.v", 24, 22, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rdata1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[424]), first, "../rtl/serv_rf_if.v", 27, 23, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_trap", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[422]), first, "../rtl/serv_rf_if.v", 28, 23, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_mret", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[217]), first, "../rtl/serv_rf_if.v", 29, 21, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_mepc[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[408]), first, "../rtl/serv_rf_if.v", 30, 36, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_mtval_pc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[526]), first, "../rtl/serv_rf_if.v", 31, 21, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_bufreg_q[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[593]), first, "../rtl/serv_rf_if.v", 32, 21, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_bad_pc[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[330]), first, "../rtl/serv_rf_if.v", 33, 22, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_csr_pc[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[463]), first, "../rtl/serv_rf_if.v", 35, 23, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_csr_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[464]), first, "../rtl/serv_rf_if.v", 36, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_csr_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[465]), first, "../rtl/serv_rf_if.v", 36, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_csr_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[629]), first, "../rtl/serv_rf_if.v", 37, 21, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_csr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[630]), first, "../rtl/serv_rf_if.v", 38, 22, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_csr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[452]), first, "../rtl/serv_rf_if.v", 40, 23, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rd_wen", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[381]), first, "../rtl/serv_rf_if.v", 41, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rd_waddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[382]), first, "../rtl/serv_rf_if.v", 41, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rd_waddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[383]), first, "../rtl/serv_rf_if.v", 41, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rd_waddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[384]), first, "../rtl/serv_rf_if.v", 41, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rd_waddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[385]), first, "../rtl/serv_rf_if.v", 41, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rd_waddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[592]), first, "../rtl/serv_rf_if.v", 42, 21, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_ctrl_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[614]), first, "../rtl/serv_rf_if.v", 43, 21, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_alu_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[411]), first, "../rtl/serv_rf_if.v", 44, 23, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rd_alu_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[631]), first, "../rtl/serv_rf_if.v", 45, 21, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_csr_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[412]), first, "../rtl/serv_rf_if.v", 46, 23, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rd_csr_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[632]), first, "../rtl/serv_rf_if.v", 47, 21, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_mem_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[413]), first, "../rtl/serv_rf_if.v", 48, 23, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rd_mem_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[386]), first, "../rtl/serv_rf_if.v", 51, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rs1_raddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[387]), first, "../rtl/serv_rf_if.v", 51, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rs1_raddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[388]), first, "../rtl/serv_rf_if.v", 51, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rs1_raddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[389]), first, "../rtl/serv_rf_if.v", 51, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rs1_raddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[390]), first, "../rtl/serv_rf_if.v", 51, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rs1_raddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[318]), first, "../rtl/serv_rf_if.v", 52, 22, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rs1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[391]), first, "../rtl/serv_rf_if.v", 54, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rs2_raddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[392]), first, "../rtl/serv_rf_if.v", 54, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rs2_raddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[393]), first, "../rtl/serv_rf_if.v", 54, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rs2_raddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[394]), first, "../rtl/serv_rf_if.v", 54, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rs2_raddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[395]), first, "../rtl/serv_rf_if.v", 54, 28, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "i_rs2_raddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[330]), first, "../rtl/serv_rf_if.v", 55, 22, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "o_rs2[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[633]), first, "../rtl/serv_rf_if.v", 62, 15, ".tb_cov_top.dut.u_servile.cpu.rf_if", "v_toggle/serv_rf_if", "rd_wen", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_mem_if.v", 15, 21, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[455]), first, "../rtl/serv_mem_if.v", 17, 22, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "i_bytecnt[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[456]), first, "../rtl/serv_mem_if.v", 17, 22, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "i_bytecnt[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[320]), first, "../rtl/serv_mem_if.v", 18, 22, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "i_lsb[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[321]), first, "../rtl/serv_mem_if.v", 18, 22, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "i_lsb[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[458]), first, "../rtl/serv_mem_if.v", 19, 22, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "o_misalign", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[454]), first, "../rtl/serv_mem_if.v", 21, 21, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "i_signed", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_mem_if.v", 22, 21, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "i_word", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_mem_if.v", 23, 21, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "i_half", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_mem_if.v", 25, 21, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "i_mdu_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[538]), first, "../rtl/serv_mem_if.v", 27, 21, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "i_bufreg2_q[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[632]), first, "../rtl/serv_mem_if.v", 28, 22, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "o_rd[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[103]), first, "../rtl/serv_mem_if.v", 30, 22, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "o_wb_sel[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[104]), first, "../rtl/serv_mem_if.v", 30, 22, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "o_wb_sel[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[105]), first, "../rtl/serv_mem_if.v", 30, 22, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "o_wb_sel[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[106]), first, "../rtl/serv_mem_if.v", 30, 22, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "o_wb_sel[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[634]), first, "../rtl/serv_mem_if.v", 32, 8, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "signbit", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[635]), first, "../rtl/serv_mem_if.v", 34, 9, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_toggle/serv_mem_if__Wz1", "dat_valid", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[636]), first, "../rtl/serv_mem_if.v", 48, 7, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_branch/serv_mem_if__Wz1", "if", "48-49");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[637]), first, "../rtl/serv_mem_if.v", 48, 8, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_branch/serv_mem_if__Wz1", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[638]), first, "../rtl/serv_mem_if.v", 47, 4, ".tb_cov_top.dut.u_servile.cpu.mem_if", "v_line/serv_mem_if__Wz1", "block", "47");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_csr.v", 15, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[1]), first, "../rtl/serv_csr.v", 16, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_rst", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[250]), first, "../rtl/serv_csr.v", 18, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_trig_irq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[427]), first, "../rtl/serv_csr.v", 19, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[428]), first, "../rtl/serv_csr.v", 20, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_cnt0to3", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[433]), first, "../rtl/serv_csr.v", 21, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_cnt3", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[434]), first, "../rtl/serv_csr.v", 22, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_cnt7", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[435]), first, "../rtl/serv_csr.v", 23, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_cnt11", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[436]), first, "../rtl/serv_csr.v", 24, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_cnt12", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[437]), first, "../rtl/serv_csr.v", 25, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_cnt_done", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[639]), first, "../rtl/serv_csr.v", 26, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_mem_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_csr.v", 27, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_mtip", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[424]), first, "../rtl/serv_csr.v", 28, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_trap", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[470]), first, "../rtl/serv_csr.v", 29, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "o_new_irq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[406]), first, "../rtl/serv_csr.v", 31, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_e_op", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[407]), first, "../rtl/serv_csr.v", 32, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_ebreak", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[173]), first, "../rtl/serv_csr.v", 33, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_mem_cmd", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[460]), first, "../rtl/serv_csr.v", 34, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_mstatus_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[461]), first, "../rtl/serv_csr.v", 35, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_mie_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[462]), first, "../rtl/serv_csr.v", 36, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_mcause_en", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[322]), first, "../rtl/serv_csr.v", 37, 21, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_csr_source[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[323]), first, "../rtl/serv_csr.v", 37, 21, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_csr_source[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[422]), first, "../rtl/serv_csr.v", 38, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_mret", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[324]), first, "../rtl/serv_csr.v", 39, 20, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_csr_d_sel", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[630]), first, "../rtl/serv_csr.v", 41, 25, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_rf_csr_out[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[629]), first, "../rtl/serv_csr.v", 42, 26, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "o_csr_in[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[386]), first, "../rtl/serv_csr.v", 43, 25, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_csr_imm[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[318]), first, "../rtl/serv_csr.v", 44, 25, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "i_rs1[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[631]), first, "../rtl/serv_csr.v", 45, 26, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "o_q[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[640]), first, "../rtl/serv_csr.v", 53, 14, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "mstatus_mie", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[641]), first, "../rtl/serv_csr.v", 54, 14, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "mstatus_mpie", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[642]), first, "../rtl/serv_csr.v", 55, 14, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "mie_mtie", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[643]), first, "../rtl/serv_csr.v", 57, 10, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "mcause31", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[644]), first, "../rtl/serv_csr.v", 58, 15, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "mcause3_0[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[645]), first, "../rtl/serv_csr.v", 58, 15, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "mcause3_0[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[646]), first, "../rtl/serv_csr.v", 58, 15, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "mcause3_0[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[647]), first, "../rtl/serv_csr.v", 58, 15, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "mcause3_0[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[648]), first, "../rtl/serv_csr.v", 59, 15, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "mcause[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[629]), first, "../rtl/serv_csr.v", 61, 15, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "csr_in[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[631]), first, "../rtl/serv_csr.v", 62, 15, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "csr_out[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[649]), first, "../rtl/serv_csr.v", 64, 10, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "timer_irq_r", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[650]), first, "../rtl/serv_csr.v", 66, 15, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "d[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[651]), first, "../rtl/serv_csr.v", 74, 15, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "mstatus[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[142]), first, "../rtl/serv_csr.v", 90, 10, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_toggle/serv_csr", "timer_irq", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[652]), first, "../rtl/serv_csr.v", 99, 7, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "if", "99-101");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[653]), first, "../rtl/serv_csr.v", 99, 8, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[654]), first, "../rtl/serv_csr.v", 104, 7, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "if", "104-105");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[655]), first, "../rtl/serv_csr.v", 104, 8, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[656]), first, "../rtl/serv_csr.v", 117, 7, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "if", "117-118");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[657]), first, "../rtl/serv_csr.v", 117, 8, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[658]), first, "../rtl/serv_csr.v", 124, 7, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "if", "124-125");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[659]), first, "../rtl/serv_csr.v", 124, 8, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[660]), first, "../rtl/serv_csr.v", 149, 7, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "if", "149-153");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[661]), first, "../rtl/serv_csr.v", 149, 8, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[662]), first, "../rtl/serv_csr.v", 155, 7, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "if", "155-156");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[663]), first, "../rtl/serv_csr.v", 155, 8, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[664]), first, "../rtl/serv_csr.v", 158, 2, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "if", "158-160");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[665]), first, "../rtl/serv_csr.v", 158, 3, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[666]), first, "../rtl/serv_csr.v", 157, 7, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "if", "157");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[667]), first, "../rtl/serv_csr.v", 157, 8, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_branch/serv_csr", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[668]), first, "../rtl/serv_csr.v", 98, 4, ".tb_cov_top.dut.u_servile.cpu.gen_csr.csr", "v_line/serv_csr", "block", "98");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/serv_rf_ram.v", 11, 16, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[175]), first, "../rtl/serv_rf_ram.v", 12, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_waddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[176]), first, "../rtl/serv_rf_ram.v", 12, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_waddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[177]), first, "../rtl/serv_rf_ram.v", 12, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_waddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[178]), first, "../rtl/serv_rf_ram.v", 12, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_waddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[179]), first, "../rtl/serv_rf_ram.v", 12, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_waddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[180]), first, "../rtl/serv_rf_ram.v", 12, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_waddr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[181]), first, "../rtl/serv_rf_ram.v", 12, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_waddr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[182]), first, "../rtl/serv_rf_ram.v", 12, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_waddr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[183]), first, "../rtl/serv_rf_ram.v", 12, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_waddr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[184]), first, "../rtl/serv_rf_ram.v", 12, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_waddr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[185]), first, "../rtl/serv_rf_ram.v", 13, 32, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_wdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[186]), first, "../rtl/serv_rf_ram.v", 13, 32, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_wdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[187]), first, "../rtl/serv_rf_ram.v", 14, 22, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_wen", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[188]), first, "../rtl/serv_rf_ram.v", 15, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_raddr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[189]), first, "../rtl/serv_rf_ram.v", 15, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_raddr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[190]), first, "../rtl/serv_rf_ram.v", 15, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_raddr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[191]), first, "../rtl/serv_rf_ram.v", 15, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_raddr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[192]), first, "../rtl/serv_rf_ram.v", 15, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_raddr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[193]), first, "../rtl/serv_rf_ram.v", 15, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_raddr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[194]), first, "../rtl/serv_rf_ram.v", 15, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_raddr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[195]), first, "../rtl/serv_rf_ram.v", 15, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_raddr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[196]), first, "../rtl/serv_rf_ram.v", 15, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_raddr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[197]), first, "../rtl/serv_rf_ram.v", 15, 36, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_raddr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[200]), first, "../rtl/serv_rf_ram.v", 16, 21, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "i_ren", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[198]), first, "../rtl/serv_rf_ram.v", 17, 33, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "o_rdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[199]), first, "../rtl/serv_rf_ram.v", 17, 33, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "o_rdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[669]), first, "../rtl/serv_rf_ram.v", 20, 25, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "rdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[670]), first, "../rtl/serv_rf_ram.v", 20, 25, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "rdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[671]), first, "../rtl/serv_rf_ram.v", 23, 7, ".tb_cov_top.dut.u_rf_ram", "v_branch/serv_rf_ram__W2", "if", "23-24");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[672]), first, "../rtl/serv_rf_ram.v", 23, 8, ".tb_cov_top.dut.u_rf_ram", "v_branch/serv_rf_ram__W2", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[673]), first, "../rtl/serv_rf_ram.v", 22, 4, ".tb_cov_top.dut.u_rf_ram", "v_line/serv_rf_ram__W2", "block", "22,25");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[674]), first, "../rtl/serv_rf_ram.v", 38, 8, ".tb_cov_top.dut.u_rf_ram", "v_toggle/serv_rf_ram__W2", "regzero", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[675]), first, "../rtl/serv_rf_ram.v", 40, 4, ".tb_cov_top.dut.u_rf_ram", "v_line/serv_rf_ram__W2", "block", "40-41");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[0]), first, "../rtl/gpio_periph.v", 25, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_clk", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[1]), first, "../rtl/gpio_periph.v", 26, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_rst", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[3]), first, "../rtl/gpio_periph.v", 27, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_addr[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[4]), first, "../rtl/gpio_periph.v", 27, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_addr[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[5]), first, "../rtl/gpio_periph.v", 27, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_addr[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[6]), first, "../rtl/gpio_periph.v", 27, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_addr[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[7]), first, "../rtl/gpio_periph.v", 27, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_addr[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[8]), first, "../rtl/gpio_periph.v", 27, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_addr[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[9]), first, "../rtl/gpio_periph.v", 27, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_addr[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[10]), first, "../rtl/gpio_periph.v", 27, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_addr[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[11]), first, "../rtl/gpio_periph.v", 27, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_addr[8]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[12]), first, "../rtl/gpio_periph.v", 27, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_addr[9]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[13]), first, "../rtl/gpio_periph.v", 28, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_wdata[0]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[14]), first, "../rtl/gpio_periph.v", 28, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_wdata[1]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[15]), first, "../rtl/gpio_periph.v", 28, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_wdata[2]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[16]), first, "../rtl/gpio_periph.v", 28, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_wdata[3]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[17]), first, "../rtl/gpio_periph.v", 28, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_wdata[4]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[18]), first, "../rtl/gpio_periph.v", 28, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_wdata[5]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[19]), first, "../rtl/gpio_periph.v", 28, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_wdata[6]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[20]), first, "../rtl/gpio_periph.v", 28, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_wdata[7]", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[29]), first, "../rtl/gpio_periph.v", 29, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_we", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[30]), first, "../rtl/gpio_periph.v", 30, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "i_cyc", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[2]), first, "../rtl/gpio_periph.v", 31, 30, ".tb_cov_top.dut.u_gpio", "v_toggle/gpio_periph", "o_gpio", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[676]), first, "../rtl/gpio_periph.v", 38, 12, ".tb_cov_top.dut.u_gpio", "v_branch/gpio_periph", "if", "38-39");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[677]), first, "../rtl/gpio_periph.v", 38, 13, ".tb_cov_top.dut.u_gpio", "v_branch/gpio_periph", "else", "");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[678]), first, "../rtl/gpio_periph.v", 36, 7, ".tb_cov_top.dut.u_gpio", "v_line/gpio_periph", "elsif", "36-37");
    vlSelf->__vlCoverInsert(&(vlSymsp->__Vcoverage[679]), first, "../rtl/gpio_periph.v", 35, 4, ".tb_cov_top.dut.u_gpio", "v_line/gpio_periph", "block", "35");
}
