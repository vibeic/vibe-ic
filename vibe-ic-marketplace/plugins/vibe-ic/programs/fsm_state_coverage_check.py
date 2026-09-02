#!/usr/bin/env python3
"""fsm_state_coverage_check.py — v0.119.45 (Wave 13) gate.

Closes a real-world bug class surfaced by the v0.119.44 <benchmark> fresh-
agent benchmark (18th attempt). One root-cause hypothesis: the FSM
ships with fewer states than L9 / L11 specs name, so behavioural
sequences that traverse `RX_VALIDATE → DISPATCH → SEND_TEST_REPLY`
collapse onto a default arm and the chip emits all-padding bytes.

This gate enforces that EVERY FSM state name listed in L9.json
(``integration_spec.fsm_states`` / ``state_machine.states``) or L11
(``behavioral_sequences[].state_sequence``) appears as a
``localparam`` / ``parameter`` / SystemVerilog ``enum`` value in the
RTL FSM.

CHIP-AGNOSTIC. Pure synonym-list + identifier-presence detection. No
specific state name / chip / pin / opcode hard-coded.

Detection algorithm
-------------------
1. Collect state names from L9 + L11. Synonym keys (lower-case):
       ``fsm_states`` / ``state_machine.states`` / ``states`` /
       ``state_list`` / ``behavioral_sequences[].state`` /
       ``behavioral_sequences[].state_sequence[]``
   Walk the JSON recursively for any of these keys; any list of
   strings under one of those keys is treated as state names.
2. Normalise: strip prefixes ``S_``, ``ST_``, ``STATE_``; lowercase
   the result.
3. Find FSM RTL files (same heuristic as opcode dispatch gate). For
   each file, extract:
       - ``localparam <NAME>`` / ``parameter <NAME>`` lines whose
         identifier matches UPPER_SNAKE_CASE (state-like)
       - SystemVerilog ``typedef enum {...}`` value list
4. Apply the same prefix stripping + lowercasing.
5. FAIL when any L9/L11 state name has no matching RTL state.
6. WARN when RTL declares strictly more states than the docs (over-
   implementation; might mask incorrect ratio).
7. SKIP when L9 + L11 combined yield no state names.
8. Honors waiver ``fsm_state_intentionally_collapsed`` (≥40 chars)
   per state.

Usage
-----
    python3 fsm_state_coverage_check.py <project_dir>
        [--json <out>]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER / WARN-only
    1 — FAIL
    2 — input-missing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional
import _path_layout as _pl


WAIVER_KEY = "fsm_state_intentionally_collapsed"
WAIVER_MIN = 40

STATE_KEY_SYNONYMS = {
    "fsm_states", "states", "state_list",
    "state_sequence", "state_machine_states",
}
PREFIX_STRIP = ("STATE_", "ST_", "S_")

FSM_FILENAME_PATTERNS = (
    re.compile(r"main_fsm", re.IGNORECASE),
    re.compile(r"top_fsm", re.IGNORECASE),
    re.compile(r"ctrl.*fsm", re.IGNORECASE),
    re.compile(r"cmd.*fsm", re.IGNORECASE),
    re.compile(r"dispatch", re.IGNORECASE),
    re.compile(r"protocol.*fsm", re.IGNORECASE),
)


def waived(project: Path) -> tuple[bool, str]:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
        text = d.get(WAIVER_KEY)
        if isinstance(text, str) and len(text.strip()) >= WAIVER_MIN:
            return True, text.strip()
    except Exception:
        pass
    return False, ""


def _normalise(name: str) -> str:
    s = name.strip()
    upper = s.upper()
    for pfx in PREFIX_STRIP:
        if upper.startswith(pfx):
            upper = upper[len(pfx):]
            break
    return upper.lower()


def _walk_for_state_lists(node, into: list[str], in_state_key: bool = False):
    """Recursively walk JSON; collect strings whose owning key is in
    STATE_KEY_SYNONYMS, OR strings inside ``state_machine.states`` /
    ``behavioral_sequences[*].state`` patterns."""
    if isinstance(node, dict):
        # Special-case: state_machine.states
        sm = node.get("state_machine")
        if isinstance(sm, dict):
            states = sm.get("states")
            if isinstance(states, list):
                for s in states:
                    if isinstance(s, str):
                        into.append(s)
                    elif isinstance(s, dict):
                        for k in ("name", "id", "state"):
                            if isinstance(s.get(k), str):
                                into.append(s[k])
                                break
        # Behavioural sequences
        bs = node.get("behavioral_sequences")
        if isinstance(bs, list):
            for item in bs:
                if isinstance(item, dict):
                    if isinstance(item.get("state"), str):
                        into.append(item["state"])
                    seq = item.get("state_sequence")
                    if isinstance(seq, list):
                        for s in seq:
                            if isinstance(s, str):
                                into.append(s)
        for k, v in node.items():
            klower = k.lower()
            child_in_state = klower in STATE_KEY_SYNONYMS
            if child_in_state and isinstance(v, list):
                for s in v:
                    if isinstance(s, str):
                        into.append(s)
                    elif isinstance(s, dict):
                        for kk in ("name", "id", "state"):
                            if isinstance(s.get(kk), str):
                                into.append(s[kk])
                                break
            else:
                _walk_for_state_lists(v, into, child_in_state)
    elif isinstance(node, list):
        for item in node:
            _walk_for_state_lists(item, into, in_state_key)


def _collect_doc_states(project: Path) -> list[str]:
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        return []
    raw: list[str] = []
    for pat in ("L9*.json", "L11*.json"):
        for f in sorted(gd.glob(pat)):
            try:
                data = json.loads(f.read_text())
            except Exception:
                continue
            _walk_for_state_lists(data, raw)
    # Dedupe; preserve insertion order
    seen: set[str] = set()
    out: list[str] = []
    for s in raw:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _find_fsm_files(project: Path) -> list[Path]:
    out: list[Path] = []
    rtl_root = _pl.rtl_dir(project)
    candidates: list[Path] = []
    if rtl_root.is_dir():
        candidates.extend(rtl_root.rglob("*.v"))
        candidates.extend(rtl_root.rglob("*.sv"))
    else:
        candidates.extend(project.rglob("*.v"))
        candidates.extend(project.rglob("*.sv"))

    # v1.15.67 — the eligible set is decided by the SHARED structural rule
    # as well as by the name convention below, because the DOCUMENT side of
    # this comparison is now produced by that rule.
    #
    # MEASURED on opentitan_aes (2026-09-02, plugin v1.15.66): of a 130-file
    # staged tree declaring FIVE credited state machines, the convention
    # clauses selected exactly ONE file. `prim_sync_reqack.sv` declares
    #     typedef enum logic { EVEN, ODD } sync_reqack_fsm_e;
    # and binds it to `src_fsm_cs` / `dst_fsm_ns` — a state machine by the
    # rule, and invisible to a selector that requires the identifier prefix
    # `S_` / `ST_` / `STATE_` to appear somewhere in the file. Phase 1's L6/L9
    # producer reads the tree with `_rtl_fsm_extract`, so EVEN and ODD reached
    # the documents; this gate then reported them as states "the RTL lacks"
    # while they sat in the RTL it had declined to read. Two readers of one
    # artefact, two answers — the shape `_rtl_fsm_extract` exists to end.
    #
    # ADDITIVE: every file the convention used to select is still selected, so
    # the missing-state set can only shrink and the orphan-in-RTL set can only
    # grow. A design whose FSM files carry the convention is byte-unchanged.
    eligible: list[Path] = []
    texts: dict[Path, str] = {}
    for f in candidates:
        if not f.is_file():
            continue
        parts = set(p.lower() for p in f.parts)
        if {"build", "sim", "synth", "formal", "pnr", "gds",
            "output_files", "incremental_db", "db"} & parts:
            continue
        eligible.append(f)

    structural: set[Path] = set()
    try:
        import _rtl_fsm_extract as _rtlfsm
        for f in eligible:
            try:
                texts[f] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        # Eligibility is decided over the WHOLE map: the package/module split
        # every real design uses declares the type in one file and binds it in
        # another, and only the whole map can see both.
        by_key = {str(f): t for f, t in texts.items()}
        for mach in _rtlfsm.declared_state_machines(by_key):
            src = mach.get("source_file")
            if isinstance(src, str) and src:
                structural.add(Path(src))
    except Exception:   # noqa: BLE001 — the convention clauses still decide
        structural = set()

    seen: set[Path] = set()
    for f in eligible:
        if f in seen:
            continue
        if f in structural:
            out.append(f)
            seen.add(f)
            continue
        name = f.name.lower()
        if any(p.search(name) for p in FSM_FILENAME_PATTERNS):
            out.append(f)
            seen.add(f)
            continue
        text = texts.get(f)
        if text is None:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        if "typedef enum" in text and (
            re.search(r"\bS_\w+", text) or
            re.search(r"\bST_\w+", text) or
            re.search(r"\bSTATE_\w+", text)
        ):
            out.append(f)
            seen.add(f)
    return out


# Match localparam / parameter STATE_NAME = ...
_LOCALPARAM_RE = re.compile(
    r"\b(?:localparam|parameter)\b[^;]*?\b([A-Z][A-Z0-9_]{2,})\b\s*=",
)
# Match enum body: typedef enum [type] { A, B, C } name;
_ENUM_RE = re.compile(
    r"typedef\s+enum\b[^{]*\{([^}]+)\}",
    re.DOTALL,
)
_ENUM_NAME_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")


def _collect_rtl_states(files: list[Path]) -> set[str]:
    """Return the set of normalised state names declared in any FSM RTL
    file. Includes both localparam-style and SV typedef-enum styles."""
    found: set[str] = set()
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ident in _LOCALPARAM_RE.findall(text):
            if any(ident.startswith(pfx) for pfx in PREFIX_STRIP) or \
                    "STATE" in ident:
                found.add(_normalise(ident))
        for body in _ENUM_RE.findall(text):
            for ident in _ENUM_NAME_RE.findall(body):
                found.add(_normalise(ident))
    return found


def _collect_rtl_states_with_origin(files: list[Path]
                                    ) -> dict[str, tuple[str, str]]:
    """v1.6.94 (issue #25 Bug 4) — like ``_collect_rtl_states`` but also
    return, for each normalised state name, the original RTL identifier
    and the basename of the file it was declared in. Used to populate
    the ``[orphan_state_in_rtl]`` marker.
    Returns: {normalised_name: (original_ident, filename)}.
    """
    found: dict[str, tuple[str, str]] = {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ident in _LOCALPARAM_RE.findall(text):
            if any(ident.startswith(pfx) for pfx in PREFIX_STRIP) or \
                    "STATE" in ident:
                norm = _normalise(ident)
                found.setdefault(norm, (ident, f.name))
        for body in _ENUM_RE.findall(text):
            for ident in _ENUM_NAME_RE.findall(body):
                norm = _normalise(ident)
                found.setdefault(norm, (ident, f.name))
    return found


def check(project: Path) -> dict:
    findings: list[dict] = []
    warnings: list[dict] = []
    info: dict = {}

    doc_states_raw = _collect_doc_states(project)
    info["doc_states_raw"] = doc_states_raw

    if not doc_states_raw:
        return {
            "program": "fsm_state_coverage_check",
            "skip_reason": (
                "L9/L11 generated_docs lack any fsm_states / "
                "state_machine.states / behavioral_sequences "
                "state_sequence list — different gate covers extraction"
            ),
            "pass": True,
            "findings": [],
            "warnings": [],
            **info,
        }

    fsm_files = _find_fsm_files(project)
    info["fsm_files"] = [str(f.relative_to(project)) for f in fsm_files]
    if not fsm_files:
        return {
            "program": "fsm_state_coverage_check",
            "skip_reason": (
                "no FSM-like RTL file found (rtl/*main_fsm*, *top_fsm*, "
                "*ctrl*fsm*, or typedef enum with S_*/ST_*/STATE_*)"
            ),
            "pass": True,
            "findings": [],
            "warnings": [],
            **info,
        }

    rtl_state_origin = _collect_rtl_states_with_origin(fsm_files)
    rtl_states = set(rtl_state_origin.keys())
    info["rtl_state_count"] = len(rtl_states)
    info["rtl_states"] = sorted(rtl_states)

    # Honour per-state waiver: list of state names that are intentionally
    # collapsed. Single waiver text covers all listed states.
    is_waived, waiver_text = waived(project)

    # Forward direction: states named in L9/L11 but missing from RTL.
    missing: list[str] = []          # orphan_state_in_l11 (legacy field)
    for s_raw in doc_states_raw:
        norm = _normalise(s_raw)
        if not norm:
            continue
        if norm in rtl_states:
            continue
        # Permit substring fallback (e.g., doc says "RX_VALIDATE" and RTL has
        # "RX_VALIDATE_CRC" — that's a closer state, treat as match)
        if any(norm in r or r in norm for r in rtl_states):
            continue
        missing.append(s_raw)

    # v1.6.94 (issue #25 Bug 4) — reverse direction: states declared in
    # RTL FSM but not catalogued in L11 / L9. Same substring-fallback so
    # impl-detail substates of a documented state don't trip this.
    doc_state_norms = {_normalise(s) for s in doc_states_raw if _normalise(s)}
    orphan_in_rtl: list[tuple[str, str]] = []  # (original_ident, filename)
    for norm, (orig, fname) in sorted(rtl_state_origin.items()):
        if norm in doc_state_norms:
            continue
        if any(norm in d or d in norm for d in doc_state_norms):
            continue
        orphan_in_rtl.append((orig, fname))

    info["missing_states"] = missing
    info["orphan_state_in_rtl"] = [
        {"state": orig, "file": fname} for orig, fname in orphan_in_rtl
    ]
    info["doc_state_count"] = len(doc_state_norms)

    if missing:
        # v1.6.94 (issue #25 Bug 4): emit per-state ``[orphan_state_in_l11]``
        # markers naming the state + the L11 catalogue field, so the field
        # agent knows the L11 emitter (not the RTL template) needs the fix.
        markers = "\n".join(
            f"[orphan_state_in_l11] {s} appears in "
            f"L11.fsm_state_catalogue but main_fsm.sv has no transition to it"
            for s in missing
        )
        findings.append({
            "rule": "FSM_STATE_COVERAGE_MISSING",
            "severity": "FAIL",
            "message": (
                f"L9/L11 docs name {info['doc_state_count']} FSM "
                f"state(s) but RTL FSM(s) lack matches for "
                f"{len(missing)}: [{', '.join(missing[:8])}"
                f"{'...' if len(missing) > 8 else ''}]. "
                f"RTL declared {len(rtl_states)} states. Without the "
                f"missing state(s) in the FSM, behavioural sequences "
                f"that traverse them will collapse onto a default arm "
                f"and emit incorrect / no response.\n" + markers
            ),
        })

    if orphan_in_rtl:
        # v1.6.94 (issue #25 Bug 4): emit per-state ``[orphan_state_in_rtl]``
        # markers naming the state + the RTL filename, so the field agent
        # knows the RTL template (not the L11 emitter) needs the fix —
        # either remove the dead state from RTL, or add it to
        # L11.fsm_state_catalogue.
        #
        # Severity policy: WARN (not FAIL) — extra RTL states are a soft
        # over-implementation signal, not a coverage hole. The legacy
        # ``RTL_STATES_OVER_IMPLEMENTATION`` WARN is kept below for the
        # aggregate count; this WARN adds the per-state markers the
        # field agent needs to bisect.
        markers = "\n".join(
            f"[orphan_state_in_rtl] {orig} is declared in {fname} but not "
            f"in L11.fsm_state_catalogue"
            for orig, fname in orphan_in_rtl
        )
        warnings.append({
            "rule": "FSM_STATE_ORPHAN_IN_RTL",
            "severity": "WARN",
            "message": (
                f"RTL FSM(s) declare {len(orphan_in_rtl)} state(s) absent "
                f"from L11.fsm_state_catalogue: "
                f"[{', '.join(o for o, _ in orphan_in_rtl[:8])}"
                f"{'...' if len(orphan_in_rtl) > 8 else ''}]. Either "
                f"remove the unused state(s) from RTL, or extend the L11 "
                f"emitter to catalogue them.\n" + markers
            ),
        })

    # WARN: RTL has strictly more states than docs
    if len(rtl_states) > info["doc_state_count"] + 2:
        warnings.append({
            "rule": "RTL_STATES_OVER_IMPLEMENTATION",
            "severity": "WARN",
            "message": (
                f"RTL declares {len(rtl_states)} state(s) but L9/L11 "
                f"docs name {info['doc_state_count']} — possible over-"
                f"implementation (extra states could mask incorrect "
                f"behaviour or just be impl-detail substates)."
            ),
        })

    return {
        "program": "fsm_state_coverage_check",
        "pass": len(findings) == 0,
        "findings": findings,
        "warnings": warnings,
        **info,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}", file=sys.stderr)
        return 2

    result = check(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    if "skip_reason" in result:
        print(f"PASS_SKIP — {result['skip_reason']}")
        return 0

    if result["pass"]:
        if result.get("warnings"):
            print(
                f"PASS_WITH_WARN — FSM state coverage complete "
                f"({result.get('doc_state_count')} doc states / "
                f"{result.get('rtl_state_count')} rtl states); "
                f"{len(result['warnings'])} warning(s)"
            )
            for w in result["warnings"]:
                print(f"WARN: {w['rule']} — {w['message']}")
        else:
            print(
                f"PASS — FSM state coverage complete "
                f"({result.get('doc_state_count')} doc states all "
                f"present in RTL FSM)"
            )
        return 0

    is_waived, why = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(result['findings'])} state-"
            f"coverage finding(s); waiver `{WAIVER_KEY}` set: "
            f"{why[:80]}..."
        )
        for f in result["findings"]:
            print(f"  • {f['rule']} — {f['message'][:120]}")
        return 0

    print(f"FAIL — {len(result['findings'])} fsm-state-coverage violation(s)")
    for f in result["findings"]:
        print(f"FAIL: {f['rule']} — {f['message']}")
    for w in result.get("warnings", []):
        print(f"WARN: {w['rule']} — {w['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
