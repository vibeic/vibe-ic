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

Scans: phase3/analog/**/*.{sp,cir,spice,spi,net}, and the flow-declared
phase2/analog/ alternative (A4's own `required_outputs` accepts either).

MEASURED DEFECTS REPAIRED 2026-08-03 (vibe-ic#693 analog-corner family).
This lint had never run outside its own unit test. Exercised against
fixtures before wiring, its FAIL branch — the whole point of the lint —
was silenced by three different accidents:

  * ONE ORDINARY ENGLISH WORD. `_DISCLOSURE_TOKENS` carried bare
    `modeled` / `modelled`, so a deck with a silent LEVEL=1 model plus
    the comment `* channel-length modulation is modeled with LAMBDA`
    went rc 1 → rc 0. Repaired: only the PHRASE forms remain; the bare
    words are gone.
  * ANY sibling `corner_results.json` whose raw text happened to contain
    `modelled` anywhere (`{"notes": "resistance modelled at 27C"}`)
    silenced the deck beside it. Repaired: the sibling disclosure is now
    read from the STRUCTURED `model_disclosure` field (top-level or
    per-corner), not from a substring scan of the whole document.
  * A DENIED WAIVER SILENCED IT PROJECT-WIDE. `_project_waiver`
    substring-matched the raw text of `waivers.json` and never read a
    waiver's own status, so `{"topic": "level1", "status": "DENIED"}` —
    a waiver a reviewer REFUSED — downgraded every finding in the
    project to advisory. Repaired: waivers are parsed, and only a waiver
    whose own status is approved/accepted/granted counts.

Together these meant any project could silence this lint permanently
with one token in a file it writes itself. A blocking gate that any
subject can switch off is a check that lies.

Detection (chip-AGNOSTIC — structural SPICE tokens, no chip/SKU literal):
  * an inline `.model <name> [np]mos ( ... LEVEL=1 ... )` card (continuation
    lines folded), OR a bare `level = 1` MOSFET model card, OR a model whose
    name/comment marks it `ideal`.

Disclosure phrases (any => downgrade to WARNING): `standin` / `stand-in` /
`modeled, not silicon` / `not silicon sign-off` / `no public ngspice` /
`documented level=1`, or an APPROVED waivers.json entry mentioning
`corner_lib` / `level1` / `ideal_model`.

Verdict:
  PASS — no LEVEL=1 / ideal model card in any analog deck.
  PASS-with-WARN — LEVEL=1 / ideal present but DISCLOSED (advisory, exit 0).
  FAIL — LEVEL=1 / ideal present with NO disclosure (silent substitution).
  SKIP — no analog decks → exit 2 (VACUOUS), never a plain PASS.

Exit codes: 0 = PASS / PASS-with-WARN, 1 = FAIL, 2 = VACUOUS (nothing was
read) / IO error.

#521 TIER: SKIP used to print `[SKIP]` and exit 0. `flow_compliance_check`
matches only a line-start `VACUOUS_PASS`, so an analog-declared project with
zero decks — or one laid out under `phase2/analog/` while this lint looked
only under `phase3/analog/` — was credited a PLAIN PASS by a lint that read
nothing. That is #521's exact defect. SKIP now routes through
`_vacuous_exit` (rc 2) like its A-track siblings.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import _path_layout as _pl
import _vacuous_exit as _vx

GATE = "analog_corner_lib_realism_lint"

# A4's own `required_outputs` accepts `phase3/analog/*/corner_results.json OR
# phase2/analog/*/corner_results.json`, and `migrate_to_layout_p.py` moves
# A2-A4 artefacts to `phase2/analog/`. Reading only the canonical root made a
# byte-identical project self-skip and measure nothing — measured: the same
# silent-substitution tree is rc 1 under phase3 and rc 0 SKIP under phase2.
_ANALOG_ROOTS = ("phase3/analog", "phase2/analog")

_DECK_EXTS = (".sp", ".cir", ".spice", ".spi", ".net")

# A .model card, with continuation lines (`+`) folded, that declares a MOSFET
# built-in analytic model at LEVEL=1 (the ideal/first-order MOS1 model).
_MODEL_CARD_RE = re.compile(
    r"^\s*\.model\s+(?P<name>\S+)\s+(?P<kind>[np]mos)\b(?P<body>.*)$",
    re.IGNORECASE,
)
_LEVEL1_RE = re.compile(r"\blevel\s*=?\s*1\b", re.IGNORECASE)
_IDEAL_RE = re.compile(r"\bideal\b", re.IGNORECASE)

# PHRASES ONLY. Bare `modeled` / `modelled` used to live here; measured, the
# ordinary deck comment `* channel-length modulation is modeled with LAMBDA`
# downgraded a silent LEVEL=1 substitution from FAIL to WARN. A disclosure has
# to say what it is disclosing.
_DISCLOSURE_TOKENS = (
    "standin", "stand-in", "modeled, not silicon", "modelled, not silicon",
    "not silicon sign-off", "no public ngspice", "documented level=1",
    "documented level 1", "level=1 standin",
)
_WAIVER_TOKENS = ("corner_lib", "corner-lib", "level1", "level_1",
                  "ideal_model", "ideal-model", "standin_model")
# A waiver only counts when someone APPROVED it. Measured: a waiver whose own
# `status` was "DENIED" silenced this lint project-wide, because the old code
# substring-matched the raw file and never read the status.
_WAIVER_APPROVED = ("approved", "accepted", "granted", "waived", "active")


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
    """A sibling corner_results.json that discloses a standin in its OWN
    `model_disclosure` field (top-level or per-corner).

    Reads the STRUCTURED field, not the raw document. A substring scan of the
    whole JSON meant any unrelated prose that happened to contain a token
    silenced the deck beside it — measured with
    `{"notes": "resistance modelled at 27C"}`.
    """
    cr = block_dir / "corner_results.json"
    if not cr.is_file():
        return False
    try:
        data = json.loads(cr.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    fields = [data.get("model_disclosure")]
    corners = data.get("corners")
    if isinstance(corners, list):
        fields.extend(c.get("model_disclosure") for c in corners
                      if isinstance(c, dict))
    return any(isinstance(f, str) and _text_discloses(f) for f in fields)


def _waiver_is_approved(entry: dict) -> bool:
    """A waiver counts only when its OWN status says someone approved it.
    A waiver with no status field at all is treated as approved, so the
    pre-existing shape (a bare list of topics) keeps working."""
    for key in ("status", "state", "decision", "verdict"):
        v = entry.get(key)
        if isinstance(v, str):
            return v.strip().lower() in _WAIVER_APPROVED
    return True


def _project_waiver(project: Path) -> bool:
    """True iff waivers.json carries an APPROVED waiver naming this topic."""
    wpath = project / "waivers.json"
    if not wpath.is_file():
        return False
    try:
        raw = wpath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Unparsable waivers file cannot establish an approval.
        return False

    entries: List[dict] = []
    if isinstance(data, dict):
        for key in ("waivers", "entries", "items"):
            v = data.get(key)
            if isinstance(v, list):
                entries.extend(e for e in v if isinstance(e, dict))
        if not entries:
            entries = [data]
    elif isinstance(data, list):
        entries = [e for e in data if isinstance(e, dict)]

    for entry in entries:
        text = json.dumps(entry, ensure_ascii=False).lower()
        if any(tok in text for tok in _WAIVER_TOKENS) \
                and _waiver_is_approved(entry):
            return True
    return False


def _analog_roots(project: Path) -> List[Path]:
    """Every analog root this project may legitimately use. The canonical
    runner dir first, then the flow-declared phase2 alternative."""
    roots = [project / r for r in _ANALOG_ROOTS]
    canonical = _pl.analog_dir(project)
    if canonical not in roots:
        roots.insert(0, canonical)
    return [r for r in roots if r.is_dir()]


def run_audit(project: Path) -> dict:
    roots = _analog_roots(project)
    if not roots:
        return {"gate": GATE, "verdict": "SKIP",
                "reason": "no_analog_dir", "findings": []}

    decks: List[Path] = []
    for root in roots:
        decks.extend(p for p in root.rglob("*")
                     if p.is_file() and p.suffix.lower() in _DECK_EXTS)
    decks = sorted(set(decks))
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
    skipped = verdict == "SKIP"
    reason = report.get("reason") or "no_analog_decks"

    if skipped:
        # #521 — a lint that read nothing must not be credited a plain PASS.
        # `_vacuous_exit` prints the line-start sentinel the flow auditor
        # matches, and returns rc 2 (VACUOUS_PASS tier).
        print(_vx.verdict_line(GATE, True, True, reason))
        _vx.announce_vacuous(GATE, reason)
        return _vx.exit_code(True, True)

    print(f"[{verdict}] {GATE}")
    for f in report["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
