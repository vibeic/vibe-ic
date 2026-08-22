#!/usr/bin/env python3
"""The `drv` feasibility axis, as canonical records — the ONE axis that has no
producer anywhere in `programs/`.

WHY THIS FILE EXISTS
====================
`_ppa/feasibility.DEFAULT_AXES` proves `drv` from either

    timing.drv.violations == 0                                   (proof set 1)
    timing.drv.max_tran_violations == 0
      AND timing.drv.max_cap_violations == 0
      AND timing.drv.max_fanout_violations == 0                  (proof set 2)

and NOTHING in `programs/` emits any of those five names. `_ppa/timing.py`
emits setup and hold rows only; `_ppa/backends/openroad.py` emits
`drv.max_slew.violation.count.pre_repair`, which is a different metric at a
different stage and explicitly PRE-repair. So `drv` adjudicates UNDETERMINED on
every run of this flow, and "both arms feasible" — one of the four conditions a
head-to-head requires — can never hold. This is a CALLER-side reference
implementation of the missing producer, in the same shape as the caller-side
sign-off bridge the previous lane published and this tree has since shipped as
`ppa_signoff_records.py`.

THE DISCRIMINATOR, WHICH IS THE WHOLE DIFFICULTY
================================================
The flow drives

    report_check_types -recovery -removal -max_slew -min_pulse_width
                       -max_capacitance -max_fanout -violators -max_count 2000

and `-violators` prints ONLY violating entries, so a clean design prints NOTHING
AT ALL. "The design is clean" and "the command never ran" therefore produce a
byte-identical empty region, and reading that emptiness as zero is precisely the
vacuous pass this repository exists to refuse.

The flow's OWN emitter supplies the discriminator, and this parser uses it and
nothing else:

    SIGNOFF_CHECK_TYPES_REPORTED <types...>   the command RAN and returned
    SIGNOFF_CHECK_TYPES_FAILED reason=...     the command raised
    neither marker                            the session did not reach the call

Only the first admits a count. The other two are NOT_MEASURED with the reason,
never a zero.

AND THE SECOND TRAP, WHICH THE REPORT ITSELF WARNS ABOUT
========================================================
    SIGNOFF_MAX_FANOUT_SEMANTICS an empty max-fanout table means no net
    exceeded a set_max_fanout limit; when the sign-off SDC declares NO
    set_max_fanout the table is empty BY CONSTRUCTION and MUST NOT be read as
    ZERO fanout violations (UNMEASURED is not ZERO)

So each of the three counts is admitted only when the SDC THE SIGN-OFF SESSION
ACTUALLY READ declares the corresponding limit. The session's own tcl names that
SDC (`read_sdc <path>`); this parser reads the path out of the tcl rather than
assuming which SDC was in force, because on this design the phase-2 SDC and the
PnR SDC do not declare the same limits.

Usage: drv_records.py <run-dir> [--json OUT] [--selftest]
Exit codes follow docs/PPA_INTERFACES.md §1: 0 measured something, 2 nothing.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path

PROGRAM = "drv_records"
_MARK_OK = "SIGNOFF_CHECK_TYPES_REPORTED"
_MARK_FAIL = "SIGNOFF_CHECK_TYPES_FAILED"
_GROUP_TABLE_END = re.compile(r"SIGNOFF_WORST_PATHS_REPORTED[^\n]*\n"
                              r"(?:[^\n]*\n)*?(?:No paths found\.|\n)")
_SDC_RE = re.compile(r"^\s*read_sdc\s+(\S+)", re.M)

_CHECKS = (("timing.drv.max_tran_violations", "max_slew", "set_max_transition"),
           ("timing.drv.max_cap_violations", "max_capacitance",
            "set_max_capacitance"),
           ("timing.drv.max_fanout_violations", "max_fanout", "set_max_fanout"))


def _sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def violator_regions(text: str):
    """One entry per `report_check_types` invocation the report carries:

        ("REPORTED", <violator text>, <types declared>)
        ("FAILED",   "",              <reason>)

    The violator text is what stands between the end of the preceding
    group-path table and the marker — which is exactly where
    `report_check_types` appended, because the flow appends both to the same
    file in that order."""
    out = []
    pos = 0
    for m in re.finditer(rf"^({_MARK_OK}|{_MARK_FAIL})(.*)$", text, re.M):
        kind, rest = m.group(1), m.group(2).strip()
        region = text[pos:m.start()]
        # drop everything up to and including the last group-path table
        g = None
        for g in _GROUP_TABLE_END.finditer(region):
            pass
        if g is not None:
            region = region[g.end():]
        out.append(("REPORTED" if kind == _MARK_OK else "FAILED",
                    region, rest))
        pos = m.end()
    return out


def count_violators(region: str, header: str) -> int:
    """Violating entries `report_check_types -violators` printed under one
    check type. A clean run prints no section at all, so an absent section is
    zero ONLY because the caller has already established that the command RAN."""
    m = re.search(rf"^\s*{re.escape(header)}\s*$", region, re.M)
    if not m:
        return 0
    body = region[m.end():]
    nxt = re.search(r"^\s*(max_slew|max_capacitance|max_fanout|"
                    r"min_pulse_width|recovery|removal)\s*$", body, re.M)
    if nxt:
        body = body[:nxt.start()]
    return len([ln for ln in body.splitlines()
                if ln.strip() and not set(ln.strip()) <= set("-")
                and not ln.strip().lower().startswith(("pin", "net", "slew",
                                                       "capacitance", "fanout",
                                                       "limit"))])


def records(run: Path):
    rpt = run / "phase3" / "stage3" / "sta" / "sta_spef_multicorner.rpt"
    tcl = run / "phase3" / "stage3" / "sta" / "sta_spef_setup.tcl"
    notes = []
    if not rpt.is_file():
        return [], [f"no sign-off STA report at {rpt}"]
    text = rpt.read_text(errors="replace")
    src = {"path": str(rpt), "sha256": _sha(rpt), "tool": "opensta",
           "parser": f"{PROGRAM}.py"}
    scope = {"stage": "post_route", "tool": "opensta", "check": "drv"}

    sdc_text, sdc_path = "", None
    if tcl.is_file():
        m = _SDC_RE.search(tcl.read_text(errors="replace"))
        if m:
            sdc_path = Path(m.group(1))
            if sdc_path.is_file():
                sdc_text = sdc_path.read_text(errors="replace")
    notes.append(f"sign-off SDC in force: {sdc_path}")

    regions = violator_regions(text)
    ran = [r for r in regions if r[0] == "REPORTED"]
    failed = [r for r in regions if r[0] == "FAILED"]

    out = []

    def emit(metric, value, reason=None):
        r = {"schema": "vibeic.ppa.metric.v1", "metric": metric,
             "status": "MEASURED" if value is not None else "NOT_MEASURED",
             "unit": "count", "scope": dict(scope), "source": dict(src)}
        if value is not None:
            r["value"] = value
        else:
            r["reason"] = reason
        out.append(r)

    for metric, header, sdc_cmd in _CHECKS:
        if not regions:
            emit(metric, None,
                 f"the sign-off report carries neither `{_MARK_OK}` nor "
                 f"`{_MARK_FAIL}`, so the session never reached "
                 f"report_check_types. An empty violator region with no marker "
                 f"beside it is not a clean design.")
            continue
        if failed and not ran:
            emit(metric, None,
                 f"`{_MARK_FAIL}` — report_check_types raised "
                 f"({failed[0][2][:160]}), so no violator list exists.")
            continue
        if sdc_cmd not in sdc_text:
            emit(metric, None,
                 f"the sign-off SDC in force ({sdc_path}) declares no "
                 f"`{sdc_cmd}`, so this check was never constrained. The "
                 f"report's own SIGNOFF_MAX_FANOUT_SEMANTICS line says an "
                 f"empty table under an undeclared limit MUST NOT be read as "
                 f"zero: UNMEASURED is not ZERO.")
            notes.append(f"{metric}: unconstrained ({sdc_cmd} absent)")
            continue
        n = sum(count_violators(reg, header) for _, reg, _ in ran)
        emit(metric, n)
        notes.append(f"{metric}: {n} over {len(ran)} reported invocation(s), "
                     f"`{sdc_cmd}` declared")
    return out, notes


_FIX_CLEAN = ("SIGNOFF_WORST_PATHS_REPORTED path_delay=max group_path_count=3\n"
              "Group                                  Slack\n"
              "--------------------------------------------\n"
              "No paths found.\n\n"
              "SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew "
              "min_pulse_width max_capacitance max_fanout\n")
_FIX_DIRTY = _FIX_CLEAN.replace(
    "\nSIGNOFF_CHECK_TYPES_REPORTED",
    "\nmax_slew\n"
    "_1234_/A  1.83  1.50  0.33 (VIOLATED)\n"
    "_5678_/B  1.71  1.50  0.21 (VIOLATED)\n"
    "\nSIGNOFF_CHECK_TYPES_REPORTED")
_FIX_FAILED = _FIX_CLEAN.replace(_MARK_OK + " recovery removal max_slew "
                                 "min_pulse_width max_capacitance max_fanout",
                                 _MARK_FAIL + " reason=no_liberty")
_FIX_VACUOUS = _FIX_CLEAN.split("SIGNOFF_CHECK_TYPES_REPORTED")[0]


def selftest() -> int:
    """The four fixtures PPA_INTERFACES §7 requires, on the discriminator that
    decides everything here."""
    fails = []
    for name, text, want in (
            ("positive", _FIX_CLEAN, 0),
            ("negative", _FIX_DIRTY, 2),
            ("vacuous", _FIX_VACUOUS, None),
            ("tool-failed", _FIX_FAILED, None)):
        regs = violator_regions(text)
        ran = [r for r in regs if r[0] == "REPORTED"]
        if want is None:
            got = None if not ran else sum(count_violators(r, "max_slew")
                                           for _, r, _ in ran)
        else:
            got = sum(count_violators(r, "max_slew") for _, r, _ in ran) \
                if ran else None
        if got != want:
            fails.append(f"{name}: want {want}, got {got}")
        print(f"  {name:12s} -> {got!r} (want {want!r})"
              f" {'OK' if got == want else 'FAIL'}")
    if fails:
        for f in fails:
            print(f"[{PROGRAM}] SELFTEST FAILED: {f}", file=sys.stderr)
        return 1
    print(f"[{PROGRAM}] selftest: 4/4 fixtures behave")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", nargs="?")
    ap.add_argument("--json", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.run:
        print(f"[{PROGRAM}] bad invocation: give a run dir or --selftest",
              file=sys.stderr)
        return 3
    run = Path(a.run).resolve()
    recs, notes = records(run)
    doc = {"schema": "vibeic.ppa.drv_records.v1", "program": PROGRAM,
           "run": str(run), "records": recs, "notes": notes}
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(doc, indent=2, ensure_ascii=False)
                                + "\n", encoding="utf-8")
    meas = sum(1 for r in recs if r["status"] == "MEASURED")
    print(f"{PROGRAM}: {len(recs)} record(s), {meas} MEASURED, "
          f"{len(recs)-meas} NOT_MEASURED")
    for n in notes:
        print(f"  {n}")
    if not meas:
        print(f"[CANNOT CHECK] {PROGRAM}: nothing was measured", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
