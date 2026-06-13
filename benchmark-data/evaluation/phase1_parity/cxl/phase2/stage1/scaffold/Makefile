# Auto-generated cocotb Makefile for cxl.
# Override SIM=verilator (etc.) on the command line if desired.

TOPLEVEL_LANG ?= verilog
SIM ?= icarus

VERILOG_SOURCES = $(PWD)/cxl_top.v
# Add register-file / FSM / soc-wrap sources here as the design grows:
# VERILOG_SOURCES += $(PWD)/cxl_regs.v
# VERILOG_SOURCES += $(PWD)/cxl_fsm.v
# VERILOG_SOURCES += $(PWD)/cxl_soc_wrap.v

TOPLEVEL = cxl
MODULE   = cxl_cocotb_test

include $(shell cocotb-config --makefiles)/Makefile.sim
