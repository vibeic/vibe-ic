// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_cov_top.h for the primary calling header

#include "Vtb_cov_top__pch.h"
#include "Vtb_cov_top___024root.h"

VL_ATTR_COLD void Vtb_cov_top___024root___eval_static__TOP(Vtb_cov_top___024root* vlSelf);

VL_ATTR_COLD void Vtb_cov_top___024root___eval_static(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_static\n"); );
    // Body
    Vtb_cov_top___024root___eval_static__TOP(vlSelf);
}

VL_ATTR_COLD void Vtb_cov_top___024root___eval_initial__TOP(Vtb_cov_top___024root* vlSelf);

VL_ATTR_COLD void Vtb_cov_top___024root___eval_initial(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_initial\n"); );
    // Body
    Vtb_cov_top___024root___eval_initial__TOP(vlSelf);
    vlSelf->__Vtrigprevexpr___TOP__clk__0 = vlSelf->clk;
}

VL_ATTR_COLD void Vtb_cov_top___024root___eval_final(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_final\n"); );
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_cov_top___024root___dump_triggers__stl(Vtb_cov_top___024root* vlSelf);
#endif  // VL_DEBUG
VL_ATTR_COLD bool Vtb_cov_top___024root___eval_phase__stl(Vtb_cov_top___024root* vlSelf);

VL_ATTR_COLD void Vtb_cov_top___024root___eval_settle(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_settle\n"); );
    // Init
    IData/*31:0*/ __VstlIterCount;
    CData/*0:0*/ __VstlContinue;
    // Body
    __VstlIterCount = 0U;
    vlSelf->__VstlFirstIteration = 1U;
    __VstlContinue = 1U;
    while (__VstlContinue) {
        if (VL_UNLIKELY((0x64U < __VstlIterCount))) {
#ifdef VL_DEBUG
            Vtb_cov_top___024root___dump_triggers__stl(vlSelf);
#endif
            VL_FATAL_MT("tb_cov_top.v", 2, "", "Settle region did not converge.");
        }
        __VstlIterCount = ((IData)(1U) + __VstlIterCount);
        __VstlContinue = 0U;
        if (Vtb_cov_top___024root___eval_phase__stl(vlSelf)) {
            __VstlContinue = 1U;
        }
        vlSelf->__VstlFirstIteration = 0U;
    }
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_cov_top___024root___dump_triggers__stl(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___dump_triggers__stl\n"); );
    // Body
    if ((1U & (~ (IData)(vlSelf->__VstlTriggered.any())))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelf->__VstlTriggered.word(0U))) {
        VL_DBG_MSGF("         'stl' region trigger index 0 is active: Internal 'stl' trigger - first iteration\n");
    }
}
#endif  // VL_DEBUG

VL_ATTR_COLD void Vtb_cov_top___024root___stl_sequent__TOP__0(Vtb_cov_top___024root* vlSelf);

VL_ATTR_COLD void Vtb_cov_top___024root___eval_stl(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_stl\n"); );
    // Body
    if ((1ULL & vlSelf->__VstlTriggered.word(0U))) {
        Vtb_cov_top___024root___stl_sequent__TOP__0(vlSelf);
    }
}

VL_ATTR_COLD void Vtb_cov_top___024root___eval_triggers__stl(Vtb_cov_top___024root* vlSelf);

VL_ATTR_COLD bool Vtb_cov_top___024root___eval_phase__stl(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_phase__stl\n"); );
    // Init
    CData/*0:0*/ __VstlExecute;
    // Body
    Vtb_cov_top___024root___eval_triggers__stl(vlSelf);
    __VstlExecute = vlSelf->__VstlTriggered.any();
    if (__VstlExecute) {
        Vtb_cov_top___024root___eval_stl(vlSelf);
    }
    return (__VstlExecute);
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_cov_top___024root___dump_triggers__ico(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___dump_triggers__ico\n"); );
    // Body
    if ((1U & (~ (IData)(vlSelf->__VicoTriggered.any())))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelf->__VicoTriggered.word(0U))) {
        VL_DBG_MSGF("         'ico' region trigger index 0 is active: Internal 'ico' trigger - first iteration\n");
    }
}
#endif  // VL_DEBUG

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_cov_top___024root___dump_triggers__act(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___dump_triggers__act\n"); );
    // Body
    if ((1U & (~ (IData)(vlSelf->__VactTriggered.any())))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelf->__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 0 is active: @(posedge clk)\n");
    }
}
#endif  // VL_DEBUG

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_cov_top___024root___dump_triggers__nba(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___dump_triggers__nba\n"); );
    // Body
    if ((1U & (~ (IData)(vlSelf->__VnbaTriggered.any())))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelf->__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 0 is active: @(posedge clk)\n");
    }
}
#endif  // VL_DEBUG

VL_ATTR_COLD void Vtb_cov_top___024root___ctor_var_reset(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___ctor_var_reset\n"); );
    // Body
    vlSelf->clk = VL_RAND_RESET_I(1);
    vlSelf->rst_in = VL_RAND_RESET_I(1);
    vlSelf->gpio_o = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__sr = VL_RAND_RESET_I(8);
    for (int __Vi0 = 0; __Vi0 < 1024; ++__Vi0) {
        vlSelf->tb_cov_top__DOT__mem[__Vi0] = VL_RAND_RESET_I(8);
    }
    vlSelf->tb_cov_top__DOT__i = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__init = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT____Vtogcov__clk = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT____Vtogcov__rst_in = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT____Vtogcov__gpio_o = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT____Vtogcov__sa = VL_RAND_RESET_I(10);
    vlSelf->tb_cov_top__DOT____Vtogcov__sw = VL_RAND_RESET_I(8);
    vlSelf->tb_cov_top__DOT____Vtogcov__sr = VL_RAND_RESET_I(8);
    vlSelf->tb_cov_top__DOT____Vtogcov__swe = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT____Vtogcov__scyc = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT____Vtogcov__init = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_stb = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr = VL_RAND_RESET_I(10);
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_wdata = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_wen = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr = VL_RAND_RESET_I(10);
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT__bstate = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__br_addr = VL_RAND_RESET_I(10);
    vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata = VL_RAND_RESET_I(8);
    vlSelf->tb_cov_top__DOT__dut__DOT__br_we = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_adr = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_dat = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_sel = VL_RAND_RESET_I(4);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_we = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_stb = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_rdt = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_ack = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_adr = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_we = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_stb = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_waddr = VL_RAND_RESET_I(10);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wdata = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wen = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_raddr = VL_RAND_RESET_I(10);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_rdata = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_ren = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__bstate = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel = VL_RAND_RESET_I(4);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_stb = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wen0 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wen1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata0 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ready = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_adr = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_stb = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_ack = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_stb = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_rdt = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_ack = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dmem_stb = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dmem_ack = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_wreq = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_rreq = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg0 = VL_RAND_RESET_I(6);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wreg1 = VL_RAND_RESET_I(6);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wen0 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wen1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wdata0 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wdata1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg0 = VL_RAND_RESET_I(6);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rreg1 = VL_RAND_RESET_I(6);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_ready = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rdata0 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rdata1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_rs1 = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__mdu_op = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT__sim_ack = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT____Vtogcov__sim_ack = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT____Vtogcov__ext = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgnt = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt = VL_RAND_RESET_I(5);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata0_r = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata1_r = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen0_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen1_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0 = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgate = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreq_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__i_wdata0 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__i_wdata1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__o_rdata1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rgnt = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rcnt = VL_RAND_RESET_I(5);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rtrig1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wcnt = VL_RAND_RESET_I(5);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata0_r = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wdata1_r = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wen0_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wen1_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wreg = VL_RAND_RESET_I(6);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreg = VL_RAND_RESET_I(6);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata0 = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreq_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_pc_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__jump = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt3 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt7 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2_q = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_cmp = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_addr = VL_RAND_RESET_I(5);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs1_addr = VL_RAND_RESET_I(5);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rs2_addr = VL_RAND_RESET_I(5);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_ctrl = VL_RAND_RESET_I(4);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__immdec_en = VL_RAND_RESET_I(4);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cond_branch = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__two_stage_op = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__e_op = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ebreak = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__branch_op = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__shift_op = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_op = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_alu_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_csr_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_mem_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ctrl_rd = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_rd = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_rd = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ctrl_pc_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__jump = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__jal_or_jalr = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__utype = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mret = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__imm = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__trap = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__pc_rel = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__init = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt0to3 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt12to31 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt0 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt1 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt2 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt3 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt7 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt11 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt12 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt_done = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_sh_signed = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_rs1_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_imm_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_clr_lsb = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_q = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg2_q = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_sub = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_cmp_eq = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_cmp_sig = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_cmp = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_rd_sel = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__op_b = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_signed = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_bytecnt = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__sh_done = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_misalign = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bad_pc = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_mstatus_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_mie_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_mcause_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_addr = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_imm_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__csr_in = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rf_csr_out = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__dbus_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__new_irq = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__init_done = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__ibus_cyc = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__take_branch = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__last_init = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__trap_pending = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__init_done = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__misalign_trap_sync = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__o_cnt = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__cnt_r = VL_RAND_RESET_I(4);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__ibus_cyc = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__take_branch = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__last_init = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__trap_pending = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb = VL_RAND_RESET_I(4);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_csr__DOT__misalign_trap_sync_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____VdfgTmp_hb0ab83f8__0 = 0;
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode = VL_RAND_RESET_I(5);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3 = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op22 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm25 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm30 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_alu_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_mret = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_e_op = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_sub = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mstatus_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mie_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mcause_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl = VL_RAND_RESET_I(4);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en = VL_RAND_RESET_I(4);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__opcode = VL_RAND_RESET_I(5);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op21 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op22 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op26 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__imm25 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__csr_valid = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT____Vtogcov__o_imm = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm31 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20 = VL_RAND_RESET_I(9);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm7 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25 = VL_RAND_RESET_I(6);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20 = VL_RAND_RESET_I(5);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7 = VL_RAND_RESET_I(5);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__signbit = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__q = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data = VL_RAND_RESET_I(32);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__i_shamt = VL_RAND_RESET_I(3);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__o_q = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__c = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__q = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__c_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__clr_lsb = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi = VL_RAND_RESET_I(8);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo = VL_RAND_RESET_I(24);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__shift_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt = VL_RAND_RESET_I(8);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__o_op_b = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__o_q = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dhi = VL_RAND_RESET_I(8);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dlo = VL_RAND_RESET_I(24);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__byte_valid = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__shift_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_en = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__cnt_next = VL_RAND_RESET_I(8);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__dat_shamt = VL_RAND_RESET_I(8);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__new_pc = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__i_trap = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__o_rd = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__o_bad_pc = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4_cy = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4_cy_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset_cy = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset_cy_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__plus_4 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__new_pc = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__offset_a = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__offset_b = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__cmp_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__o_rd = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_add = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_slt = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__cmp_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__add_cy = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__add_cy_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__rs1_sx = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__op_b_sx = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__add_b = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_lt = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_eq = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_bool = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__i_csr = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__o_csr = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__i_csr_rd = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__i_mem_rd = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__rf_if__DOT____Vtogcov__rd_wen = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__signbit = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT____Vtogcov__signbit = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT____Vtogcov__dat_valid = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mpie = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mie_mtie = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause31 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0 = VL_RAND_RESET_I(4);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__timer_irq_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__i_mem_op = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus_mie = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus_mpie = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mie_mtie = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause31 = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause3_0 = VL_RAND_RESET_I(4);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__timer_irq_r = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__d = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus = VL_RAND_RESET_I(1);
    for (int __Vi0 = 0; __Vi0 < 576; ++__Vi0) {
        vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory[__Vi0] = VL_RAND_RESET_I(2);
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__rdata = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__regzero = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__rdata = VL_RAND_RESET_I(2);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__regzero = VL_RAND_RESET_I(1);
    vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vlvbound_h930b250c__0 = VL_RAND_RESET_I(2);
    vlSelf->__Vtrigprevexpr___TOP__clk__0 = VL_RAND_RESET_I(1);
}
