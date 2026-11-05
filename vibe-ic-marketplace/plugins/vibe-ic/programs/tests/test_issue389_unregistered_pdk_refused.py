#!/usr/bin/env python3
"""#389 — `--pdk <unregistered>` silently resolved to sky130A.

An invented PDK name and a real-but-unregistered one produced BYTE-IDENTICAL
results, with nothing on stderr and nothing in any artefact. A cell was driven
to a verdict, written up and discussed as `spm x ihp-sg13cmos5l` while every
tool read sky130A: the physical numbers were real, the PDK attribution was not.

This defect is recorded THREE times in `_detect_pdk`'s own comments — asap7,
then the registry-declared set, now ihp-sg13cmos5l — and each previous fix
added ANOTHER named branch. Branches cannot close it: the hole is the
fall-through, which converts "I cannot resolve what you asked for" into "here
is something else".

The fallback stays for AUTO-detect. Defaulting when the operator expressed no
preference is a choice; substituting for a name they DID give is not.
"""
from __future__ import annotations

import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))












def test_389_the_refusal_is_driven_by_failure_not_by_a_denylist():
    """The refusal must fire because resolution FAILED, not because the name
    matched a list of known-bad ones — a denylist lets the NEXT unregistered
    PDK through, which is precisely how this recurred three times.

    (An earlier version of this test asserted `X or True`, which is no
    assertion at all — the exact vacuous-check shape this repo removes
    elsewhere. Rewritten to test the branch CONDITION.)"""
    import ast
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_detect_pdk")
    raises = [n for n in ast.walk(fn)
              if isinstance(n, ast.Raise)
              and "REFUSING to fall" in ast.dump(n)]
    assert raises, "the refusal must be a raise inside _detect_pdk"
    # Locate THIS refusal from its own marker forward. The file already
    # contains a DIFFERENT "REFUSING to fall" — for a PDK that IS registered
    # but whose assets cannot be resolved in the container — and an
    # index-from-the-start search finds that one instead. The two are
    # complementary: registered-but-unresolvable vs not-registered-at-all.
    mark = src.index("vibe-ic#389")
    guard_src = src[mark:src.index("REFUSING to fall", mark)]
    assert 'if override and override != "auto":' in guard_src
    for name in ("ihp-sg13cmos5l", "totally-made-up", "gf180mcuD",
                 "nangate45", "asap7"):
        assert f'override == "{name}"' not in guard_src, (
            f"a denylist entry for {name!r} gates the refusal")
