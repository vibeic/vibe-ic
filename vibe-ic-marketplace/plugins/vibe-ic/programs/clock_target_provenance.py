#!/usr/bin/env python3
"""clock_target_provenance.py — say WHERE the clock period a run signs off
against came from, and mark it ASSUMED when the design never stated one.

THE DEFECT THIS CLOSES (measured, vibe-ic#2091, opentitan_aes x sky130A)
=======================================================================
The whole opentitan_aes input states no target clock period for the sky130A
build.  The only frequency anywhere in it is a reference point attached to an
entropy-rate figure::

    input/docs/aes_README.md:36
      "...max entropy consumption rates ranging from 343 Mbit/s to
       0.042 Mbit/s (at 100 MHz)."

Phase 1's L8 nevertheless shipped ``clk_i`` at ``period_ns: 10.0`` and the run
signed off post-route timing against it — WNS reached -42.140 ns.  Nowhere in
the SDC, the STA reports or the sign-off record does a single line say that the
10 ns is not a specification.  A reader of that verdict has no way to tell a
design that MISSED its target from a design that was never given one.

`_resolve_clock_spec` in the Phase-3 runner already walks a documented ladder
of period sources, ending in a last-resort plugin literal.  What it does NOT do
is report WHICH rung answered — it returns a bare float.  So the difference
between "the design declared this" and "the plugin supplied this because the
design did not" is erased at the one call every downstream consumer reads.

WHAT THIS PROGRAM DOES
======================
It re-walks the same ladder for the purpose of PROVENANCE ONLY and returns the
tier that answered, its citation, and — the load-bearing field — ``assumed``.

It deliberately does NOT resolve the period for the flow.  Resolution stays
where it is; this is an additive disclosure.  Two readers of the same project
must not be able to disagree about the number, so when the caller already has
the resolved period it passes it in and this program only classifies it.

THE TIERS, highest authority first, matching `_resolve_clock_spec`:

    staged_sdc            input/constraints/*.sdc, input/reference_flow/**.sdc
    declared_pdk_table    a period-keyed table row matching this run's library
    phase2_emitted_sdc    a create_clock Phase 2 already wrote
    l8_declared           L8 clock_domains[] / clocks[] carrying a period
    doc_prose             an L9/L1 `-period <num>` statement
    config_json           CLOCK_PERIOD in a config.json
    plugin_default        NOTHING IN THE DESIGN SAID SO   <-- assumed = True

``assumed`` is True for exactly one tier.  Every other tier cites a file the
design owns, and a caller that reports "the design declared X" about them is
telling the truth.

SUFFICIENCY: WHY THIS ASSUMES AND DECLARES RATHER THAN REFUSING
==============================================================
`phase1_sufficiency_check`'s own severity model settles this, and it is worth
quoting because the alternative reading is defensible until you read it::

    ADVISORY : warn only ... NEVER blocking (clock/reset is advisory even on a
               sequential design)
    ... the deterministic gate never blocks on clock/reset.

So the flow's own definition of sufficiency says a missing clock target is an
ADVISORY, not a REQUIRED fact — the deterministic track must not refuse the
run over it.  The IC-expert dialogue track ASKS (a plain-language question,
which `phase1_sufficiency_check` now emits), and the doc-only Path-B track
proceeds with the value RECORDED AS AN ASSUMPTION.  That is this program's
contract: never invent silently, never refuse on the deterministic track.

``would_have_stated`` carries the sentence the input would have had to contain
for the value to be a specification, so the assumption is actionable and not
just labelled.

HONESTY BOUNDARY (§4.05)
========================
Only the design INPUT and the run's own generated artefacts are read; no
oracle, harness or golden.  Nothing is defaulted here — when no tier answers,
``period_ns`` is None and ``tier`` is ``not_determined``.  A prose statement is
consulted through `_prose_polarity` (the repo's one negation vocabulary), so a
sentence that RETRACTS a period is not published as a declaration.

Chip / PDK-AGNOSTIC: no chip, vendor, PDK or library literal appears here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
from _prose_polarity import is_denied as _is_denied  # noqa: E402

#: The one tier that means "the design did not say".
PLUGIN_DEFAULT_TIER = "plugin_default"
#: No tier answered at all.
NOT_DETERMINED_TIER = "not_determined"

#: Tier order = authority order, highest first. Mirrors
#: `phase3_one_shot_runner._resolve_clock_spec`'s documented ladder.
TIERS: Sequence[str] = (
    "staged_sdc",
    "declared_pdk_table",
    "phase2_emitted_sdc",
    "l8_declared",
    "doc_prose",
    "config_json",
    PLUGIN_DEFAULT_TIER,
)

#: The disclosure sentence a consumer MUST carry when `assumed` is True.
#: One constant, so the emitter and the checker cannot drift apart.
ASSUMED_DISCLOSURE = (
    "timing measured against an ASSUMED clock period, not a spec")

_PERIOD_TOKEN_RE = re.compile(
    r"(?:CLOCK_PERIOD|-period|clock period|時脈週期)\s*"
    # A document writes the copula as often as it writes a colon
    # ("the clock period IS 8 ns"); the Phase-3 prose regex accepts only the
    # punctuated form, and a statement it cannot read is a statement this
    # program would misreport as ABSENT — which is the #2091 harm pointed the
    # other way.
    r"(?:is|of|=|:)?\s*"
    r"\*?\*?(\d+(?:\.\d+)?)\*?\*?\s*(?:ns\b)?", re.IGNORECASE)
_CREATE_CLOCK_PERIOD_RE = re.compile(
    r"create_clock[^\n]*?-period\s+(\d+(?:\.\d+)?)", re.IGNORECASE)

# A numeric clock observation is not automatically a physical implementation
# target. The producer stamps this status into ``freq_evidence`` and every
# physical consumer reads the same finite vocabulary. Missing status remains
# DECLARED for backwards compatibility with older design-owned L8 records.
PHYSICAL_TARGET_STATUS_KEY = "physical_target_status"
PHYSICAL_TARGET_DECLARED = "DECLARED"
PHYSICAL_TARGET_CONTEXT_ONLY = "CONTEXT_ONLY"
PHYSICAL_TARGET_AMBIGUOUS = "AMBIGUOUS"

_SIMULATION_CONTEXT_RE = re.compile(
    r"\bfor\s+(?=[^.!?\n]*(?:lint|simulation)\b)"
    r"(?=[^.!?\n]*(?:context|purposes?|only)\b)"
    r"[^.!?\n]*(?:lint|simulation)\b[^.!?\n]*"
    r"(?:context|purposes?|only)\b",
    re.IGNORECASE,
)
_PHYSICAL_TARGET_RE = re.compile(
    r"\b(?:for|as)\s+(?:the\s+)?physical\s+"
    r"(?:implementation|sign-?off)(?:\s+(?:clock\s+)?(?:target|constraint))?\b|"
    r"\b(?:physical\s+)?(?:implementation|sign-?off)\s+"
    r"(?:clock\s+)?(?:target|constraint)\b",
    re.IGNORECASE,
)


def physical_target_status(text: object) -> str:
    """Classify the bounded clock-use qualifier on one evidence sentence."""
    value = text if isinstance(text, str) else ""
    contextual = bool(_SIMULATION_CONTEXT_RE.search(value))
    physical = bool(_PHYSICAL_TARGET_RE.search(value))
    if contextual and physical:
        return PHYSICAL_TARGET_AMBIGUOUS
    if contextual:
        return PHYSICAL_TARGET_CONTEXT_ONLY
    return PHYSICAL_TARGET_DECLARED


def clock_record_physical_target_status(rec: object) -> str:
    """Return one L8 record's physical-target authority, fail-closed."""
    if not isinstance(rec, dict):
        return PHYSICAL_TARGET_AMBIGUOUS
    evidence = rec.get("freq_evidence")
    if not isinstance(evidence, dict) or PHYSICAL_TARGET_STATUS_KEY not in evidence:
        return PHYSICAL_TARGET_DECLARED
    status = evidence.get(PHYSICAL_TARGET_STATUS_KEY)
    if status in (PHYSICAL_TARGET_DECLARED, PHYSICAL_TARGET_CONTEXT_ONLY,
                  PHYSICAL_TARGET_AMBIGUOUS):
        return status
    return PHYSICAL_TARGET_AMBIGUOUS


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _sdc_period(paths: Sequence[Path]) -> Optional[Dict[str, object]]:
    for p in paths:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for m in _CREATE_CLOCK_PERIOD_RE.finditer(text):
            val = _f(m.group(1))
            if val is None:
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            return {"period_ns": val, "cite": f"{p}:{line_no}",
                    "row": m.group(0).strip()[:200]}
    return None


def _staged_sdc(project: Path) -> Optional[Dict[str, object]]:
    # The flow's one staged-SDC collector, so this record and the SDC the flow
    # signs off against are read from the same files. A private copy of the two
    # globs read `input/constraints/golden_timing.sdc` here after the collector
    # stopped (FX_405, §4.05): the provenance and L19 cited the golden clock.
    import sdc_constraints as _sdc  # noqa: PLC0415
    return _sdc_period(list(_sdc.collect_sdc_files(project)))


def _phase2_sdc(project: Path) -> Optional[Dict[str, object]]:
    cands: List[Path] = []
    for sub in ("phase2/stage1/fpga", "phase2/stage2/constraints"):
        d = project / sub
        if d.is_dir():
            cands.extend(sorted(d.rglob("*.sdc")))
    return _sdc_period(cands)


def _l8_declared(project: Path) -> Optional[Dict[str, object]]:
    """A period L8 carries on a clock record, when L8 is unambiguous."""
    gd = project / "phase1" / "generated_docs"
    vals: List[float] = []
    cite = None
    for name in ("L8_RTL_CONSTANTS.json", "L8_TIMING_WAVEFORM.json"):
        p = gd / name
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(errors="replace"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        mhz = _f(data.get("clock_mhz"))
        if mhz:
            vals.append(round(1000.0 / mhz, 6))
            cite = cite or f"{p}::clock_mhz"
        for key in ("clock_domains", "clocks"):
            for rec in (data.get(key) or []):
                if not isinstance(rec, dict):
                    continue
                if (clock_record_physical_target_status(rec)
                        != PHYSICAL_TARGET_DECLARED):
                    continue
                per = _f(rec.get("period_ns"))
                if per is None:
                    m = _f(rec.get("freq_mhz"))
                    per = round(1000.0 / m, 6) if m else None
                if per is None:
                    continue
                vals.append(round(per, 6))
                cite = cite or f"{p}::{key}[{rec.get('name')}]"
    uniq = sorted(set(vals))
    if len(uniq) != 1:
        return None       # absent, or contradictory — either way not a declaration
    return {"period_ns": uniq[0], "cite": cite or str(gd), "row": ""}


def _doc_prose(project: Path) -> Optional[Dict[str, object]]:
    docs_dir = project / "input" / "docs"
    if not docs_dir.is_dir():
        return None
    for md in (sorted(docs_dir.glob("L9_*.md"))
               + sorted(docs_dir.glob("L1_*.md"))):
        try:
            text = md.read_text(errors="replace")
        except OSError:
            continue
        for m in _PERIOD_TOKEN_RE.finditer(text):
            val = _f(m.group(1))
            if val is None:
                continue
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            line = text[line_start:line_end if line_end != -1 else len(text)]
            # vibe-ic#712 — a RETRACTED period is not a declared period. This
            # value lands in the SDC that pins the whole backend, which is the
            # literal form of that harm, so the polarity consult is not a
            # formality here.
            if _is_denied(line):
                continue
            if physical_target_status(line) != PHYSICAL_TARGET_DECLARED:
                continue
            return {"period_ns": val,
                    "cite": f"{md}:{text.count(chr(10), 0, m.start()) + 1}",
                    "row": line.strip()[:200]}
    return None


def _config_json(project: Path) -> Optional[Dict[str, object]]:
    cands = [project / "config.json"]
    cands.extend(sorted(project.glob("baseline/*/config.json")))
    cands.extend(sorted(project.glob("plugin_output/openlane_workdir*/config.json")))
    for p in cands:
        if not p.is_file():
            continue
        try:
            cfg = json.loads(p.read_text(errors="replace"))
        except Exception:
            continue

        def walk(d):
            if isinstance(d, dict):
                if "CLOCK_PERIOD" in d:
                    v = _f(d["CLOCK_PERIOD"])
                    if v is not None:
                        return v
                for v in d.values():
                    r = walk(v)
                    if r is not None:
                        return r
            return None
        val = walk(cfg)
        if val is not None:
            return {"period_ns": val, "cite": f"{p}::CLOCK_PERIOD", "row": ""}
    return None


_FINDERS = (
    ("staged_sdc", _staged_sdc),
    ("declared_pdk_table", None),   # filled in by resolve(), needs the library
    ("phase2_emitted_sdc", _phase2_sdc),
    ("l8_declared", _l8_declared),
    ("doc_prose", _doc_prose),
    ("config_json", _config_json),
)


def _declared_pdk_table(project: Path, library: str, pdk: str):
    if not (library or pdk):
        return None
    try:
        import declared_clock_period as _dcp
    except Exception:
        return None
    try:
        rep = _dcp.declared_period_ns(
            _dcp.docs_in(project / "input" / "docs"),
            [c for c in (library, pdk) if c])
    except Exception:
        return None
    if not rep.get("period_ns"):
        return None
    return {"period_ns": float(rep["period_ns"]),
            "cite": f"{rep.get('source')}:{rep.get('line')}",
            # L19 makes the embedded source citation project-relative. Keep
            # it intact here; truncating first cuts long temporary paths and
            # discards the filename/line before that consumer can read them.
            "row": str(rep.get("note", ""))}


def resolve(project: Path, *, pdk: str = "", library: str = "",
            applied_period_ns: Optional[float] = None) -> Dict[str, object]:
    """Classify the clock period this project's flow will sign off against.

    ``applied_period_ns`` is the number the flow actually resolved.  When it is
    supplied and no design-owned tier answered, the tier is ``plugin_default``
    and ``assumed`` is True — the honest statement that the number came from
    the plugin, not the design.  When it is omitted and no tier answers, the
    tier is ``not_determined`` and no number is published.
    """
    rep: Dict[str, object] = {
        "project": str(project),
        "pdk": pdk,
        "library": library,
        "period_ns": None,
        "tier": NOT_DETERMINED_TIER,
        "assumed": False,
        "cite": None,
        "row": "",
        "tiers_consulted": [],
        "would_have_stated": "",
        "disclosure": "",
        "note": "",
    }
    consulted: List[str] = []
    for tier, fn in _FINDERS:
        consulted.append(tier)
        hit = (_declared_pdk_table(project, library, pdk)
               if tier == "declared_pdk_table" else fn(project))
        if hit:
            rep.update({"period_ns": float(hit["period_ns"]), "tier": tier,
                        "cite": hit.get("cite"), "row": hit.get("row", "")})
            rep["tiers_consulted"] = consulted
            rep["note"] = (
                f"the design declares {rep['period_ns']:g} ns via '{tier}' "
                f"at {rep['cite']}")
            return rep
    rep["tiers_consulted"] = consulted
    rep["would_have_stated"] = (
        "no target clock period is stated for "
        f"'{pdk or library or 'the target library'}' anywhere in the design "
        "input; a statement of the form 'target clock period for "
        "<library> = <N> ns' in an input document, or a create_clock "
        "-period line in input/constraints/, would make it a specification")
    if applied_period_ns is None:
        rep["note"] = ("NOT DETERMINED — no tier of the period ladder "
                       "answered and no applied period was supplied")
        return rep
    rep.update({
        "period_ns": float(applied_period_ns),
        "tier": PLUGIN_DEFAULT_TIER,
        "assumed": True,
        "cite": None,
        "disclosure": (f"{ASSUMED_DISCLOSURE}: {float(applied_period_ns):g} ns "
                       "was supplied by the flow, not by the design input"),
    })
    rep["note"] = rep["disclosure"] + " — " + str(rep["would_have_stated"])
    return rep


# ── the flow-facing half: write the report, stamp the sign-off record ───────
#
# These two live HERE and not in `phase3_one_shot_runner` on purpose. The
# runner ORCHESTRATES — it resolves the period it already resolves and hands it
# over; a `clock`-named helper defined in the runner is timing logic in the
# orchestrator, and `test_ppa_runner_extraction_ledger` is the gate that says
# so. It caught exactly that in this change's first shape.

#: Where the run's clock-target provenance is published, project-relative.
PROVENANCE_REL = "reports/phase3/clock_target_provenance.json"

#: The sign-off records that may carry the disclosure. A record that is absent
#: cannot excuse a record that is present, so every one that EXISTS is stamped.
SIGNOFF_RELS = (
    "reports/phase3/sta/post_route_summary.json",
    "reports/phase3/sta/post_route_signoff_corner.json",
    "reports/phase3/post_route_signoff_corner.json",
)


def emit_report(project: Path, *, pdk: str = "", library: str = "",
                applied_period_ns: Optional[float] = None) -> Dict[str, object]:
    """Resolve the provenance and publish it at :data:`PROVENANCE_REL`."""
    rep = resolve(project, pdk=pdk, library=library,
                  applied_period_ns=applied_period_ns)
    out = project / PROVENANCE_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out, json.dumps(rep, indent=2) + "\n")
    return rep


def stamp_signoff_records(project: Path) -> List[str]:
    """Stamp the assumption into every sign-off record that exists.

    The flag AND the sentence, both: a flag with no sentence is invisible in
    every report a human reads, and a sentence with no flag cannot be enforced
    anywhere else. `sta_assumed_clock_disclosure_check` asserts exactly this
    pair, importing the sentence from :data:`ASSUMED_DISCLOSURE` so the writer
    and the checker cannot drift into asserting different strings.

    A run whose period is DESIGN-OWNED is stamped with nothing — the records'
    bytes are left exactly as they were. Returns the paths it rewrote.
    """
    written: List[str] = []
    try:
        prov = json.loads((project / PROVENANCE_REL).read_text(errors="replace"))
    except Exception:
        return written
    if not (isinstance(prov, dict) and prov.get("assumed")):
        return written
    note = (f"{ASSUMED_DISCLOSURE}: {float(prov['period_ns']):g} ns was "
            f"supplied by the flow, not by the design input. "
            f"{prov.get('would_have_stated', '')}")
    # Step 23 on the tool (F15): STAPostPNR's own sign-off record is a
    # sign-off record too, and `sta_assumed_clock_disclosure_check` reads it.
    from librelane_signoff import SIGNOFF_RECORD
    for rel in SIGNOFF_RELS + (SIGNOFF_RECORD,):
        f = project / rel
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(errors="replace"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        data["clock_period_assumed"] = True
        data["clock_period_ns"] = float(prov["period_ns"])
        data["clock_period_note"] = note
        data["clock_period_provenance"] = PROVENANCE_REL
        atomic_write_text(f, json.dumps(data, indent=2) + "\n")
        written.append(str(f))
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Report WHERE this run's clock period came from, and "
                    "whether it is an assumption rather than a spec.")
    ap.add_argument("project")
    ap.add_argument("--pdk", default="")
    ap.add_argument("--library", default="")
    ap.add_argument("--applied-period-ns", type=float, default=None)
    ap.add_argument("--json", help="write the structured report here")
    args = ap.parse_args(argv)
    rep = resolve(Path(args.project), pdk=args.pdk, library=args.library,
                  applied_period_ns=args.applied_period_ns)
    if args.json:
        atomic_write_text(Path(args.json), json.dumps(rep, indent=2) + "\n")
    print(json.dumps(rep, indent=2))
    # 0 = the design owns the period; 1 = it is assumed; 2 = not determined.
    if rep["tier"] == NOT_DETERMINED_TIER:
        return 2
    return 1 if rep["assumed"] else 0


if __name__ == "__main__":
    sys.exit(main())
