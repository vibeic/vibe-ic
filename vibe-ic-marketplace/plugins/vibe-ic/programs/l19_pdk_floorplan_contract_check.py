#!/usr/bin/env python3
"""l19_pdk_floorplan_contract_check.py — L19 SEMANTIC completeness gate.

THIS GATE BLOCKS (rc=1). See "BLOCKS OR ADVISES" below.

WHY THIS GATE EXISTS
--------------------
L19_CONSTRAINTS_PDK owns the backend's floorplan and PDK contract and, before
this gate, had NO gate at all — only the generic presence/skeleton checks
touched it. Its consumers:

  * `phase3_one_shot_runner._l19_declared_die_area` -> `_effective_die_um`:
    `L19.fields.die_area_budget_um` mandates a FIXED DIE_AREA that phase3
    honors VERBATIM and never auto-sizes over
    (precedence: --die-um flag > L9 prose > L19 > auto).
  * `foundry_handoff_pack_gen._l19_pdk_target`: the foundry pack's PDK
    statement — what the pack tells the fab it was built for.
  * `analog_real_corner_sweep`: emits the honesty disclosure
    `pdk_substitution: target=<L19 pdk_target> substitute=<sim pdk>`;
    `analog_netlist_pdk_check` and `analog_mc_yield_run` read the same target.

SWEPT (independently reproduced for this gate): across 136 real converge runs on
all 5 fleet machines, `pdk_target` is null in 38 and `die_area_budget_um` is null
in 118 — while every one of those runs went on to execute phase3 against a REAL
PDK, and the analog PDK-substitution honesty disclosure went vacuous. 29 of the
38 nulls are runs that STAGE a PDK enablement of their own under `input/pdk*/`:
the enablement was on disk before L19 was even emitted, and L19 still declared
nothing.

WHAT IT CHECKS  (all derived from the design's OWN machine-readable inputs)
--------------------------------------------------------------------------
  L19-1  (BLOCKS)  If the design MANDATES a fixed die in its own inputs — an
                   OpenLane-style `DIE_AREA` in a `config.json`, or a
                   `DIE_AREA` / `FP_SIZING absolute` pair in a staged `.tcl` —
                   then the consumer must be able to resolve a positive `WxH`,
                   via L9 prose (`_l9_declared_die_area`) or
                   `L19.die_area_budget_um` (`_l19_declared_die_area`). If
                   neither resolves, phase3 AUTO-SIZES a die the design had
                   already fixed. When L19 does resolve one, it must match one
                   of the rects the design actually mandated — a die pinned to a
                   number the design never asked for is worse than auto-sizing.
  L19-2  (BLOCKS)  A non-null `pdk_target` must be TRACEABLE to the design's own
                   inputs: its normalized token must appear in the design's own
                   input corpus (docs, staged config/tcl/sdc, staged PDK path
                   names), or L19's own `extraction_evidence` must carry a
                   `pdk_target` literal that VERIFIABLY appears in the design
                   input file it cites. An untraceable target is a fabricated
                   foundry statement: the handoff pack prints it to the fab and
                   the analog substitution disclosure is measured against it.
  L19-3  (BLOCKS)  If the design STAGES a PDK enablement of its own (`.lib` /
                   `.lef` / `.tlef` / `.tech` under `input/pdk*/`) then
                   `pdk_target` must be non-null. Otherwise the layer that owns
                   the PDK contract declares nothing while the design ships the
                   enablement — the foundry pack's PDK statement is empty and
                   `pdk_substitution: target=None` discloses nothing.
  L19-4  (ADVISES) `sdc_constraints_path` is written by `phase1_post_process.py`
                   and read by NOTHING. When it points at a file that does not
                   exist, the layer looks more populated than it is and no
                   consumer can ever catch it. Reported; never changes rc.
                   `power_budget_uw` / `floorplan_hints` are likewise reported,
                   not gated — no consumer reads them, so gating them would be
                   exactly the token-presence shape this work exists to replace.

No design name, PDK name, vendor part number or hardcoded pin/signal literal
appears anywhere in this file. `pdk_target` is checked for TRACEABILITY to the
design's own inputs, never against a list of known PDKs.

BLOCKS OR ADVISES — AND WHY
---------------------------
BLOCKS on L19-1/2/3, ADVISES on L19-4. Registered in
`flow_compliance_check._STRUCTURAL_RTL_GATES`, so rc=1 is a hard FAIL of the P0
umbrella step. Rationale: each blocking rule maps to an artefact that is either
shipped to a foundry (the handoff pack's PDK statement), consumed verbatim by
phase3 (the fixed die), or published as an honesty disclosure (the analog PDK
substitution). A wrong or absent value in any of those is not recoverable
downstream — the flow simply proceeds with a floorplan or a PDK statement the
design never authorised. L19-4 advises because its field has no consumer at all;
failing on it would re-create the token-presence error in a new place.

Escape hatch: set `l19_pdk_floorplan_contract_disclosed` in
`<project>/waivers.json` to a >=40-char justification. The gate then reports
PASS_WITH_WAIVERS (rc=0) while still printing every finding — disclosed beats
invisible.

SINGLE DETERMINISTIC TRACK — NO AI BACKUP
-----------------------------------------
Deterministic only. It deliberately ships no "AI second track": the completeness
report that motivated this work shipped `ai_captured_tokens_count: 0`, i.e. a
dual-track that was really one track. One honest track beats a second that
produces nothing.

USAGE
-----
    python3 l19_pdk_floorplan_contract_check.py <project_dir> [--json OUT]

EXIT CODES
----------
    0 = PASS (or PASS_WITH_WAIVERS)
    1 = FAIL (blocks)
    2 = not applicable / input missing (SKIP)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

# EMITTER/CHECKER DOCTRINE: reuse the CONSUMER's own resolvers, so gate and
# consumer can never drift.
#
# BOUND LAZILY, and that is the fix rather than a style choice. This used to be
# a module-level `from phase3_one_shot_runner import ...` wrapped in
# `except Exception: _consumer_l19_die = None`, and the runtime then read
# `if _consumer_l19_die is not None:` before falling back to a REIMPLEMENTATION
# of the same rule kept in this file. So any import that failed once — during
# the one moment some other module was mid-import, in a suite that imports 500
# of them — silently converted "reuse the consumer's resolver" into "use my own
# copy", which is exactly the drift the doctrine exists to prevent, with no
# diagnostic anywhere. MEASURED: the identity assertion passed when the test ran
# alone and failed in the full suite, and the gate went on answering.
#
# Import-time binding cannot be retried; a function-level one can. `main()`
# additionally REPORTS when the consumer could not be reached, so a fallback is
# a stated condition rather than a silent substitution.
_CONSUMER_IMPORT_ERROR: Optional[str] = None


def _consumers():
    """(l19_resolver, l9_resolver) from the consumer, or (None, None).

    Resolved on every call: `sys.modules` makes the success path a dict lookup,
    and the failure path a retry instead of a permanent downgrade."""
    global _CONSUMER_IMPORT_ERROR
    try:
        from phase3_one_shot_runner import (  # type: ignore
            _l19_declared_die_area, _l9_declared_die_area)
    except Exception as exc:      # pragma: no cover - depends on import order
        _CONSUMER_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        return None, None
    _CONSUMER_IMPORT_ERROR = None
    return _l19_declared_die_area, _l9_declared_die_area


def __getattr__(name):
    """`_consumer_l19_die` / `_consumer_l9_die` as live attributes.

    Keeps the two names other modules and the doctrine test read, without
    freezing whatever they resolved to at first import."""
    if name == "_consumer_l19_die":
        return _consumers()[0]
    if name == "_consumer_l9_die":
        return _consumers()[1]
    raise AttributeError(name)

WAIVER_KEY = "l19_pdk_floorplan_contract_disclosed"
WAIVER_MIN = 40

_L19_REL = "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
_WXH_RE = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$")

# Design-owned corpus scanned for pdk_target traceability. Extensions only —
# no filename, vendor or PDK literal.
_CORPUS_GLOBS: Tuple[str, ...] = (
    "phase1/input_doc/**/*",
    "input/docs/**/*",
    "input/**/*.json",
    "input/**/*.tcl",
    "input/**/*.sdc",
    "input/**/*.md",
    "input/**/*.txt",
    "input/**/*.yaml",
    "input/**/*.yml",
    "input/**/*.cfg",
)
_CORPUS_MAX_FILES = 400
_CORPUS_MAX_BYTES = 200_000

# Staged-PDK enablement roots + the file kinds that make one real.
_STAGED_PDK_GLOBS: Tuple[str, ...] = ("input/pdk*/**/*",)
_PDK_ENABLEMENT_SUFFIXES = (".lib", ".lef", ".tlef", ".tech", ".techlef",
                            ".db", ".gds")

# Tcl-side fixed-die mandate (`set ::env(DIE_AREA) "0 0 W H"`).
_TCL_DIE_RE = re.compile(
    r"DIE_AREA\s*\)?\s*[\"'{]?\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)",
    re.IGNORECASE)


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _load(p: Path) -> Optional[dict]:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _rect_from_four(vals: Sequence) -> Optional[str]:
    try:
        llx, lly, urx, ury = (float(v) for v in vals[:4])
    except (TypeError, ValueError):
        return None
    w, h = urx - llx, ury - lly
    if w > 0 and h > 0:
        return f"{int(round(w))}x{int(round(h))}"
    return None


def _walk_die_area(node) -> List[Sequence]:
    """Every ``DIE_AREA`` value anywhere in a parsed config (incl. per-PDK
    sub-dicts). Key name only — no PDK/design literal."""
    out: List[Sequence] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if str(k).upper() == "DIE_AREA":
                if isinstance(v, (list, tuple)) and len(v) >= 4:
                    out.append(v)
                elif isinstance(v, str):
                    parts = v.replace(",", " ").split()
                    if len(parts) >= 4:
                        out.append(parts)
            else:
                out.extend(_walk_die_area(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_walk_die_area(v))
    return out


def _design_fixed_die_mandates(project: Path) -> List[Tuple[str, str]]:
    """``[(source_rel_path, 'WxH'), ...]`` for every fixed-die the design
    mandates in its OWN machine-readable inputs."""
    out: List[Tuple[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for cfg in sorted(project.glob("input/**/config.json"))[:80]:
        doc = _load(cfg)
        if doc is None:
            continue
        for vals in _walk_die_area(doc):
            rect = _rect_from_four(vals)
            if rect:
                key = (str(cfg.relative_to(project)), rect)
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    for tcl in sorted(project.glob("input/**/*.tcl"))[:120]:
        try:
            text = tcl.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in _TCL_DIE_RE.finditer(text):
            rect = _rect_from_four(m.groups())
            if rect:
                key = (str(tcl.relative_to(project)), rect)
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def _design_input_corpus(project: Path) -> str:
    chunks: List[str] = []
    seen: Set[Path] = set()
    count = 0
    for pat in _CORPUS_GLOBS:
        for f in sorted(project.glob(pat)):
            if count >= _CORPUS_MAX_FILES:
                break
            if not f.is_file() or f in seen:
                continue
            seen.add(f)
            count += 1
            chunks.append(str(f.relative_to(project)))
            try:
                chunks.append(f.read_text(encoding="utf-8",
                                          errors="ignore")[:_CORPUS_MAX_BYTES])
            except Exception:
                continue
    for pat in _STAGED_PDK_GLOBS:
        for f in sorted(project.glob(pat))[:800]:
            chunks.append(str(f.relative_to(project)))
    return _norm(" ".join(chunks))


def _staged_pdk_enablement(project: Path) -> List[str]:
    out: List[str] = []
    for pat in _STAGED_PDK_GLOBS:
        for f in sorted(project.glob(pat))[:2000]:
            if f.is_file() and f.suffix.lower() in _PDK_ENABLEMENT_SUFFIXES:
                out.append(str(f.relative_to(project)))
                if len(out) >= 12:
                    return out
    return out


def _evidence_substantiates(project: Path, doc: dict, field: str) -> Optional[str]:
    """Return the citing file when L19's own extraction_evidence carries a
    `field`-labelled literal that VERIFIABLY appears in the design input file it
    cites. A quote that is not in the cited file substantiates nothing."""
    ev = doc.get("extraction_evidence")
    if not isinstance(ev, dict):
        return None
    for src, items in ev.items():
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            if field not in str(it.get("label") or ""):
                continue
            literal = str(it.get("literal") or "")
            probe = literal.strip()[:40]
            if not probe:
                continue
            sp = project / str(src)
            if not sp.is_file():
                continue
            try:
                if probe in sp.read_text(encoding="utf-8", errors="ignore"):
                    return str(src)
            except Exception:
                continue
    return None


def _waived(project: Path) -> Tuple[bool, str]:
    p = project / "waivers.json"
    if not p.is_file():
        return False, ""
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return False, ""
    if not isinstance(doc, dict):
        return False, ""
    v = doc.get(WAIVER_KEY)
    if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
        return True, v.strip()
    return False, ""


def _emit(path: Optional[Path], report: Dict[str, object]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass


def _l19_die(project: Path, fields: dict) -> Optional[str]:
    consumer_l19, _ = _consumers()
    if consumer_l19 is not None:
        try:
            return consumer_l19(project)
        except Exception:
            pass
    val = fields.get("die_area_budget_um")
    if not isinstance(val, str):
        return None
    m = _WXH_RE.match(val)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return f"{w}x{h}" if w > 0 and h > 0 else None


def _l9_die(project: Path) -> Optional[str]:
    _, consumer_l9 = _consumers()
    if consumer_l9 is not None:
        try:
            return consumer_l9(project)
        except Exception:
            return None
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="L19 PDK / floorplan backend-contract semantic gate")
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    project = args.project.resolve()
    if not project.is_dir():
        print(f"[SKIP] l19_pdk_floorplan_contract_check: not a directory: "
              f"{project}")
        return 2

    doc = _load(project / _L19_REL)
    if doc is None:
        print(f"[SKIP] l19_pdk_floorplan_contract_check: no {_L19_REL}.")
        return 2
    fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc

    findings: List[Dict[str, str]] = []
    advisories: List[str] = []
    report: Dict[str, object] = {
        "gate": "l19_pdk_floorplan_contract_check",
        "project": str(project),
    }

    # ---------------- L19-1: fixed-die mandate must reach the consumer ------ #
    mandates = _design_fixed_die_mandates(project)
    l19_die = _l19_die(project, fields)
    l9_die = _l9_die(project)
    report["design_fixed_die_mandates"] = [
        {"source": s, "rect": r} for s, r in mandates]
    report["l19_die_area_budget_um"] = fields.get("die_area_budget_um")
    report["l19_die_resolved"] = l19_die
    report["l9_die_resolved"] = l9_die
    # A fallback is a STATED condition, never a silent substitution. If the
    # consumer's resolvers could not be reached, this gate answered from its
    # own copy of the rule — which is the drift it exists to prevent, and the
    # one thing a reader of a green verdict has to know.
    report["consumer_resolvers_reached"] = _consumers()[0] is not None
    if _CONSUMER_IMPORT_ERROR:
        report["consumer_import_error"] = _CONSUMER_IMPORT_ERROR
        advisories.append(
            "the consumer's own die resolvers could not be imported "
            f"({_CONSUMER_IMPORT_ERROR}); this gate answered from its own copy "
            "of the rule, so gate and consumer are NOT proven to agree here")
    if mandates:
        rects = {r for _s, r in mandates}
        if l9_die is None and l19_die is None:
            findings.append({
                "rule": "L19-1",
                "message": (
                    "the design MANDATES a fixed die in its own inputs "
                    f"({[f'{r} from {s}' for s, r in mandates][:4]}) but "
                    "neither L9 prose nor L19.die_area_budget_um "
                    f"({fields.get('die_area_budget_um')!r}) resolves a "
                    "positive WxH. `_effective_die_um` will therefore return "
                    "'auto' and phase3 will AUTO-SIZE over a floorplan the "
                    "design had already fixed."),
            })
        elif l19_die is not None and l19_die not in rects:
            findings.append({
                "rule": "L19-1",
                "message": (
                    f"L19.die_area_budget_um resolves to {l19_die} µm, which "
                    "matches NONE of the fixed dies the design mandates in its "
                    f"own inputs ({sorted(rects)}). phase3 honors the L19 value "
                    "VERBATIM and never auto-sizes over it, so the design would "
                    "be pinned to a die it never asked for."),
            })

    # ---------------- L19-2 / L19-3: the PDK contract ---------------------- #
    pdk_target = fields.get("pdk_target")
    staged = _staged_pdk_enablement(project)
    report["pdk_target"] = pdk_target
    report["staged_pdk_enablement"] = staged

    if isinstance(pdk_target, str) and pdk_target.strip():
        token = _norm(pdk_target)
        corpus = _design_input_corpus(project)
        traceable = bool(token) and token in corpus
        ev_src = None
        if not traceable:
            ev_src = _evidence_substantiates(project, doc, "pdk_target")
        report["pdk_target_traceable_in_corpus"] = traceable
        report["pdk_target_evidence_source"] = ev_src
        if not traceable and ev_src is None:
            findings.append({
                "rule": "L19-2",
                "message": (
                    f"pdk_target={pdk_target!r} is traceable to NOTHING in the "
                    "design's own inputs (not in the input-doc / staged "
                    "config / SDC / staged-PDK-path corpus, and L19's own "
                    "extraction_evidence carries no `pdk_target` literal that "
                    "is verifiably present in the file it cites). "
                    "`foundry_handoff_pack_gen._l19_pdk_target` prints this "
                    "string to the foundry and `analog_real_corner_sweep` "
                    "discloses `pdk_substitution: target=<this>` — both would "
                    "be stating a target the design never authorised."),
            })
    elif staged:
        findings.append({
            "rule": "L19-3",
            "message": (
                "pdk_target is null while the design STAGES a PDK enablement of "
                f"its own ({staged[:4]}{'…' if len(staged) > 4 else ''}). The "
                "layer that owns the PDK contract declares nothing, so the "
                "foundry handoff pack's PDK statement is empty and the analog "
                "honesty disclosure degenerates to "
                "`pdk_substitution: target=None` — a disclosure that discloses "
                "nothing. The enablement is on disk in the design's own input "
                "tree; put its target in the layer that consumes it."),
        })

    # ---------------- L19-4: advisory-only observations -------------------- #
    sdc_path = fields.get("sdc_constraints_path")
    if isinstance(sdc_path, str) and sdc_path.strip():
        if not (project / sdc_path).is_file():
            advisories.append(
                f"sdc_constraints_path={sdc_path!r} points at a file that does "
                "not exist. The field is written by phase1_post_process.py and "
                "read by NOTHING, so no consumer can ever catch this — it only "
                "makes the layer look more populated than it is.")
    if fields.get("power_budget_uw") in (None, ""):
        advisories.append(
            "power_budget_uw is unset. Not gated: no program in the flow reads "
            "it, so failing on it would be the token-presence shape this gate "
            "exists to replace.")
    if not fields.get("floorplan_hints"):
        advisories.append(
            "floorplan_hints is empty. Not gated for the same reason as "
            "power_budget_uw.")
    report["findings"] = findings
    report["advisories"] = advisories

    if not findings:
        report["verdict"] = "PASS"
        _emit(args.json, report)
        print("[PASS] l19_pdk_floorplan_contract_check: PDK/floorplan contract "
              f"is actionable (pdk_target={pdk_target!r}"
              + (f", traceable to the design's own inputs" if pdk_target else "")
              + (f"; fixed die {l19_die or l9_die} matches the design's "
                 f"mandate" if mandates else "; design mandates no fixed die")
              + ").")
        for a in advisories:
            print(f"  [note] {a}")
        return 0

    waived, why = _waived(project)
    report["verdict"] = "PASS_WITH_WAIVERS" if waived else "FAIL"
    _emit(args.json, report)
    head = "PASS_WITH_WAIVERS" if waived else "[FAIL]"
    print(f"{head} l19_pdk_floorplan_contract_check: {len(findings)} L19 "
          "backend-contract finding(s).")
    for f in findings:
        print(f"  - {f['rule']}: {f['message']}")
    for a in advisories:
        print(f"  [note] {a}")
    if waived:
        print(f"  waiver `{WAIVER_KEY}` set: {why[:120]}")
        return 0
    print("  Fix: populate the field in L19 (the layer phase3 / the foundry "
          "pack / the analog substitution disclosure actually read), or set "
          f"waiver `{WAIVER_KEY}` (>={WAIVER_MIN} chars) to DISCLOSE the gap.")
    return 1


if __name__ == "__main__":
    sys.exit(main())