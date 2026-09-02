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


def code_only(src: str) -> str:
    """`src` with comments and docstrings blanked out, line numbering preserved.

    THE OTHER HALF OF THE SAME PROBLEM `func_src` SOLVES. That one fixed the
    SCOPE of a source-pin assertion; this fixes its CONTENT. A negative pin —
    `assert "<thing>" not in src` — is asserted over the docstring and every
    comment too, so documenting the very property the test enforces turns it
    red. Measured on `mpw_precheck_result_gate`, adding one accurate line:

        # NOTE: this parser must never key on caravel_user_project.
        -> 1 failed, 16 passed

    The obvious repair for whoever hits that is to delete the sentence, which is
    the wrong one: the property is real and the explanation is the most useful
    thing in the file. The same trap in the other direction cost a round on
    vibe-ic#551, where an ordering check read six step names out of a comment
    describing what the exclusion governs and reported all six as violations.

    Blanks IN PLACE, on the original text, so line N of the result is line N of
    the input. My first version tokenized first and then removed docstrings by
    line index — but tokenizing had already shifted the lines, so the docstring
    indices pointed at real code and it deleted `x = 1` and `return x`. Caught
    by printing the two side by side rather than trusting the three assertions
    that passed.

    `tokenize`, not a `startswith("#")` filter: a `#` inside a string literal is
    not a comment, and the naive version deletes that line of real code.
    """
    import io
    import tokenize

    lines = src.splitlines()
    blank = [False] * (len(lines) + 1)          # 1-based, per source line

    # 1. docstrings — located on the ORIGINAL text, so the indices are valid.
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            for n in range(first.lineno, (first.end_lineno or first.lineno) + 1):
                if n < len(blank):
                    blank[n] = True

    # 2. comments — cut at the token's own column, so code before a trailing
    #    `# ...` on the same line survives.
    cut = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                row, col = tok.start
                cut[row] = min(cut.get(row, col), col)
    except (tokenize.TokenError, IndentationError):
        # Unparseable is NOT clean — an empty haystack makes every negative
        # assertion pass, which is the failure mode this helper is about.
        return src

    out = []
    for n, line in enumerate(lines, 1):
        if blank[n]:
            out.append("")
        elif n in cut:
            out.append(line[:cut[n]].rstrip())
        else:
            out.append(line)
    return "\n".join(out)


def if_block_src(src: str, func: str, needle: str) -> str:
    """Source of the ONE ``if`` statement inside ``func`` whose *test* contains
    ``needle``, resolved with ``ast``.

    THE THIRD FAILURE MODE OF A SOURCE PIN, after the two `func_src` documents.
    `func_src` fixed the scope's END; this fixes its START. A pin anchored with
    ``src.index(<token>)`` binds to the FIRST TEXTUAL occurrence, and a comment
    that quotes the token — the natural way to explain a verdict — silently
    becomes the anchor. Measured on `design_one_shot_runner`:

        `"FULL_STACK_TB_DONE" in out`  line  8377  <- a comment in another
                                                      function (e5d569ace7)
        `"FULL_STACK_TB_DONE" in out`  line 10525  <- the branch being pinned

    so the 3800-char window landed ~97,000 chars from the return it asserts on
    and the test failed against correct code.

    Widening the window is the wrong repair twice over: it also reaches the
    NEIGHBOURING return in the same function, and a pin satisfied by a
    neighbour's text is a pin no mutation of its own subject can turn red.
    Here the neighbouring `iverilog unavailable` branch carries the same
    ``StepResult("reference_tb", "WAIVED")`` literal, ~3000 chars after the
    real one — so a widened window passes on a tree where the pinned branch
    says ``PASS``.

    Matched on the ``if``'s TEST expression only, never its body, so the
    statement a pin is about cannot be selected by something it contains.
    Raises when the match is not unique — a pin that quietly picks one of two
    is the defect this exists to stop.
    """
    body = func_src(src, func)
    tree = ast.parse(_dedent_for_parse(body))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test_src = ast.get_source_segment(_dedent_for_parse(body), node.test) or ""
        if needle in test_src:
            hits.append(node)
    if not hits:
        raise AssertionError(
            f"if_block_src: no `if` in {func!r} tests {needle!r}")
    if len(hits) > 1:
        raise AssertionError(
            f"if_block_src: {len(hits)} `if` statements in {func!r} test "
            f"{needle!r}; the pin would silently take one of them")
    lines = _dedent_for_parse(body).splitlines()
    node = hits[0]
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


def _dedent_for_parse(body: str) -> str:
    """``body`` shifted to column 0 so `ast.parse` accepts a nested extract.

    Line numbering is preserved: only leading whitespace is removed, and the
    same number of characters from every line, so line N in equals line N out.
    """
    import textwrap
    return textwrap.dedent(body)
