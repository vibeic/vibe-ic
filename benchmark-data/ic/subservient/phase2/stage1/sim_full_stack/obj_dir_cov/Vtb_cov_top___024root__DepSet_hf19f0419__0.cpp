// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_cov_top.h for the primary calling header

#include "Vtb_cov_top__pch.h"
#include "Vtb_cov_top__Syms.h"
#include "Vtb_cov_top___024root.h"

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_cov_top___024root___dump_triggers__ico(Vtb_cov_top___024root* vlSelf);
#endif  // VL_DEBUG

void Vtb_cov_top___024root___eval_triggers__ico(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_triggers__ico\n"); );
    // Body
    vlSelf->__VicoTriggered.set(0U, (IData)(vlSelf->__VicoFirstIteration));
#ifdef VL_DEBUG
    if (VL_UNLIKELY(vlSymsp->_vm_contextp__->debug())) {
        Vtb_cov_top___024root___dump_triggers__ico(vlSelf);
    }
#endif
}

VL_INLINE_OPT void Vtb_cov_top___024root___ico_sequent__TOP__0(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___ico_sequent__TOP__0\n"); );
    // Init
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb = 0;
    CData/*0:0*/ tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_ack;
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_ack = 0;
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
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb 
        = ((~ (IData)(vlSelf->rst_in)) & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__ibus_cyc));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_stb))) {
        ++(vlSymsp->__Vcoverage[249]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_stb 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_stb = 
        ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_stb) 
         | (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb));
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_stb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_stb))) {
        ++(vlSymsp->__Vcoverage[108]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_stb 
            = vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_stb;
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
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
           | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__trap_pending) 
              & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__last_init)));
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_rreq))) {
        ++(vlSymsp->__Vcoverage[288]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_rreq 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_ack))) {
        ++(vlSymsp->__Vcoverage[284]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_ack 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack;
    }
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_wreq))) {
        ++(vlSymsp->__Vcoverage[287]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_wreq 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ready 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq) 
           | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgnt));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ready) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_ready))) {
        ++(vlSymsp->__Vcoverage[317]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rf_ready 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ready;
    }
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_cov_top___024root___dump_triggers__act(Vtb_cov_top___024root* vlSelf);
#endif  // VL_DEBUG

void Vtb_cov_top___024root___eval_triggers__act(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___eval_triggers__act\n"); );
    // Body
    vlSelf->__VactTriggered.set(0U, ((IData)(vlSelf->clk) 
                                     & (~ (IData)(vlSelf->__Vtrigprevexpr___TOP__clk__0))));
    vlSelf->__Vtrigprevexpr___TOP__clk__0 = vlSelf->clk;
#ifdef VL_DEBUG
    if (VL_UNLIKELY(vlSymsp->_vm_contextp__->debug())) {
        Vtb_cov_top___024root___dump_triggers__act(vlSelf);
    }
#endif
}

VL_INLINE_OPT void Vtb_cov_top___024root___nba_sequent__TOP__0(Vtb_cov_top___024root* vlSelf) {
    if (false && vlSelf) {}  // Prevent unused
    Vtb_cov_top__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_cov_top___024root___nba_sequent__TOP__0\n"); );
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
    SData/*9:0*/ __Vdlyvdim0__tb_cov_top__DOT__mem__v0;
    __Vdlyvdim0__tb_cov_top__DOT__mem__v0 = 0;
    CData/*7:0*/ __Vdlyvval__tb_cov_top__DOT__mem__v0;
    __Vdlyvval__tb_cov_top__DOT__mem__v0 = 0;
    CData/*0:0*/ __Vdlyvset__tb_cov_top__DOT__mem__v0;
    __Vdlyvset__tb_cov_top__DOT__mem__v0 = 0;
    CData/*2:0*/ __Vdly__tb_cov_top__DOT__dut__DOT__bstate;
    __Vdly__tb_cov_top__DOT__dut__DOT__bstate = 0;
    SData/*9:0*/ __Vdly__tb_cov_top__DOT__dut__DOT__br_addr;
    __Vdly__tb_cov_top__DOT__dut__DOT__br_addr = 0;
    CData/*4:0*/ __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt;
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt = 0;
    CData/*2:0*/ __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt;
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt = 0;
    CData/*3:0*/ __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb;
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb = 0;
    SData/*8:0*/ __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20;
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20 = 0;
    CData/*5:0*/ __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25;
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25 = 0;
    IData/*31:0*/ __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data;
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data = 0;
    CData/*0:0*/ __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie;
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie = 0;
    CData/*3:0*/ __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0;
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0 = 0;
    SData/*9:0*/ __Vdlyvdim0__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0;
    __Vdlyvdim0__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0 = 0;
    CData/*1:0*/ __Vdlyvval__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0;
    __Vdlyvval__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0 = 0;
    CData/*0:0*/ __Vdlyvset__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0;
    __Vdlyvset__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0 = 0;
    VlWide<4>/*127:0*/ __Vtemp_11;
    // Body
    ++(vlSymsp->__Vcoverage[38]);
    ++(vlSymsp->__Vcoverage[216]);
    ++(vlSymsp->__Vcoverage[357]);
    ++(vlSymsp->__Vcoverage[369]);
    ++(vlSymsp->__Vcoverage[380]);
    ++(vlSymsp->__Vcoverage[490]);
    ++(vlSymsp->__Vcoverage[493]);
    ++(vlSymsp->__Vcoverage[496]);
    ++(vlSymsp->__Vcoverage[507]);
    ++(vlSymsp->__Vcoverage[522]);
    ++(vlSymsp->__Vcoverage[531]);
    ++(vlSymsp->__Vcoverage[536]);
    ++(vlSymsp->__Vcoverage[590]);
    ++(vlSymsp->__Vcoverage[613]);
    ++(vlSymsp->__Vcoverage[612]);
    ++(vlSymsp->__Vcoverage[628]);
    ++(vlSymsp->__Vcoverage[638]);
    ++(vlSymsp->__Vcoverage[668]);
    ++(vlSymsp->__Vcoverage[673]);
    ++(vlSymsp->__Vcoverage[675]);
    ++(vlSymsp->__Vcoverage[679]);
    if (vlSelf->tb_cov_top__DOT__init) {
        ++(vlSymsp->__Vcoverage[35]);
    }
    if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_wen)))) {
        ++(vlSymsp->__Vcoverage[672]);
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mie_en) 
         & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt7))) {
        ++(vlSymsp->__Vcoverage[654]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mie_mtie 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in;
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mie_en) 
                  & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt7))))) {
        ++(vlSymsp->__Vcoverage[655]);
    }
    if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid)))) {
        ++(vlSymsp->__Vcoverage[637]);
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq) 
                  | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq))))) {
        ++(vlSymsp->__Vcoverage[373]);
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__shift_en) 
         | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack))) {
        ++(vlSymsp->__Vcoverage[588]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
            = (0xffffffU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack)
                             ? vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt
                             : ((0x800000U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
                                              << 0x17U)) 
                                | (0x7fffffU & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo 
                                                >> 1U)))));
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__shift_en) 
                  | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack))))) {
        ++(vlSymsp->__Vcoverage[589]);
    }
    if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack)))) {
        ++(vlSymsp->__Vcoverage[506]);
        ++(vlSymsp->__Vcoverage[511]);
        ++(vlSymsp->__Vcoverage[653]);
    }
    if ((1U & (~ (IData)(vlSelf->rst_in)))) {
        ++(vlSymsp->__Vcoverage[215]);
        ++(vlSymsp->__Vcoverage[379]);
        ++(vlSymsp->__Vcoverage[489]);
        ++(vlSymsp->__Vcoverage[492]);
        ++(vlSymsp->__Vcoverage[667]);
        if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate) 
                      >> 2U)))) {
            if ((2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
                if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)))) {
                    ++(vlSymsp->__Vcoverage[208]);
                }
                if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
                    ++(vlSymsp->__Vcoverage[209]);
                }
            }
            if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate) 
                          >> 1U)))) {
                if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
                    ++(vlSymsp->__Vcoverage[207]);
                }
                if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)))) {
                    ++(vlSymsp->__Vcoverage[206]);
                    if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_stb)))) {
                        ++(vlSymsp->__Vcoverage[205]);
                    }
                    if (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_stb) {
                        ++(vlSymsp->__Vcoverage[204]);
                    }
                }
            }
        }
        if ((4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
            if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate) 
                          >> 1U)))) {
                if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
                    ++(vlSymsp->__Vcoverage[211]);
                }
                if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)))) {
                    ++(vlSymsp->__Vcoverage[210]);
                }
            }
            if ((2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
                if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)))) {
                    ++(vlSymsp->__Vcoverage[212]);
                }
                if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
                    ++(vlSymsp->__Vcoverage[213]);
                }
            }
        }
        if ((1U & (~ (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc) 
                       & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_we)) 
                      & (0x3ffU == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)))))) {
            ++(vlSymsp->__Vcoverage[677]);
        }
        if ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc) 
              & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_we)) 
             & (0x3ffU == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)))) {
            ++(vlSymsp->__Vcoverage[676]);
        }
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_pc_en) 
         | (IData)(vlSelf->rst_in))) {
        ++(vlSymsp->__Vcoverage[609]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
            = ((IData)(vlSelf->rst_in) ? 0U : (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__new_pc) 
                                                << 0x1fU) 
                                               | (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr 
                                                  >> 1U)));
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_pc_en) 
                  | (IData)(vlSelf->rst_in))))) {
        ++(vlSymsp->__Vcoverage[610]);
    }
    if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_en)))) {
        ++(vlSymsp->__Vcoverage[533]);
    }
    __Vdlyvset__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0 = 0U;
    if (vlSelf->tb_cov_top__DOT__dut__DOT__rf_wen) {
        ++(vlSymsp->__Vcoverage[671]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vlvbound_h930b250c__0 
            = vlSelf->tb_cov_top__DOT__dut__DOT__rf_wdata;
        if ((0x23fU >= (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr))) {
            __Vdlyvval__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0 
                = vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vlvbound_h930b250c__0;
            __Vdlyvset__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0 = 1U;
            __Vdlyvdim0__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0 
                = vlSelf->tb_cov_top__DOT__dut__DOT__rf_waddr;
        }
    }
    if ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__shift_en) 
          | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_en)) 
         | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack))) {
        ++(vlSymsp->__Vcoverage[586]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi 
            = (0xffU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack)
                         ? (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
                            >> 0x18U) : ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dat_shamt) 
                                         & (0xdfU | 
                                            (0x20U 
                                             & ((~ 
                                                 (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op) 
                                                   & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt7)) 
                                                  & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_en)))) 
                                                << 5U))))));
    }
    if ((1U & (~ (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__shift_en) 
                   | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__cnt_en)) 
                  | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack))))) {
        ++(vlSymsp->__Vcoverage[587]);
    }
    if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt)))) {
        ++(vlSymsp->__Vcoverage[356]);
        ++(vlSymsp->__Vcoverage[375]);
    }
    if ((1U & (~ ((0x1fU == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt)) 
                  | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq))))) {
        ++(vlSymsp->__Vcoverage[371]);
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init)
                   ? ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0) 
                      | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt1))
                   : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_en))))) {
        ++(vlSymsp->__Vcoverage[535]);
    }
    if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)))) {
        ++(vlSymsp->__Vcoverage[485]);
    }
    if ((1U & (~ (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
                   | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)) 
                  | (IData)(vlSelf->rst_in))))) {
        ++(vlSymsp->__Vcoverage[483]);
        ++(vlSymsp->__Vcoverage[495]);
    }
    if ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
          | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)) 
         | (IData)(vlSelf->rst_in))) {
        ++(vlSymsp->__Vcoverage[482]);
        ++(vlSymsp->__Vcoverage[494]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_csr__DOT__misalign_trap_sync_r 
            = ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
                   | (IData)(vlSelf->rst_in))) & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__trap_pending) 
                                                   & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init)) 
                                                  | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_csr__DOT__misalign_trap_sync_r)));
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__ibus_cyc 
            = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_pc_en) 
               | (IData)(vlSelf->rst_in));
    }
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt 
        = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt;
    if ((1U & (~ (IData)((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)))))) {
        ++(vlSymsp->__Vcoverage[627]);
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
                  | (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)))))) {
        ++(vlSymsp->__Vcoverage[515]);
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
                  | ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
                     & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en) 
                        >> 1U)))))) {
        ++(vlSymsp->__Vcoverage[513]);
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
         | ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
            & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en)))) {
        ++(vlSymsp->__Vcoverage[520]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7 
            = (0x1fU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack)
                         ? (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                            >> 7U) : ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25) 
                                                << 4U)) 
                                      | (0xfU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7) 
                                                 >> 1U)))));
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
                  | ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
                     & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en) 
                        >> 2U)))))) {
        ++(vlSymsp->__Vcoverage[519]);
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
                  | ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
                     & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en) 
                        >> 3U)))))) {
        ++(vlSymsp->__Vcoverage[517]);
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
                  | ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en)))))) {
        ++(vlSymsp->__Vcoverage[521]);
    }
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
                  & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done))))) {
        ++(vlSymsp->__Vcoverage[659]);
    }
    if ((1U & (~ (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mcause_en) 
                   & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)) 
                  | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap))))) {
        ++(vlSymsp->__Vcoverage[663]);
    }
    if ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mcause_en) 
          & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)) 
         | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap))) {
        ++(vlSymsp->__Vcoverage[662]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause31 
            = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)
                ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq)
                : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in));
    }
    if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1)))) {
        ++(vlSymsp->__Vcoverage[368]);
    }
    __Vdly__tb_cov_top__DOT__dut__DOT__bstate = vlSelf->tb_cov_top__DOT__dut__DOT__bstate;
    __Vdly__tb_cov_top__DOT__dut__DOT__br_addr = vlSelf->tb_cov_top__DOT__dut__DOT__br_addr;
    if ((1U & (~ ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
                    & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)) 
                   | (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mstatus_en) 
                       & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt3)) 
                      & (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)))) 
                  | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_mret))))) {
        ++(vlSymsp->__Vcoverage[657]);
    }
    if ((1U & (~ ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mcause_en) 
                    & (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb))) 
                   & (0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt))) 
                  | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)))))) {
        ++(vlSymsp->__Vcoverage[661]);
    }
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb 
        = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb;
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie 
        = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie;
    if (((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)) 
          | (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mstatus_en) 
              & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt3)) 
             & (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)))) 
         | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_mret))) {
        ++(vlSymsp->__Vcoverage[656]);
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie 
            = ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)) 
               & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_mret)
                   ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mpie)
                   : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in)));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
         & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done))) {
        ++(vlSymsp->__Vcoverage[658]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mpie 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie;
    }
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt 
        = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt;
    if ((1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc) 
                  & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_we))))) {
        ++(vlSymsp->__Vcoverage[37]);
    }
    __Vdlyvset__tb_cov_top__DOT__mem__v0 = 0U;
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc) 
         & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_we))) {
        ++(vlSymsp->__Vcoverage[36]);
        __Vdlyvval__tb_cov_top__DOT__mem__v0 = vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata;
        __Vdlyvset__tb_cov_top__DOT__mem__v0 = 1U;
        __Vdlyvdim0__tb_cov_top__DOT__mem__v0 = vlSelf->tb_cov_top__DOT__dut__DOT__br_addr;
    }
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
        = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data;
    if (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_en) {
        ++(vlSymsp->__Vcoverage[532]);
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
            = ((3U & __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data) 
               | ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init)
                     ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__q)
                     : ((vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                         >> 0x1fU) & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm30))) 
                   << 0x1fU) | (0x7ffffffcU & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                                               >> 1U))));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init)
          ? ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0) 
             | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt1))
          : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_en))) {
        ++(vlSymsp->__Vcoverage[534]);
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
            = ((0xfffffffcU & __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data) 
               | ((2U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init)
                           ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__q)
                           : (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                              >> 2U)) << 1U)) | (1U 
                                                 & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                                                    >> 1U))));
    }
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25 
        = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25;
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
         | ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
            & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en) 
               >> 3U)))) {
        ++(vlSymsp->__Vcoverage[516]);
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25 
            = (0x3fU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack)
                         ? (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                            >> 0x19U) : ((0x20U & (
                                                   ((4U 
                                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl))
                                                     ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm7)
                                                     : 
                                                    ((2U 
                                                      & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl))
                                                      ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__signbit)
                                                      : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20))) 
                                                   << 5U)) 
                                         | (0x1fU & 
                                            ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25) 
                                             >> 1U)))));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
         | (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)))) {
        ++(vlSymsp->__Vcoverage[514]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm7 
            = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack)
                      ? (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                         >> 7U) : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__signbit)));
    }
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20 
        = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20;
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
         | ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
            & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en) 
               >> 1U)))) {
        ++(vlSymsp->__Vcoverage[512]);
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20 
            = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack)
                ? ((0x1feU & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                              >> 0xbU)) | (1U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                                                 >> 0x14U)))
                : ((0x100U & (((8U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl))
                                ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__signbit)
                                : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20)) 
                              << 8U)) | (0xffU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                                                  >> 1U))));
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) 
         | ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
            & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_en) 
               >> 2U)))) {
        ++(vlSymsp->__Vcoverage[518]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20 
            = (0x1fU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack)
                         ? (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                            >> 0x14U) : ((0x10U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25) 
                                                   << 4U)) 
                                         | (0xfU & 
                                            ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20) 
                                             >> 1U)))));
    }
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0 
        = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0;
    if (((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_mcause_en) 
           & (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb))) 
          & (0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt))) 
         | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap) 
            & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)))) {
        ++(vlSymsp->__Vcoverage[660]);
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0 
            = ((7U & (IData)(__Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0)) 
               | ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_e_op) 
                    & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20))) 
                   | ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)) 
                      & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__csr_in))) 
                  << 3U));
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0 
            = ((0xbU & (IData)(__Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0)) 
               | (4U & ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq) 
                          | (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                                >> 4U))) << 2U) | (0x7ffffffcU 
                                                   & (((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)) 
                                                       << 2U) 
                                                      & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0) 
                                                         >> 1U))))));
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0 
            = ((0xdU & (IData)(__Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0)) 
               | (2U & (((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq) 
                           | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_e_op)) 
                          | (IData)((8U == (0x18U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))))) 
                         << 1U) | (0x7ffffffeU & ((
                                                   (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)) 
                                                   << 1U) 
                                                  & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0) 
                                                     >> 1U))))));
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0 
            = ((0xeU & (IData)(__Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0)) 
               | (1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq) 
                         | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_e_op)) 
                        | ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__trap)) 
                           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0) 
                              >> 1U)))));
    }
    if (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack) {
        ++(vlSymsp->__Vcoverage[505]);
        ++(vlSymsp->__Vcoverage[510]);
        ++(vlSymsp->__Vcoverage[652]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__timer_irq_r = 0U;
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm25 
            = (1U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     >> 0x19U));
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op22 
            = (1U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     >> 0x16U));
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm31 
            = (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
               >> 0x1fU);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26 
            = (1U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     >> 0x1aU));
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21 
            = (1U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     >> 0x15U));
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3 
            = (7U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     >> 0xcU));
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm30 
            = (1U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     >> 0x1eU));
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq = 0U;
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20 
            = (1U & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                     >> 0x14U));
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode 
            = (0x1fU & (vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                        >> 2U));
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata0_r 
        = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata0) 
            << 1U) | (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata0_r) 
                            >> 1U)));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata1_r 
        = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wdata1) 
            << 2U) | (3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wdata1_r) 
                            >> 1U)));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0 
        = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0) 
                 >> 1U));
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb 
        = ((0xeU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
                    << 1U)) | (1U & ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
                                       >> 3U) & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done))) 
                                     | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ready))));
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt 
        = (7U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                 + (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
                          >> 3U))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy_r 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_pc_en) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy_r 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl_pc_en) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c_r = 0U;
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c_r 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg_en));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgnt 
        = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreq_r;
    vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__regzero 
        = (1U & (~ (IData)((0U != (0x3fU & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr) 
                                            >> 4U))))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy_r = 0U;
    if ((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb))) {
        ++(vlSymsp->__Vcoverage[626]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__cmp_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu_cmp;
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy;
    } else {
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__add_cy_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_sub;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__rdata 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgate)
            ? ((0x23fU >= (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr))
                ? vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory
               [vlSelf->tb_cov_top__DOT__dut__DOT__rf_raddr]
                : 0U) : 0U);
    if (((0x1fU == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt)) 
         | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq))) {
        ++(vlSymsp->__Vcoverage[370]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgate 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
        = __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data;
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25 
        = __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm30_25;
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20 
        = __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20;
    if (__Vdlyvset__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0) {
        vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory[__Vdlyvdim0__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0] 
            = __Vdlyvval__tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__memory__v0;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0 
        = __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause3_0;
    if (vlSelf->rst_in) {
        ++(vlSymsp->__Vcoverage[214]);
        ++(vlSymsp->__Vcoverage[376]);
        ++(vlSymsp->__Vcoverage[378]);
        ++(vlSymsp->__Vcoverage[488]);
        ++(vlSymsp->__Vcoverage[486]);
        ++(vlSymsp->__Vcoverage[491]);
        ++(vlSymsp->__Vcoverage[666]);
        ++(vlSymsp->__Vcoverage[664]);
        ++(vlSymsp->__Vcoverage[678]);
    }
    if (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done) {
        ++(vlSymsp->__Vcoverage[484]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__init_done 
            = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init) 
               & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__init_done)));
    }
    if (vlSelf->rst_in) {
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__init_done = 0U;
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb = 0U;
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt = 0U;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt 
        = __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt;
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
    if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt))) {
        ++(vlSymsp->__Vcoverage[355]);
        ++(vlSymsp->__Vcoverage[374]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0 
            = vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata;
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rdata0)))) {
        ++(vlSymsp->__Vcoverage[318]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__rdata0 
            = (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0));
    }
    if ((2U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata0)))) {
        ++(vlSymsp->__Vcoverage[364]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata0 
            = ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata0)) 
               | (2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0)));
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
    if (((0U != (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                 >> 0x1eU)) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT____Vtogcov__ext))) {
        ++(vlSymsp->__Vcoverage[326]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__mux__DOT____Vtogcov__ext 
            = (0U != (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                      >> 0x1eU));
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__timer_irq_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__timer_irq_r))) {
        ++(vlSymsp->__Vcoverage[649]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__timer_irq_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__timer_irq_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4_cy_r))) {
        ++(vlSymsp->__Vcoverage[596]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_4_cy_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_4_cy_r;
    }
    if (vlSelf->rst_in) {
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mie_mtie = 0U;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mie_mtie) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mie_mtie))) {
        ++(vlSymsp->__Vcoverage[642]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mie_mtie 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mie_mtie;
    }
    if (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid) {
        ++(vlSymsp->__Vcoverage[636]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__signbit 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2_q;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__signbit) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT____Vtogcov__signbit))) {
        ++(vlSymsp->__Vcoverage[634]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT____Vtogcov__signbit 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__signbit;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset_cy_r))) {
        ++(vlSymsp->__Vcoverage[599]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT____Vtogcov__pc_plus_offset_cy_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__ctrl__DOT__pc_plus_offset_cy_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__c_r))) {
        ++(vlSymsp->__Vcoverage[529]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__c_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__c_r;
    }
    if (vlSelf->rst_in) {
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgnt = 0U;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgnt) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rgnt))) {
        ++(vlSymsp->__Vcoverage[331]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rgnt 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgnt;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreq_r 
        = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq;
    if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt))) {
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen1_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wen1;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen1_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wen1_r))) {
        ++(vlSymsp->__Vcoverage[348]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wen1_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen1_r;
    }
    if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt))) {
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen0_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wen0;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen0_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wen0_r))) {
        ++(vlSymsp->__Vcoverage[347]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__wen0_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen0_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__regzero) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__regzero))) {
        ++(vlSymsp->__Vcoverage[674]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT____Vtogcov__regzero 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__regzero;
    }
    if (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done) {
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__jump 
            = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__init) 
               & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__take_branch));
    }
    if (vlSelf->rst_in) {
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__jump = 0U;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__jump) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__jump))) {
        ++(vlSymsp->__Vcoverage[419]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__jump 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__jump;
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
    if (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1) {
        ++(vlSymsp->__Vcoverage[367]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata1 
            = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata) 
                     >> 1U));
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata = (
                                                   (~ 
                                                    (- (IData)((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__regzero)))) 
                                                   & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_rf_ram__DOT__rdata));
    __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt 
        = (0x1fU & ((IData)(1U) + (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt)));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_rreq) 
         | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq))) {
        ++(vlSymsp->__Vcoverage[372]);
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt 
            = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_wreq) 
               << 1U);
    }
    if (vlSelf->rst_in) {
        vlSelf->gpio_o = 0U;
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreq_r = 0U;
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgate = 0U;
        __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt = 0U;
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq = 0U;
        __Vdly__tb_cov_top__DOT__dut__DOT__bstate = 0U;
        __Vdly__tb_cov_top__DOT__dut__DOT__br_addr = 0U;
        vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata = 0U;
        vlSelf->tb_cov_top__DOT__dut__DOT__br_we = 0U;
        vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc = 0U;
        vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm = 0U;
    } else {
        if ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc) 
              & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_we)) 
             & (0x3ffU == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_addr)))) {
            vlSelf->gpio_o = (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata));
        }
        if ((4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
            if ((2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
                if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
                    __Vdly__tb_cov_top__DOT__dut__DOT__bstate = 0U;
                } else {
                    vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc = 0U;
                    vlSelf->tb_cov_top__DOT__dut__DOT__br_we = 0U;
                    __Vdly__tb_cov_top__DOT__dut__DOT__bstate = 0U;
                }
            } else if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
                vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                    = ((0xffffffU & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm) 
                       | ((IData)(vlSelf->tb_cov_top__DOT__sr) 
                          << 0x18U));
                vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc = 0U;
                vlSelf->tb_cov_top__DOT__dut__DOT__br_we = 0U;
                __Vdly__tb_cov_top__DOT__dut__DOT__bstate = 6U;
            } else {
                vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                    = ((0xff00ffffU & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm) 
                       | ((IData)(vlSelf->tb_cov_top__DOT__sr) 
                          << 0x10U));
                vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc = 0U;
                vlSelf->tb_cov_top__DOT__dut__DOT__br_we = 0U;
                __Vdly__tb_cov_top__DOT__dut__DOT__bstate = 5U;
            }
        } else if ((2U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
            if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
                vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                    = ((0xffff00ffU & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm) 
                       | ((IData)(vlSelf->tb_cov_top__DOT__sr) 
                          << 8U));
                __Vdly__tb_cov_top__DOT__dut__DOT__br_addr 
                    = (3U | (0x3fcU & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
                vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata 
                    = (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                       >> 0x18U);
                vlSelf->tb_cov_top__DOT__dut__DOT__br_we 
                    = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we) 
                       & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel) 
                          >> 3U));
                vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc = 1U;
                __Vdly__tb_cov_top__DOT__dut__DOT__bstate = 4U;
            } else {
                vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm 
                    = ((0xffffff00U & vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm) 
                       | (IData)(vlSelf->tb_cov_top__DOT__sr));
                __Vdly__tb_cov_top__DOT__dut__DOT__br_addr 
                    = (2U | (0x3fcU & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
                vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata 
                    = (0xffU & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                                >> 0x10U));
                vlSelf->tb_cov_top__DOT__dut__DOT__br_we 
                    = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we) 
                       & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel) 
                          >> 2U));
                vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc = 1U;
                __Vdly__tb_cov_top__DOT__dut__DOT__bstate = 3U;
            }
        } else if ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate))) {
            __Vdly__tb_cov_top__DOT__dut__DOT__br_addr 
                = (1U | (0x3fcU & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr));
            vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata 
                = (0xffU & (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
                            >> 8U));
            vlSelf->tb_cov_top__DOT__dut__DOT__br_we 
                = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we) 
                   & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel) 
                      >> 1U));
            vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc = 1U;
            __Vdly__tb_cov_top__DOT__dut__DOT__bstate = 2U;
        } else {
            vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc = 0U;
            vlSelf->tb_cov_top__DOT__dut__DOT__br_we = 0U;
            if (vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_stb) {
                __Vdly__tb_cov_top__DOT__dut__DOT__br_addr 
                    = (0x3fcU & vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr);
                vlSelf->tb_cov_top__DOT__dut__DOT__br_wdata 
                    = (0xffU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat);
                vlSelf->tb_cov_top__DOT__dut__DOT__br_we 
                    = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we) 
                       & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_sel));
                vlSelf->tb_cov_top__DOT__dut__DOT__br_cyc = 1U;
                __Vdly__tb_cov_top__DOT__dut__DOT__bstate = 1U;
            }
        }
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__ibus_cyc) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__ibus_cyc))) {
        ++(vlSymsp->__Vcoverage[478]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__ibus_cyc 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__ibus_cyc;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb 
        = ((~ (IData)(vlSelf->rst_in)) & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__ibus_cyc));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata1))) {
        ++(vlSymsp->__Vcoverage[365]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rdata1 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata1;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1 
        = (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__rdata1 
        = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1)
                  ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_rdata)
                  : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata1)));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm25) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__imm25))) {
        ++(vlSymsp->__Vcoverage[503]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__imm25 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm25;
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op21))) {
        ++(vlSymsp->__Vcoverage[500]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__op21 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21;
    }
    if (((IData)(vlSelf->gpio_o) ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__gpio_o))) {
        ++(vlSymsp->__Vcoverage[2]);
        vlSelf->tb_cov_top__DOT____Vtogcov__gpio_o 
            = vlSelf->gpio_o;
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
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d 
        = (1U & ((4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))
                  ? ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm19_12_20) 
                     >> 4U) : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rdata0)));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_rd_sel 
        = ((4U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)) 
           | (((1U == (3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                             >> 1U))) << 1U) | (0U 
                                                == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_misalign 
        = (1U & ((vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                  & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                     | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                        >> 1U))) | ((vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                                     & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)) 
                                    >> 1U)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_cmp_sig 
        = (1U & (~ (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                     & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                        >> 1U)) | (IData)((6U == (6U 
                                                  & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)))))));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause31) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause31))) {
        ++(vlSymsp->__Vcoverage[643]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause31 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause31;
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
    if (((0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt0to3))) {
        ++(vlSymsp->__Vcoverage[428]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt0to3 
            = (0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt));
    }
    if ((1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__o_cnt)))) {
        ++(vlSymsp->__Vcoverage[473]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__o_cnt 
            = ((6U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT____Vtogcov__o_cnt)) 
               | (1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)));
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
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid 
        = (1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                  >> 1U) | ((0U == (3U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                                          >> 1U))) 
                            | ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                                   >> 2U)) & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3)))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12to31 
        = (IData)((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt) 
                    >> 2U) | (3U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie 
        = __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie;
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb 
        = __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb;
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
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_stb))) {
        ++(vlSymsp->__Vcoverage[249]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_ibus_stb 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt 
        = __Vdly__tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt;
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__d))) {
        ++(vlSymsp->__Vcoverage[650]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__d 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__d;
    }
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
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_misalign) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_misalign))) {
        ++(vlSymsp->__Vcoverage[458]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__mem_misalign 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_misalign;
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
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__byte_valid) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__byte_valid))) {
        ++(vlSymsp->__Vcoverage[568]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT____Vtogcov__byte_valid 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__byte_valid;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT____Vtogcov__dat_valid))) {
        ++(vlSymsp->__Vcoverage[635]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT____Vtogcov__dat_valid 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12to31) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt12to31))) {
        ++(vlSymsp->__Vcoverage[429]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt12to31 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt12to31;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mpie) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus_mpie))) {
        ++(vlSymsp->__Vcoverage[641]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus_mpie 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mpie;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus_mie))) {
        ++(vlSymsp->__Vcoverage[640]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mstatus_mie 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mstatus_mie;
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
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_rd 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__dat_valid)
            ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2_q)
            : ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__mem_if__DOT__signbit) 
               & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                     >> 2U))));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm30) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_sh_signed))) {
        ++(vlSymsp->__Vcoverage[439]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_sh_signed 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm30;
    }
    if (((0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb)) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt_en))) {
        ++(vlSymsp->__Vcoverage[427]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt_en 
            = (0U != (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb));
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
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt7 
        = ((1U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
              >> 3U));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt1 
        = ((0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
              >> 1U));
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
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0 
        = ((0U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done 
        = ((7U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__o_cnt)) 
           & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__state__DOT__gen_cnt_w_eq_1__DOT__cnt_lsb) 
              >> 3U));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreq_r) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreq_r))) {
        ++(vlSymsp->__Vcoverage[366]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rreq_r 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rreq_r;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgate) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_ren))) {
        ++(vlSymsp->__Vcoverage[200]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_ren 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rgate;
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rtrig1))) {
        ++(vlSymsp->__Vcoverage[337]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT____Vtogcov__rtrig1 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__rf_wen = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rtrig1) 
                                                  & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen0_r)) 
                                                 | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__rcnt) 
                                                    & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__rf_ram_if__DOT__wen1_r)));
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__rs1_sx) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__rs1_sx))) {
        ++(vlSymsp->__Vcoverage[620]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__rs1_sx 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__rs1_sx;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__new_irq))) {
        ++(vlSymsp->__Vcoverage[470]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__new_irq 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__new_irq;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ebreak))) {
        ++(vlSymsp->__Vcoverage[407]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__ebreak 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_csr_addr 
        = ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20) 
             & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26)) 
            << 1U) | (1U & ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26)) 
                            | (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_valid 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op20) 
           | ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op21)) 
              & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__op26)));
    if ((1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                >> 3U) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_we)))) {
        ++(vlSymsp->__Vcoverage[173]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_ext_we 
            = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                     >> 3U));
    }
    if ((1U & ((~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)) 
               ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cond_branch)))) {
        ++(vlSymsp->__Vcoverage[404]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cond_branch 
            = (1U & (~ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)));
    }
    if ((IData)((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                  >> 4U) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__branch_op)))) {
        ++(vlSymsp->__Vcoverage[408]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__branch_op 
            = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                     >> 4U));
    }
    if ((1U & ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                   >> 2U)) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_imm_en)))) {
        ++(vlSymsp->__Vcoverage[441]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_imm_en 
            = (1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                        >> 2U)));
    }
    if ((1U ^ (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                >> 4U) ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__i_mem_op)))) {
        ++(vlSymsp->__Vcoverage[639]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__i_mem_op 
            = (1U & (~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                        >> 4U)));
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
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_mem_en 
        = (IData)((0U == (5U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_rs1_en 
        = (1U & ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                     >> 4U)) | (IData)((1U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_clr_lsb 
        = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
            >> 4U) & ((0U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))) 
                      | (3U == (3U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode)))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_alu_en 
        = (IData)((4U == (0x15U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_dbus_en 
        = (IData)((0U == (0x14U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_jal_or_jalr 
        = (IData)((0x11U == (0x11U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h95a35778__0 
        = (IData)((5U == (5U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_sub 
        = (1U & (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                  >> 1U) | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                            | ((((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                                 >> 3U) & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__imm30)) 
                               | ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                                  >> 4U)))));
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op 
        = (1U & ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3) 
                     >> 1U)) & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                                >> 2U)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hb268fff8__0 
        = (IData)((0U == (0x11U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
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
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h9b5de16a__0 
        = (IData)((0x14U == (0x14U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode))));
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt7) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt7))) {
        ++(vlSymsp->__Vcoverage[434]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt7 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt7;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt1) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt1))) {
        ++(vlSymsp->__Vcoverage[431]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt1 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt1;
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt0))) {
        ++(vlSymsp->__Vcoverage[430]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__cnt0 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_slt 
        = ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__cmp_r) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0));
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__rf_wen) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wen))) {
        ++(vlSymsp->__Vcoverage[187]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__rf_wen 
            = vlSelf->tb_cov_top__DOT__dut__DOT__rf_wen;
    }
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
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_valid) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__csr_valid))) {
        ++(vlSymsp->__Vcoverage[504]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____Vtogcov__csr_valid 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__csr_valid;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we = 
        (1U & ((~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb)) 
               & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                  >> 3U)));
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
    vlSelf->tb_cov_top__DOT__dut__DOT__bstate = __Vdly__tb_cov_top__DOT__dut__DOT__bstate;
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_dat 
        = (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dhi) 
            << 0x18U) | vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg2__DOT__dlo);
    vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_adr = 
        ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb)
          ? vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__wb_ibus_adr
          : (0xfffffffcU & vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data));
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
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_clr_lsb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_clr_lsb))) {
        ++(vlSymsp->__Vcoverage[442]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__bufreg_clr_lsb 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_clr_lsb;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__clr_lsb 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_bufreg_clr_lsb) 
           & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt0));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_alu_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_alu_en))) {
        ++(vlSymsp->__Vcoverage[411]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__rd_alu_en 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_rd_alu_en;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_dbus_en) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__dbus_en))) {
        ++(vlSymsp->__Vcoverage[469]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__dbus_en 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_dbus_en;
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
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_utype 
        = ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
               >> 4U)) & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_h95a35778__0));
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_sub) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_sub))) {
        ++(vlSymsp->__Vcoverage[445]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__alu_sub 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_alu_sub;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__shift_op))) {
        ++(vlSymsp->__Vcoverage[409]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__shift_op 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_shift_op;
    }
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_two_stage_op 
        = (1U & ((~ ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__opcode) 
                     >> 2U)) | ((IData)(((1U == (3U 
                                                 & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))) 
                                         & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hb268fff8__0))) 
                                | (IData)(((2U == (6U 
                                                   & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__funct3))) 
                                           & (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT____VdfgTmp_hb268fff8__0))))));
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
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_slt) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_slt))) {
        ++(vlSymsp->__Vcoverage[616]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT____Vtogcov__result_slt 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__alu__DOT__result_slt;
    }
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause))) {
        ++(vlSymsp->__Vcoverage[648]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT____Vtogcov__mcause 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__gen_csr__DOT__csr__DOT__mcause;
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_we))) {
        ++(vlSymsp->__Vcoverage[107]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_we 
            = vlSelf->tb_cov_top__DOT__dut__DOT__wb_mem_we;
    }
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
    if (((6U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_ack))) {
        ++(vlSymsp->__Vcoverage[141]);
        vlSelf->tb_cov_top__DOT__dut__DOT____Vtogcov__wb_mem_ack 
            = (6U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate));
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
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_ack 
        = ((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb) 
           & (6U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)));
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dmem_ack 
        = ((~ (IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_ibus_stb)) 
           & (6U == (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__bstate)));
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
    if ((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__init)))) {
        ++(vlSymsp->__Vcoverage[34]);
    }
    if (VL_UNLIKELY((1U & (~ (IData)(vlSelf->tb_cov_top__DOT__init))))) {
        vlSelf->tb_cov_top__DOT__i = 0U;
        while (VL_GTS_III(32, 0x400U, vlSelf->tb_cov_top__DOT__i)) {
            vlSelf->tb_cov_top__DOT__mem[(0x3ffU & vlSelf->tb_cov_top__DOT__i)] = 0U;
            ++(vlSymsp->__Vcoverage[33]);
            vlSelf->tb_cov_top__DOT__i = ((IData)(1U) 
                                          + vlSelf->tb_cov_top__DOT__i);
        }
        vlSelf->tb_cov_top__DOT__init = 1U;
        __Vtemp_11[0U] = 0x2e686578U;
        __Vtemp_11[1U] = 0x79746573U;
        __Vtemp_11[2U] = 0x696f5f62U;
        __Vtemp_11[3U] = 0x6770U;
        VL_READMEM_N(true, 8, 1024, 0, VL_CVT_PACK_STR_NW(4, __Vtemp_11)
                     ,  &(vlSelf->tb_cov_top__DOT__mem)
                     , 0, ~0ULL);
    }
    vlSelf->tb_cov_top__DOT__sr = vlSelf->tb_cov_top__DOT__mem
        [vlSelf->tb_cov_top__DOT__dut__DOT__br_addr];
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
    vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_rdt 
        = ((0U != (vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__data 
                   >> 0x1eU)) ? 0U : vlSelf->tb_cov_top__DOT__dut__DOT__rdt_asm);
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__clr_lsb) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__clr_lsb))) {
        ++(vlSymsp->__Vcoverage[530]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT____Vtogcov__clr_lsb 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__bufreg__DOT__clr_lsb;
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
    if (((IData)(tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_utype) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__utype))) {
        ++(vlSymsp->__Vcoverage[421]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT____Vtogcov__utype 
            = tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_ctrl_utype;
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
    tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__imm 
        = (1U & ((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__cnt_done)
                  ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__signbit)
                  : ((1U & (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__decode__DOT__co_immdec_ctrl))
                      ? (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm11_7)
                      : (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__cpu__DOT__immdec__DOT__gen_immdec_w_eq_1__DOT__imm24_20))));
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
    if (__Vdlyvset__tb_cov_top__DOT__mem__v0) {
        vlSelf->tb_cov_top__DOT__mem[__Vdlyvdim0__tb_cov_top__DOT__mem__v0] 
            = __Vdlyvval__tb_cov_top__DOT__mem__v0;
    }
    vlSelf->tb_cov_top__DOT__dut__DOT__br_addr = __Vdly__tb_cov_top__DOT__dut__DOT__br_addr;
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
    if (((IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack) 
         ^ (IData)(vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_ack))) {
        ++(vlSymsp->__Vcoverage[284]);
        vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT____Vtogcov__wb_dbus_ack 
            = vlSelf->tb_cov_top__DOT__dut__DOT__u_servile__DOT__wb_dbus_ack;
    }
    if (((IData)(vlSelf->tb_cov_top__DOT__init) ^ (IData)(vlSelf->tb_cov_top__DOT____Vtogcov__init))) {
        ++(vlSymsp->__Vcoverage[31]);
        vlSelf->tb_cov_top__DOT____Vtogcov__init = vlSelf->tb_cov_top__DOT__init;
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
