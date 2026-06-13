# Auto-generated cocotb Makefile for ethernet.
# Override SIM=verilator (etc.) on the command line if desired.

TOPLEVEL_LANG ?= verilog
SIM ?= icarus

VERILOG_SOURCES = $(PWD)/ethernet_top.v
# Add register-file / FSM / soc-wrap sources here as the design grows:
# VERILOG_SOURCES += $(PWD)/ethernet_regs.v
# VERILOG_SOURCES += $(PWD)/ethernet_fsm.v
# VERILOG_SOURCES += $(PWD)/ethernet_soc_wrap.v

TOPLEVEL = ethernet
MODULE   = ethernet_cocotb_test

include $(shell cocotb-config --makefiles)/Makefile.sim
