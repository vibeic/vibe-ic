# Auto-generated cocotb Makefile for chip_top.
# Override SIM=verilator (etc.) on the command line if desired.

TOPLEVEL_LANG ?= verilog
SIM ?= icarus

VERILOG_SOURCES = $(PWD)/chip_top_top.v
# Add register-file / FSM / soc-wrap sources here as the design grows:
# VERILOG_SOURCES += $(PWD)/chip_top_regs.v
# VERILOG_SOURCES += $(PWD)/chip_top_fsm.v
# VERILOG_SOURCES += $(PWD)/chip_top_soc_wrap.v

TOPLEVEL = chip_top
MODULE   = chip_top_cocotb_test

include $(shell cocotb-config --makefiles)/Makefile.sim
