# Auto-generated cocotb Makefile for can.
# Override SIM=verilator (etc.) on the command line if desired.

TOPLEVEL_LANG ?= verilog
SIM ?= icarus

VERILOG_SOURCES = $(PWD)/can_top.v
# Add register-file / FSM / soc-wrap sources here as the design grows:
# VERILOG_SOURCES += $(PWD)/can_regs.v
# VERILOG_SOURCES += $(PWD)/can_fsm.v
# VERILOG_SOURCES += $(PWD)/can_soc_wrap.v

TOPLEVEL = can
MODULE   = can_cocotb_test

include $(shell cocotb-config --makefiles)/Makefile.sim
