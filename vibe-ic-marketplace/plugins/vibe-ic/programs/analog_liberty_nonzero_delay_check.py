#!/usr/bin/env python3
"""analog_liberty_nonzero_delay_check.py — deterministic Liberty non-degeneracy gate.

Extracted from the `analog-hardmacro-gen` skill "Do not" rule:
    "Do not generate Liberty with zero delays — use actual SPICE-measured values"
and the Step-3 worst-case-corner requirement
    "Derived from SPICE corner results (worst-case SS corner)".

The skill documented these as prose; this program turns the
non-degeneracy half into a deterministic structural check on the
emitted Liberty (`hardmacro/<block>/<block>.lib`):

  1. The .lib parses to a `library(...) { cell(<block>) { ... } }` shape.
  2. The cell carries at least one timing-bearing numeric attribute and
     ALL such numbers are non-zero — i.e. it is NOT a zero-delay /
     area-only stub. Timing-bearing attributes checked:
        cell_rise / cell_fall / rise_transition / fall_transition
        cell_leakage_power / leakage_power value
        intrinsic_rise / intrinsic_fall
        timing() { ... values( ... ) ... }  (NLDM table — any non-zero entry)
  3. If `analog/<block>/corner_results.json` exists, its provenance is
     reported (real_ngspice vs stub) so a reviewer can see whether the
     Liberty was derived from a real corner sweep.
  4. If the design declares a clock period in its SDC or L8, every Liberty
     propagation-delay arc must fit within that period. An analog settling
     time longer than a clock period is an interface contract, not a
     synchronous cell arc; it belongs in `interface.json` `timing_contract`.

The defect this catches (real): a Liberty that only declares `area`
(or whose every delay is `0.0`) passes STA vacuously — every path has
zero delay, so the macro never violates setup/hold and the integration
STA is meaningless. That is exactly the stub Liberty emitted at the
A7 stub tier (`library(ldo_stub) { cell(ldo) { area : 10000 ; } }`).

Honesty rules (NO vacuous PASS):
  * No analog blocks                 -> VACUOUS (rc 2).
  * .lib missing for a spec'd block  -> FAIL (cannot sign off STA).
  * .lib present but unparseable     -> FAIL.
  * .lib has a cell but NO timing-bearing attribute at all -> FAIL
    (area-only stub, the documented zero-delay defect).
  * .lib has a timing attribute whose value is 0 / 0.0 -> FAIL.
  * .lib is non-degenerate, and NOTHING says what circuit those delays
    model -> FAIL (LIB_SUBJECT_UNDECLARED). Asked LAST, after every rule
    above. A model that records a library default still signs off, in the
    PASS_STRUCTURE_ONLY tier; only silence costs.

Usage:
    python3 analog_liberty_nonzero_delay_check.py <project_dir>
    python3 analog_liberty_nonzero_delay_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS: at least one analog block was found and every Liberty is
        non-degenerate
    1 = FAIL (>=1 zero-delay / stub / missing Liberty)
    2 = VACUOUS: nothing was examined — this project declares no analog block,
        so there is no Liberty to prove non-degenerate. #521: the header
        already said "Honesty rules (NO vacuous PASS)" and this branch was
        exactly that, exiting 0 on 197 of the 200 tracked project roots. Also
        rc 2 for an IO / argument error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Tuple

try:
    import _path_layout as _pl
except ImportError:  # pragma: no cover
    _pl = None

import _vacuous_exit as _vx
import _analog_a_check_common as _acc
from macro_non_seq_arc_contract_check import design_clock_period_ns
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


# ── A NON-ZERO DELAY IS A DELAY OF SOMETHING ──────────────────────────────
# THE RULE, with no tool, step or block name in it:
#
#   A gate that signs off a model another tool will consume is certifying
#   what that model represents. It must read what the model represents, and
#   an artefact that declines to say what it contains must not certify the
#   step it is the evidence for.
#
# MEASURED, on three synthetic trees identical in every artefact except the
# one recorded `design_content` value: this gate signed off the Liberty that
# INTEGRATION STA WILL CONSUME with `[PASS]` rc 0 and a byte-identical
# `--json` on all three — including the tree whose corner artefact records,
# in as many words, that its circuit came from a topology library and that no
# bound input reached any device parameter. A non-degenerate delay taken from
# a library nominal is a real number about a library nominal; STA closed on it
# is closed on a circuit this project did not design.
#
# WHERE THE ANSWER IS READ, and why it is not this file's own record. Nothing
# writes `design_content` into a `.lib`; asking the Liberty its own question
# would classify EVERY tree undisclosed and fail the honest one too. The
# record belongs to the artefact the delays are DERIVED FROM — the corner
# sweep, which this gate ALREADY opens for exactly this purpose. Until now it
# read `_provenance` from it and reported `corner provenance=real_ngspice`:
# true of the simulator, silent about the subject, which is the defect this
# whole track started from, one field along. The chain is ordered nearest
# first and ends at the corner artefact — the gate of record for that content
# — so this gate can never certify a tree its own gate of record refuses.
#
# THREE OUTCOMES, ranked so that disclosure is never the expensive answer:
#   design-bound   -> PASS, unchanged.
#   structure-only -> PASS_STRUCTURE_ONLY. Certifies, in its own tier.
#   undisclosed    -> does not certify. Including the case where NO corner
#                     artefact exists at all: then nothing anywhere says what
#                     circuit these delays model, and a Liberty that will not
#                     name its subject must not be signed off for STA.
#
# ASKED LAST, after every value rule (missing / unreadable / no cell / no
# timing / all-zero), each of which already `continue`s. Those name a deeper
# cause and answer this one as a side effect; the reverse is not true.
#
# THE SITE MOVED, THE BEHAVIOUR DID NOT. This gate was the first to get the
# rule right, and it kept the rule in a PRIVATE constant. Two other gates over
# the same package (`analog_hardmacro_check`, which is the one the FLOW
# declares for A8, and `analog_a8_hardmacro_gen_check`) then answered
# PASS / PASS / PASS on the three trees this one reads
# PASS / PASS_STRUCTURE_ONLY / FAIL over. A private constant is how that
# happened, so the rule now lives at ONE site,
# `_analog_a_check_common.hardmacro_content`, and every gate over the package
# calls it. This name is kept, pointing at the shared constant, so a reader of
# this file still sees what is read.
_CONTENT_CHAIN = (_acc.CONTENT_GATE_OF_RECORD_ARTEFACT,)


# Timing-bearing scalar attributes (single `attr : value ;`).
_SCALAR_TIMING_ATTRS = (
    "cell_rise", "cell_fall", "rise_transition", "fall_transition",
    "intrinsic_rise", "intrinsic_fall", "cell_leakage_power",
)
_SCALAR_RE = {
    a: re.compile(rf"\b{a}\s*:\s*([-+0-9.eE]+)\s*;")
    for a in _SCALAR_TIMING_ATTRS
}

# NLDM-style table: values("0.1, 0.2", "0.3, 0.4");  inside a timing()/
# table group. We pull every numeric token out of every values(...) blob.
_VALUES_RE = re.compile(r"values\s*\(", re.IGNORECASE)
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_LEAKAGE_GROUP_RE = re.compile(
    r"leakage_power\s*\([^)]*\)\s*\{(?P<body>.*?)\}", re.DOTALL | re.IGNORECASE)
_LEAKAGE_VALUE_RE = re.compile(r"\bvalue\s*:\s*([-+0-9.eE]+)\s*;")
_CELL_RE = re.compile(r"\bcell\s*\(\s*([^)\s]+)\s*\)\s*\{", re.IGNORECASE)

# A propagation delay is not the same thing as a leakage number or an output
# transition. The comparison below therefore reads only the Liberty groups
# that STA treats as propagation delays. This distinction is load-bearing for
# analog macros: a leakage+capacitance-only model is valid, while copying a
# microsecond analog settling measurement into cell_rise/cell_fall fabricates a
# synchronous path through the macro.
_ARC_DELAY_ATTRS = (
    "cell_rise", "cell_fall", "intrinsic_rise", "intrinsic_fall",
)
_ARC_GROUP_RE = re.compile(
    rf"\b(?P<kind>{'|'.join(_ARC_DELAY_ATTRS)})\s*"
    r"(?:\([^)]*\))?\s*\{",
    re.IGNORECASE,
)
_TIME_UNIT_RE = re.compile(
    r"\btime_unit\s*:\s*\"?\s*"
    r"(?P<mult>\d+(?:\.\d+)?)\s*(?P<unit>fs|ps|ns|us|ms|s)\s*\"?\s*;",
    re.IGNORECASE,
)
_TIME_UNIT_TO_NS = {
    "fs": 1e-6,
    "ps": 1e-3,
    "ns": 1.0,
    "us": 1e3,
    "ms": 1e6,
    "s": 1e9,
}


def _extract_values_blocks(text: str) -> List[str]:
    """Return the raw content of each values(...) call (balanced-paren scan)."""
    blocks: List[str] = []
    for m in _VALUES_RE.finditer(text):
        i = m.end()  # position right after the '('
        depth = 1
        start = i
        while i < len(text) and depth > 0:
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        blocks.append(text[start:i - 1])
    return blocks


def _balanced_group_body(text: str, open_brace: int) -> str:
    """Return one Liberty group's body, starting at its opening ``{``."""
    depth = 1
    i = open_brace + 1
    start = i
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[start:i - 1] if depth == 0 else text[start:]


def _without_liberty_comments(text: str) -> str:
    """Remove C- and C++-style comments before finding live arc syntax."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def liberty_arc_delays_ns(text: str) -> Tuple[List[dict], str]:
    """Return propagation-delay samples normalised to ns and the time unit.

    Only ``cell_rise``, ``cell_fall``, ``intrinsic_rise`` and
    ``intrinsic_fall`` are propagation delays. Leakage and capacitance keep a
    no-arc analog model non-degenerate but never become synchronous arcs here.
    An absent/unrecognised ``time_unit`` returns raw samples with
    ``delay_ns=None`` so the caller can refuse an uncheckable comparison.
    """
    text = _without_liberty_comments(text)
    tm = _TIME_UNIT_RE.search(text)
    scale = None
    unit = "absent"
    if tm:
        unit = f"{tm.group('mult')}{tm.group('unit').lower()}"
        scale = (float(tm.group("mult")) *
                 _TIME_UNIT_TO_NS[tm.group("unit").lower()])

    samples: List[dict] = []

    # Scalar Liberty spelling: ``cell_rise : 0.42 ;``.
    for kind in _ARC_DELAY_ATTRS:
        for m in _SCALAR_RE[kind].finditer(text):
            raw = float(m.group(1))
            samples.append({
                "kind": kind,
                "raw_value": raw,
                "delay_ns": raw * scale if scale is not None else None,
            })

    # NLDM spelling: ``cell_rise(template) { values("..."); }``. Restrict
    # values() to the delay group body; a whole-file values() scan would also
    # mistake power tables for timing arcs.
    for m in _ARC_GROUP_RE.finditer(text):
        body = _balanced_group_body(text, m.end() - 1)
        for blob in _extract_values_blocks(body):
            for token in _NUM_RE.findall(blob):
                raw = float(token)
                samples.append({
                    "kind": m.group("kind").lower(),
                    "raw_value": raw,
                    "delay_ns": raw * scale if scale is not None else None,
                })

    return samples, unit


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    block: str = ""


@dataclass
class Result:
    program: str = "analog_liberty_nonzero_delay_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def analyze_liberty(text: str) -> Tuple[bool, List[float], str]:
    """Return (has_timing, numeric_values, cell_name).

    has_timing      — True if >=1 timing-bearing attribute/table found.
    numeric_values  — every timing-bearing number found (for zero check).
    cell_name       — first cell(...) name (or "").
    """
    cm = _CELL_RE.search(text)
    cell_name = cm.group(1) if cm else ""

    values: List[float] = []
    has_timing = False

    # 1. scalar timing attrs
    for attr, rx in _SCALAR_RE.items():
        for m in rx.finditer(text):
            has_timing = True
            try:
                values.append(float(m.group(1)))
            except ValueError:
                values.append(float("nan"))

    # 2. NLDM values(...) tables
    for blob in _extract_values_blocks(text):
        nums = [float(n) for n in _NUM_RE.findall(blob)]
        if nums:
            has_timing = True
            values.extend(nums)

    # 3. leakage_power groups with `value : x ;`
    for lg in _LEAKAGE_GROUP_RE.finditer(text):
        for vm in _LEAKAGE_VALUE_RE.finditer(lg.group("body")):
            has_timing = True
            try:
                values.append(float(vm.group(1)))
            except ValueError:
                values.append(float("nan"))

    return has_timing, values, cell_name


def _discover_blocks(project: Path) -> List[str]:
    analog = (_pl.analog_dir(project) if _pl is not None else project / "analog")
    if not analog.is_dir():
        return []
    return sorted(p.parent.name for p in analog.glob("*/spec.json"))


def _hardmacro_dir(project: Path) -> Path:
    return _pl.hardmacro_dir(project) if _pl is not None else project / "hardmacro"


def _analog_dir(project: Path) -> Path:
    return _pl.analog_dir(project) if _pl is not None else project / "analog"


def run_audit(project: Path) -> Result:
    res = Result()
    blocks = _discover_blocks(project)
    if not blocks:
        res.findings.append(Finding(
            rule="SKIP_NO_ANALOG", severity="INFO",
            message="No analog blocks found; nothing to check."))
        res.summary = {"skipped": True, "reason": "no_analog_blocks"}
        return res

    hm_dir = _hardmacro_dir(project)
    an_dir = _analog_dir(project)
    ok_blocks: List[str] = []
    failed: List[str] = []
    structure_only: List[str] = []
    design_bound: List[str] = []
    period_ns = design_clock_period_ns(project)
    arc_samples_examined = 0
    arc_period_violations: List[dict] = []

    for block in blocks:
        lib = hm_dir / block / f"{block}.lib"
        corner = an_dir / block / "corner_results.json"

        provenance = "absent"
        if corner.exists():
            try:
                cd = json.loads(corner.read_text(errors="replace"))
                provenance = str(cd.get("_provenance", "unknown"))
            except (json.JSONDecodeError, OSError):
                provenance = "unparseable"

        if not lib.exists():
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_MISSING", severity="ERROR", block=block,
                message=f"Block '{block}': {block}.lib absent; cannot sign off STA."))
            continue

        try:
            text = lib.read_text(errors="replace")
        except OSError as exc:
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_UNREADABLE", severity="ERROR", block=block,
                message=f"Block '{block}': {block}.lib unreadable: {exc}"))
            continue

        has_timing, values, cell_name = analyze_liberty(text)

        if not _CELL_RE.search(text):
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_NO_CELL", severity="ERROR", block=block,
                message=f"Block '{block}': Liberty has no cell(...) definition."))
            continue

        if not has_timing:
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_NO_TIMING", severity="ERROR", block=block,
                message=(f"Block '{block}': Liberty cell '{cell_name}' has no "
                         f"timing/leakage attributes (area-only stub). This is "
                         f"the documented zero-delay defect: STA would pass "
                         f"vacuously.")))
            continue

        nonzero = [v for v in values if v == v and v != 0.0]  # v==v drops NaN
        all_zero = (len([v for v in values if v == v]) > 0 and not nonzero)
        if all_zero:
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_ZERO_DELAY", severity="ERROR", block=block,
                message=(f"Block '{block}': every timing value in the Liberty "
                         f"is 0 — zero-delay model (forbidden). Use actual "
                         f"SPICE-measured delays.")))
            continue

        arc_samples, time_unit = liberty_arc_delays_ns(text)
        arc_samples_examined += len(arc_samples)
        if period_ns is not None and arc_samples and time_unit == "absent":
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_ARC_TIME_UNIT_UNDECLARED", severity="ERROR",
                block=block,
                message=(f"Block '{block}': {len(arc_samples)} propagation "
                         f"delay sample(s) exist but the Liberty declares no "
                         f"time_unit, so they cannot be compared with the "
                         f"design clock period ({period_ns:g} ns).")))
            continue

        oversized = ([
            sample for sample in arc_samples
            if sample["delay_ns"] is not None
            and sample["delay_ns"] > period_ns
        ] if period_ns is not None else [])
        if oversized:
            res.passed = False
            failed.append(block)
            worst = max(oversized, key=lambda sample: sample["delay_ns"])
            evidence = {
                "block": block,
                "cell": cell_name,
                "kind": worst["kind"],
                "delay_ns": worst["delay_ns"],
                "clock_period_ns": period_ns,
                "time_unit": time_unit,
                "samples_over_period": len(oversized),
            }
            arc_period_violations.append(evidence)
            res.findings.append(Finding(
                rule="LIB_ARC_EXCEEDS_CLOCK_PERIOD", severity="ERROR",
                block=block,
                message=(f"Block '{block}': Liberty cell '{cell_name}' "
                         f"{worst['kind']} delay {worst['delay_ns']:g} ns "
                         f"exceeds the design clock period {period_ns:g} ns "
                         f"({len(oversized)} sample(s) exceed it); an analog "
                         f"macro carries no synchronous cell arc; move the "
                         f"settling contract to interface.json "
                         f"timing_contract.")))
            continue

        # ── the certification question, asked LAST ────────────────────────
        # `provenance` above says the numbers came out of a simulator.
        # `content` says what the simulator was pointed at.
        _bounded = _acc.hardmacro_content(an_dir / block)
        content, content_src = _bounded.klass, _bounded.source
        cited = (str(content_src.relative_to(project))
                 if content_src is not None else None)

        if content == _acc.CONTENT_UNDISCLOSED:
            res.passed = False
            failed.append(block)
            said = ("no corner artefact exists to say"
                    if not corner.exists() else
                    f"`{corner.name}` records no answer to")
            res.findings.append(Finding(
                rule="LIB_SUBJECT_UNDECLARED", severity="ERROR", block=block,
                message=(f"Block '{block}': Liberty cell '{cell_name}' has "
                         f"{len(nonzero)} non-zero timing value(s), and "
                         f"{said} what circuit those delays model "
                         f"(`design_content`). Integration STA will consume "
                         f"this model as this design's; a Liberty that will "
                         f"not name its subject must not be signed off for "
                         f"it. Naming a library default "
                         f"(`{_acc.CONTENT_STRUCTURE_ONLY}`) signs off in its "
                         f"own tier; declining to answer does not, or saying "
                         f"nothing would cost less than saying so.")))
            continue

        ok_blocks.append(block)
        if content == _acc.CONTENT_STRUCTURE_ONLY:
            structure_only.append(block)
            res.findings.append(Finding(
                rule="LIB_STRUCTURE_ONLY", severity="WARNING", block=block,
                message=(f"Block '{block}': Liberty cell '{cell_name}' has "
                         f"{len(nonzero)} non-zero timing value(s) measured "
                         f"OF A LIBRARY TOPOLOGY — `{cited}` records that its "
                         f"circuit came from a topology library and that no "
                         f"bound input reached any device parameter. The "
                         f"delays are real and they are the default's; STA "
                         f"closed on them is not closed on a designed "
                         f"macro. corner provenance={provenance}.")))
        else:
            design_bound.append(block)
            res.findings.append(Finding(
                rule="LIB_NONZERO_OK", severity="INFO", block=block,
                message=(f"Block '{block}': Liberty cell '{cell_name}' has "
                         f"{len(nonzero)} non-zero timing value(s); corner "
                         f"provenance={provenance}; design content "
                         f"design-bound per `{cited}`.")))

    if failed:
        res.passed = False

    # Same ranking as the sibling corner gates: the tier reaches the verdict
    # word only when NO block was signed off as design-bound. A project with
    # both has a design-bound macro to report and the structure-only subset is
    # named beside it.
    verdict_tier = ("PASS_STRUCTURE_ONLY"
                    if (res.passed and structure_only and not design_bound)
                    else "PASS")
    res.summary = {
        "skipped": False,
        "total_blocks": len(blocks),
        "passed_blocks": ok_blocks,
        "design_bound_blocks": design_bound,
        "structure_only_blocks": structure_only,
        "verdict_tier": verdict_tier,
        "failed_blocks": failed,
        "design_clock_period_ns": period_ns,
        "arc_delay_samples_examined": arc_samples_examined,
        "arc_period_violations": arc_period_violations,
        "pass": res.passed,
    }
    return res


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    res = run_audit(args.project_dir)
    out = json.dumps(asdict(res), indent=2, ensure_ascii=False)

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(res.summary)
    reason = _vx.skip_reason(res.summary)

    so_blocks = (res.summary or {}).get("structure_only_blocks") or []
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)
    else:
        # The tier travels on the verdict WORD — `pass_token` is the seam
        # `_vacuous_exit` already provides for it — so a reader of the one
        # line can tell a designed macro's timing from a library topology's.
        print(_vx.verdict_line(
            "analog_liberty_nonzero_delay_check", res.passed, skipped, reason,
            pass_token=((res.summary or {}).get("verdict_tier") or "PASS")))
        for f in res.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if res.passed and skipped:
        _vx.announce_vacuous(res.program, reason)
    # LAST, SHORT, and on every path — the disclosure the flow auditor reads
    # from a fixed-width TAIL of this stream, whatever the verdict was. To
    # stderr for the same reason `announce_vacuous` is: `--json` puts a
    # document on stdout and a sentinel mixed into it would not parse.
    if so_blocks:
        names = ", ".join(str(b) for b in so_blocks)
        if len(names) > 60:
            names = f"{names[:57]}..."
        print(f"{_acc.STRUCTURE_ONLY_TOKEN} {len(so_blocks)} Liberty "
              f"artefact(s) ({names}) model a library default, not a bound "
              f"input [analog_liberty_nonzero_delay_check]", file=sys.stderr)
    return _vx.exit_code(res.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
