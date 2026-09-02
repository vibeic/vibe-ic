#!/usr/bin/env python3
"""The ONE reader of "is this RTL file a COMMAND-OPCODE DISPATCHER?".

WHY THIS MODULE EXISTS — the predicate had two copies, and only one of them
had been corrected.

`packet_length_check_present` fired an ERROR on `aes_ctrl_reg_shadowed.sv`,
which decodes a two-value `aes_op_e` field with `unique case (op)` over
AES_ENC / AES_DEC. No command, no packet, no length. The discriminator matched
the bare identifier `op`. That was fixed there, in place, by making the
AMBIGUOUS selectors (`cmd`, `op`) require CORROBORATION — a byte-wide opcode
literal in the same file, which is what a received-command dispatch looks like
and what an enum decode does not.

`dispatcher_awake_gate_check` carried the SAME rule, uncorrected, and on the
SAME file reached the same wrong conclusion one round later:

    [ERROR] NO_AWAKE_SIGNAL: Dispatcher RTL
    (phase2/stage1/rtl/aes_ctrl_reg_shadowed.sv) has a command opcode case but
    references no awake/wake state register

MEASURED on opentitan_aes, plugin v1.15.66 — in a run that declares
`command_protocol_applicable=false`, and where eight sibling gates skip on
exactly that fact.

A rule with two copies and no owner will eventually be corrected in one of
them. This module is that rule, written once; both gates import it.

THE RULE — structural, and never a vocabulary about any design
==============================================================
A file dispatches on a command opcode iff any of:

  1. `case (cmd_op | opcode | cmd_code)` — an UNAMBIGUOUS selector name, which
     keeps its standalone force so every dispatcher caught before is still
     caught;
  2. `case (cmd | op)` — names reused widely enough in ordinary RTL that they
     are credited only when the SAME file also carries a byte-wide opcode
     literal (`8'hXX`);
  3. three or more `if (<...>cmd<...> == 8'hXX)` comparisons — the per-opcode
     if-cascade, which already required the byte literal.

No chip, vendor, PDK or opcode-name literal participates.
"""
from __future__ import annotations

import re

# UNAMBIGUOUS selector names — standalone force.
CASE_DISPATCH_UNAMBIGUOUS_RE = re.compile(
    r"\bcase\s*\(\s*(?:\w+\s*\.\s*)?"
    r"(cmd_op|opcode|cmd_code)\b",
    re.IGNORECASE,
)

# AMBIGUOUS selector names — require corroboration.
CASE_DISPATCH_AMBIGUOUS_RE = re.compile(
    r"\bcase\s*\(\s*(?:\w+\s*\.\s*)?"
    r"(cmd|op)\b",
    re.IGNORECASE,
)

#: A byte-wide literal — the corroboration an ambiguous selector needs.
BYTE_OPCODE_LITERAL_RE = re.compile(r"\b8'h[0-9a-fA-F]{1,2}\b")

# Cascade of opcode equality: if (cmd == 8'hXX) or if (cmd_x == 8'hYY).
IF_OPCODE_EQ_RE = re.compile(
    r"\bif\s*\(\s*\w*cmd\w*\s*==\s*8'h[0-9a-fA-F]{1,2}",
)


def is_opcode_dispatcher(text: str) -> bool:
    """True when `text` dispatches on a command opcode. Pure."""
    if not isinstance(text, str) or not text:
        return False
    if CASE_DISPATCH_UNAMBIGUOUS_RE.search(text):
        return True
    if (CASE_DISPATCH_AMBIGUOUS_RE.search(text)
            and BYTE_OPCODE_LITERAL_RE.search(text)):
        return True
    if len(IF_OPCODE_EQ_RE.findall(text)) >= 3:
        return True
    return False
