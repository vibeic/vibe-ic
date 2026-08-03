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

It is honest about the legitimate case. Some real foundries (an open PDK with
no public ngspice corner library, for instance) require a DOCUMENTED LEVEL=1
STANDIN — the deck itself discloses this and the result is reported as
MODELED, not silicon sign-off. When such a disclosure is present (in the deck
text, a sibling `corner_results.json` disclosure FIELD, or a LIVE project
waiver), the finding is downgraded to an advisory WARNING (non-failing). A
LEVEL=1 / ideal model used with NO disclosure is a hard FAIL — that is the
silent substitution this lint exists to catch.

Scans: `phase3/analog/**` AND `phase2/analog/**` for `*.{sp,cir,spice,spi,net}`

Detection (chip-AGNOSTIC — structural SPICE tokens, no chip/SKU literal):
  * an inline `.model <name> [np]mos ( ... LEVEL=1 ... )` card (continuation
    lines folded), OR a bare `level = 1` MOSFET model card, OR a model whose
    name/comment marks it `ideal`.

Verdict:
  PASS    — no LEVEL=1 / ideal model card in any analog deck.
  WARN    — LEVEL=1 / ideal present but DISCLOSED (advisory, exit 0).
  FAIL    — LEVEL=1 / ideal present with NO disclosure (silent substitution).
  VACUOUS — no analog decks anywhere. rc 2, NOT a pass over the design.

Exit codes: 0 = PASS / WARN, 1 = FAIL, 2 = VACUOUS (nothing examined) or
IO error.

FOUR MEASURED DEFECTS THIS FILE REPAIRS
---------------------------------------
Nothing but this lint's own unit test had ever run it, so every widening in
its disclosure path was untested against a tree that tried to abuse it. Ten
synthetic trees, five wrong answers:

  1. ONE ORDINARY ENGLISH WORD DISARMED THE FAIL BRANCH. `_DISCLOSURE_TOKENS`
     carried the bare words `modeled` / `modelled`. Measured: a deck with a
     SILENT LEVEL=1 substitution plus the unremarkable comment
     `* channel-length modulation is modeled with LAMBDA below` went from
     rc 1 FAIL to rc 0 WARN. Nothing in that comment discloses anything. The
     phrase forms (`modeled, not silicon`, `documented level=1`, `standin`)
     already carry the intent, so the bare words are gone.

  2. THE SIBLING-JSON CHANNEL READ THE WHOLE FILE. `_sibling_disclosure`
     ran the token scan over the raw text of `corner_results.json`, so any
     unrelated occurrence of a disclosure word anywhere in that artefact
     downgraded the finding. It now reads the DISCLOSURE FIELDS by name.

  3. A DENIED WAIVER SILENCED THE GATE. `_project_waiver` substring-matched
     the raw text of `waivers.json` and never looked at a waiver's STATUS,
     so a waiver request that had been explicitly DENIED — the record of a
     refusal — disabled the check project-wide. A gate any project can
     switch off with one token in a rejected waiver is a check that lies.

  4. `SKIP` EXITED 0, AND A PROJECT WITH DECKS COULD HIT IT. It printed
     `[SKIP]` and returned 0, which `flow_compliance_check` credits in the
     plain PASS tier — vibe-ic#521's exact defect. Worse than the empty
     case: it read ONLY `phase3/analog/`, while A4's own `required_outputs`
     accepts `phase2/analog/*/corner_results.json` as an alternative, so a
     project laid out under `phase2/analog/` had its decks read by nobody
     and was credited a plain PASS. Both halves are fixed: the scan covers
     both analog roots, and a genuinely empty scan routes through
     `_vacuous_exit` to rc 2.
"""
from __future__ import annotations

import argparse
import json
import sys
import re
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

import _path_layout as _pl
import _vacuous_exit as _vx

GATE = "analog_corner_lib_realism_lint"

_DECK_EXTS = (".sp", ".cir", ".spice", ".spi", ".net")

# A4's own `required_outputs` accepts either root, so a lint that judges A4's
# inputs must read either root. Ordered canonical-first.
_ANALOG_ROOTS = ("phase3/analog", "phase2/analog")

# A .model card, with continuation lines (`+`) folded, that declares a MOSFET
# built-in analytic model at LEVEL=1 (the ideal/first-order MOS1 model).
_MODEL_CARD_RE = re.compile(
    r"^\s*\.model\s+(?P<name>\S+)\s+(?P<kind>[np]mos)\b(?P<body>.*)$",
    re.IGNORECASE,
)
_LEVEL1_RE = re.compile(r"\blevel\s*=?\s*1\b", re.IGNORECASE)
_IDEAL_RE = re.compile(r"\bideal\b", re.IGNORECASE)

# PHRASES, never bare words — see defect 1. Each of these says the thing a
# disclosure has to say: that the model is a stand-in and the numbers are not
# silicon sign-off.
_DISCLOSURE_TOKENS = (
    "standin", "stand-in", "stand in",
    "modeled, not silicon", "modelled, not silicon",
    "not silicon sign-off", "not silicon signoff",
    "no public ngspice", "no public spice",
    "documented level=1", "documented level 1", "level=1 standin",
    "level=1 stand-in", "level 1 standin",
)
_WAIVER_TOKENS = ("corner_lib", "corner-lib", "level1", "level_1",
                  "ideal_model", "ideal-model", "standin_model")

# A waiver in one of these states is a record of a REFUSAL (or of a waiver
# that has lapsed). It must not silence anything — defect 3.
_DEAD_WAIVER_STATES = frozenset((
    "denied", "rejected", "refused", "withdrawn", "revoked", "expired",
    "closed", "superseded", "void", "invalid", "proposed", "requested",
    "pending",
))

# Keys whose VALUE is a disclosure. Reading the whole artefact instead was
# defect 2.
_DISCLOSURE_KEYS = ("model_disclosure", "corner_lib_disclosure",
                    "model_standin_disclosure", "device_model_disclosure",
                    "disclosure", "model_note", "model_provenance")


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


def _disclosure_values(node: Any, keys: Iterable[str]) -> List[str]:
    """Every value reached THROUGH one of `keys`, rendered as text.

    Walks the whole document looking for the KEY, then takes that key's
    whole subtree — a disclosure recorded per-corner
    (`corners[].model_disclosure`) or as a nested object is still a
    disclosure. What it never does is read a value the document did not
    file under a disclosure key.
    """
    wanted = {k.lower() for k in keys}
    out: List[str] = []
    stack: List[Any] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(k, str) and k.lower() in wanted:
                    out.append(v if isinstance(v, str)
                               else json.dumps(v, ensure_ascii=False))
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return out


def _sibling_disclosure(block_dir: Path) -> bool:
    """A sibling `corner_results.json` whose DISCLOSURE FIELD honestly
    discloses a standin.

    Reads the fields by name (defect 2). Scanning the whole artefact meant
    any incidental occurrence of a disclosure word anywhere in it — in a
    block note, a spec label, a warning string — downgraded a silent
    substitution to an advisory.
    """
    cr = block_dir / "corner_results.json"
    if not cr.is_file():
        return False
    try:
        data = json.loads(cr.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return False
    return any(_text_discloses(s)
               for s in _disclosure_values(data, _DISCLOSURE_KEYS))


def _waiver_is_live(entry: Any) -> bool:
    """A waiver silences nothing unless it is actually in force (defect 3)."""
    if not isinstance(entry, dict):
        return False
    for key in ("status", "state", "decision", "disposition", "verdict"):
        v = entry.get(key)
        if isinstance(v, str) and v.strip().lower() in _DEAD_WAIVER_STATES:
            return False
    for key in ("approved", "active", "granted"):
        if entry.get(key) is False:
            return False
    return True


def _waiver_entries(data: Any) -> List[Any]:
    if isinstance(data, list):
        return list(data)
    if isinstance(data, dict):
        for key in ("waivers", "entries", "items", "records"):
            v = data.get(key)
            if isinstance(v, list):
                return list(v)
        if isinstance(data.get("waivers"), dict):
            return list(data["waivers"].values())
        return [data]
    return []


def _project_waiver(project: Path) -> bool:
    wpath = project / "waivers.json"
    if not wpath.is_file():
        return False
    try:
        data = json.loads(wpath.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return False
    for entry in _waiver_entries(data):
        if not _waiver_is_live(entry):
            continue
        blob = json.dumps(entry, ensure_ascii=False).lower()
        if any(tok in blob for tok in _WAIVER_TOKENS):
            return True
    return False


def _analog_roots(project: Path) -> List[Path]:
    """Every analog root that exists. `_pl.analog_dir` first so the canonical
    layout is unchanged; `phase2/analog` because A4 accepts it (defect 4)."""
    roots: List[Path] = []
    canon = _pl.analog_dir(project)
    if canon.is_dir():
        roots.append(canon)
    for rel in _ANALOG_ROOTS:
        d = project / rel
        if d.is_dir() and d not in roots:
            roots.append(d)
    return roots


def run_audit(project: Path) -> dict:
    roots = _analog_roots(project)
    if not roots:
        return {"gate": GATE, "verdict": "SKIP", "reason": "no_analog_dir",
                "decks_scanned": 0, "roots_scanned": [], "findings": []}

    decks: List[Path] = []
    for root in roots:
        decks.extend(p for p in root.rglob("*")
                     if p.is_file() and p.suffix.lower() in _DECK_EXTS)
    decks = sorted(set(decks))
    rel_roots = [str(r.relative_to(project)) for r in roots]
    if not decks:
        return {"gate": GATE, "verdict": "SKIP", "reason": "no_analog_decks",
                "decks_scanned": 0, "roots_scanned": rel_roots, "findings": []}

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
        "roots_scanned": rel_roots,
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
    # #521 — a scan that read NO deck examined nothing, and rc 0 would have it
    # credited in the plain PASS tier beside a project whose every deck was
    # read and cleared. Routed from the gate's OWN verdict word, never text.
    skipped = verdict == "SKIP"
    passed = verdict != "FAIL"
    reason = report.get("reason") or "unspecified"

    print(_vx.verdict_line(GATE, passed, skipped, reason,
                           pass_token=("WARN" if verdict == "WARN"
                                       else "PASS")))
    for f in report["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    if passed and skipped:
        _vx.announce_vacuous(GATE, reason)
    return _vx.exit_code(passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
