#!/usr/bin/env python3
"""analog_corner_lib_realism_lint.py — R15 stale-corner-lib doc-lint (A4).

An analog corner sweep is only as trustworthy as the device models it runs.
A deck that quietly stands in an IDEAL / analytic LEVEL=1 MOSFET model (or a
behavioural VCVS "transistor") in place of the foundry's real corner library
produces corner NUMBERS that do not reflect silicon — the classic way a PVT
sweep "passes" on a process that was never actually modelled. This lint scans
the analog SPICE decks for inline LEVEL=1 / ideal device model cards and
flags them, so a corner sweep can't silently claim foundry closure on toy
models.

It is honest about the legitimate case. Some real foundries (e.g. an open
PDK with no public ngspice corner library) require a DOCUMENTED LEVEL=1
STANDIN — the deck itself discloses this and the result is reported as
MODELED, not silicon sign-off. When such a disclosure is present (in the deck
text, a sibling corner_results.json `model_disclosure`, or a project waiver),
the finding is downgraded to an advisory WARNING (non-failing). A LEVEL=1 /
ideal model used with NO disclosure is a hard FAIL — that is the silent
substitution this lint exists to catch.

Scans: phase3/analog/**/*.{sp,cir,spice,spi,net}

Detection (chip-AGNOSTIC — structural SPICE tokens, no chip/SKU literal):
  * an inline `.model <name> [np]mos ( ... LEVEL=1 ... )` card (continuation
    lines folded), OR a bare `level = 1` MOSFET model card, OR a model whose
    name/comment marks it `ideal`.

Disclosure tokens (any => downgrade to WARNING): `standin` / `stand-in` /
`modeled, not silicon` / `not silicon sign-off` / `no public ngspice` /
`documented level=1` / `modelled`, or a waivers.json entry mentioning
`corner_lib` / `level1` / `ideal_model`.

Verdict:
  PASS — no LEVEL=1 / ideal model card in any analog deck.
  PASS-with-WARN — LEVEL=1 / ideal present but DISCLOSED (advisory, exit 0).
  FAIL — LEVEL=1 / ideal present with NO disclosure (silent substitution).
  SKIP — no analog decks.

Exit codes: 0 = PASS / PASS-with-WARN / SKIP, 1 = FAIL, 2 = IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import _path_layout as _pl

GATE = "analog_corner_lib_realism_lint"

_DECK_EXTS = (".sp", ".cir", ".spice", ".spi", ".net")

# A .model card, with continuation lines (`+`) folded, that declares a MOSFET
# built-in analytic model at LEVEL=1 (the ideal/first-order MOS1 model).
_MODEL_CARD_RE = re.compile(
    r"^\s*\.model\s+(?P<name>\S+)\s+(?P<kind>[np]mos)\b(?P<body>.*)$",
    re.IGNORECASE,
)
_LEVEL1_RE = re.compile(r"\blevel\s*=?\s*1\b", re.IGNORECASE)
_IDEAL_RE = re.compile(r"\bideal\b", re.IGNORECASE)

_DISCLOSURE_TOKENS = (
    "standin", "stand-in", "modeled, not silicon", "modelled, not silicon",
    "not silicon sign-off", "no public ngspice", "documented level=1",
    "documented level 1", "level=1 standin", "modeled", "modelled",
)
_WAIVER_TOKENS = ("corner_lib", "corner-lib", "level1", "level_1",
                  "ideal_model", "ideal-model", "standin_model")


def _fold_continuations(text: str) -> List[Tuple[int, str]]:
    """Return [(line_no_of_card_start, folded_logical_line), ...] with SPICE
    `+` continuation lines merged onto the preceding logical line."""
    out: List[Tuple[int, str]] = []
    cur_no = 0
    cur = ""
    for i, raw in enumerate(text.splitlines(), start=1):
        if raw.lstrip().startswith("+"):
            cur += " " + raw.lstrip()[1:].strip()
            continue
        if cur:
            out.append((cur_no, cur))
        cur = raw
        cur_no = i
    if cur:
        out.append((cur_no, cur))
    return out


def _deck_has_ideal_model(text: str) -> List[Tuple[int, str, str]]:
    """Return [(line_no, model_name, reason), ...] for each LEVEL=1 / ideal
    MOSFET model card in `text`."""
    hits: List[Tuple[int, str, str]] = []
    for line_no, logical in _fold_continuations(text):
        m = _MODEL_CARD_RE.match(logical)
        if not m:
            continue
        body = m.group("body")
        name = m.group("name")
        if _LEVEL1_RE.search(body):
            hits.append((line_no, name, "LEVEL=1"))
        elif _IDEAL_RE.search(body) or _IDEAL_RE.search(name):
            hits.append((line_no, name, "ideal-model"))
    return hits


def _text_discloses(text: str) -> bool:
    low = text.lower()
    return any(tok in low for tok in _DISCLOSURE_TOKENS)


def _sibling_disclosure(block_dir: Path) -> bool:
    """A sibling corner_results.json `model_disclosure` (or top-level text)
    that honestly discloses a standin."""
    cr = block_dir / "corner_results.json"
    if not cr.is_file():
        return False
    try:
        raw = cr.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _text_discloses(raw)


def _project_waiver(project: Path) -> bool:
    wpath = project / "waivers.json"
    if not wpath.is_file():
        return False
    try:
        raw = wpath.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return any(tok in raw for tok in _WAIVER_TOKENS)


def run_audit(project: Path) -> dict:
    analog = _pl.analog_dir(project)
    if not analog.is_dir():
        return {"gate": GATE, "verdict": "SKIP",
                "reason": "no_analog_dir", "findings": []}

    decks = sorted(p for p in analog.rglob("*")
                   if p.is_file() and p.suffix.lower() in _DECK_EXTS)
    if not decks:
        return {"gate": GATE, "verdict": "SKIP",
                "reason": "no_analog_decks", "findings": []}

    waived = _project_waiver(project)
    findings: List[dict] = []
    any_fail = False
    any_warn = False

    for deck in decks:
        try:
            text = deck.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = _deck_has_ideal_model(text)
        if not hits:
            continue
        disclosed = (waived or _text_discloses(text)
                     or _sibling_disclosure(deck.parent))
        rel = str(deck.relative_to(project))
        for line_no, name, reason in hits:
            sev = "WARNING" if disclosed else "ERROR"
            findings.append({
                "file": rel,
                "line": line_no,
                "model": name,
                "reason": reason,
                "severity": sev,
                "rule": ("CORNER_LIB_STANDIN_DISCLOSED" if disclosed
                         else "CORNER_LIB_IDEAL_MODEL"),
                "message": (
                    f"{rel}:{line_no} model '{name}' is a {reason} device "
                    f"model" + (
                        " — DISCLOSED standin, advisory only "
                        "(MODELED, not silicon sign-off)" if disclosed else
                        " used with NO disclosure; corner numbers do not "
                        "reflect the foundry corner library. Use the real "
                        "foundry corner lib, or add a documented standin "
                        "disclosure / waiver."
                    )
                ),
            })
        if disclosed:
            any_warn = True
        else:
            any_fail = True

    verdict = "FAIL" if any_fail else ("WARN" if any_warn else "PASS")
    return {
        "gate": GATE,
        "verdict": verdict,
        "decks_scanned": len(decks),
        "findings": findings,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    report = run_audit(args.project_dir.resolve())

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2,
                                              ensure_ascii=False) + "\n")

    verdict = report["verdict"]
    print(f"[{verdict}] {GATE}")
    for f in report["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
