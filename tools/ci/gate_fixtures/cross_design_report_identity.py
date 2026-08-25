"""`cross-design report identity` — a per-design report that is byte-identical
across two DIFFERENT designs.

THE MUTATION IS THE MEASURED DEFECT ITSELF. The gate's docstring records the
4-IC campaign whose canned cross-design reports — coverage, CDC, PERC memo and
handoff members byte-identical across different chips — were caught only by a
MANUAL md5 sweep, and the capture that re-derived the rule records the same
thing again: "this is why two published cells' identical reports were only ever
caught by a manual sweep."

So the mutation is exactly that: one design's report-class artefact is replaced
by a byte-for-byte copy of the other design's. Both designs keep the same
report at the same relative path; only its CONTENT stops being about the design
it sits under.

THE DENOMINATOR IS THE SAME IN BOTH ARMS
========================================
Both subjects carry the same two project directories, each with the same one
report at the same relative path:

    project dirs compared:               2   (both arms)
    report-class relative paths tabled:  1   (both arms)
    files hashed:                        2   (both arms)

Nothing is added to the corpus and nothing is removed from it — in particular
neither project is emptied, which would reach the gate's `rc 2` "need >= 2
project dirs" / zero-population path and prove only that it notices an absent
subject. What moves is the number of DISTINCT digests behind that one path:
two in `can_pass`, one in `can_fail`.

WHY THE REPORT IS THE ONE IT IS
===============================
The subject mirrors the paths the landing declaration names, because
`_resolve_argv` substitutes only `$ROOT` and the two project directories are
spelled out relative to it. The report lives under `reports/`, which is the
first of the gate's `_SCAN_GLOBS`, and its basename is deliberately NOT one of
the `--allow` wrapper names the declaration inherits (`ir_drop.json`,
`power.json`): an allowlisted basename takes the conditional wrapper branch,
whose refusal is a different rule (`CROSS_DESIGN_WRAPPER_NOT_EXEMPT`) than the
one this pair exercises. The path also carries none of `_INPUT_TOKENS`
(`/input/`, `/inputs/`, `/pdk/`, `/vendor_ref/`), which are exempt by
construction because shared inputs are EXPECTED to be identical.

The copied report carries a substantive `verdict` and non-empty `findings`, so
it is never eligible for the `--allow-honest-na` verdict-only exemption — and
that flag is not on the declaration in any case.

chip-AGNOSTIC: the two directory names are the tracked evidence corpus's own
open-source design folders; nothing here reasons about a vendor, SKU or
process.
"""
import json
from pathlib import Path

GATE = "cross-design report identity"

#: The two project dirs the landing declaration names, relative to `$ROOT`.
_BASE = Path("docs/research/fleet_run_folder_triage_evidence/112/_gk198_gk")
_DESIGNS = ("ibex", "opentitan_aes")

#: Under `reports/` (the gate's first scan glob), and not an allowlisted
#: wrapper basename.
_REL = Path("reports/phase1/l20_dft_scan_topology_actionable_check.json")


def _report(design: str, chains: int, verdict: str, findings) -> str:
    return json.dumps({
        "program": "l20_dft_scan_topology_actionable_check",
        "design": design,
        "verdict": verdict,
        "scan_chains": chains,
        "findings": findings,
    }, indent=2) + "\n"


#: What a per-design report looks like when it really was produced per design.
_PER_DESIGN = {
    "ibex": _report("ibex", 4, "FAIL", ["no scan-enable pin is declared"]),
    "opentitan_aes": _report("opentitan_aes", 8, "PASS", []),
}


def _tree(work: Path, canned: bool) -> Path:
    root = work / "subject"
    for design in _DESIGNS:
        target = root / _BASE / design / _REL
        target.parent.mkdir(parents=True, exist_ok=True)
        body = _PER_DESIGN[_DESIGNS[0] if canned else design]
        target.write_text(body, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Two designs, one report path, two different reports."""
    return _tree(work, canned=False)


def can_fail(work: Path):
    """The same two designs and the same one report path — and the second
    design's report is a byte-for-byte copy of the first's."""
    return (_tree(work, canned=True),
            "byte-identical across DIFFERENT designs")
