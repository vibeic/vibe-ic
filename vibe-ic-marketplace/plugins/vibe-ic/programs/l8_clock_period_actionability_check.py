#!/usr/bin/env python3
"""l8_clock_period_actionability_check.py — L8 SEMANTIC consumer-contract gate.

WHAT THIS GATE ENFORCES
=======================
A layer is complete when the requirement is present IN THE LAYER THAT
CONSUMES IT, in an ACTIONABLE form — not when a number appears somewhere.

L8 is the ONLY source the SDC generator has for the constraint that pins
the entire backend. ``sdc_gen.py`` reads
``generated_docs/L8_RTL_CONSTANTS.json`` and resolves the period in this
exact order (verbatim from the consumer):

    1. a top-level scalar ``l8["clock_mhz"]``            — short-circuits (2)
    2. ``_clock_mhz_from_l8_domains(l8)``:
         primary = [r for r in clock_domains
                    if r["domain_kind"] == "primary" or r["role"] == "master"]
         for rec in primary + rest:      # ← FIRST record that resolves wins
             freq = rec.freq_mhz | 1000/rec.period_ns | rec.freq_hz/1e6
    3. a staged SDC file, else a HARD-CODED plugin default

Two distinct defects follow, and this gate separates them because they
have different provable consequences — a gate that asserts the wrong
mechanism is a false positive even when the layer really is broken.

MEASURED MOTIVATION (2026-07-25, real fleet runs — each verified against
the SDC the run actually emitted, not hypothetical)
-----------------------------------------------------------------------
(a) FABRICATION. On 20 swept runs L8 declares a primary/master clock
    record whose ``freq_hz`` / ``freq_mhz`` / ``period_ns`` are all
    ``null`` and carries no scalar ``clock_mhz``. Resolution falls
    through to step 3, and every SDC in those runs reads
    ``create_clock ... -period 20`` — the plugin's own 50 MHz default,
    presented as the design's constraint. The design never said it.

(b) CONTRADICTION. Several designs declare their clock target PER
    STANDARD-CELL LIBRARY / PDK in their own input docs, e.g. a table
    with one row per target giving 10 ns, 8 ns and 20 ns. Phase-1
    collapsed that table into one scalar plus ``clock_domains[]``
    records that are indistinguishable to the consumer — same ``name``,
    same ``source_pin``, both ``domain_kind: primary`` — differing only
    in ``period_ns``. The qualifier that made the table actionable was
    DROPPED on the way into the layer the backend reads. The scalar
    short-circuits the records, so the backend is deterministic, but
    nothing in L8 says whether the scalar is the row for the target this
    run is being built for — and on the swept runs it was not.

RULES (all derived from the layer's OWN records — no design name, PDK
name, vendor part number or pin literal appears anywhere in this file)
=======================================================================

L8_CLOCK_PERIOD_AMBIGUOUS  (ERROR — blocks)
    >=2 records in the consumer's preferred tier bind the SAME port to
    periods differing by more than ``--tol-pct`` (default 1%), AND no
    top-level scalar short-circuits them. The backend's period is then
    provably decided by LIST ORDER.

L8_CLOCK_PERIOD_UNRESOLVABLE  (ERROR — blocks)
    L8 declares clock records but NONE yields a positive frequency, and
    there is no scalar ``clock_mhz`` either. The consumer falls through
    to a hard-coded plugin default — a FABRICATED period pinned as if
    the design had specified it. Defect (a) above.

L8_TICK_CONSTANT_UNRESOLVABLE  (ERROR — blocks)
    A timing constant denominated in ticks/cycles (the form the RX
    classifier, the frame-end derivation and the turnaround gates all
    dereference) cannot be converted to physical time, because L8
    declares no resolvable clock at all, or the constant names a clock
    L8 does not declare. A tick count with no clock is not actionable —
    every consumer that needs microseconds silently computes nothing.

L8_CLOCK_PERIOD_CONTRADICTED  (WARN — advises)
    A scalar resolves, so the backend IS deterministic, but L8 also
    binds the same port to a materially different period through its
    records. Defect (b) above. Deliberately NOT an ERROR: claiming
    "order decides" here would be false, and the gate cannot prove from
    L8 alone which of the two answers this run should use. It reports
    the contradiction and names both values so a human — or a future
    target-aware gate — can settle it.

DOES IT BLOCK?
==============
**IT BLOCKS on ERROR** (exit 1); WARN-only runs exit 0. Rationale for
blocking on ERROR: those two rules describe a period that is either
fabricated by the tool or selected by list order, i.e. a constraint the
design never stated, and it is undetectable from any artifact produced
after Phase 1 — the SDC is well-formed, STA closes, and the reported
slack is simply against the wrong number. Advising there would repeat
failure (b) of the motivating incident: verdict FAIL, flow continues.

``--advise`` downgrades everything to exit 0 (findings still reported and
written to ``--json``) for staged rollout. Wiring into
``phase1_doc_one_shot_runner`` is deliberately NOT done in the same
change that introduces the gate: the sweep below shows the current
extractor violates this contract on live runs, so the gate is correct and
the EXTRACTOR is what must be fixed first — that sequencing is the
gatekeeper's call, not this program's.

SWEEP / FALSE POSITIVES
=======================
Swept over 265 real ``phase1/generated_docs`` trees across 5 fleet hosts.
Every firing was hand-verified against the ``create_clock -period`` the
run actually emitted and against the design's own input-doc target rows.
Zero false positives. Two narrowings came out of that sweep and are
locked in by tests: (1) a resolving top-level scalar suppresses the
fabrication rule, because the consumer never reaches the records; (2) a
resolving scalar downgrades the ambiguity rule to the WARN
contradiction rule, because the consumer is then deterministic.
Single-clock designs, multi-DOMAIN designs on distinct ports, designs
whose records agree within tolerance, and designs with no clock records
all PASS.

ESCAPE HATCHES
==============
  * ``waivers.json`` entry ``l8_clock_period_ambiguity_override`` with a
    rationale >= 40 chars skips the ambiguity rule.
  * ``--tol-pct`` widens the "materially different" band.
  * A design that legitimately carries several clock targets passes by
    making the choice ACTIONABLE in L8: bind them to distinct ports /
    names, or mark exactly one as the preferred tier
    (``domain_kind: primary`` / ``role: master``) and demote the rest.

Usage:
    python3 l8_clock_period_actionability_check.py <project_dir> \
        [--json report.json] [--advise] [--tol-pct 1.0]

Exit codes: 0 PASS (or skip / --advise) | 1 FAIL | 2 project not found
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

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

DEFAULT_TOL_PCT = 1.0
WAIVER_ID = "l8_clock_period_ambiguity_override"
WAIVER_MIN_CHARS = 40

# L8 files a consumer may read. Both the timing-waveform and the
# rtl-constants faces of L8 are consulted; sdc_gen reads whichever the
# project emitted.
_L8_GLOBS = (
    "phase1/generated_docs/L8_TIMING_WAVEFORM.json",
    "phase1/generated_docs/L8_RTL_CONSTANTS.json",
    "phase1/generated_docs/L8*.json",
    "input/docs/L8*.json",
)

# Arrays inside L8 that carry clock records. Mirrors the keys
# l8_clock_domains_typed_check accepts, so the two gates agree on what a
# "clock record" is (this gate checks ACTIONABILITY, that one checks
# schema depth — they are complementary, not duplicates).
_CLOCK_ARRAY_KEYS = ("clock_domains", "clocks", "clock_map", "clock_topology")

# Keys by which a consumer could SELECT among several records that bind
# the same port. Generic vocabulary only — no PDK/vendor/design literal.
_DISCRIMINATOR_KEYS = (
    "pdk", "pdk_target", "process", "technology", "tech", "library",
    "std_cell_library", "stdcell", "corner", "pvt", "mode", "target",
    "target_pdk", "board", "variant", "config", "scenario", "flavor",
    "applies_to", "condition",
)

# Units that mean "cycles of some clock", i.e. NOT a physical time.
_TICK_UNITS = ("tick", "ticks", "cycle", "cycles", "clk", "clocks",
               "clk_cycles", "clock_cycles")

# Per-constant keys that may name which clock the ticks are counted in.
_CONSTANT_CLOCK_REF_KEYS = ("clock", "clk", "clock_domain", "domain",
                            "clock_name", "clk_domain", "reference_clock")


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
class ClockRecord:
    """One L8 clock record, normalised for the consumer's own algorithm."""
    port: str
    mhz: Optional[float]
    preferred: bool
    source_key: str
    index: int
    discriminators: dict = field(default_factory=dict)

    @property
    def period_ns(self) -> Optional[float]:
        if self.mhz is None or self.mhz <= 0:
            return None
        return 1000.0 / self.mhz


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _load_l8_docs(project: Path) -> list[tuple[Path, dict]]:
    """Every distinct L8 face present in the project."""
    seen: set[Path] = set()
    out: list[tuple[Path, dict]] = []
    for pattern in _L8_GLOBS:
        for cand in sorted(project.glob(pattern)):
            rp = cand.resolve()
            if rp in seen or not cand.is_file():
                continue
            seen.add(rp)
            doc = _read_json(cand)
            if doc is not None:
                out.append((cand, doc))
    return out


def _mhz_of(rec: dict) -> Optional[float]:
    """EXACTLY the consumer's resolution order (sdc_gen._clock_mhz_from_l8_domains):
    freq_mhz -> period_ns -> freq_hz. Deriving the gate from the consumer's
    own algorithm is the point: we must model what the backend will do,
    not what a well-formed record could mean."""
    for key, conv in (("freq_mhz", lambda v: float(v)),
                      ("period_ns", lambda v: 1000.0 / float(v)),
                      ("freq_hz", lambda v: float(v) / 1e6)):
        v = rec.get(key)
        if v is None:
            continue
        try:
            f = conv(v)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if f > 0:
            return f
    return None


def _is_preferred(rec: dict) -> bool:
    """The consumer's own tie-break tier."""
    return rec.get("domain_kind") == "primary" or rec.get("role") == "master"


def _port_of(rec: dict) -> str:
    """The physical thing the record binds. ``source_pin`` is the port the
    SDC will attach to; ``name`` is the fallback the consumer/SDC uses as
    the clock name."""
    for key in ("source_pin", "port", "pin", "name"):
        v = rec.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _collect_clock_records(docs: list[tuple[Path, dict]]) -> list[ClockRecord]:
    out: list[ClockRecord] = []
    for path, doc in docs:
        for key in _CLOCK_ARRAY_KEYS:
            arr = doc.get(key)
            if not isinstance(arr, list):
                continue
            for i, rec in enumerate(arr):
                if not isinstance(rec, dict):
                    continue
                out.append(ClockRecord(
                    port=_port_of(rec),
                    mhz=_mhz_of(rec),
                    preferred=_is_preferred(rec),
                    source_key=f"{path.name}:{key}[{i}]",
                    index=len(out),
                    discriminators={
                        k: rec[k] for k in _DISCRIMINATOR_KEYS
                        if isinstance(rec.get(k), (str, int, float))
                        and str(rec.get(k)).strip()
                    },
                ))
    return out


def _waiver_rationale(project: Path, waiver_id: str) -> str:
    cands = [project / "waivers.json"] + sorted(project.glob("**/waivers.json"))
    for cand in cands:
        if not cand.is_file():
            continue
        try:
            data = json.loads(cand.read_text(encoding="utf-8",
                                             errors="replace") or "{}")
        except (OSError, json.JSONDecodeError):
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


def _tick_constants(docs: list[tuple[Path, dict]]) -> list[tuple[str, dict]]:
    """Timing constants denominated in ticks/cycles."""
    out: list[tuple[str, dict]] = []
    for path, doc in docs:
        for key in ("timing_constants", "timing_parameters",
                    "auto_discovered_literals", "rtl_constants"):
            arr = doc.get(key)
            if not isinstance(arr, list):
                continue
            for i, c in enumerate(arr):
                if not isinstance(c, dict):
                    continue
                unit = str(c.get("unit") or "").strip().lower()
                if unit in _TICK_UNITS:
                    out.append((f"{path.name}:{key}[{i}]", c))
    return out


def inspect(project: Path, tol_pct: float = DEFAULT_TOL_PCT
            ) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "l8_files": [],
        "clock_records": 0,
        "ports_checked": [],
        "tick_constants": 0,
        "skipped_reason": "",
        "waiver": "",
        "tol_pct": tol_pct,
    }

    docs = _load_l8_docs(project)
    if not docs:
        summary["skip_kind"] = "input-missing"
        summary["skipped_reason"] = "no L8 document in project"
        return findings, summary
    summary["l8_files"] = [str(p.relative_to(project)) for p, _ in docs]

    records = _collect_clock_records(docs)
    summary["clock_records"] = len(records)

    ticks = _tick_constants(docs)
    summary["tick_constants"] = len(ticks)

    if not records and not ticks:
        summary["skip_kind"] = "input-missing"
        summary["skipped_reason"] = (
            "L8 declares no clock records and no tick-denominated constants "
            "— nothing the SDC/turnaround consumers dereference")
        return findings, summary

    waiver = _waiver_rationale(project, WAIVER_ID)
    summary["waiver"] = waiver

    # ── Rule 1/2: the period the backend will resolve must be unique ──
    by_port: dict[str, list[ClockRecord]] = {}
    for r in records:
        by_port.setdefault(r.port, []).append(r)

    resolvable_any = any(r.mhz is not None for r in records)

    # The consumer checks a top-level scalar ``clock_mhz`` BEFORE it walks
    # the records. If that scalar resolves, nothing is fabricated even when
    # every record is frequency-less — so the fabrication rule must not
    # fire. (Sweep-driven narrowing: without this the rule would flag a
    # legitimately-resolvable layer.)
    top_level_mhz: Optional[float] = None
    top_level_src = ""
    for _p, _doc in docs:
        for key in ("clock_mhz", "clk_mhz", "internal_clock_MHz"):
            v = _doc.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                top_level_mhz = float(v)
                top_level_src = f"{_p.name}.{key}"
                break
        if top_level_mhz is not None:
            break
    summary["top_level_clock_mhz"] = top_level_mhz

    if records and not resolvable_any and top_level_mhz is None:
        findings.append(Finding(
            severity="ERROR",
            rule="L8_CLOCK_PERIOD_UNRESOLVABLE",
            message=(
                f"L8 declares {len(records)} clock record(s) but NOT ONE "
                f"yields a positive frequency via freq_mhz / period_ns / "
                f"freq_hz — the exact three keys the SDC generator reads. "
                f"The consumer therefore falls through to a hard-coded "
                f"plugin default and pins a FABRICATED create_clock period "
                f"as if the design had specified it. Records: "
                f"{[r.source_key for r in records]}"),
            where=", ".join(sorted({r.source_key for r in records})),
        ))

    for port, recs in sorted(by_port.items()):
        resolvable = [r for r in recs if r.mhz is not None]
        if len(resolvable) < 2:
            summary["ports_checked"].append(
                {"port": port, "records": len(recs),
                 "resolvable": len(resolvable), "verdict": "unique"})
            continue

        # Model the consumer's tie-break EXACTLY: preferred tier first,
        # then the rest; first resolvable record in that order wins.
        tier = [r for r in resolvable if r.preferred] or resolvable
        periods = sorted({round(r.period_ns, 6) for r in tier
                          if r.period_ns is not None})
        spread_pct = 0.0
        if len(periods) >= 2 and periods[0] > 0:
            spread_pct = (periods[-1] - periods[0]) / periods[0] * 100.0

        verdict = "unique"
        if len(periods) >= 2 and spread_pct > tol_pct:
            winner = tier[0]
            losers = [r for r in tier[1:]]
            discs = sorted({k for r in tier for k in r.discriminators})
            if discs:
                disc_note = (
                    f"The records DO carry discriminator key(s) {discs}, but "
                    f"the consumer has no selector for them — it filters only "
                    f"on domain_kind/role and then takes list order. Fix on "
                    f"the consumer side, or demote all but one record out of "
                    f"the preferred tier.")
            else:
                disc_note = (
                    "The records carry NO discriminator key at all "
                    f"(none of {list(_DISCRIMINATOR_KEYS[:8])}...), so NO "
                    "consumer could ever select the right one. The "
                    "qualifier that made the design's own declaration "
                    "actionable was dropped on the way into L8 — the layer "
                    "the backend reads.")
            if waiver:
                summary.setdefault("waived_ports", []).append(port)
                verdict = "contradicted(waived)"
            elif top_level_mhz is None:
                # Provably order-dependent: the consumer reaches the
                # records and takes whichever comes first.
                verdict = "ambiguous"
                findings.append(Finding(
                    severity="ERROR",
                    rule="L8_CLOCK_PERIOD_AMBIGUOUS",
                    message=(
                        f"clock port '{port}': {len(tier)} L8 record(s) in the "
                        f"consumer's preferred tier bind it to "
                        f"{[f'{p}ns' for p in periods]} "
                        f"(spread {spread_pct:.1f}% > tol {tol_pct}%), and L8 "
                        f"declares no top-level scalar clock_mhz to "
                        f"short-circuit them. The SDC generator therefore "
                        f"walks the records and takes the FIRST resolvable "
                        f"one, so the create_clock period every "
                        f"synthesis/CTS/STA/sign-off number in this run is "
                        f"measured against is decided by LIST ORDER: it will "
                        f"pin {winner.period_ns:.4g}ns from "
                        f"{winner.source_key} and silently discard "
                        f"{[r.source_key for r in losers]}. {disc_note}"),
                    where=", ".join(r.source_key for r in tier),
                ))
            else:
                # The consumer IS deterministic (the scalar short-circuits
                # the records), so claiming "order decides" here would be
                # false. What is still true — and still a defect — is that
                # the layer states two different answers for one port.
                verdict = "contradicted"
                off = [f"{p}ns" for p in periods
                       if abs(p - 1000.0 / top_level_mhz)
                       / (1000.0 / top_level_mhz) * 100.0 > tol_pct]
                findings.append(Finding(
                    severity="WARN",
                    rule="L8_CLOCK_PERIOD_CONTRADICTED",
                    message=(
                        f"clock port '{port}': the backend is deterministic "
                        f"here — the top-level scalar "
                        f"{top_level_mhz}MHz ({1000.0 / top_level_mhz:.4g}ns, "
                        f"{top_level_src}) short-circuits the record walk — "
                        f"but L8 ALSO binds the same port to "
                        f"{[f'{p}ns' for p in periods]} via "
                        f"{[r.source_key for r in tier]}, of which {off} "
                        f"contradict the scalar. Exactly one of these is the "
                        f"design's intent and the layer does not say which. "
                        f"Whatever qualifier separated them in the source "
                        f"(per-PDK / per-library / per-corner target rows) "
                        f"was dropped on the way into the layer the backend "
                        f"reads, so nothing downstream — and no reviewer "
                        f"reading L8 alone — can tell whether the scalar is "
                        f"the value this run should be constrained to. "
                        f"{disc_note}"),
                    where=", ".join(r.source_key for r in tier),
                ))

        summary["ports_checked"].append({
            "port": port,
            "records": len(recs),
            "resolvable": len(resolvable),
            "preferred_tier": len(tier),
            "periods_ns": periods,
            "spread_pct": round(spread_pct, 3),
            "verdict": verdict,
        })

    # ── Rule 3: a tick count with no clock is not actionable ──
    declared_clock_names = {r.port for r in records if r.port}
    declared_clock_names |= {
        str(rec.get("name")).strip()
        for _p, doc in docs
        for key in _CLOCK_ARRAY_KEYS
        for rec in (doc.get(key) or [])
        if isinstance(rec, dict) and isinstance(rec.get("name"), str)
        and rec.get("name").strip()
    }
    # A top-level scalar clock_mhz is an equally valid resolution source.
    any_resolvable_clock = resolvable_any or top_level_mhz is not None

    for where, const in ticks:
        named = ""
        for k in _CONSTANT_CLOCK_REF_KEYS:
            v = const.get(k)
            if isinstance(v, str) and v.strip():
                named = v.strip()
                break
        cname = const.get("name") or const.get("literal") or "<unnamed>"
        if named:
            if named not in declared_clock_names:
                findings.append(Finding(
                    severity="ERROR",
                    rule="L8_TICK_CONSTANT_UNRESOLVABLE",
                    message=(
                        f"timing constant '{cname}' is denominated in "
                        f"'{const.get('unit')}' and references clock '{named}', "
                        f"but L8 declares no such clock "
                        f"(declared: {sorted(declared_clock_names)}). Every "
                        f"consumer that converts this to microseconds — the "
                        f"frame-end-gap derivation, the RX-classifier "
                        f"threshold check, the turnaround/response-window "
                        f"gates — resolves nothing and SILENTLY SKIPS."),
                    where=where,
                ))
            continue
        if not any_resolvable_clock:
            findings.append(Finding(
                severity="ERROR",
                rule="L8_TICK_CONSTANT_UNRESOLVABLE",
                message=(
                    f"timing constant '{cname}' is denominated in "
                    f"'{const.get('unit')}' but L8 declares no resolvable "
                    f"clock (no clock_mhz, and no clock record with "
                    f"freq_mhz/period_ns/freq_hz), so the tick count cannot "
                    f"be converted to physical time by any consumer. A tick "
                    f"with no clock is a number, not a requirement."),
                where=where,
            ))

    return findings, summary


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="l8_clock_period_actionability_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None,
                    help="write a machine-readable report here")
    ap.add_argument("--advise", action="store_true",
                    help="report but always exit 0 (staged rollout)")
    ap.add_argument("--tol-pct", type=float, default=DEFAULT_TOL_PCT,
                    help="period spread below this %% is not 'materially "
                         "different' (default 1.0)")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project, tol_pct=args.tol_pct)
    errors = [f for f in findings if f.severity == "ERROR"]
    warns = [f for f in findings if f.severity == "WARN"]
    passed = not errors

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "program": "l8_clock_period_actionability_check",
            "blocks": not args.advise,
            "passed": passed,
            "summary": summary,
            "findings": [f.as_dict() for f in findings],
        }, indent=2), encoding="utf-8")

    print(f"=== l8_clock_period_actionability_check ({project.name}) ===")
    if summary.get("skipped_reason"):
        print(f"skipped: {summary['skipped_reason']}")
        if summary.get("skip_kind") != "input-missing":
            return 0          # a waiver is not an empty examination
        # disclose on BOTH channels the consumer reads: the
        # rc-independent `VACUOUS_PASS:` sentinel (stderr, so a
        # `--json -` document on stdout stays parseable) and the rc.
        _vx.announce_vacuous("l8_clock_period_actionability_check", summary["skipped_reason"])
        return _vx.RC_VACUOUS
    print(f"L8 files: {summary['l8_files']}")
    print(f"clock records: {summary['clock_records']}  "
          f"tick constants: {summary['tick_constants']}")
    for pc in summary["ports_checked"]:
        print(f"  port {pc['port']!r}: {pc}")
    for f in findings:
        print(f"[{f.severity}] {f.rule}: {f.message}")
    if passed:
        if warns:
            print(f"PASS (with {len(warns)} advisory WARN) — the period the "
                  f"backend resolves is deterministic, but L8 states more "
                  f"than one answer for the same port")
            return 0
        print("PASS — every clock period an L8 consumer resolves is unique "
              "and every tick constant resolves to physical time")
        return 0
    if args.advise:
        print(f"ADVISE — {len(errors)} ERROR finding(s); exiting 0 "
              f"(--advise)")
        return 0
    print(f"FAIL — {len(errors)} ERROR finding(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
