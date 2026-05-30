# Auto-generated cocotb Makefile for tilelink.
# Override SIM=verilator (etc.) on the command line if desired.

TOPLEVEL_LANG ?= verilog
SIM ?= icarus

VERILOG_SOURCES = $(PWD)/tilelink_top.v
# Add register-file / FSM / soc-wrap sources here as the design grows:
# VERILOG_SOURCES += $(PWD)/tilelink_regs.v
# VERILOG_SOURCES += $(PWD)/tilelink_fsm.v
# VERILOG_SOURCES += $(PWD)/tilelink_soc_wrap.v

TOPLEVEL = tilelink
MODULE   = tilelink_cocotb_test

include $(shell cocotb-config --makefiles)/Makefile.sim
