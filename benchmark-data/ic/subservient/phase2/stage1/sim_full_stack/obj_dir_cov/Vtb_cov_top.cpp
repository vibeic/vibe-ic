// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Model implementation (design independent parts)

#include "Vtb_cov_top__pch.h"

//============================================================
// Constructors

Vtb_cov_top::Vtb_cov_top(VerilatedContext* _vcontextp__, const char* _vcname__)
    : VerilatedModel{*_vcontextp__}
    , vlSymsp{new Vtb_cov_top__Syms(contextp(), _vcname__, this)}
    , clk{vlSymsp->TOP.clk}
    , rst_in{vlSymsp->TOP.rst_in}
    , gpio_o{vlSymsp->TOP.gpio_o}
    , rootp{&(vlSymsp->TOP)}
{
    // Register model with the context
    contextp()->addModel(this);
}

Vtb_cov_top::Vtb_cov_top(const char* _vcname__)
    : Vtb_cov_top(Verilated::threadContextp(), _vcname__)
{
}

//============================================================
// Destructor

Vtb_cov_top::~Vtb_cov_top() {
    delete vlSymsp;
}

//============================================================
// Evaluation function

#ifdef VL_DEBUG
void Vtb_cov_top___024root___eval_debug_assertions(Vtb_cov_top___024root* vlSelf);
#endif  // VL_DEBUG
void Vtb_cov_top___024root___eval_static(Vtb_cov_top___024root* vlSelf);
void Vtb_cov_top___024root___eval_initial(Vtb_cov_top___024root* vlSelf);
void Vtb_cov_top___024root___eval_settle(Vtb_cov_top___024root* vlSelf);
void Vtb_cov_top___024root___eval(Vtb_cov_top___024root* vlSelf);

void Vtb_cov_top::eval_step() {
    VL_DEBUG_IF(VL_DBG_MSGF("+++++TOP Evaluate Vtb_cov_top::eval_step\n"); );
#ifdef VL_DEBUG
    // Debug assertions
    Vtb_cov_top___024root___eval_debug_assertions(&(vlSymsp->TOP));
#endif  // VL_DEBUG
    vlSymsp->__Vm_deleter.deleteAll();
    if (VL_UNLIKELY(!vlSymsp->__Vm_didInit)) {
        vlSymsp->__Vm_didInit = true;
        VL_DEBUG_IF(VL_DBG_MSGF("+ Initial\n"););
        Vtb_cov_top___024root___eval_static(&(vlSymsp->TOP));
        Vtb_cov_top___024root___eval_initial(&(vlSymsp->TOP));
        Vtb_cov_top___024root___eval_settle(&(vlSymsp->TOP));
    }
    VL_DEBUG_IF(VL_DBG_MSGF("+ Eval\n"););
    Vtb_cov_top___024root___eval(&(vlSymsp->TOP));
    // Evaluate cleanup
    Verilated::endOfEval(vlSymsp->__Vm_evalMsgQp);
}

//============================================================
// Events and timing
bool Vtb_cov_top::eventsPending() { return false; }

uint64_t Vtb_cov_top::nextTimeSlot() {
    VL_FATAL_MT(__FILE__, __LINE__, "", "%Error: No delays in the design");
    return 0;
}

//============================================================
// Utilities

const char* Vtb_cov_top::name() const {
    return vlSymsp->name();
}

//============================================================
// Invoke final blocks

void Vtb_cov_top___024root___eval_final(Vtb_cov_top___024root* vlSelf);

VL_ATTR_COLD void Vtb_cov_top::final() {
    Vtb_cov_top___024root___eval_final(&(vlSymsp->TOP));
}

//============================================================
// Implementations of abstract methods from VerilatedModel

const char* Vtb_cov_top::hierName() const { return vlSymsp->name(); }
const char* Vtb_cov_top::modelName() const { return "Vtb_cov_top"; }
unsigned Vtb_cov_top::threads() const { return 1; }
void Vtb_cov_top::prepareClone() const { contextp()->prepareClone(); }
void Vtb_cov_top::atClone() const {
    contextp()->threadPoolpOnClone();
}

//============================================================
// Trace configuration

VL_ATTR_COLD void Vtb_cov_top::trace(VerilatedVcdC* tfp, int levels, int options) {
    vl_fatal(__FILE__, __LINE__, __FILE__,"'Vtb_cov_top::trace()' called on model that was Verilated without --trace option");
}
