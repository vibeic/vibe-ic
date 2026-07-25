#!/usr/bin/env python3
"""_source_pin.py — shared helper for SOURCE-PIN tests.

Lives in its OWN module, not in conftest.py, because there are TWO
conftest.py files on the path (this tests/ one and the plugin-root one).
A bare `from conftest import func_src` resolves to whichever pytest
imported first, so on some file-set collections it hit the plugin-root
conftest — which has no func_src — and 4 modules failed to import.
Introduced in v1.5.78; caught here. A uniquely-named module cannot be
shadowed that way.
"""
from __future__ import annotations

import ast
import re  # noqa: F401

def func_src(src: str, name: str) -> str:
    """Source of exactly ONE function `name`, resolved with `ast`.

    Source-pin tests assert that a program's implementation still contains some
    token. They used to scope that with a magic character count
    (``src[i:i + 6800]``), which is wrong in BOTH directions as the file evolves:

      * window too SHORT -> **false FAIL**. `_report_check_types_tcl` grew to
        1845 chars, so a 1200-char window stopped before the marker it asserts
        (offset 1763) and the test failed on correct code.
      * window too LONG  -> **false PASS**. A 6800-char window over
        `_emit_spef_sta` (really 6323) bled 477 chars into the NEXT function, so
        an assertion could be satisfied by a neighbouring function's text —
        precisely the regression a source-pin exists to catch.
      * on a NEGATIVE (`not in`) pin the SHORT direction is the dangerous one:
        a 6000-char window over `_emit_mcorner_ocv_sta` (really 6951) left its
        last ~950 chars unchecked for the very construct it forbids.

    `ast` is used rather than text scanning because two text approaches both
    break on real code here:
      * `src.index(f"def {name}")` is a PREFIX match — asking for `_run` would
        happily return `_run_oracle_tb`;
      * scanning forward to the next ``\\ndef`` assumes a TOP-LEVEL definition,
        but e.g. `_auto` in phase3_one_shot_runner is nested at col_offset=4, so
        that scan would run to the next top-level def thousands of lines later.

    A missing name raises rather than returning something plausible — a
    source-pin that silently pins nothing is worse than one that fails.
    """
    tree = ast.parse(src)
    hits = [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if not hits:
        raise AssertionError(f"func_src: no function named {name!r} in this source")
    # Prefer a top-level definition when a nested helper shares the name;
    # otherwise take the first in source order. Deterministic either way.
    node = next((n for n in hits if n.col_offset == 0), hits[0])
    lines = src.splitlines()
    return "\n".join(lines[node.lineno - 1:node.end_lineno])
