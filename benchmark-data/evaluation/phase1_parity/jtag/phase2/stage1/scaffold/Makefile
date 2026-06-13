# Auto-generated cocotb Makefile for jtag.
# Override SIM=verilator (etc.) on the command line if desired.

TOPLEVEL_LANG ?= verilog
SIM ?= icarus

VERILOG_SOURCES = $(PWD)/jtag_top.v
# Add register-file / FSM / soc-wrap sources here as the design grows:
# VERILOG_SOURCES += $(PWD)/jtag_regs.v
# VERILOG_SOURCES += $(PWD)/jtag_fsm.v
# VERILOG_SOURCES += $(PWD)/jtag_soc_wrap.v

TOPLEVEL = jtag
MODULE   = jtag_cocotb_test

include $(shell cocotb-config --makefiles)/Makefile.sim
