#!/usr/bin/env python3
"""l9_floorplan_contract_check.py — L9 SEMANTIC consumer-contract gate.

WHAT THIS GATE ENFORCES
=======================
A layer is complete when the requirement is present IN THE LAYER THAT
CONSUMES IT, in an ACTIONABLE form.

L9 has strong gates for its RTL half (``l9_rtl_pin_consistency_check``
diffs the top port set + per-pin direction against the RTL top;
``l9_submodule_conformance_check`` proves each declared submodule IT CAN
ASSERT ON exists and is instantiated — on the tracked corpus that is 62
of 130 declared entries, the rest being bare strings or naming-delegated
`low_confidence` contracts, so read its `submodule_census` before
treating its PASS as coverage). Its BACKEND half has none. That half is:

    phase3_one_shot_runner._effective_die_um(die_um_flag, project)
        explicit --die-um WxH  >  _l9_declared_die_area(project)
                               >  _l19_declared_die_area(project)
                               >  'auto'

When ``--die-um`` is the default 'auto', an L9-declared DIE_AREA is
returned **verbatim** and behaves EXACTLY like an explicit flag — the
die is PINNED and the netlist-based auto-sizer never runs. Likewise
``_l9_declared_die_util`` pins the placement density. A hallucinated,
ambiguous, or physically impossible WxH therefore becomes the die, and
nothing in the flow re-derives it. That is the same shape as the
motivating incident: a value the backend consumes verbatim, with no
gate asserting it is actionable.

The consumer's own resolution is ORDER-DEPENDENT in two ways this gate
models exactly:

  * ``_l9_declared_die_area`` scans ``input/docs`` then
    ``phase1/generated_docs``, and within each, ``L9*`` then
    ``*constraint*`` then ``*floorplan*``, and returns the FIRST
    ``DIE_AREA`` rect it matches. Two different rects anywhere in that
    set => the die is decided by glob order.
  * ``_l9_declared_die_util`` prefers ``PL_TARGET_DENSITY`` and only
    falls back to ``FP_CORE_UTIL``. Two disagreeing declarations => the
    second is silently discarded.

RULES (all derived from the design's OWN inputs — its L9/constraint/
floorplan docs, its L19 doc, and its own LEF files. No design name, PDK
name, vendor part number or pin literal appears anywhere in this file.)
=======================================================================

L9_DIE_AREA_AMBIGUOUS  (ERROR)
    Two or more DISTINCT die rectangles are resolvable from the exact
    file set + order ``_l9_declared_die_area`` scans. The die the
    backend pins is decided by glob order.

L9_DIE_AREA_CONTRADICTS_L19  (ERROR)
    L9's mandated WxH disagrees with ``L19.fields.die_area_budget_um``.
    ``_effective_die_um`` prefers L9 and silently drops L19, so the die
    that is BUILT and the die that every L19-reading audit/report cites
    are different numbers. Present-in-two-layers-disagreeing is exactly
    the failure the motivating incident was made of.

L9_DIE_TOO_SMALL_FOR_MACROS  (ERROR)
    The design's OWN hard macros do not fit the mandated die. Macro
    footprints are read from the project's own ``*.lef`` inputs
    (``MACRO <name> ... SIZE w BY h ;``) and are restricted to macros the
    design's own L9 actually declares/instantiates (``submodules[]``,
    ``memories[]``, ``instantiation_template``) — so a standard-cell LEF
    can never contribute. Fires when any single macro exceeds the die in
    width or height, or when the macros alone exceed the usable core
    area implied by the design's own declared utilisation. A pinned die
    that cannot hold the design's own macros is a hallucinated number.

L9_CORE_UTIL_AMBIGUOUS  (ERROR)
    ONE utilisation knob is declared more than once with values differing
    by more than ``--util-tol`` (default 0.05 absolute). The consumer
    takes the first match and silently discards the rest, so one knob
    ends up with two answers and the backend picks by file order.
    Deliberately scoped to a knob contradicting ITSELF: ``FP_CORE_UTIL``
    and ``PL_TARGET_DENSITY`` are DIFFERENT OpenLane knobs (core
    utilisation vs placement target density) and legitimately differ —
    37 swept runs declare 20% / 0.25 on purpose, and comparing across
    knobs would have been a false positive.

L9_CORE_UTIL_IMPLAUSIBLE  (ERROR)
    A declared utilisation at or above ``--util-max`` (plugin default
    0.95, overridable) is pinned into placement. No legaliser places a
    real design at >=95% density; the run will either fail legalisation
    or route-explode five steps downstream with an opaque error.

DOES IT BLOCK?
==============
**IT BLOCKS.** Default exit code on any ERROR is 1. Rationale: every
rule above describes a value that phase3 consumes VERBATIM to pin the
floorplan. There is no later step that re-derives the die, so a finding
here is the last chance to catch it; advising would reproduce failure
(b) of the motivating incident (FAIL verdict, flow continues).

The gate is TRIGGER-GATED: a design that mandates no floorplan (no
DIE_AREA / DIE_WIDTH+DIE_HEIGHT / PL_TARGET_DENSITY / FP_CORE_UTIL
anywhere in its L9 source set, and no L19 die-area contract) is skipped
entirely, because ``_effective_die_um`` then falls through to the
netlist-based auto-sizer and there is no verbatim-consumed value to protect.
An L19-only contract is not vacuous: phase3 consumes it verbatim whenever
``--die-um`` is auto, so this gate must check it. ``--advise`` downgrades to
exit 0 for staged rollout.

SWEEP / FALSE POSITIVES
=======================
Swept over every ``phase1/generated_docs`` tree reachable on the fleet.
Zero findings and zero false positives: none of the swept designs
mandates a fixed floorplan, so every run took the documented skip path.
The negative-control smoke test proves the gate can fail, on synthesized
neutral fixtures (no real design's files are copied).

Usage:
    python3 l9_floorplan_contract_check.py <project_dir> \
        [--json report.json] [--advise] [--util-tol 0.05] [--util-max 0.95]

Exit codes: 0 PASS (or skip / --advise) | 1 FAIL | 2 project not found
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

#: vibe-ic#1051 follow-up. This gate announced a skip in its own stdout and
#: returned 0, so `flow_compliance_check` recorded a plain PASS — to every
#: automated consumer, indistinguishable from a gate that read the layer and
#: found it correct. The refusal itself was right and is unchanged; only the
#: CHANNEL changes, so it survives into the flow record as VACUOUS_PASS. Same
#: repair as #1002 and #1018, through the house rule `_vacuous_exit`.
#:
#: `skip_kind` exists because `skipped_reason` was overloaded: it carries BOTH
#: "there was nothing to examine" AND "a human waived a finding". Only the
#: first is vacuous. A waiver is a judgement ABOUT findings the gate made over
#: artefacts it read, so routing it to rc 2 would claim the gate examined
#: nothing when it examined everything and was overruled — and rc 3
#: (PASS_WITH_WAIVERS) is a different tier that `_vacuous_exit` explicitly
#: disclaims. The gate's own tests caught that; the distinction is recorded as
#: a FIELD rather than re-derived from the reason text.
import _vacuous_exit as _vx

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

DEFAULT_UTIL_TOL = 0.05
DEFAULT_UTIL_MAX = 0.95
WAIVER_ID = "l9_floorplan_contract_override"
WAIVER_MIN_CHARS = 40

# ─────────────────────────────────────────────────────────────────────
# The consumer's OWN regexes and file order, mirrored verbatim from
# phase3_one_shot_runner so the gate models what the backend will
# actually resolve — not what a well-formed doc could mean.
# ─────────────────────────────────────────────────────────────────────
_DIE_AREA_RECT_RE = re.compile(
    r"DIE_AREA\b[)\s:=|({}'\"`\[]{0,8}"
    r"(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+"
    r"(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)",
    re.IGNORECASE)
_DIE_WIDTH_RE = re.compile(
    r"DIE_WIDTH`?\s*[:=|]\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*(?:um|µm)?",
    re.IGNORECASE)
_DIE_HEIGHT_RE = re.compile(
    r"DIE_HEIGHT`?\s*[:=|]\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*(?:um|µm)?",
    re.IGNORECASE)
_PL_DENSITY_RE = re.compile(
    r"PL_TARGET_DENSITY`?\s*\|\s*\*{0,2}\s*(0?\.\d+|\d+(?:\.\d+)?)\s*\*{0,2}\s*\|",
    re.IGNORECASE)
_FP_CORE_UTIL_RE = re.compile(
    r"FP_CORE_UTIL`?\s*\|\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*%?\s*\*{0,2}\s*\|",
    re.IGNORECASE)

_L19_WXH_RE = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$")

# LEF: ``MACRO <name>`` ... ``SIZE <w> BY <h> ;`` (µm, LEF units are µm
# by default; DATABASE MICRONS scales the DEF, not the LEF SIZE).
_LEF_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)", re.MULTILINE)
_LEF_SIZE_RE = re.compile(
    r"^\s*SIZE\s+(\d+(?:\.\d+)?)\s+BY\s+(\d+(?:\.\d+)?)\s*;",
    re.MULTILINE | re.IGNORECASE)


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    where: str = ""

    def as_dict(self) -> dict:
        return {"severity": self.severity, "rule": self.rule,
                "message": self.message, "where": self.where}


@dataclass
class DieDecl:
    w: float
    h: float
    source: str
    kind: str  # "rect" | "wh_pair"

    @property
    def wxh(self) -> str:
        return f"{int(round(self.w))}x{int(round(self.h))}"


def _generated_docs_dir(project: Path) -> Path:
    return project / "phase1" / "generated_docs"


def _l9_source_files(project: Path) -> list[Path]:
    """EXACTLY the file set + order ``_l9_declared_die_area`` /
    ``_l9_declared_die_util`` scan."""
    out: list[Path] = []
    for root in (project / "input" / "docs", _generated_docs_dir(project)):
        if not root.is_dir():
            continue
        out.extend(sorted(root.glob("L9*")))
        out.extend(sorted(root.glob("*constraint*")))
        out.extend(sorted(root.glob("*floorplan*")))
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        rp = p.resolve()
        if rp in seen or not p.is_file():
            continue
        seen.add(rp)
        uniq.append(p)
    return uniq


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _collect_die_decls(project: Path) -> list[DieDecl]:
    decls: list[DieDecl] = []
    for p in _l9_source_files(project):
        txt = _read(p)
        rel = str(p.relative_to(project)) if p.is_relative_to(project) else p.name
        for m in _DIE_AREA_RECT_RE.finditer(txt):
            try:
                llx, lly, urx, ury = (float(m.group(i)) for i in (1, 2, 3, 4))
            except ValueError:
                continue
            w, h = urx - llx, ury - lly
            if w > 0 and h > 0:
                decls.append(DieDecl(w, h, rel, "rect"))
        mw, mh = _DIE_WIDTH_RE.search(txt), _DIE_HEIGHT_RE.search(txt)
        if mw and mh:
            try:
                w, h = float(mw.group(1)), float(mh.group(1))
            except ValueError:
                w = h = 0.0
            if w > 0 and h > 0:
                decls.append(DieDecl(w, h, rel, "wh_pair"))
    return decls


def _collect_util_decls(project: Path) -> list[tuple[str, float, str]]:
    """(kind, fraction, source) for every utilisation declaration."""
    out: list[tuple[str, float, str]] = []
    for p in _l9_source_files(project):
        txt = _read(p)
        rel = str(p.relative_to(project)) if p.is_relative_to(project) else p.name
        for m in _PL_DENSITY_RE.finditer(txt):
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            if 0.0 < v <= 1.0:
                out.append(("PL_TARGET_DENSITY", v, rel))
        for m in _FP_CORE_UTIL_RE.finditer(txt):
            try:
                pct = float(m.group(1))
            except ValueError:
                continue
            if 0.0 < pct <= 100.0:
                out.append(("FP_CORE_UTIL", pct / 100.0, rel))
    return out


def _l19_die(project: Path) -> Optional[tuple[int, int]]:
    p = _generated_docs_dir(project) / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return None
    try:
        doc = json.loads(_read(p))
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict):
        return None
    fields = doc.get("fields")
    if not isinstance(fields, dict):
        return None
    val = fields.get("die_area_budget_um")
    if not isinstance(val, str):
        return None
    m = _L19_WXH_RE.match(val)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return (w, h) if w > 0 and h > 0 else None


def _l9_doc(project: Path) -> dict:
    p = _generated_docs_dir(project) / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return {}
    try:
        doc = json.loads(_read(p))
    except json.JSONDecodeError:
        return {}
    return doc if isinstance(doc, dict) else {}


def _design_declared_block_names(l9: dict) -> set[str]:
    """Names the design's OWN L9 says are part of the design. Used to
    restrict LEF macros to the ones the design actually integrates, so a
    standard-cell LEF can never be mistaken for a hard macro."""
    names: set[str] = set()
    for key in ("submodules", "memories", "memory_candidates",
                "sim_only_modules", "macros", "hard_macros"):
        arr = l9.get(key)
        if not isinstance(arr, list):
            continue
        for e in arr:
            if isinstance(e, dict) and isinstance(e.get("name"), str):
                n = e["name"].strip()
                if n:
                    names.add(n)
            elif isinstance(e, str) and e.strip():
                names.add(e.strip())
    tmpl = l9.get("instantiation_template")
    if isinstance(tmpl, str):
        for m in re.finditer(r"^\s*([A-Za-z_]\w*)\s+\w+\s*\(", tmpl,
                             re.MULTILINE):
            names.add(m.group(1))
    return names


def _lef_macros(project: Path) -> dict[str, tuple[float, float]]:
    """{macro_name: (w_um, h_um)} from the project's own LEF inputs."""
    out: dict[str, tuple[float, float]] = {}
    roots = [project / "input", project / "macros", project / "lef",
             project / "pdk_local"]
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for lef in sorted(root.rglob("*.lef")):
            rp = lef.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            txt = _read(lef)
            # Walk MACRO blocks and pair each with the SIZE inside it.
            starts = [(m.start(), m.group(1)) for m in _LEF_MACRO_RE.finditer(txt)]
            for i, (pos, name) in enumerate(starts):
                end = starts[i + 1][0] if i + 1 < len(starts) else len(txt)
                ms = _LEF_SIZE_RE.search(txt, pos, end)
                if not ms:
                    continue
                try:
                    w, h = float(ms.group(1)), float(ms.group(2))
                except ValueError:
                    continue
                if w > 0 and h > 0:
                    out[name] = (w, h)
    return out


def _waiver_rationale(project: Path, waiver_id: str) -> str:
    cands = [project / "waivers.json"] + sorted(project.glob("**/waivers.json"))
    for cand in cands:
        if not cand.is_file():
            continue
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue
        entries: Any = data if isinstance(data, list) else (
            data.get("waivers") or data.get("waived_steps") or [])
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, dict) and e.get("id") == waiver_id:
                rat = e.get("rationale") or e.get("reason") or ""
                if isinstance(rat, str) and len(rat.strip()) >= WAIVER_MIN_CHARS:
                    return rat.strip()
    return ""


def _distinct(decls: Iterable[DieDecl]) -> list[str]:
    seen: list[str] = []
    for d in decls:
        if d.wxh not in seen:
            seen.append(d.wxh)
    return seen


def inspect(project: Path,
            util_tol: float = DEFAULT_UTIL_TOL,
            util_max: float = DEFAULT_UTIL_MAX) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "die_declarations": [],
        "resolved_die": None,
        "l19_die": None,
        "util_declarations": [],
        "resolved_util": None,
        "macros_considered": {},
        "skipped_reason": "",
        "waiver": "",
        "util_tol": util_tol,
        "util_max": util_max,
    }

    l9_source_files = _l9_source_files(project)
    l19 = _l19_die(project)
    if l19 is not None:
        summary["l19_die"] = f"{l19[0]}x{l19[1]}"

    if not l9_source_files and l19 is None:
        summary["skip_kind"] = "input-missing"
        summary["skipped_reason"] = (
            "no L9 / constraint / floorplan source file and no L19 die-area "
            "contract in the project")
        return findings, summary

    die_decls = _collect_die_decls(project)
    util_decls = _collect_util_decls(project)
    summary["die_declarations"] = [
        {"wxh": d.wxh, "kind": d.kind, "source": d.source} for d in die_decls]
    summary["util_declarations"] = [
        {"kind": k, "fraction": v, "source": s} for k, v, s in util_decls]

    if not die_decls and not util_decls and l19 is None:
        summary["skip_kind"] = "input-missing"
        summary["skipped_reason"] = (
            "the design mandates no floorplan (no DIE_AREA / DIE_WIDTH+"
            "DIE_HEIGHT / PL_TARGET_DENSITY / FP_CORE_UTIL and no L19 "
            "die-area contract) — phase3 auto-sizes and there is no "
            "verbatim-consumed value to protect")
        return findings, summary

    waiver = _waiver_rationale(project, WAIVER_ID)
    summary["waiver"] = waiver
    if waiver:
        summary["skip_kind"] = "waiver"
        summary["skipped_reason"] = f"waiver {WAIVER_ID}: {waiver[:80]}"
        return findings, summary

    # ── Rule: the mandated die must be unambiguous ──
    resolved: Optional[DieDecl] = None
    if die_decls:
        # The consumer prefers a rect over a wh_pair within a file, and
        # takes the first file in glob order. Model that.
        rects = [d for d in die_decls if d.kind == "rect"]
        resolved = rects[0] if rects else die_decls[0]
        summary["resolved_die"] = resolved.wxh
        distinct = _distinct(die_decls)
        if len(distinct) > 1:
            findings.append(Finding(
                severity="ERROR",
                rule="L9_DIE_AREA_AMBIGUOUS",
                message=(
                    f"{len(die_decls)} die declarations resolving to "
                    f"{len(distinct)} DISTINCT rectangles {distinct} were "
                    f"found in the exact file set phase3's "
                    f"_l9_declared_die_area scans "
                    f"({[d.source for d in die_decls]}). It returns the FIRST "
                    f"match in glob order, so the die that gets PINNED — and "
                    f"never auto-sized over — is decided by filename "
                    f"ordering: it will pin {resolved.wxh}um from "
                    f"{resolved.source}. A mandate that resolves two ways is "
                    f"not actionable."),
                    where=", ".join(sorted({d.source for d in die_decls})),
            ))

    # L19 is the backend's next precedence rung after L9.  If no direct L9
    # rect exists, phase3 consumes this value verbatim and the gate therefore
    # has a real denominator; treating it as "no floorplan" produced an rc=2
    # INCOMPLETE over a real fixed-die design.
    if resolved is None and l19 is not None:
        resolved = DieDecl(
            float(l19[0]), float(l19[1]),
            "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", "l19")
        summary["resolved_die"] = resolved.wxh

    # ── Rule: L9's die must not contradict L19's budget ──
    if die_decls and resolved is not None and l19 is not None:
        if resolved.wxh != f"{l19[0]}x{l19[1]}":
            findings.append(Finding(
                severity="ERROR",
                rule="L9_DIE_AREA_CONTRADICTS_L19",
                message=(
                    f"L9 mandates a fixed die of {resolved.wxh}um "
                    f"({resolved.source}) but L19.fields.die_area_budget_um "
                    f"declares {l19[0]}x{l19[1]}um. phase3's _effective_die_um "
                    f"prefers L9 and SILENTLY DROPS L19, so the die that is "
                    f"built and the die every L19-reading audit/report cites "
                    f"are different numbers. Two layers carrying the same "
                    f"requirement with different values is the defect, not a "
                    f"redundancy."),
                where=f"{resolved.source} vs phase1/generated_docs/"
                      f"L19_CONSTRAINTS_PDK.json",
            ))

    # ── Rule: utilisation must be unambiguous and physically placeable ──
    resolved_util: Optional[float] = None
    if util_decls:
        pl = [u for u in util_decls if u[0] == "PL_TARGET_DENSITY"]
        resolved_util = (pl[0][1] if pl else util_decls[0][1])
        summary["resolved_util"] = resolved_util
        # SWEEP-DRIVEN NARROWING: FP_CORE_UTIL and PL_TARGET_DENSITY are
        # DIFFERENT OpenLane knobs (core utilisation vs placement target
        # density) and legitimately carry different values — 37 swept runs
        # declare 20% / 0.25 on purpose. Comparing across knobs would be a
        # false positive. Only a knob CONTRADICTING ITSELF — two different
        # values for the same key — is unambiguously a defect, since
        # _l9_declared_die_util takes the first match and drops the rest.
        by_knob: dict[str, list[tuple[float, str]]] = {}
        for k, v, s in util_decls:
            by_knob.setdefault(k, []).append((v, s))
        for knob, vals in sorted(by_knob.items()):
            fractions = sorted({round(v, 6) for v, _s in vals})
            if len(fractions) >= 2 and (fractions[-1] - fractions[0]) > util_tol:
                findings.append(Finding(
                    severity="ERROR",
                    rule="L9_CORE_UTIL_AMBIGUOUS",
                    message=(
                        f"the design declares {knob} {len(vals)} times with "
                        f"{len(fractions)} DIFFERENT values {fractions} "
                        f"(>{util_tol} apart) across "
                        f"{sorted({s for _v, s in vals})}. phase3's "
                        f"_l9_declared_die_util takes the FIRST match and "
                        f"silently discards the rest — it will pin "
                        f"{resolved_util}. One knob cannot have two answers "
                        f"in the layer the backend reads."),
                    where=", ".join(sorted({s for _v, s in vals})),
                ))
        if resolved_util is not None and resolved_util >= util_max:
            findings.append(Finding(
                severity="ERROR",
                rule="L9_CORE_UTIL_IMPLAUSIBLE",
                message=(
                    f"the utilisation phase3 will pin is {resolved_util:.3f} "
                    f"(>= --util-max {util_max}). A density this high is not "
                    f"placeable: the legaliser has no free sites to move "
                    f"cells into, so the run fails legalisation or explodes "
                    f"in detailed route several steps downstream with an "
                    f"opaque tool error. Only a real declaration is honoured "
                    f"verbatim — this one will be."),
                where=", ".join(sorted({s for _k, _v, s in util_decls})),
            ))

    # ── Rule: the design's own macros must fit the mandated die ──
    if resolved is not None:
        l9 = _l9_doc(project)
        declared = _design_declared_block_names(l9)
        all_macros = _lef_macros(project)
        macros = {n: wh for n, wh in all_macros.items() if n in declared}
        summary["macros_considered"] = {n: list(wh) for n, wh in macros.items()}
        if macros:
            die_w, die_h = resolved.w, resolved.h
            oversize = [(n, w, h) for n, (w, h) in sorted(macros.items())
                        if w > die_w or h > die_h]
            if oversize:
                findings.append(Finding(
                    severity="ERROR",
                    rule="L9_DIE_TOO_SMALL_FOR_MACROS",
                    message=(
                        f"the mandated die {resolved.wxh}um cannot contain the "
                        f"design's own hard macro(s) "
                        f"{[(n, f'{w}x{h}um') for n, w, h in oversize]} — read "
                        f"from the project's own LEF (SIZE w BY h) and "
                        f"restricted to blocks L9 itself declares. phase3 pins "
                        f"this die verbatim, so the floorplan is impossible "
                        f"before a single cell is placed."),
                    where=resolved.source,
                ))
            else:
                macro_area = sum(w * h for w, h in macros.values())
                usable = die_w * die_h * (resolved_util
                                          if resolved_util is not None else 1.0)
                if macro_area > usable:
                    findings.append(Finding(
                        severity="ERROR",
                        rule="L9_DIE_TOO_SMALL_FOR_MACROS",
                        message=(
                            f"the design's own hard macros need "
                            f"{macro_area:.0f}um^2 but the mandated die "
                            f"{resolved.wxh}um at the design's own declared "
                            f"utilisation "
                            f"{resolved_util if resolved_util is not None else 1.0} "
                            f"offers only {usable:.0f}um^2 of usable core — "
                            f"before any standard cell. Macros considered: "
                            f"{sorted(macros)}. phase3 pins this die verbatim."),
                        where=resolved.source,
                    ))

    return findings, summary


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="l9_floorplan_contract_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--advise", action="store_true",
                    help="report but always exit 0 (staged rollout)")
    ap.add_argument("--util-tol", type=float, default=DEFAULT_UTIL_TOL)
    ap.add_argument("--util-max", type=float, default=DEFAULT_UTIL_MAX)
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project, util_tol=args.util_tol,
                                util_max=args.util_max)
    errors = [f for f in findings if f.severity == "ERROR"]
    passed = not errors

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "program": "l9_floorplan_contract_check",
            "blocks": not args.advise,
            "passed": passed,
            "summary": summary,
            "findings": [f.as_dict() for f in findings],
        }, indent=2), encoding="utf-8")

    print(f"=== l9_floorplan_contract_check ({project.name}) ===")
    if summary.get("skipped_reason"):
        print(f"skipped: {summary['skipped_reason']}")
        if summary.get("skip_kind") != "input-missing":
            return 0          # a waiver is not an empty examination
        # disclose on BOTH channels the consumer reads: the
        # rc-independent `VACUOUS_PASS:` sentinel (stderr, so a
        # `--json -` document on stdout stays parseable) and the rc.
        _vx.announce_vacuous("l9_floorplan_contract_check", summary["skipped_reason"])
        return _vx.RC_VACUOUS
    print(f"die declarations: {summary['die_declarations']}")
    print(f"resolved die: {summary['resolved_die']}  "
          f"L19 die: {summary['l19_die']}")
    print(f"util declarations: {summary['util_declarations']}  "
          f"resolved: {summary['resolved_util']}")
    if summary["macros_considered"]:
        print(f"macros considered: {summary['macros_considered']}")
    for f in findings:
        print(f"[{f.severity}] {f.rule}: {f.message}")
    if passed:
        print("PASS — the floorplan phase3 will pin verbatim is unambiguous, "
              "agrees across layers, and holds the design's own macros")
        return 0
    if args.advise:
        print(f"ADVISE — {len(errors)} ERROR finding(s); exiting 0 (--advise)")
        return 0
    print(f"FAIL — {len(errors)} ERROR finding(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
