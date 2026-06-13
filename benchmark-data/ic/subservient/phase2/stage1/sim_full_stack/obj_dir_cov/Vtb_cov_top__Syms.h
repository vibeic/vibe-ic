// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Symbol table internal header
//
// Internal details; most calling programs do not need this header,
// unless using verilator public meta comments.

#ifndef VERILATED_VTB_COV_TOP__SYMS_H_
#define VERILATED_VTB_COV_TOP__SYMS_H_  // guard

#include "verilated.h"

// INCLUDE MODEL CLASS

#include "Vtb_cov_top.h"

// INCLUDE MODULE CLASSES
#include "Vtb_cov_top___024root.h"

// SYMS CLASS (contains all model state)
class alignas(VL_CACHE_LINE_BYTES)Vtb_cov_top__Syms final : public VerilatedSyms {
  public:
    // INTERNAL STATE
    Vtb_cov_top* const __Vm_modelp;
    VlDeleter __Vm_deleter;
    bool __Vm_didInit = false;

    // MODULE INSTANCE STATE
    Vtb_cov_top___024root          TOP;

    // COVERAGE
    uint32_t __Vcoverage[680];

    // CONSTRUCTORS
    Vtb_cov_top__Syms(VerilatedContext* contextp, const char* namep, Vtb_cov_top* modelp);
    ~Vtb_cov_top__Syms();

    // METHODS
    const char* name() { return TOP.name(); }
};

#endif  // guard
