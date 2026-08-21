#!/usr/bin/env python3
"""Shared, value-aware argv splitting for the ``eda_report_audit`` wrapper family.

WHY THIS MODULE EXISTS — seven sibling wrappers (``drc`` / ``lvs`` / ``power`` /
``em`` / ``ir_drop`` / ``sta`` / ``antenna``) all have the same job: take a
caller's command line, decide which bare token is the project directory, pin the
audit mode this wrapper is named for, and forward everything else to
``eda_report_audit.main``. At the time #489 was filed the repo held THREE
divergent hand-written answers to that one question, and the defect #489 reports
is exactly a copy of one of them that was never re-derived. A hand-rolled argv
splitter per wrapper is how an argv defect propagates; this module is the single
place a wrapper adopts instead of copying.

Deliberately NOT adopted here by the other six wrappers: each is wired to a
different flow step with a different sign-off domain, so each adoption owes its
own blast-radius measurement (the doctrine ``sta_report_check.py`` already states
in its own docstring). This module is the destination for those adoptions, not a
licence to do them unmeasured.

THE TWO DEFECTS THIS SPLITTER IS BUILT AGAINST (both MEASURED, see
``tests/test_issue489_lvs_report_check_argv.py``):

1. ``--mode`` was pinned only against the space-separated spelling. ``--mode=x``
   starts with ``-``, so it was forwarded, and — arriving AFTER the pinned pair
   — argparse's last-wins handed the caller's value to the mode dispatcher.
   Measured on ``lvs_report_check.py`` at v1.7.66: ``--mode=power`` produced an
   audit whose own ``program`` field read ``eda_report_audit:power``.

2. The splitter was not value-aware. ``--json out.json <proj>`` took the FIRST
   bare token as the project directory, i.e. ``out.json``, leaving ``<proj>`` as
   the argument of ``--json``. Measured: ``IsADirectoryError`` and NO audit
   written at all.

Both are properties of the SPLIT, not of any one sign-off domain, which is why
they belong to a shared function and not to seven copies.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

# Options of the WRAPPED program (``eda_report_audit``) that consume the token
# after them. A splitter that does not know these reads a value-taking option's
# ARGUMENT as the positional project dir — defect 2.
#
# ``--mode`` is listed for completeness even though ``split_and_pin`` intercepts
# it before this tuple is consulted: the tuple is a faithful description of the
# wrapped CLI, and a test derives the same set from ``eda_report_audit``'s real
# parser so a new value-taking option there cannot silently reintroduce defect 2.
# Every option `eda_report_audit` takes a VALUE for. The anti-drift test
# derives this set from that program's REAL argparse parser, so adding one
# there reddens immediately instead of silently making the next token look
# like a project directory.
#
# `--under` was added by the step-21 scoping work landing in the same batch.
# Without it here, `--under sub/dir myproj` resolved the project to `sub/dir`
# — the exact defect class this helper exists to close, arriving through a
# sibling change rather than a copy. The guard caught it on the accumulation
# branch; neither PR alone was red.
VALUE_FLAGS: Tuple[str, ...] = ("--mode", "--json", "--under")


def split_argv(
    rest: Sequence[str],
    value_flags: Sequence[str] = VALUE_FLAGS,
) -> Tuple[str, List[str]]:
    """Split a caller argv into ``(project_dir, passthrough)``.

    The project dir is the first bare token that is NOT the argument of a
    preceding value-taking option; it defaults to ``"."``. Every other token is
    forwarded verbatim, in order. ``--`` ends option processing (so a project
    directory whose name starts with a dash can be named).

    A second bare token is forwarded rather than swallowed: two positionals is a
    broken declaration, and argparse must be allowed to say so.
    """
    proj, passthrough, _ = _split(rest, mode=None, value_flags=value_flags)
    return proj, passthrough


def split_and_pin(
    rest: Sequence[str],
    *,
    mode: str,
    value_flags: Sequence[str] = VALUE_FLAGS,
) -> Tuple[str, List[str], Optional[str]]:
    """``split_argv`` plus mode pinning, in BOTH caller spellings.

    Returns ``(project_dir, passthrough, refusal)``.

    ``--mode <m>`` and ``--mode=<m>`` are both recognised. When ``m`` is the
    mode this wrapper pins, the pair is dropped (the wrapper supplies its own).
    When it is anything else — or when ``--mode`` is given with no value — the
    caller is asking a wrapper named for one sign-off domain to certify a
    different one, and ``refusal`` comes back as a human-readable reason.

    Refusal is a RETURN VALUE, not an exception and not a silent drop: silently
    dropping a caller's ``--mode power`` tells the caller power was audited when
    lvs was, and silently honouring it lets a caller change a hard sign-off's
    audit domain by flag spelling. The caller decides the exit code; see
    ``lvs_report_check.py`` for why that code must not be 2.
    """
    return _split(rest, mode=mode, value_flags=value_flags)


def _is_option(tok: str) -> bool:
    """Does this token look like an option to argparse? (a lone ``-`` does not)"""
    return tok.startswith("-") and tok != "-"


def _split(
    rest: Sequence[str],
    *,
    mode: Optional[str],
    value_flags: Sequence[str],
) -> Tuple[str, List[str], Optional[str]]:
    toks = list(rest)
    proj: Optional[str] = None
    passthrough: List[str] = []
    refusal: Optional[str] = None
    end_of_flags = False
    i = 0

    def _bare(tok: str) -> None:
        nonlocal proj
        if proj is None:
            proj = tok
        else:
            passthrough.append(tok)

    while i < len(toks):
        tok = toks[i]

        # A lone "-" is a conventional positional, never an option.
        if end_of_flags or not tok.startswith("-") or tok == "-":
            _bare(tok)
            i += 1
            continue

        if tok == "--":
            end_of_flags = True
            i += 1
            continue

        if mode is not None and tok == "--mode":
            # An option-looking next token is NOT this option's value — that is
            # how argparse reads it too ("expected one argument"), and
            # swallowing it would silently eat a real flag.
            if i + 1 >= len(toks) or _is_option(toks[i + 1]):
                refusal = refusal or (
                    "`--mode` was given with no value; this wrapper pins "
                    f"`--mode {mode}` and cannot infer what was intended")
                i += 1
                continue
            if toks[i + 1] != mode:
                refusal = refusal or (
                    f"`--mode {toks[i + 1]}` was requested, but this wrapper "
                    f"pins `--mode {mode}`")
            i += 2
            continue

        if mode is not None and tok.startswith("--mode="):
            value = tok.split("=", 1)[1]
            if value != mode:
                refusal = refusal or (
                    f"`--mode={value}` was requested, but this wrapper pins "
                    f"`--mode {mode}`")
            i += 1
            continue

        passthrough.append(tok)
        if tok in value_flags and i + 1 < len(toks) and not _is_option(toks[i + 1]):
            # The next token is this option's ARGUMENT, not the project dir.
            passthrough.append(toks[i + 1])
            i += 2
            continue
        i += 1

    return (proj if proj is not None else "."), passthrough, refusal


def json_target(passthrough: Sequence[str]) -> Optional[str]:
    """The path a ``--json`` in ``passthrough`` names, in either spelling."""
    toks = list(passthrough)
    for i, tok in enumerate(toks):
        if tok == "--json" and i + 1 < len(toks):
            return toks[i + 1]
        if tok.startswith("--json="):
            return tok.split("=", 1)[1]
    return None
