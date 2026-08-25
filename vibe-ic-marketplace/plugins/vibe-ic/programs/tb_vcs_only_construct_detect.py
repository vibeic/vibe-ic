#!/usr/bin/env python3
"""tb_vcs_only_construct_detect.py — detect VCS/Xcelium-only
SystemVerilog testbench constructs that iverilog cannot run.

Extracted from open-benchmark-methodology § 4 Category D
(tool-substitution gap). When a benchmark mandates Synopsys VCS or
Cadence Xcelium and we substitute iverilog, a failing TB may be
failing purely because it uses a commercial-only construct iverilog
rejects — that is a Category-D tool-gap, not an agent-fixable RTL
bug. This program scans the TB for the known iverilog-rejecting
constructs and reports the offending line(s) as evidence, so the
triage can auto-classify Category-D instead of burning close-loop
compute on it.

FORK-FIXABLE, NOT a terminal FLOOR (v1.3.43 doctrine update): because
we FORK the EDA tools (`vibeic/{iverilog,verilator,yosys,OpenROAD,…}`,
shipped as `vibeic-eda`), a Category-D hit is an ENGINEERING BACKLOG
ITEM against the fork — route it to `tools/vibeic-eda/FIX_STATUS.md`,
NOT a permanent ceiling. Detecting the construct does NOT by itself
prove the case is unwinnable: run the § 4.1 floor-proof (build+run the
GOLDEN under a tool that supports the feature — Verilator `--timing`,
forked iverilog). If the golden PASSES → confirmed genuine tool-gap →
fork the capability (many are already closed, e.g. `break;`/`continue;`
in the forked iverilog 14-devel). If the golden ALSO fails there → it
was NEVER a pure tool-gap; re-triage as a dataset/RTL floor. NEVER
patch a tool to "pass benchmark X" — fix the CAPABILITY, not the case.

Detected constructs (the ones observed to reject under iverilog 12
in the 2026-05-28 RTLLM sweep, e.g. ring_counter / asyn_fifo):
  * array-aggregate / assignment-pattern init   `'{ ... }`
  * `break;` / `continue;` inside SV loops (iverilog -g2012 gap)
  * `std::randomize` / `.randomize()` constrained-random
  * `$urandom_range(` system task
  * `unique`/`priority` case (some iverilog versions reject)
  * `wait_order` / `fork ... join_none` advanced fork
  * SV `string` queue ops `.push_back(` / `.pop_front(`

Usage
=====
  python3 tb_vcs_only_construct_detect.py <testbench.v|.sv> [--json out.json]

  # RUN the § 4.1 floor-proof instead of only asking for one:
  python3 tb_vcs_only_construct_detect.py <tb> --golden <golden.v>
      --tb-top <tb_module> --dut-name <name-the-TB-instantiates>
      [--golden-top <name>] [--data-dir <dir>] [--json out.json]

  # ALSO try the deterministic safe-subset rewrite (break;/continue;/
  # unique-priority) into a *_iv sidecar instead of routing straight to the
  # fork backlog. With --golden the rewrite is rejected unless the golden
  # STILL passes the rewritten TB:
  python3 tb_vcs_only_construct_detect.py <tb> --remediate
      [--remediate-out <path>] [--golden <golden.v> --tb-top ... --dut-name ...]

  With `--golden` the report carries a `floor_proof` record measured by
  `verilator_timing_fallback_check.adjudicate` — golden PASSES its own TB under
  Verilator --timing => `disposition = SCORABLE-UNDER-VERILATOR`; golden FAILS
  or Verilator is absent => the FLOOR-D stands and the disposition is unchanged.
  The exit code is the DETECTOR's either way: the construct is present, and
  rc 1 means "the detector fired", which is this program's stated contract.

Honest failure / semantics
==========================
  * FAIL (rc 1) means "VCS-only construct(s) FOUND" → the TB is a
    Category-D tool-gap; the report lists the construct + line and
    marks `disposition = FORK-FIXABLE` with a `fork_route` to
    FIX_STATUS.md. (FAIL here is the *detector firing*, i.e. evidence
    the case fails under our current substitution — the next step is
    the § 4.1 floor-proof + fork the capability, NOT shelve a floor.)
  * PASS (rc 0) means "no known VCS-only construct found" → the TB
    is NOT a Category-D tool-gap; a failing run must be triaged
    elsewhere (real RTL bug / spec-ambiguity / etc.).
  * Missing / unreadable TB → rc 2 (usage error): cannot scan a file
    that isn't there; never a vacuous PASS.

Exit codes
==========
  0 — PASS (no VCS-only construct detected)
  1 — FAIL (VCS-only construct detected — Category-D floor evidence)
  2 — usage error (missing/unreadable input)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# (construct id, human label, compiled regex). Patterns are line-oriented
# and avoid common false positives (e.g. `'{` requires the apostrophe-brace
# assignment-pattern form, not a plain `{`).
PATTERNS = [
    ("assignment_pattern",
     "array-aggregate / assignment-pattern init ('{...})",
     re.compile(r"'\s*\{")),
    ("break_stmt",
     "break; statement",
     re.compile(r"\bbreak\s*;")),
    ("continue_stmt",
     "continue; statement",
     re.compile(r"\bcontinue\s*;")),
    ("std_randomize",
     "std::randomize / .randomize() constrained-random",
     re.compile(r"(std\s*::\s*randomize|\.\s*randomize\s*\()")),
    ("urandom_range",
     "$urandom_range() system task",
     re.compile(r"\$urandom_range\s*\(")),
    ("unique_priority_case",
     "unique/priority case",
     re.compile(r"\b(unique|priority)\s+case\b")),
    ("advanced_fork",
     "fork...join_none / wait_order advanced fork",
     re.compile(r"\b(join_none|join_any|wait_order)\b")),
    ("queue_ops",
     "SV queue ops (.push_back/.pop_front)",
     re.compile(r"\.\s*(push_back|pop_front|push_front|pop_back)\s*\(")),
]

# Strip line comments and block comments before matching (a construct
# mentioned in a comment is not actually compiled).
_LINE_COMMENT = re.compile(r"//.*$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT.sub("", text)
    return "\n".join(_LINE_COMMENT.sub("", ln) for ln in text.splitlines())


def scan_text(text: str) -> list[dict]:
    """Return a list of {construct, label, line, snippet} hits."""
    clean = _strip_comments(text)
    hits: list[dict] = []
    for i, line in enumerate(clean.splitlines(), start=1):
        for cid, label, rx in PATTERNS:
            if rx.search(line):
                hits.append({"construct": cid, "label": label,
                             "line": i, "snippet": line.strip()[:120]})
    return hits


#: THE § 4.1 FLOOR-PROOF, RUN RATHER THAN REQUESTED (the chain edge).
#:
#: Everything above detects a construct. The docstring then says the next step
#: is to "build+run the GOLDEN under a tool that supports the feature —
#: Verilator `--timing`" — and until this edge existed that sentence was the
#: whole of it: `floor_proof_required` was a STRING asking a reader to go and
#: measure something, and `verilator_timing_fallback_check.py`, which performs
#: exactly that measurement, was reachable from nothing but its own unit test.
#:
#: The adjudicator is the one in `verilator_timing_fallback_check.adjudicate`,
#: imported rather than re-implemented: it carries the FAITHFULNESS GUARD (the
#: golden must pass its OWN TB under Verilator before Verilator is allowed to
#: score anything), which a second copy here would drift away from.
#:
#: rc is DELIBERATELY UNCHANGED by the proof. This program's own contract says
#: rc 1 is "the detector firing", and the construct is present either way; what
#: the proof decides is the DISPOSITION, which is the thing a triage reads.
def floor_proof(tb, golden, tb_top: str, dut_name: str,
                golden_top: str | None = None,
                data_dir=None) -> dict:
    """Run the § 4.1 floor-proof for a detected Category-D construct.

    Returns a record with `verdict` in
    VERILATOR_FAITHFUL / VERILATOR_UNFAITHFUL / VERILATOR_ABSENT, the
    adjudicator's own sentence, and the disposition the triage should carry.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import verilator_timing_fallback_check as _vtf

    rc, detail = _vtf.adjudicate(
        Path(tb), Path(golden), tb_top, dut_name,
        golden_top or dut_name,
        Path(data_dir) if data_dir else None,
        list(_vtf._DEFAULT_PASS), list(_vtf._DEFAULT_FAIL))
    verdict, disposition = {
        0: ("VERILATOR_FAITHFUL", "SCORABLE-UNDER-VERILATOR"),
        1: ("VERILATOR_UNFAITHFUL", "FORK-FIXABLE"),
    }.get(rc, ("VERILATOR_ABSENT", "FORK-FIXABLE"))
    return {"tool": "verilator_timing_fallback_check",
            "verdict": verdict, "rc": rc, "detail": detail,
            "disposition": disposition,
            "golden": str(golden), "tb_top": tb_top, "dut_name": dut_name}


#: THE OTHER HALF OF § 4.1, AND THE OTHER EDGE THAT WAS MISSING.
#:
#: `floor_proof` answers "is this construct really a tool-gap". This answers the
#: question that comes next and is cheaper: "does this construct need the fork at
#: all, or is it one of the three iverilog rejects for a reason a deterministic
#: source rewrite removes?" `tb_vcs_only_construct_remediate` was written to
#: answer exactly that -- break; / continue; / unique-priority case, rewritten to
#: labelled-block `disable` and a dropped qualifier, into a `*_iv` SIDECAR with
#: the ORIGINAL TB untouched -- and it was reachable from nothing but its own
#: unit test, so every Category-D hit was routed to the fork backlog including
#: the ones a rewrite already closes.
#:
#: THE REWRITE IS NOT TRUSTED, IT IS CHECKED. Two guards, both the remediator's
#: own and neither re-implemented here: it RE-SCANS its output and REFUSES if any
#: blocking construct survives (never a partially-fixed TB), and when a golden is
#: supplied the golden must STILL PASS the rewritten TB or the sidecar is deleted
#: and the case stays FLOOR-D. A rewrite that lets a wrong design pass is a
#: weaker TB, which is the one outcome worse than a missing capability.
#:
#: OPT-IN AND rc-NEUTRAL, for the same reason `floor_proof` is: the construct is
#: present either way, so this program's rc 1 ("the detector fired") does not
#: move. What changes is the DISPOSITION a triage reads.
def remediate(tb, out=None, golden=None) -> dict:
    """Attempt the closed-safe-subset rewrite of a Category-D testbench.

    Returns a record with `verdict` in REMEDIATED / REFUSED, the remediator's
    own reason, the sidecar path when one was written, and the disposition the
    triage should carry.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tb_vcs_only_construct_remediate as _rem

    tb = Path(tb)
    remediated, report = _rem.remediate_text(
        tb.read_text(encoding="utf-8", errors="replace"))
    rec = {"tool": "tb_vcs_only_construct_remediate",
           "rewrites": report.get("rewrites", {}),
           "refuse_constructs": report.get("refuse_constructs", []),
           "residual": report.get("residual", []),
           "sidecar": None, "golden_still_passes": None}
    if remediated is None:
        rec.update(verdict="REFUSED", reason=report.get("reason", ""),
                   disposition="FORK-FIXABLE")
        return rec

    sidecar = Path(out) if out else tb.with_name(tb.stem + "_iv" + tb.suffix)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(remediated, encoding="utf-8")
    rec["sidecar"] = str(sidecar)

    if golden is not None:
        # §4.05 TB-WEAKENING GUARD. A rewrite the golden no longer passes is
        # rejected and its sidecar removed, so a refused remediation cannot
        # leave a file behind that a later step would pick up as scorable.
        if not _rem.golden_still_passes(Path(golden), sidecar):
            try:
                sidecar.unlink()
            except OSError:
                pass
            rec.update(verdict="REFUSED", sidecar=None,
                       golden_still_passes=False,
                       reason="golden does NOT still pass the remediated TB "
                              "-- rewrite rejected as TB-weakening (§4.05)",
                       disposition="FORK-FIXABLE")
            return rec
        rec["golden_still_passes"] = True

    rec.update(verdict="REMEDIATED",
               reason="closed safe subset rewritten; original TB untouched",
               disposition="SCORABLE-AFTER-REWRITE")
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tb", help="path to the testbench .v / .sv")
    ap.add_argument("--json", help="write JSON report to this path")
    # THE § 4.1 FLOOR-PROOF, OPTIONAL AND OFF BY DEFAULT. Supplying a golden is
    # what turns `floor_proof_required` from a request into a measurement; a
    # caller that has no golden gets byte-for-byte the report it got before.
    ap.add_argument("--golden",
                    help="the dataset's OWN golden RTL — supply it to RUN the "
                         "§ 4.1 floor-proof instead of only asking for one")
    ap.add_argument("--tb-top", help="the testbench's top module name "
                                     "(required with --golden)")
    ap.add_argument("--dut-name", help="the module name the TB instantiates "
                                       "(required with --golden)")
    ap.add_argument("--golden-top",
                    help="the golden's own top module name (default --dut-name)")
    ap.add_argument("--data-dir",
                    help="directory holding $readmemh/$readmemb data files")
    # THE SAFE-SUBSET REWRITE, OPTIONAL AND OFF BY DEFAULT. Without it the
    # report is byte-for-byte what it was; with it the same run also says
    # whether the construct needs the fork at all. `--remediate-out` keeps the
    # sidecar out of a read-only dataset directory when the caller wants it
    # elsewhere; `--golden` (already required to be a real golden above) is
    # reused as the TB-weakening guard's reference when it is supplied.
    ap.add_argument("--remediate", action="store_true",
                    help="attempt the closed-safe-subset rewrite (break; / "
                         "continue; / unique-priority case) into a *_iv "
                         "SIDECAR; the ORIGINAL testbench is never modified")
    ap.add_argument("--remediate-out",
                    help="sidecar path for --remediate "
                         "(default: <tb-stem>_iv<ext> beside the testbench)")
    a = ap.parse_args(argv)

    if a.golden and not (a.tb_top and a.dut_name):
        print("usage error: --golden requires --tb-top and --dut-name",
              file=sys.stderr)
        return 2

    p = Path(a.tb)
    if not p.is_file():
        print(f"usage error: testbench not found: {p}", file=sys.stderr)
        return 2
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:  # pragma: no cover - unreadable file
        print(f"usage error: cannot read {p}: {e}", file=sys.stderr)
        return 2

    hits = scan_text(text)
    report = {"program": "tb_vcs_only_construct_detect",
              "tb": str(p), "hits": hits}
    if hits:
        report["verdict"] = "FAIL"
        report["category"] = "D"
        report["reason"] = "vcs_only_construct_detected"
        # v1.3.43: Category-D is FORK-FIXABLE (route to the vibeic-eda fork
        # backlog), NOT a terminal floor. Detection is evidence for the § 4.1
        # floor-proof, not a verdict of unwinnable.
        report["disposition"] = "FORK-FIXABLE"
        report["fork_route"] = "tools/vibeic-eda/FIX_STATUS.md"
        report["floor_proof_required"] = (
            "run the GOLDEN under a tool that supports the feature "
            "(Verilator --timing / forked iverilog); PASS => genuine tool-gap "
            "=> fork the capability; golden ALSO fails => re-triage dataset/RTL")
        if a.golden:
            proof = floor_proof(p, Path(a.golden), a.tb_top, a.dut_name,
                                a.golden_top, a.data_dir)
            report["floor_proof"] = proof
            report["disposition"] = proof["disposition"]
            print(f"FLOOR-PROOF {proof['verdict']}: {proof['detail']}",
                  file=sys.stderr)
        if a.remediate:
            rem = remediate(p, a.remediate_out, a.golden)
            report["remediation"] = rem
            # A successful rewrite RELAXES the disposition; a refusal leaves
            # whatever the floor-proof (or the default) already decided,
            # because a rewrite that did not happen changes nothing.
            if rem["verdict"] == "REMEDIATED":
                report["disposition"] = rem["disposition"]
            print(f"REMEDIATION {rem['verdict']}: {rem['reason']}",
                  file=sys.stderr)
        _emit(a, report)
        for h in hits:
            print(f"CATEGORY-D (FORK-FIXABLE, route to FIX_STATUS.md): "
                  f"{h['label']} at line {h['line']}: {h['snippet']}",
                  file=sys.stderr)
        return 1
    report["verdict"] = "PASS"
    _emit(a, report)
    print(f"PASS: no VCS/Xcelium-only construct found in {p.name}")
    return 0


def _emit(a, report: dict) -> None:
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
