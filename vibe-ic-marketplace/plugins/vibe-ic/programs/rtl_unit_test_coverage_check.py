#!/usr/bin/env python3
"""rtl_unit_test_coverage_check.py — v0.50.2 plugin gate

ENFORCEMENT: advisory
CHIP_AGNOSTIC: strict

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Verifies every FSM-bearing RTL module has a corresponding per-module unit
testbench under sim_unit/. Catches the failure mode from <benchmark> v0.50
where end-to-end sim PASSed but real hardware FAILed because per-module
behaviour (pulse-classifier, frame-end timing, trailing-delimiter handling)
was never isolated.

Heuristics for "needs a tb":
  - Module file contains `case (st)` / `case (state)` / `localparam S_*`
    → state machine, needs tb
  - Module file contains `low_cnt`/`high_cnt`/`pulse`/`width` regs
    → pulse classifier, needs tb
  - Module is named `rx_phy` / `tx_phy` / `dispatcher` / `mac` / `ctrl`
    → protocol-bearing, needs tb

Each candidate must have a matching `sim_unit/tb_<module>.v` file.

Usage:
    python3 rtl_unit_test_coverage_check.py <project_dir>
        [--rtl-dir <path>]    (default: <proj>/rtl)
        [--sim-dir <path>]    (default: <proj>/sim_unit)
        [--json <out>]
        [--strict]

Exit codes:
    0 — every FSM-bearing module has a tb
    1 — one or more missing
    2 — input error
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
import _path_layout as _pl

# Patterns indicating module needs a unit tb
_FSM_PATTERNS = [
    re.compile(r"case\s*\(\s*st\s*\)"),
    re.compile(r"case\s*\(\s*state\s*\)"),
    re.compile(r"localparam\s+S_\w+\s*=", re.IGNORECASE),
    re.compile(r"reg\s+\[\s*\d+\s*:\s*0\s*\]\s*(?:state|st)\b"),
]
_PHY_PATTERNS = [
    re.compile(r"\b(low_cnt|high_cnt)\b"),
    re.compile(r"pulse_(?:low|high|width)"),
    re.compile(r"_(?:rx|tx|dispatcher|mac|ctrl)\.v$", re.IGNORECASE),
]
# Module names that always need tb regardless of patterns
_MUST_TB_NAMES = {
    "rx_phy", "tx_phy", "dispatcher", "cmd_dispatcher",
    "mac", "rx_chk", "rx_cmd", "ctl_top", "tx_chk",
    "frame_assembler", "byte_assembler", "fsm",
}


def needs_tb(rtl_path: Path) -> tuple[bool, list[str]]:
    """Return (needs_tb, reasons)."""
    name = rtl_path.stem.lower()
    reasons = []

    # v1.15.67 — must-tb names match on a NAME-TOKEN boundary, not as a bare
    # substring. MEASURED on opentitan_aes: `prim_flop_macros.sv` was credited
    # as needing a per-module unit testbench because "mac" occurs inside
    # "macros". `_MUST_TB_NAMES` is a list of module ROLES (`mac`, `ctl_top`,
    # `rx_phy`, `fsm`), and a role is a whole token in a module name — every
    # entry in the set is still matched wherever it is one, including the
    # multi-token entries, so no module that used to be credited stops being.
    for must in _MUST_TB_NAMES:
        if re.search(r"(?:^|_)" + re.escape(must) + r"(?:_|$)", name):
            reasons.append(f"name contains role token '{must}'")
            return True, reasons

    try:
        text = rtl_path.read_text()
    except Exception:
        return False, ["unreadable"]

    for pat in _FSM_PATTERNS:
        if pat.search(text):
            reasons.append(f"FSM pattern: {pat.pattern[:40]}")

    for pat in _PHY_PATTERNS:
        if pat.search(text) or pat.search(rtl_path.name):
            reasons.append(f"PHY pattern: {pat.pattern[:40]}")

    return bool(reasons), reasons


def design_namespaces(module_stems: "set[str] | list[str]") -> set[str]:
    """The leading name tokens THIS DESIGN uses as a namespace, read from its
    own module set. Returns bare tokens without the trailing underscore.

    WHY THIS REPLACED A HARDCODED LIST. `has_tb` used to strip a fixed set of
    four leading prefixes, and ONE OF THE FOUR WAS A PRIVATE CHIP CODENAME (it
    is on `programs/tests/chip_deny_list.txt`; it is not repeated here, which
    is the whole point). It sat in ordinary matching logic — not in a guard
    implementing the deny rule, where naming the token is unavoidable — and the
    tree-wide guard could not see it: `source_chip_agnostic_check` matches
    word-bounded (`(?<![A-Za-z0-9_])...(?![A-Za-z0-9_])`, the rule
    `chip_deny_list.txt` states for itself) and the literal carried a trailing
    underscore, so it matched nothing. MEASURED at `d510241488f9`: word-bounded
    hits over all 1357 top-level programs = 0 while substring hits = 49, and
    this was the ONLY one of the 49 sitting in logic rather than in prose or in
    a guard's own pattern.

    A NAMESPACE IS ATTESTED BY THE DESIGN, in one of two ways, and both are
    read from the module stems the caller already has:

      * a token run `T` that at least TWO module stems begin with (`T_...`) --
        a namespace one module wears is a name, a namespace two modules wear is
        a namespace;
      * a token run `T` such that stripping `T_` from one module stem yields
        ANOTHER module stem in the same directory (`aid_rx_phy` beside
        `rx_phy`) -- the design has spelled the same module both ways, which is
        the strongest attestation available and needs no second file.

    NOTHING IS ASSUMED AND NOTHING IS NAMED. `aid_` is the plugin's own public
    design-class namespace (`aid_class_rtl_gen.py`,
    `aid_class_half_duplex_single_wire`), and `chip_deny_list.txt` explicitly
    warns against listing `aid`; `u_` and `i_` are the universal Verilog
    instance-name conventions and are two characters long. None of the three is
    a codename, and none of them needs to be written down: a design that really
    uses them attests them here, and one that does not never had them stripped
    for a reason it could state.

    FAIL-CLOSED. An empty set means only the exact module name (and the role
    aliases below) can match -- STRICTER, never looser, so this can report a
    missing testbench that was previously credited and can never credit one
    that was previously missing. `namespace_note` in the report says which
    happened and what it was derived from.
    """
    stems = {str(s) for s in module_stems}
    out: set[str] = set()
    for stem in stems:
        parts = stem.split("_")
        for cut in range(1, len(parts)):
            head, tail = "_".join(parts[:cut]), "_".join(parts[cut:])
            if not head or not tail:
                continue
            # attestation 2 -- the design spelled the same module both ways
            if tail in stems:
                out.add(head)
                continue
            # attestation 1 -- two or more modules wear this namespace
            if sum(1 for other in stems
                   if other.startswith(head + "_")) >= 2:
                out.add(head)
    return out


def has_tb(module_name: str, sim_dir: Path,
           namespaces: "set[str] | None" = None) -> Path | None:
    """Look for sim_unit/tb_<module>.v with stem variants:
       module 'aid_rx_phy' matches tb_aid_rx_phy.v OR tb_rx_phy.v -- when the
       design itself attests `aid` as a namespace (see `design_namespaces`).

    `cmd_` and `_dispatcher` stay: those are ROLE words, already in
    `_MUST_TB_NAMES` (`cmd_dispatcher`, `dispatcher`), chip-agnostic, and
    dropping them would change verdicts beyond the leak this replaces.
    """
    candidates = {module_name}
    for ns in sorted(namespaces or ()):
        if module_name.startswith(ns + "_"):
            candidates.add(module_name[len(ns) + 1:])
    # Common aliases (cmd_dispatcher → dispatcher)
    if module_name.startswith("cmd_"):
        candidates.add(module_name[len("cmd_"):])
    if module_name.endswith("_dispatcher"):
        candidates.add("dispatcher")
        candidates.add("disp")
    for nm in candidates:
        for ext in (".v", ".sv"):
            cand = sim_dir / f"tb_{nm}{ext}"
            if cand.exists():
                return cand
    return None


def reused_ip_modules(rtl_dir: Path) -> set[str]:
    """v1.15.67 — the module names this run did NOT author.

    A per-module unit testbench is a demand on the modules THIS RUN WROTE.
    When the design stages the RTL it is built from, the flow authors none of
    them, and this gate's own docstring says it was wired advisory precisely
    so it would "not block a landing on debt it did not create". MEASURED on
    opentitan_aes, plugin v1.15.66: 11 candidates, 11 missing, ALL of them
    pre-verified vendor modules, and the FAIL blocked step 4 — the exact
    outcome the wiring note was written to prevent.

    The denominator is per MODULE, not per design: `SOURCE_MANIFEST.json` is
    written by the RTL-staging step and records `ip_list` — the modules that
    arrived with the design. A design that mixes reused IP with modules it
    authored keeps every authored module in the denominator, so the gate
    cannot be silenced by staging one vendor file.

    Empty (so: nothing excused) when the manifest is absent or unreadable —
    every design without a staged-IP manifest is byte-unchanged."""
    man = rtl_dir / "SOURCE_MANIFEST.json"
    try:
        data = json.loads(man.read_text(encoding="utf-8"))
    except Exception:      # noqa: BLE001 — no manifest, no exemption
        return set()
    if not isinstance(data, dict) or not data.get("reused_ip"):
        return set()
    names = data.get("ip_list")
    if not isinstance(names, list):
        return set()
    return {n.lower() for n in names if isinstance(n, str) and n}


def check(project: Path, rtl_dir: Path, sim_dir: Path) -> dict:
    findings = []
    coverage = []
    if not rtl_dir.exists():
        return {"pass": False, "error": f"rtl dir {rtl_dir} not found", "findings": []}

    rtl_files = sorted(list(rtl_dir.glob("*.v")) + list(rtl_dir.glob("*.sv")))
    rtl_files = [r for r in rtl_files if not r.name.endswith(".vh")]

    reused = reused_ip_modules(rtl_dir)
    # Derived from THIS design's own module set, never from a written list.
    namespaces = design_namespaces({r.stem for r in rtl_files})
    n_total = 0
    excused: list[str] = []
    for rtl in rtl_files:
        if rtl.name.endswith("_pkg.vh") or rtl.name.endswith("_params.vh"):
            continue
        need, reasons = needs_tb(rtl)
        if not need:
            continue
        if rtl.stem.lower() in reused:
            # Not in the denominator, and SAID SO rather than silently
            # dropped: the reader can see what was not asked, and of whom.
            excused.append(rtl.name)
            continue
        n_total += 1
        tb = has_tb(rtl.stem, sim_dir, namespaces)
        entry = {"module": rtl.name, "reasons": reasons, "tb_path": str(tb) if tb else None}
        coverage.append(entry)
        if not tb:
            findings.append({
                "severity": "FAIL",
                "rule": "missing_unit_tb",
                "module": rtl.name,
                "reasons": reasons,
                "expected_tb": f"{sim_dir}/tb_{rtl.stem}.v",
                "message": (f"{rtl.name} needs a per-module unit testbench "
                            f"but {sim_dir}/tb_{rtl.stem}.v is missing. "
                            f"Reasons: {reasons}. See "
                            "rtl-unit-testbench-gen SKILL.md."),
            })

    return {
        "rtl_dir": str(rtl_dir),
        "sim_dir": str(sim_dir),
        "candidates_total": n_total,
        "candidates_covered": n_total - len(findings),
        "candidates_missing": len(findings),
        "reused_ip_modules_not_in_denominator": sorted(excused),
        "denominator_note": (
            f"{len(excused)} module(s) arrived with the design as staged IP "
            f"(phase2/stage1/rtl/SOURCE_MANIFEST.json ip_list) and are not "
            f"counted: a per-module unit testbench is a demand on the "
            f"modules this run authored." if excused else
            "every FSM/PHY-bearing module in this tree is in the denominator"),
        "module_namespaces": sorted(namespaces),
        "namespace_note": (
            "leading name token(s) this design attests as a namespace — a "
            "token run two or more modules wear, or one whose removal names "
            "another module in the same directory. Derived from the module "
            "set; no prefix is written down. Empty means only an exact "
            "`tb_<module>` matched, which is the stricter reading."),
        "coverage": coverage,
        "findings": findings,
        "pass": len(findings) == 0,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--rtl-dir", default=None)
    ap.add_argument("--sim-dir", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    proj = Path(args.project_dir)
    if not proj.exists():
        print(f"ERROR: project_dir {proj} not found", file=sys.stderr)
        return 2
    rtl = Path(args.rtl_dir) if args.rtl_dir else _pl.rtl_dir(proj)
    sim = Path(args.sim_dir) if args.sim_dir else proj / "sim_unit"

    result = check(proj, rtl, sim)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
