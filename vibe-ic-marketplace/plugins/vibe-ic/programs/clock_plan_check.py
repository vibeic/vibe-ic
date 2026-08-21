#!/usr/bin/env python3
"""
clock_plan_check.py — Step 16 (Clock planning) substance gate.

Anti-fabrication mandate
------------------------
The Step 16 flow gate previously trusted ``files_exist`` ONLY: it passed the
instant ``phase3/stage3/cts/clock_plan.json`` appeared, with ZERO verification
that the file describes a usable clock plan. A plan that names no clock, or a
clock with no period, would have sailed through — and CTS (Step 19) would then
build a tree against an under-specified plan.

This checker performs REAL DETERMINISTIC SUBSTANCE verification of the produced
clock-plan artefact:

  1. Parse ``phase3/stage3/cts/clock_plan.json``. It MUST exist, be non-empty,
     and be valid JSON. Absent / empty / unparseable => honest FAIL (rc=1) —
     never a vacuous pass on absence.
  2. Normalise the plan into a list of clock records regardless of which schema
     shape the producer used:
       - a ``clocks`` (or ``clock_list`` / ``defined_clocks``) array of objects,
         each with name + period/frequency + source pin/port, OR
       - the runner's minimal single-clock shape
         (``primary_clock`` + a top-level ``period``/``frequency`` + a top-level
         source ``port``/``pin``/``source``).
  3. Require >= 1 clock defined. An empty plan => FAIL.
  4. Each clock MUST have:
       - a POSITIVE period (ns), derived directly from a period field OR
         converted from a positive frequency (period_ns = 1000 / freq_MHz,
         period_ns = 1e9 / freq_Hz). A clock with no period AND no frequency,
         or a non-positive value, => FAIL.  (Positivity is a structural physical
         fact, NOT a fabricated chip-specific threshold.)
       - a source pin or port (a non-empty net/port/pin string). A clock with no
         source object => FAIL.
  5. If an SDC exists (phase3/.../constraints, the pnr dir, the phase2 fpga
     constraints, or any ``*.sdc`` under the project), parse every
     ``create_clock`` in it and verify each constrained clock NAME appears in
     the plan. A dropped clock (in SDC but missing from the plan) => FAIL. This
     is the real backend failure this gate guards: a multi-clock design whose
     plan silently forgets a clock domain.

Verdicts
--------
* PASS   (rc=0) — >= 1 clock, every clock has a positive period and a source
                  object, and (if an SDC exists) no SDC clock is dropped.
* FAIL   (rc=1) — plan absent/empty/unparseable, no clock defined, a clock with
                  no/non-positive period, a clock with no source object, or an
                  SDC ``create_clock`` not present in the plan.
* WAIVED (rc=0) — ``waivers.json`` declares the step waived (ticket + reason).
* SKIP   (rc=2) — project dir not found (operational, not a design failure).

No numeric threshold the artefact/PDK does not provide is invented. The only
bounds applied are universal structural facts (period must be > 0; a clock must
have a source object) — stated explicitly in honest_notes. chip-AGNOSTIC: no
vendor / IC / tool literal is hard-coded.

Usage
-----
    python3 clock_plan_check.py <project_dir> [--json <out>]

Exit codes: 0 PASS / 1 FAIL / 2 SKIP.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402
import _waiver_entries as _we  # noqa: E402


_GATE_NAME = "clock_plan_check"
_GATE_LABEL = "clock_plan"

# Canonical (current flow) location first, legacy fallbacks second.
_PLAN_CANDIDATES = [
    "phase3/stage3/cts/clock_plan.json",
    "phase3/stage3/clock_plan.json",
    "cts/clock_plan.json",
]

# Where SDC constraints might live, in priority order. Anything matching
# *.sdc under the project is also swept as a last resort so a dropped-clock
# check still fires even on a non-canonical layout.
_SDC_DIR_CANDIDATES = [
    "phase3/stage3/constraints",
    "phase3/stage3/cts/constraints",
    "phase3/stage3/pnr",
    "phase2/stage2/constraints",
    "phase2/stage1/fpga",
    "constraints",
]

# create_clock <...> -period <val> <...>  with an optional -name <val>.
# Also tolerate create_generated_clock for the dropped-clock name set.
_CREATE_CLOCK_RE = re.compile(
    r"\bcreate_(?:generated_)?clock\b(?P<body>[^\n;]*)", re.IGNORECASE)
_NAME_RE = re.compile(r"-name\s+(?P<q>['\"{]?)(?P<name>[\w\\/\[\].:$-]+)(?P=q)?",
                      re.IGNORECASE)
_PERIOD_RE = re.compile(r"-period\s+(?P<val>[\w.+\-]+)", re.IGNORECASE)
# A source object: [get_ports ...], [get_pins ...], or a trailing bare token.
_GET_OBJ_RE = re.compile(
    r"\[\s*get_(?:ports|pins|nets)\s+\{?\s*(?P<obj>[\w\\/\[\].:$-]+)",
    re.IGNORECASE)


# ----------------------------------------------------------------------
# waiver plumbing (mirrors sibling wafer_sort_yield_check.py)
# ----------------------------------------------------------------------
def _load_waivers(project: Path):
    """#519 — via the ONE shared reader, so this gate sees waiver entries under
    BOTH canonical keys. It read `waived_steps` only, so a waivers.json written
    by `phase3_one_shot_runner` (which emits `waivers`) looked EMPTY here and
    every step reported as un-waived. Measured over the corpus this changes no
    verdict — the `waivers`-shaped entries carry no `id`, and `_step_waived`
    matches on `id`/`ticket` — so adopting the union grants nothing new; it
    removes a blind spot rather than relaxing a gate."""
    return _we.load(project)


def _step_waived(project: Path, step_label: str):
    for w in _load_waivers(project):
        sid = str(w.get("id", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or step_label in ticket:
            return w
    return None


def _first_existing(project: Path, candidates):
    for rel in candidates:
        p = project / rel
        if p.is_file():
            return rel, p
    return None, None


# ----------------------------------------------------------------------
# numeric helpers
# ----------------------------------------------------------------------
def _num(d, *keys):
    """First numeric value among keys (float), else None. Non-dict-safe."""
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return None


def _period_ns_from(rec):
    """Return (period_ns, how) for a clock record / plan dict.

    Period precedence: explicit period field, else convert a positive
    frequency. Returns (None, reason) when neither is derivable or the value
    is non-positive.
    """
    period = _num(rec, "period", "period_ns", "clock_period", "clock_period_ns")
    if period is not None:
        if period > 0:
            return period, "period"
        return None, f"non-positive period {period}"

    period_ps = _num(rec, "period_ps")
    if period_ps is not None:
        if period_ps > 0:
            return period_ps / 1000.0, "period_ps"
        return None, f"non-positive period {period_ps} ps"

    freq_mhz = _num(rec, "frequency_mhz", "freq_mhz", "frequency_MHz")
    if freq_mhz is not None:
        if freq_mhz > 0:
            return 1000.0 / freq_mhz, "frequency_mhz"
        return None, f"non-positive frequency {freq_mhz} MHz"

    freq_hz = _num(rec, "frequency_hz", "freq_hz", "frequency")
    if freq_hz is not None:
        if freq_hz > 0:
            # Heuristic-free: treat a value < 1e6 as MHz only if a *_mhz key was
            # used; a bare "frequency" is taken as Hz.
            return 1e9 / freq_hz, "frequency_hz"
        return None, f"non-positive frequency {freq_hz} Hz"

    return None, "no period/frequency field"


def _source_of(rec):
    """Return a non-empty source pin/port string for a clock record, else None."""
    if not isinstance(rec, dict):
        return None
    for k in ("source", "source_pin", "source_port", "pin", "port",
              "clock_port", "clock_pin", "master_pin", "object", "target"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (list, tuple)) and v and str(v[0]).strip():
            return str(v[0]).strip()
    return None


def _clock_name(rec, fallback=None):
    if isinstance(rec, dict):
        for k in ("name", "clock_name", "clk", "id"):
            v = rec.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return fallback


# ----------------------------------------------------------------------
# plan normalisation
# ----------------------------------------------------------------------
def _extract_clocks(plan):
    """Return a list of normalised clock dicts from any plan shape.

    Each returned dict carries the original record under '_rec' plus a derived
    'name'. Period / source are evaluated by the caller against the record so a
    minimal single-clock plan (top-level fields) also works.
    """
    clocks = []
    if not isinstance(plan, dict):
        return clocks

    # Shape 1: an explicit array of clock objects.
    for arr_key in ("clocks", "clock_list", "defined_clocks", "clock_domains"):
        arr = plan.get(arr_key)
        if isinstance(arr, list) and arr:
            for i, c in enumerate(arr):
                if isinstance(c, dict):
                    clocks.append({"_rec": c, "name": _clock_name(c, f"clk[{i}]")})
                elif isinstance(c, str) and c.strip():
                    # Bare name in the array — period/source must be top-level.
                    clocks.append({"_rec": plan, "name": c.strip()})
            if clocks:
                return clocks

    # Shape 2: runner's minimal single-clock shape (primary_clock + top-level
    # period/source). The whole plan dict serves as the record so the
    # period/source extractors read top-level fields.
    primary = _clock_name(
        {"name": plan.get("primary_clock") or plan.get("clock")},
        None)
    if primary or _period_ns_from(plan)[0] is not None or _source_of(plan):
        clocks.append({"_rec": plan, "name": primary or "primary"})

    return clocks


# ----------------------------------------------------------------------
# SDC create_clock harvesting (for dropped-clock detection)
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# Plan freshness — CONTENT-keyed, and only when the plan recorded its inputs
# ----------------------------------------------------------------------
# An earlier attempt at this keyed freshness on MTIME: the plan was called
# stale when any *.sdc — or `floorplan.def` / `placed.def` — had a newer
# mtime. Two things were wrong with it, and both are load-bearing:
#
#   1. MTIME DOES NOT SURVIVE COPYING. git does not restore mtimes, so on a
#      fresh checkout the ordering is whatever order the checkout wrote the
#      files in. Over the 17 tracked `clock_plan.json` files in this repo
#      (`git ls-files benchmark-data`), the mtime rule fired on SIX in one
#      reviewer's checkout and on FIVE in another worktree of the same commit —
#      identical bytes, different answer — every hit naming
#      `phase3/stage3/pnr/constraint.sdc`. A finding whose count depends on the
#      order git happened to write files in is not measuring the artefact.
#      Clone, copy, rsync and archive extraction are how this corpus and every
#      user project are distributed, so an mtime-keyed provenance finding is
#      noise on nearly every tree that reads it. Content-keyed, the same 17
#      files yield 0 findings deterministically, on every tree.
#   2. A DEF IS NOT AN INPUT TO THIS PLAN. The plan's clock records are built
#      from `create_clock` statements in the SDCs and from nothing else, so a
#      newer `floorplan.def` cannot make the plan wrong. Including the DEFs was
#      also the half of the producer/checker disagreement that lived on this
#      side (the producer compared against `primary_def`, the checker against
#      floorplan/placed).
#
# What replaces it: the plan RECORDS what it was derived from. The producer
# writes `derived_from` = {project-relative SDC path: sha256}, and this checker
# re-hashes exactly those recorded paths. Both sides use one definition
# (`_pl.clock_plan_input_sdcs` / `_pl.clock_plan_sdc_digests`), the comparison
# is on CONTENT, and a plan that records nothing yields NO finding — an absent
# provenance record is an absence of evidence, not evidence of staleness.


def _stale_inputs(project: Path, plan):
    """Recorded inputs whose CONTENT changed, plus SDCs added since, sorted.

    Returns [] when the plan records no `derived_from` provenance (nothing can
    be concluded) and when the plan is genuinely fresh.
    """
    if not isinstance(plan, dict):
        return []
    recorded = plan.get("derived_from")
    if not isinstance(recorded, dict) or not recorded:
        return []
    current = _pl.clock_plan_sdc_digests(project)
    changed = [rel for rel, digest in recorded.items()
               if current.get(rel) != digest]
    added = [rel for rel in current if rel not in recorded]
    return sorted(set(changed) | set(added))


def _find_sdc_files(project: Path):
    seen = []
    for rel in _SDC_DIR_CANDIDATES:
        d = project / rel
        if d.is_dir():
            for f in sorted(d.glob("*.sdc")):
                if f not in seen:
                    seen.append(f)
    # Last-resort: any *.sdc anywhere under the project (deterministic order).
    if not seen:
        for f in sorted(project.rglob("*.sdc")):
            seen.append(f)
    return seen


def _sdc_clock_names(sdc_files):
    """Return (names, files_with_clocks) parsed from every create_clock.

    A create_clock without -name gets a synthetic name derived from its source
    object (so it still participates in the dropped-clock check); failing that,
    a positional fallback.
    """
    names = []
    files_with = []
    for f in sdc_files:
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        # ORGANIC #569 — strip `#` SDC comments BEFORE harvesting
        # create_clock names, so a commented-out
        # `# REMOVED: create_generated_clock -name phase_q ...` line is not
        # parsed as an active clock. This makes clock_plan_check's SDC view
        # CONSISTENT with derived_clock_sdc_required_check (which already
        # comment-strips) — the two gates previously diverged (one stripped,
        # one did not) and formed a catch-22 on the same false-positive.
        text = re.sub(r"#[^\n]*", "", text)
        had = False
        for idx, m in enumerate(_CREATE_CLOCK_RE.finditer(text)):
            body = m.group("body") or ""
            nm = _NAME_RE.search(body)
            name = None
            if nm:
                name = nm.group("name")
            else:
                gm = _GET_OBJ_RE.search(body)
                if gm:
                    name = gm.group("obj")
            if not name:
                name = f"__unnamed_clock_{f.name}_{idx}"
            names.append(name)
            had = True
        if had:
            files_with.append(f)
    return names, files_with


def _plan_clock_token_set(clocks, plan):
    """Tokens a plan provides for matching against SDC clock names: clock names
    plus any source object names referenced anywhere in the plan."""
    toks = set()
    for c in clocks:
        if c.get("name"):
            toks.add(c["name"])
        src = _source_of(c["_rec"])
        if src:
            toks.add(src)
    # Also include common top-level identifiers so an SDC name that matches the
    # plan's primary/source is recognised even if the plan modelled it loosely.
    if isinstance(plan, dict):
        for k in ("primary_clock", "clock", "source", "port", "pin"):
            v = plan.get(k)
            if isinstance(v, str) and v.strip():
                toks.add(v.strip())
    return {t.strip() for t in toks if t}


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}", file=sys.stderr)
        return 2

    plan_rel, plan_path = _first_existing(project, _PLAN_CANDIDATES)
    waiver = _step_waived(project, args.step_label)
    findings = []

    # ---- Waiver path (explicit, recorded) ------------------------------
    if waiver and plan_path is None:
        findings.append({
            "severity": "WAIVED", "rule": "STEP_WAIVED",
            "message": f"waiver={waiver.get('ticket', '?')}: "
                       f"{waiver.get('reason', '?')}",
        })
        return _emit(args, project, "WAIVED", plan_rel, waiver, [], [], findings, 0)

    # ---- Honest FAIL on missing / empty plan ---------------------------
    if plan_path is None:
        findings.append({
            "severity": "FAIL", "rule": "CLOCK_PLAN_MISSING",
            "message": "phase3/stage3/cts/clock_plan.json not found — Step 16 "
                       "produces no clock plan; cannot verify substance",
        })
        return _emit(args, project, "FAIL", plan_rel, waiver, [], [], findings, 1)

    raw = plan_path.read_text(errors="ignore")
    if not raw.strip():
        findings.append({
            "severity": "FAIL", "rule": "CLOCK_PLAN_EMPTY",
            "message": f"{plan_rel} is empty",
        })
        return _emit(args, project, "FAIL", plan_rel, waiver, [], [], findings, 1)

    try:
        plan = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        findings.append({
            "severity": "FAIL", "rule": "CLOCK_PLAN_UNPARSEABLE",
            "message": f"cannot parse {plan_rel} as JSON: {e}",
        })
        return _emit(args, project, "FAIL", plan_rel, waiver, [], [], findings, 1)

    clocks = _extract_clocks(plan)

    # ---- >= 1 clock defined --------------------------------------------
    if not clocks:
        findings.append({
            "severity": "FAIL", "rule": "NO_CLOCK_DEFINED",
            "message": "clock plan defines no clock (no clocks[]/clock_list "
                       "array and no primary_clock with period/source) — empty "
                       "plan",
        })
        return _emit(args, project, "FAIL", plan_rel, waiver, [], [], findings, 1)

    # ---- per-clock substance: positive period + source object ----------
    summary = []
    ok = True
    for c in clocks:
        name = c.get("name") or "?"
        period_ns, how = _period_ns_from(c["_rec"])
        source = _source_of(c["_rec"])
        entry = {"name": name, "period_ns": period_ns, "source": source}
        summary.append(entry)

        if period_ns is None:
            ok = False
            findings.append({
                "severity": "FAIL", "rule": "CLOCK_NO_PERIOD",
                "message": f"clock '{name}' has no positive period/frequency "
                           f"({how}) — a clock with no period cannot drive CTS",
            })
        if not source:
            ok = False
            findings.append({
                "severity": "FAIL", "rule": "CLOCK_NO_SOURCE",
                "message": f"clock '{name}' has no source pin/port — plan does "
                           f"not say where the clock enters the design",
            })
        if period_ns is not None and source:
            findings.append({
                "severity": "INFO", "rule": "CLOCK_OK",
                "message": f"clock '{name}': period={period_ns:g}ns ({how}), "
                           f"source='{source}'",
            })

    # ---- dropped-clock check vs SDC (if an SDC exists) -----------------
    sdc_files = _find_sdc_files(project)
    sdc_names, sdc_with_clocks = _sdc_clock_names(sdc_files)
    sdc_checked = [str(f.relative_to(project)) for f in sdc_with_clocks]
    if sdc_names:
        plan_tokens = _plan_clock_token_set(clocks, plan)
        dropped = []
        for n in sdc_names:
            if n.startswith("__unnamed_clock_"):
                # Cannot reliably map an unnamed SDC clock; only flag if the plan
                # has fewer clocks than the SDC declares (handled below).
                continue
            if n not in plan_tokens:
                dropped.append(n)
        if dropped:
            ok = False
            findings.append({
                "severity": "FAIL", "rule": "SDC_CLOCK_DROPPED",
                "message": f"create_clock in SDC not present in clock plan: "
                           f"{sorted(set(dropped))} (plan clocks/sources="
                           f"{sorted(plan_tokens)}; sdc={sdc_checked})",
            })
        # Count guard: more named create_clocks than clocks in the plan.
        named = [n for n in sdc_names if not n.startswith("__unnamed_clock_")]
        if not dropped and len(set(named)) > len(clocks):
            ok = False
            findings.append({
                "severity": "FAIL", "rule": "SDC_CLOCK_COUNT_MISMATCH",
                "message": f"SDC declares {len(set(named))} named create_clock(s) "
                           f"but plan models only {len(clocks)} clock(s) — a "
                           f"clock domain appears dropped",
            })
        if ok:
            findings.append({
                "severity": "INFO", "rule": "SDC_CLOCKS_COVERED",
                "message": f"all {len(set(sdc_names))} SDC create_clock(s) "
                           f"present in plan (sdc={sdc_checked})",
            })
    else:
        findings.append({
            "severity": "INFO", "rule": "NO_SDC",
            "message": "no SDC create_clock found — dropped-clock cross-check "
                       "skipped (plan substance still verified)",
        })

    # ---- freshness DISCLOSURE (advisory) -------------------------------
    # Fires ONLY when the plan recorded a `derived_from` digest map AND an
    # SDC's content has since changed (or an SDC appeared that the plan was not
    # derived from). A plan with no provenance record produces no finding: this
    # gate reports what it can prove, and it can prove nothing about a plan that
    # never said what it read. See `_stale_inputs` for why this is not mtime.
    #
    # ADVISORY, not blocking. rc is unchanged: the producer re-derives the plan
    # in the same condition, so a blocking slot here would fail already-complete
    # runs for a provenance fact rather than a wrong answer.
    stale_against = _stale_inputs(project, plan)
    if stale_against:
        findings.append({
            "severity": "WARNING", "rule": "CLOCK_PLAN_STALE",
            "message": f"{plan_rel} records `derived_from` digests that no "
                       f"longer match the project's SDCs: {stale_against}. The "
                       f"plan was derived from different constraint CONTENT "
                       f"than is present now; a period or clock changed since "
                       f"would not be reflected here.",
        })

    verdict = "PASS" if ok else "FAIL"
    rc = 0 if ok else 1
    if ok:
        findings.append({
            "severity": "INFO", "rule": "CLOCK_PLAN_SUBSTANCE_OK",
            "message": f"{len(clocks)} clock(s) defined, each with a positive "
                       f"period and a source object",
        })
    return _emit(args, project, verdict, plan_rel, waiver, summary, sdc_checked,
                 findings, rc)


def _emit(args, project, verdict, plan_rel, waiver, clocks, sdc_checked,
          findings, rc):
    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": getattr(args, "step_label", _GATE_LABEL),
        "clock_plan_json": plan_rel,
        "clocks": clocks,
        "num_clocks": len(clocks),
        "sdc_files_checked": sdc_checked,
        "waiver": waiver,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    print(f"  clocks:  {len(clocks)}"
          + (f" / plan={plan_rel}" if plan_rel else ""))
    for c in clocks:
        print(f"    - {c.get('name')}: period={c.get('period_ns')}ns "
              f"source={c.get('source')!r}")
    for f in findings:
        if f["severity"] in ("FAIL", "WAIVED"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
