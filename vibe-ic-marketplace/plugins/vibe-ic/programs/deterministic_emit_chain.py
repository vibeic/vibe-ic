#!/usr/bin/env python3
r"""deterministic_emit_chain.py — try every deterministic RTL emitter, in order.

THE PROGRAM HALF OF PROGRAM-FIRST, AS A CALLABLE.

The emitters existed and were good — `spec_artifact_registry` alone solves
125/156 of one open corpus deterministically — but reaching them meant either
running the whole runner or importing a benchmark's tier pipeline. So the same
chain got re-assembled in `verilogeval_tier_pipeline`, `verilogeval_human_tier_
pipeline`, `rtllm_tier_pipeline`, `cvdp_solve_pipeline` and `gates_atomic`, once
per benchmark, each with its own order and its own idea of what counts as a
solve. Four of those five also had the order WRONG: they demanded an
AI-authored file first and ran the program second, overwriting it.

One chain, one order, callable from anywhere:

    kind, rtl = try_emit(prompt_text, ifc_text, top)

`kind` names which emitter fired, or None when none did — and None is a real
answer, not a failure. It is the handover point where the runner WAIVEs to the
`spec-to-rtl` AI backup, which is the designed dual track.

THE CONTRACT IS EXACT-OR-NOTHING. An emitter returns RTL only when the prompt is
parse-complete for the shape it recognises. It never returns a guess: a guess
dressed as a program result is worse than a waive, because the waive is honest
about needing judgement and the guess is not.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _registry(prompt: str, ifc: str, top: str) -> Tuple[Optional[str], Optional[str]]:
    """The canonical recognisers. Broad coverage, mutual-exclusion checked."""
    try:
        import spec_artifact_registry as _reg
    except ImportError:
        return None, None
    return _reg.generate(prompt, top)


def _supplemental(prompt: str, ifc: str, top: str) -> Tuple[Optional[str], Optional[str]]:
    """Shapes the registry deliberately does not recognise.

    Kept a separate module on purpose: these were added so that widening the
    registry's recognisers could not put its existing coverage at risk. Ordered
    AFTER the registry for the same reason.
    """
    try:
        import fsm_vector_rtl_emit as _fve
    except ImportError:
        return None, None
    return _fve.emit({"prompt": prompt, "ifc": ifc})


# ORDER IS THE CONTRACT. Broadest-and-most-checked first; the supplemental
# emitters are the fallback for what it declines. A caller that wants a
# different order is asking for a different chain, not for a parameter.
EMITTERS: List[Tuple[str, Callable[..., Tuple[Optional[str], Optional[str]]]]] = [
    ("spec_artifact_registry", _registry),
    ("fsm_vector_rtl_emit", _supplemental),
]


def try_emit(prompt_text: str, ifc_text: str = "",
             top: str = "TopModule") -> Tuple[Optional[str], Optional[str]]:
    """(kind, rtl) of the first emitter that fires, or (None, None).

    (None, None) means "no program recognised this" — hand to the AI backup.
    """
    if not (prompt_text or "").strip():
        return None, None
    for name, fn in EMITTERS:
        try:
            kind, rtl = fn(prompt_text, ifc_text, top)
        except Exception:
            # An emitter that raises must not take the chain down; the next one
            # and ultimately the AI backup are the designed fallbacks.
            continue
        if rtl:
            return (kind or name), rtl
    return None, None


def emit_would_be_blocked(prompt_text: str, rtl: str,
                          timeout: int = 60) -> List[str]:
    """The EMIT-BLOCKING conformance rules this RTL trips, [] if it is clean.

    THE PARITY THAT KEEPS A DETERMINISTIC EMIT HONEST. An emit can compile,
    simulate and still be wrong in a way the real gate catches: answer a
    "logical right shifter" spec with a pure rotate and iverilog is perfectly
    happy. Counting that as program-solved reports a capability the blind run
    does not have — the gate would refuse to emit it.

    So a deterministic emit is only genuinely a solve when THIS returns []. The
    rule set is `spec_conformance_check.EMIT_BLOCKING_CONFORMANCE_RULES`, the
    same one the gate consults, so the two cannot drift.

    Was duplicated in `verilogeval_tier_pipeline` and
    `verilogeval_human_tier_pipeline` — two copies of a check with no benchmark
    content, reachable only by importing a benchmark's pipeline. It takes prompt
    TEXT rather than a problem object so nothing about it is dataset-shaped.

    On any tool or IO error it returns [] — a missing checker must never
    manufacture a block and demote a real solve.
    """
    if not (rtl or "").strip() or not (prompt_text or "").strip():
        return []
    try:
        from spec_conformance_check import (                # noqa: PLC0415
            EMIT_BLOCKING_CONFORMANCE_RULES as _BLOCK)
    except Exception:
        return []
    import json as _json                                    # noqa: PLC0415
    import subprocess as _sp                                # noqa: PLC0415
    import tempfile as _tf                                  # noqa: PLC0415
    with _tf.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "TopModule.sv").write_text(rtl)
        spec = tdp / "spec.txt"
        spec.write_text(prompt_text)
        outj = tdp / "conf.json"
        try:
            _sp.run([sys.executable, str(_HERE / "spec_conformance_check.py"),
                     "--rtl-dir", str(tdp), "--spec", str(spec),
                     "--top", "TopModule", "--json", str(outj)],
                    capture_output=True, text=True, timeout=timeout)
            if not outj.is_file():
                return []
            # The checker writes a LIST of finding dicts. (Read off the working
            # implementation rather than guessed — the guessed shape,
            # `data.get("findings")`, raised AttributeError on the first call.)
            findings = _json.loads(outj.read_text(errors="replace"))
        except Exception:
            return []
    return sorted({f.get("rule") for f in findings
                   if isinstance(f, dict) and f.get("rule") in _BLOCK})


def which_emitters() -> List[str]:
    """The chain, in order. For tests that pin the order rather than assume it."""
    return [n for n, _ in EMITTERS]


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Run the deterministic emit chain on a prompt.")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--ifc-file", default=None)
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    prompt = Path(a.prompt_file).read_text(errors="replace")
    ifc = Path(a.ifc_file).read_text(errors="replace") if a.ifc_file else ""
    kind, rtl = try_emit(prompt, ifc, a.top)
    if not rtl:
        print("no deterministic emitter fired — this is a WAIVE to the AI backup")
        return 1
    print(f"fired: {kind}")
    if a.out:
        import _atomic_artefact as _atomic  # noqa: PLC0415
        _atomic.write_text(Path(a.out), rtl)
        print(f"wrote {a.out}")
    else:
        print(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
