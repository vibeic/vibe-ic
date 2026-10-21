"""Regression for #3395: declaration fallback must stay in type grammar."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _rtl_audit_applicability as applicability


PORTS = ("input wire clk, input wire we, input wire [1:0] addr, "
         "input wire [3:0] data, output wire [3:0] q")
DECLARATION = "  reg [3:0] bank [0:3];\n"
WRITE = "  always @(posedge clk) if (we) bank[addr] <= data;\n"
READ = "  assign q = bank[addr];\n"


def function(name: str) -> str:
    return (f"  function [3:0] {name};\n"
            "    input [3:0] value;\n"
            f"    begin {name}=value; end\n"
            "  endfunction\n")


def design(body: str) -> str:
    return f"module top({PORTS});\n{body}endmodule\n"


def native(*, width: int = 4) -> dict:
    return {"top": {"memories": {"bank": {
        "width": width, "size": 4, "start_offset": 0}}, "cells": {}}}


FIRST = function("first")
SECOND = function("second")
FIXTURES = {
    "original_ram": design(DECLARATION + WRITE + READ),
    "one_function_control": design(
        DECLARATION + FIRST + WRITE + READ.replace("bank[addr]", "first(bank[addr])")),
    "adjacent_functions": design(
        DECLARATION + FIRST + SECOND + WRITE
        + READ.replace("bank[addr]", "second(first(bank[addr]))")),
    "begin_before_array_write": design(
        DECLARATION
        + WRITE.replace("if (we) ", "if (we) begin\n    ").replace(";\n", ";\n  end\n")
        + READ),
    "else_before_array_write": design(
        DECLARATION + WRITE + "    else bank[addr] <= bank[addr];\n" + READ),
    "function_then_vector_wire": design(
        DECLARATION + FIRST + "  wire [3:0] selected;\n" + WRITE
        + "  assign selected=first(bank[addr]);\n  assign q=selected;\n"),
    "vector_wire_before_function_restore": design(
        DECLARATION + "  wire [3:0] selected;\n" + FIRST + WRITE
        + "  assign selected=first(bank[addr]);\n  assign q=selected;\n"),
}


@pytest.mark.parametrize("name", FIXTURES)
def test_language_keywords_do_not_become_unknown_memory_types(name):
    facts = applicability._memory_facts([FIXTURES[name]], native())
    assert facts == {"modules": {"top": {"bank": {
        "width": 4, "size": 4, "start_offset": 0}}}, "memory_bits": 16}


def test_actual_unknown_memory_datatype_remains_refused():
    text = design(DECLARATION + "  custom_word shadow [0:3];\n" + WRITE + READ)
    with pytest.raises(ValueError, match="^unsupported_memory_declaration$"):
        applicability._memory_facts([text], native())


def test_following_unknown_declaration_is_not_hidden_by_endfunction():
    text = design(DECLARATION + FIRST + "  custom_word shadow [0:3];\n" + WRITE + READ)
    with pytest.raises(ValueError, match="^unsupported_memory_declaration$"):
        applicability._memory_facts([text], native())


def test_source_native_storage_mismatch_remains_refused():
    with pytest.raises(ValueError, match="^source_native_memory_census_disagrees$"):
        applicability._memory_facts([FIXTURES["adjacent_functions"]], native(width=8))
