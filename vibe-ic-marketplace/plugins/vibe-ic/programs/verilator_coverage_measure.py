#!/usr/bin/env python3
"""verilator_coverage_measure.py — v0.53 plugin gate

Force machine-measured Verilator coverage instead of agent-estimated numbers.

The v0.52 fresh-agent <half-duplex-tester> PASS was accompanied by a self-reported
"≥ 95 % estimated line coverage". When actually measured with
`verilator --coverage --coverage-line --coverage-toggle`, line coverage
was 78.3 %, toggle 75.5 %, branch 82.3 %. This gate rejects reports that
lack tool-generated coverage artefacts.

Two modes:
  measure — run Verilator + compile + simulate + parse coverage.dat
  check   — only verify that a prior run produced coverage.dat +
            coverage_actual.json with tool-generated content

Usage:
    # Measure from scratch (assumes RTL under ./rtl and main driver under
    # sim/cov_build/main.cpp — see your project's conventions)
    python3 verilator_coverage_measure.py measure \\
        --rtl-dir rtl \\
        --top example_top \\
        --main sim/cov_build/main.cpp \\
        --out reports/coverage/coverage_actual.json

    # Check-only mode (no rebuild, verify stored artefact)
    python3 verilator_coverage_measure.py check \\
        --coverage-json reports/coverage/coverage_actual.json \\
        --min-line 70 --min-toggle 60 --min-branch 70

Exit code (`measure`):
    0 — all thresholds met
    1 — threshold(s) below target

Exit code (`check`) — COVERAGE-CREDIT SPLIT of the two meanings that used to
share exit 2. `flow_compliance_check._check_program_exit_zero` maps rc=2 onto
VACUOUS_PASS ("the input this gate audits does not apply to this project"),
and VACUOUS_PASS was counted into `pass_count`. So every rc=2 this program
returned bought the enclosing step PASS credit — including for an artefact
that EXISTS at the declared coverage path but carries no coverage in it.
An artefact under the coverage path with no `totals.*` is a MISLABELLED
artefact, not an inapplicable input.
(State AS MEASURED THEN. `flow_compliance_check` has since dropped
VACUOUS_PASS from the executed-PASS numerator — the tier leaves X and stays
in Y — so an rc=2 no longer buys PASS credit. The split below is unaffected:
a mislabelled artefact must be rc=1 whatever the tier above it counts, and
this program's own rc=2 was the mechanism by which step 4 was measured
VACUOUS_PASS on the host that found the numerator defect.)

    0 — a real measurement is present and every threshold is met
    1 — a DEFECT: below threshold, OR the artefact at the declared path is
        corrupt / mislabelled / forged, OR no measurement exists on a host
        where the Verilator toolchain that would have taken it IS installed
    3 — a DISCLOSED capability gap (printed with the `PASS_WITH_WAIVERS`
        stdout sentinel `_check_program_exit_zero` requires): no coverage
        measurement AND no Verilator on PATH to have taken one. The step
        resolves to WAIVED-DEFERRED — reviewable, review_required, and
        REMOVED from the executed-PASS numerator — instead of silently
        counting as a pass.

    rc=2 is no longer emitted by `check`. Other programs that legitimately
    use the input-missing convention (foundry_handoff_package_check,
    mixed_signal_merge_check) are untouched: the semantics change is local
    to this program, not to `_check_program_exit_zero`.

Generality: works for any Verilator-compatible RTL. Threshold defaults are
conservative; tighten per project maturity.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ----- measurement --------------------------------------------------


def run(cmd: List[str], cwd: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def verilate_and_run(rtl_dir: str, top: str, main_cpp: str, build_dir: str) -> str:
    """Verilate + make + execute to produce coverage.dat. Returns path to .dat."""
    rtl_files = sorted(
        [str(p) for p in Path(rtl_dir).glob("*.v")]
        + [str(p) for p in Path(rtl_dir).glob("*.sv")]
    )
    if not rtl_files:
        raise SystemExit(f"No .v/.sv under {rtl_dir}")

    Path(build_dir).mkdir(parents=True, exist_ok=True)

    # verilate
    # `-I<rtl_dir>` is required so RTL with `include "params.vh"` etc.
    # can find its headers. Without it, projects that split params/
    # types out of the main .v fail to elaborate (regression caught by
    # B3 v0.55.1 verilator-bugs analysis on phase2+3_v050_smoke).
    vcmd = [
        "verilator",
        "--cc",
        "--exe",
        "--build",
        "--coverage",
        "--coverage-line",
        "--coverage-toggle",
        "--coverage-user",
        f"-I{rtl_dir}",
        "--top-module",
        top,
        "-Mdir",
        build_dir,
        main_cpp,
    ] + rtl_files
    r = run(vcmd, check=False)
    if r.returncode != 0:
        raise SystemExit(f"verilator failed:\nSTDERR:\n{r.stderr}\nSTDOUT:\n{r.stdout}")

    # Execute
    exe = Path(build_dir) / f"V{top}"
    if not exe.exists():
        raise SystemExit(f"compiled executable not found: {exe}")
    r = run([str(exe)], cwd=build_dir, check=False)
    if r.returncode != 0:
        # run may intentionally exit non-zero; coverage.dat can still be valid
        sys.stderr.write(
            f"[warn] simulator exit={r.returncode}; continuing if coverage.dat present\n"
        )

    dat = Path(build_dir) / "coverage.dat"
    if not dat.exists():
        # Try Verilator's default location
        dat = Path(build_dir) / "logs" / "coverage.dat"
    if not dat.exists():
        raise SystemExit(f"coverage.dat not produced under {build_dir}")
    return str(dat)


# ----- parsing ------------------------------------------------------

# Coverage record format. Both Verilator 4.x and 5.x emit one record per
# line, prefixed `C` (the type) then a single-quoted blob of fields and
# a hit count: `C '<blob>' <hits>`. The blob's structure changed between
# versions:
#
#   v4.x:   `\x02<category>\x01<file>\x01<line>\x01...\x01`
#           — leading `\x02` byte then category as the first segment.
#
#   v5.x:   `<key1>\x02<value1>\x01<key2>\x02<value2>\x01...\x01`
#           — every segment is a `key\x02value` pair. Category is
#             encoded in the `page` field (`v_line/<mod>`,
#             `v_toggle/<mod>`, `v_branch/<mod>`).
#
# We support both. The 5.x branch was added after the B3 coverage gap
# analysis (2026-04-24) found Verilator 5.020's coverage.dat parsed as
# zero points by the prior 4.x-only regex.
COVERAGE_LINE_RE = re.compile(r"^C\s+'([^']*)'\s+(\d+)\s*$")

_V5_PAGE_TO_CAT = {"v_line": "line", "v_toggle": "toggle", "v_branch": "branch"}


def _classify_v5(blob: str) -> Optional[str]:
    """Verilator 5.x parser: pull the `page` field and map to a category.
    Returns None when the record isn't a recognised category (e.g.
    Verilator's own metadata records)."""
    fields: Dict[str, str] = {}
    for pair in blob.split("\x01"):
        if "\x02" in pair:
            k, v = pair.split("\x02", 1)
            fields[k] = v
    page = fields.get("page", "")
    head = page.split("/", 1)[0] if "/" in page else page
    return _V5_PAGE_TO_CAT.get(head)


def _classify_v4(blob: str) -> Optional[str]:
    """Verilator 4.x parser: leading byte is `\\x02` then category name
    as the first \\x01-separated segment."""
    parts = blob.split("\x01")
    if not parts:
        return None
    head = parts[0].lstrip("\x02").strip()
    if head in ("line", "toggle", "branch"):
        return head
    return None


def _file_v5(blob: str) -> Optional[str]:
    """Pull the `f` (filename) field from a v5.x record."""
    for pair in blob.split("\x01"):
        if pair.startswith("f\x02"):
            return pair[2:]
    return None


def _file_v4(blob: str) -> Optional[str]:
    """v4.x: file is the second \\x01-separated segment."""
    parts = blob.split("\x01")
    return parts[1] if len(parts) > 1 else None


def parse_coverage_dat(path: str) -> Dict[str, Any]:
    """Parse Verilator coverage.dat into per-category counts + per-file
    breakdown. Auto-detects 4.x vs 5.x record format on the first
    classifiable record so a single coverage.dat from either version
    works without a flag."""
    cats = {"line": [0, 0], "toggle": [0, 0], "branch": [0, 0], "other": [0, 0]}
    per_file: Dict[str, Dict[str, List[int]]] = {}
    classifier = None  # set on first successful classification

    with open(path, "r", errors="replace") as f:
        for raw in f:
            m = COVERAGE_LINE_RE.match(raw)
            if not m:
                continue
            blob, hits = m.group(1), int(m.group(2))
            if classifier is None:
                # First classifiable record selects the format.
                head = _classify_v5(blob) or _classify_v4(blob)
                if head is not None:
                    classifier = "v5" if _classify_v5(blob) is not None else "v4"
            if classifier == "v5":
                head = _classify_v5(blob)
                src = _file_v5(blob)
            elif classifier == "v4":
                head = _classify_v4(blob)
                src = _file_v4(blob)
            else:
                head, src = None, None
            if head is None:
                head = "other"
            if head not in cats:
                head = "other"
            cats[head][1] += 1
            if hits > 0:
                cats[head][0] += 1
            if src:
                per_file.setdefault(
                    src, {"line": [0, 0], "toggle": [0, 0], "branch": [0, 0]})
                pf = per_file[src]
                if head in pf:
                    pf[head][1] += 1
                    if hits > 0:
                        pf[head][0] += 1

    def pct(pair: List[int]) -> float:
        return round(100.0 * pair[0] / pair[1], 2) if pair[1] > 0 else 0.0

    return {
        "totals": {
            "line": {"covered": cats["line"][0], "total": cats["line"][1], "pct": pct(cats["line"])},
            "toggle": {"covered": cats["toggle"][0], "total": cats["toggle"][1], "pct": pct(cats["toggle"])},
            "branch": {"covered": cats["branch"][0], "total": cats["branch"][1], "pct": pct(cats["branch"])},
        },
        "per_file": {
            src: {k: {"covered": v[0], "total": v[1], "pct": pct(v)} for k, v in pf.items()}
            for src, pf in per_file.items()
        },
        "format_detected": classifier or "unknown",
    }


# ----- artefact provenance -----------------------------------------

TOOL_SIGNATURES = [
    "verilator",  # tool name often appears in coverage.dat's preamble
    "C '\x02",    # binary tag marker
    "points_count",
]

ESTIMATION_FLAGS = [
    re.compile(r"\bestimated?\b", re.I),
    re.compile(r"\bapprox(?:imate)?\b", re.I),
    re.compile(r"≥\s*\d+\s*%"),
    re.compile(r">=\s*\d+\s*%"),
    re.compile(r"\bmanual(ly)? counted\b", re.I),
]


def artefact_looks_tool_generated(json_payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Heuristic: artefact must have numeric per-category counts + reference
    a coverage.dat path that exists. Reject if narrative fields include
    'estimated', '≥ 95 %', etc.
    """
    totals = json_payload.get("totals", {})
    for cat in ("line", "toggle", "branch"):
        if cat not in totals:
            return False, f"missing totals.{cat}"
        for key in ("covered", "total", "pct"):
            if key not in totals[cat]:
                return False, f"missing totals.{cat}.{key}"
    # Narrative fields (optional but if present must not contain estimation
    # keywords)
    for field in ("note", "notes", "source", "tool"):
        v = json_payload.get(field, "")
        if isinstance(v, str):
            for pat in ESTIMATION_FLAGS:
                if pat.search(v):
                    return False, f"estimation keyword in {field!r}: {v!r}"
    # If a .dat path is recorded, verify it exists
    dat = json_payload.get("coverage_dat")
    if dat and not Path(dat).exists():
        return False, f"coverage.dat path recorded but missing: {dat}"
    return True, "ok"


# ----- artefact classification --------------------------------------
#
# The declared coverage path is shared: `design_one_shot_runner` writes a
# FUNCTIONAL-verification verdict payload (verdict / evidence /
# verification_track / scenarios_covered) to
# reports/phase2/coverage/coverage_actual.json, the same path the flow YAML
# declares as the coverage artefact this gate audits. Such a payload carries
# no `totals` container at all — no line/toggle/branch was ever measured —
# so the coverage gate must NAME that collision rather than treat the path
# as an inapplicable input.

#: Keys that assert a coverage NUMBER. A payload carrying one of these while
#: carrying no `totals` container is a coverage CLAIM with no measurement
#: behind it — a forgery, never a capability gap.
_BARE_COVERAGE_CLAIM_KEYS = (
    "line_pct", "toggle_pct", "branch_pct",
    "line_coverage", "toggle_coverage", "branch_coverage",
    "coverage_pct", "coverage_percent", "line_coverage_pct",
)

#: Artefact kinds that are always a DEFECT, whatever the host toolchain is.
_DEFECT_KINDS = ("corrupt", "malformed", "forged")
#: Artefact kinds meaning "no coverage measurement exists at this path".
_NO_MEASUREMENT_KINDS = ("absent", "foreign")


def classify_coverage_artefact(path: Path) -> Tuple[str, str, Dict[str, Any]]:
    """Classify what actually sits at the declared coverage path.

    Returns ``(kind, detail, payload)``:

      ``measured``  a well-formed tool-generated coverage artefact — apply
                    thresholds to it.
      ``absent``    nothing at the path.
      ``foreign``   valid JSON with NO ``totals`` container: another producer
                    owns this path and no coverage was measured here.
      ``corrupt``   the file exists but is not parseable JSON.
      ``malformed`` claims to be coverage (``totals`` present) but the
                    container is incomplete / its coverage.dat backlink is
                    dead.
      ``forged``    a coverage number asserted with no measurement behind it
                    — well-formed counters carrying estimation language, or a
                    bare percentage claim with no ``totals``. This is the
                    exact "≥ 95 % estimated" shape the gate exists to reject.
    """
    if not path.exists():
        return "absent", f"no artefact at {path}", {}
    try:
        data = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001 — any unparseable file is corrupt
        return "corrupt", f"{path}: parse error: {exc}", {}
    if not isinstance(data, dict):
        return ("corrupt",
                f"{path}: top level is {type(data).__name__}, not an object",
                {})

    totals = data.get("totals")
    if not isinstance(totals, dict) or not totals:
        claims = [k for k in _BARE_COVERAGE_CLAIM_KEYS if k in data]
        if claims:
            return ("forged",
                    f"{path}: asserts coverage via {claims} with no `totals` "
                    f"container behind it — a coverage claim is not a "
                    f"coverage measurement", data)
        owner = (data.get("verification_track") or data.get("verdict")
                 or "another producer")
        return ("foreign",
                f"{path}: carries no `totals` container — the file at the "
                f"declared coverage path is a {owner!r} payload written by "
                f"another producer, so line/toggle/branch was never measured "
                f"here", data)

    ok, reason = artefact_looks_tool_generated(data)
    if ok:
        return "measured", "ok", data
    if reason.startswith("estimation keyword"):
        return "forged", f"{path}: {reason}", data
    return "malformed", f"{path}: {reason}", data


# ----- CLI ----------------------------------------------------------


def cmd_measure(args: argparse.Namespace) -> int:
    dat = verilate_and_run(args.rtl_dir, args.top, args.main, args.build_dir)
    cov = parse_coverage_dat(dat)
    out = {
        "tool": "verilator",
        "coverage_dat": dat,
        **cov,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    totals = out["totals"]
    line_pct = totals["line"]["pct"]
    toggle_pct = totals["toggle"]["pct"]
    branch_pct = totals["branch"]["pct"]
    print(
        f"[measure] line={line_pct}% toggle={toggle_pct}% branch={branch_pct}% "
        f"→ {args.out}"
    )
    if any(p < t for p, t in [(line_pct, args.min_line), (toggle_pct, args.min_toggle), (branch_pct, args.min_branch)]):
        print("[measure] below one or more thresholds", file=sys.stderr)
        return 1
    return 0


#: Exit code + stdout sentinel `flow_compliance_check._check_program_exit_zero`
#: recognises as "PASSED WITH WAIVERS" -> step tier WAIVED-DEFERRED. Both are
#: required there, so a stray rc=3 from an unrelated program is never waived.
WAIVER_EXIT_CODE = 3
WAIVER_STDOUT_SENTINEL = "PASS_WITH_WAIVERS"

#: The named capability this gate needs. Printed so the deferral is
#: attributable, in the same shape the flow's other cap-gap waivers use.
COVERAGE_CAPABILITY = "cap:verilator_coverage_toolchain"

#: Which executable's presence decides "capability gap" vs "defect". Made
#: overridable so a test harness (or a container that ships Verilator under
#: another name) can PIN the decision rather than inherit whatever the host
#: happens to have. Note the only direction this can move a verdict is
#: FAIL -> WAIVED-DEFERRED, which is still not a PASS and is printed in full.
VERILATOR_BIN_ENV = "VIBE_IC_VERILATOR_BIN"
VERILATOR_BIN_DEFAULT = os.environ.get(VERILATOR_BIN_ENV, "verilator")


def _report_no_measurement(args: argparse.Namespace, kind: str,
                           detail: str) -> int:
    """No coverage measurement exists at the declared path.

    Whether that is a DEFECT or a disclosed capability gap turns on one
    question the gate can answer for itself: was the toolchain that would
    have taken the measurement even installed?
      * absent  -> rc 3 + sentinel: EXPLAIN the gap (WAIVED-DEFERRED,
                   review_required, not counted as executed-PASS).
      * present -> rc 1: the capability existed and the measurement was
                   simply never taken. That is a defect, not an exemption.
    """
    tool = shutil.which(args.verilator_bin)
    if tool is None:
        print(f"[check] coverage NOT measured — {detail}")
        print(f"[check] {args.verilator_bin!r} is not on PATH, so no "
              f"line/toggle/branch coverage could have been produced on this "
              f"host. Disclosing a named capability gap "
              f"({COVERAGE_CAPABILITY}) — NOT certifying the step. "
              f"Remediation: install Verilator and run "
              f"`verilator_coverage_measure measure --out "
              f"{args.coverage_json}`.")
        print(f"{WAIVER_STDOUT_SENTINEL}: coverage deferred on "
              f"{COVERAGE_CAPABILITY} (review_required — a tapeout review "
              f"must close this before production)")
        return WAIVER_EXIT_CODE
    print(f"[check] FAIL — {detail}", file=sys.stderr)
    print(f"[check] {args.verilator_bin!r} IS installed ({tool}): the "
          f"capability to measure coverage was available and no measurement "
          f"was taken. This is a defect, not a capability gap.",
          file=sys.stderr)
    return 1


def cmd_check(args: argparse.Namespace) -> int:
    p = Path(args.coverage_json)
    kind, detail, data = classify_coverage_artefact(p)
    if kind in _DEFECT_KINDS:
        # A file that exists at the declared coverage path but is corrupt,
        # mislabelled-as-coverage, or forged is a DEFECT — never the
        # "input not applicable" exemption. Before the coverage-credit split all three
        # returned rc=2 and bought the step a PASS-counted VACUOUS_PASS.
        print(f"[check] artefact not tool-generated ({kind}): {detail}",
              file=sys.stderr)
        return 1
    if kind in _NO_MEASUREMENT_KINDS:
        return _report_no_measurement(args, kind, detail)
    totals = data["totals"]
    line_pct = totals["line"]["pct"]
    toggle_pct = totals["toggle"]["pct"]
    branch_pct = totals["branch"]["pct"]
    below = []
    if line_pct < args.min_line:
        below.append(f"line {line_pct}% < {args.min_line}%")
    if toggle_pct < args.min_toggle:
        below.append(f"toggle {toggle_pct}% < {args.min_toggle}%")
    if branch_pct < args.min_branch:
        below.append(f"branch {branch_pct}% < {args.min_branch}%")
    if below:
        print("[check] below threshold(s):", "; ".join(below), file=sys.stderr)
        return 1
    print(
        f"[check] PASS  line={line_pct}%  toggle={toggle_pct}%  branch={branch_pct}%"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="mode", required=True)

    m = sub.add_parser("measure", help="Verilate + run + parse + write JSON")
    m.add_argument("--rtl-dir", required=True)
    m.add_argument("--top", required=True)
    m.add_argument("--main", required=True, help="path to Verilator main.cpp driver")
    m.add_argument("--build-dir", default="phase2/stage1/sim/cov_build")
    m.add_argument("--out", required=True)
    m.add_argument("--min-line", type=float, default=70.0)
    m.add_argument("--min-toggle", type=float, default=60.0)
    m.add_argument("--min-branch", type=float, default=70.0)
    m.set_defaults(func=cmd_measure)

    c = sub.add_parser("check", help="Verify an existing coverage_actual.json")
    c.add_argument("--coverage-json", required=True)
    c.add_argument("--min-line", type=float, default=70.0)
    c.add_argument("--min-toggle", type=float, default=60.0)
    c.add_argument("--min-branch", type=float, default=70.0)
    c.add_argument(
        "--verilator-bin", default=VERILATOR_BIN_DEFAULT,
        help=("executable whose presence on PATH decides whether an absent "
              f"measurement is a disclosed capability gap (rc=3) or a defect "
              f"(rc=1). Overridable via ${VERILATOR_BIN_ENV} so a harness can "
              f"pin the capability decision instead of inheriting the host's. "
              f"Default: verilator"))
    c.set_defaults(func=cmd_check)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
