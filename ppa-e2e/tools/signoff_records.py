#!/usr/bin/env python3
"""THE BRIDGE THE FLOW DOES NOT SHIP -- see RESULT.md FINDING F-3.

`_ppa/feasibility.py` proves nine axes from nine canonical metric names. Measured
on this tree, SEVEN of those names are produced by nothing under `programs/`
except feasibility.py itself, and the run tree measures every one of them in a
non-canonical artefact. This module is the missing extractor, authored HERE and
labelled as authored: it reads the run's own sign-off artefacts and emits
`vibeic.ppa.metric.v1` records with real provenance (path + sha256 + parser id).

It invents nothing. Where an artefact does not support a metric the record is
NOT_MEASURED WITH A REASON -- never a zero. In particular DRC applies the
three-way discriminator from `programs/tests/fixtures/ppa/drc/zero_three_ways/`:
a zero item count is a clean only when the deck registered categories AND the
layout it ran over demonstrably contained geometry.

Corner-independent physical facts (DRC, LVS, antenna, equivalence, IR, EM) are
emitted once PER REQUIRED VIEW, because `_evaluate_proof` matches every proof
against one global `required_views` list; the source hash is identical across
the copies, which is what says they are one measurement and not two.
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

PARSER = "jppae2e/tools/signoff_records.py"
SCHEMA = "vibeic.ppa.metric.v1"
VIEWS = ({"stage": "post_route_extracted", "process": "ss"},
         {"stage": "post_route_extracted", "process": "ff"})


def sha(p: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _parser_sha() -> str:
    return "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def rec(metric, status, unit, view, src_rel, src_sha, tool,
        value=None, reason=None, extra_scope=None):
    scope = dict(view)
    if extra_scope:
        scope.update(extra_scope)
    r = {"schema": SCHEMA, "metric": metric, "status": status, "unit": unit,
         "scope": scope,
         "source": {"path": src_rel, "sha256": src_sha, "tool": tool,
                    "parser": PARSER, "parser_sha256": _parser_sha()}}
    if status == "MEASURED":
        r["value"] = value
    if reason:
        r["reason"] = reason
    return r


def load(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def build(run: Path):
    out, notes = [], []
    R = run / "reports" / "phase3"

    def emit(metric, unit, tool, rel, fn):
        """fn(doc) -> (status, value, reason). NOT_MEASURED when the artefact
        is absent, unreadable, or does not support the metric."""
        p = run / rel
        s = sha(p)
        if s is None:
            for v in VIEWS:
                out.append(rec(metric, "NOT_MEASURED", unit, v, rel,
                               "sha256:" + "0" * 64, tool,
                               reason=f"{rel} is absent or unreadable: this is "
                                      "NOT_MEASURED, not zero"))
            notes.append(f"{metric}: {rel} absent -> NOT_MEASURED x{len(VIEWS)}")
            return
        doc = load(p)
        status, value, reason = fn(doc)
        for v in VIEWS:
            out.append(rec(metric, status, unit, v, rel, s, tool,
                           value=value, reason=reason))
        if status != "MEASURED":
            notes.append(f"{metric}: {status} -- {reason}")

    # ---- DRC: the three-way discriminator, not the report's bare zero -------
    def drc(doc):
        if not isinstance(doc, dict):
            return "NOT_MEASURED", None, "drc_signoff.json is not a document"
        s = doc.get("summary") or {}
        cats = s.get("categories_found") or []
        total = s.get("real_violation_total")
        vac = load(R / "drc_vacuous.json") or {}
        shapes = 0
        for f in ((vac.get("summary") or {}).get("per_file") or []):
            for m in (f.get("layout_measures") or []):
                shapes = max(shapes, int(m.get("shapes") or 0))
        if not cats:
            return ("NOT_MEASURED", None,
                    "the deck registered ZERO rule categories, so a zero item "
                    "count cannot be an earned clean -- there were no rules to "
                    "violate (fixtures/ppa/drc/zero_three_ways: deck_never_ran)")
        if shapes <= 0:
            return ("NOT_MEASURED", None,
                    "the layout the deck ran over contains no measured shapes, "
                    "so a zero is a statement about the layout being empty "
                    "(fixtures/ppa/drc/zero_three_ways: ran_on_empty_layout)")
        if not isinstance(total, int):
            return ("NOT_MEASURED", None,
                    "drc_signoff.json carries no integer real_violation_total")
        return ("MEASURED", total,
                f"deck registered {len(cats)} categories over a layout of "
                f"{shapes} measured shapes (earned clean discriminator)")

    emit("physical.drc.violations", "count", "klayout",
         "reports/phase3/drc_signoff.json", drc)

    def lvs(doc):
        if not isinstance(doc, dict):
            return "NOT_MEASURED", None, "lvs_verdict.json is not a document"
        st = str(doc.get("status") or doc.get("result") or "").upper()
        if st == "PASS":
            return "MEASURED", "MATCH", None
        if st:
            return "MEASURED", st, None
        return "NOT_MEASURED", None, "lvs_verdict.json declares no status"

    emit("physical.lvs.verdict", "verdict", "netgen",
         "reports/phase3/lvs_verdict.json", lvs)

    def ant(doc):
        if not isinstance(doc, dict):
            return "NOT_MEASURED", None, "antenna.json is not a document"
        if doc.get("routing_incomplete"):
            return ("NOT_MEASURED", None,
                    "the antenna check ran on an incompletely routed design")
        n, pn = doc.get("net_violations"), doc.get("pin_violations")
        if not isinstance(n, int) or not isinstance(pn, int):
            return "NOT_MEASURED", None, "antenna.json carries no integer counts"
        return "MEASURED", n + pn, None

    emit("physical.antenna.violations", "count", "openroad",
         "reports/phase3/antenna.json", ant)

    def ir(doc):
        if not isinstance(doc, dict):
            return "NOT_MEASURED", None, "ir_drop.json is not a document"
        if doc.get("unmeasured_reason"):
            return "NOT_MEASURED", None, str(doc["unmeasured_reason"])
        w, b = doc.get("worst_ir_pct_vdd"), doc.get("budget_pct_vdd")
        if not isinstance(w, (int, float)) or not isinstance(b, (int, float)):
            return ("NOT_MEASURED", None,
                    "ir_drop.json carries no worst drop and budget pair")
        return "MEASURED", (0 if w <= b else 1), (
            f"worst {w}% of VDD against a declared budget of {b}%")

    emit("power.ir.violations", "count", "openroad-psm",
         "reports/phase3/ir_drop.json", ir)

    def em(doc):
        if not isinstance(doc, dict):
            return "NOT_MEASURED", None, "em.json is not a document"
        return ("NOT_MEASURED", None,
                "the EM report carries a segment count "
                f"({doc.get('segments_analysed')}) and a maximum segment "
                f"current ({doc.get('max_segment_current_A')} A) but NO "
                "violation count and NO declared current limit, so no "
                "violation count can be established from it -- and 'the tool "
                "reported no violations' is not what this artefact says")

    emit("reliability.em.violations", "count", "openroad-psm",
         "reports/phase3/em.json", em)

    # ---- equivalence: RTL vs WHICH netlist matters --------------------------
    def lec(doc):
        if not isinstance(doc, dict):
            return "NOT_MEASURED", None, "lec.json is not a document"
        gate = str(doc.get("gate") or "")
        if doc.get("verdict") != "PASS" or not doc.get("equivalent"):
            return "MEASURED", str(doc.get("verdict") or "UNKNOWN"), None
        if "pnr" not in gate.lower() and "rout" not in gate.lower():
            return ("NOT_MEASURED", None,
                    f"the proven pair is RTL vs {gate!r}, a PRE-LAYOUT netlist. "
                    "The routed netlist that became the GDS was not the gate "
                    "side of this proof, so it establishes no post-route "
                    "equivalence")
        return "MEASURED", "PROVEN", None

    emit("equivalence.verdict", "verdict", "yosys", "reports/lec.json", lec)

    # ---- DRV: the router's own residual, from the canonical backend ---------
    def drv(_doc):
        return ("NOT_MEASURED", None,
                "the OpenROAD backend emits drv.*.violation.count.pre_repair "
                "and drv.residual.violation.count; NOTHING emits the "
                "timing.drv.* names the feasibility axis proves from, and the "
                "residual record this run carries is itself NOT_MEASURED")

    emit("timing.drv.violations", "count", "openroad",
         "phase3/stage3/pnr/openroad.log", drv)

    # ---- hold: there is no MEASURED hold WNS anywhere ----------------------
    def hold(_doc):
        return ("NOT_MEASURED", None,
                "no STA artefact in this tree prints a `wns` line for a hold "
                "check; the reports print `worst slack min`, which "
                "_ppa/timing.py emits as timing.hold.worst_slack_ns, a name "
                "the hold axis does not prove from")

    emit("timing.hold.wns_ns", "ns", "opensta",
         "phase3/stage3/sta/sta_mcorner_ocv.rpt", hold)
    return out, notes


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    if len(a) < 2:
        print("usage: signoff_records.py <run> <out-dir>", file=sys.stderr)
        return 3
    run, out = Path(a[0]).resolve(), Path(a[1]).resolve()
    if not run.is_dir():
        print(f"[CANNOT CHECK] {run} is not a directory", file=sys.stderr)
        return 2
    recs, notes = build(run)
    out.mkdir(parents=True, exist_ok=True)
    (out / "signoff_bridge_records.json").write_text(json.dumps(recs, indent=1) + "\n")
    n_m = sum(1 for r in recs if r["status"] == "MEASURED")
    print(f"bridge: {len(recs)} record(s), {n_m} MEASURED, "
          f"{len(recs)-n_m} NOT_MEASURED")
    for x in notes:
        print("  " + x)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
