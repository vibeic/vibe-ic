# Auto-generated cocotb Makefile for ethercat.
# Override SIM=verilator (etc.) on the command line if desired.

TOPLEVEL_LANG ?= verilog
SIM ?= icarus

VERILOG_SOURCES = $(PWD)/ethercat_top.v
# Add register-file / FSM / soc-wrap sources here as the design grows:
# VERILOG_SOURCES += $(PWD)/ethercat_regs.v
# VERILOG_SOURCES += $(PWD)/ethercat_fsm.v
# VERILOG_SOURCES += $(PWD)/ethercat_soc_wrap.v

TOPLEVEL = ethercat
MODULE   = ethercat_cocotb_test

include $(shell cocotb-config --makefiles)/Makefile.sim
