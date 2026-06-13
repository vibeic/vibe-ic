# Auto-generated cocotb Makefile for swd.
# Override SIM=verilator (etc.) on the command line if desired.

TOPLEVEL_LANG ?= verilog
SIM ?= icarus

VERILOG_SOURCES = $(PWD)/swd_top.v
# Add register-file / FSM / soc-wrap sources here as the design grows:
# VERILOG_SOURCES += $(PWD)/swd_regs.v
# VERILOG_SOURCES += $(PWD)/swd_fsm.v
# VERILOG_SOURCES += $(PWD)/swd_soc_wrap.v

TOPLEVEL = swd
MODULE   = swd_cocotb_test

include $(shell cocotb-config --makefiles)/Makefile.sim
