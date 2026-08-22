#!/usr/bin/env python3
"""Build the head-to-head record for (PnR-only winner) vs (cross-layer arm) and
hand it to the SHIPPED ppa_head_to_head_check.py.

Every field is read from the arms' own published records and contracts.  The two
facts that decide the outcome — the stage the power number really belongs to,
and whether either arm is feasible — are read, never asserted.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

ROOT = Path("/home/reyerchu/_jxlayer")
PLUGIN = Path(os.environ.get(
    "JXLAYER_PLUGIN",
    "/home/reyerchu/vibe-ic-wt-jxlayer/vibe-ic-marketplace/plugins/vibe-ic"))
PROGRAMS = PLUGIN / "programs"
PY_ = sys.executable

OBJECTIVE = ("area.design_report.um2", {"stage": "post_route"})


def load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def one_measured(recs, metric, want):
    hits = [r for r in recs if r.get("metric") == metric
            and all((r.get("scope") or {}).get(k) == v for k, v in want.items())
            and r.get("status") == "MEASURED"]
    if not hits:
        return None
    if len({r.get("value") for r in hits}) == 1:
        return hits[0]
    return None


def metric_block(r, unit_override=None, scale=1.0, force=None):
    if force is not None:
        return force
    if r is None:
        return None
    out = {"status": r["status"], "unit": unit_override or r.get("unit", ""),
           "scope": dict(r.get("scope") or {})}
    if r.get("status") == "MEASURED":
        out["value"] = r["value"] * scale
    if r.get("reason"):
        out["reason"] = r["reason"]
    if r.get("source"):
        out["source"] = {k: v for k, v in r["source"].items()
                         if k in ("path", "sha256", "tool", "parser")}
    return out


def feas_checks(t: str):
    """The `checks` block, from this arm's OWN feasibility adjudication.
    UNDETERMINED becomes NOT_CHECKED: an axis nobody could decide is not a
    clean one, and calling it clean here is the whole failure mode."""
    rep = load(ROOT / "records/trials" / t / "feasibility_report.json")
    flat = load(ROOT / "records/trials" / t / "records_flat.json") or []
    by = {}
    for r in flat:
        if r.get("status") == "MEASURED":
            by.setdefault(r["metric"], r)
    counts = {}
    if "physical.drc.violations" in by:
        counts["drc"] = int(by["physical.drc.violations"]["value"])
    if "physical.antenna.violations" in by:
        counts["antenna"] = int(by["physical.antenna.violations"]["value"])
    if "physical.lvs.verdict" in by:
        counts["lvs"] = 0 if by["physical.lvs.verdict"]["value"] in ("MATCH", "CLEAN") else 1
    if not rep or not rep.get("candidates"):
        return {"_unavailable": {"status": "NOT_CHECKED",
                                 "source": "no feasibility report"}}, "UNDETERMINED"
    c = rep["candidates"][0]
    floor = ("drc", "lvs", "antenna", "setup", "hold", "drv")
    out = {}
    for a in c["axes"]:
        if a["axis"] not in floor:
            continue
        st = {"SATISFIED": "CLEAN", "VIOLATED": "VIOLATIONS"}.get(
            a["status"], "NOT_CHECKED")
        row = {"status": st,
               "source": f"ppa_feasibility_check: {a['status']} "
                         f"({','.join(a.get('codes') or [])})"}
        if a["axis"] in counts and st != "NOT_CHECKED":
            row["violations"] = counts[a["axis"]]
        elif st == "CLEAN":
            row["violations"] = 0
        out[a["axis"]] = row
    return out, c["verdict"]


def diagnostic_power(t):
    d = load(ROOT / "records/trials" / t / "diag" / "power_postroute_records.json")
    if not d:
        return None
    for r in d.get("metrics", []):
        if r["metric"] == "power.total_w" and (r.get("scope") or {}).get("group") == "Total":
            return r
    return None


def arm(t, label, role, config_source, tuned, power_mode, corner="ss"):
    d = ROOT / "records/trials" / t
    contract = load(d / "contract.json")
    if contract is None:
        raise SystemExit(f"[CANNOT CHECK] {t}: no contract.json")
    problem = contract["identities"]["problem"]["digest"]
    recs = load(d / "records_flat.json") or []
    area = one_measured(recs, *OBJECTIVE)
    timing = one_measured(recs, "timing.setup.wns_ns",
                          {"stage": "post_route_extracted", "process": corner,
                           "check": "setup"})
    power = one_measured(recs, "power.total_w", {"group": "Total"})
    if power_mode == "diagnostic":
        power = diagnostic_power(t)
    force = None
    if power_mode == "withheld":
        force = {"status": "NOT_MEASURED", "unit": "mW",
                 "scope": {"stage": "post_route_extracted",
                           "mode": "functional", "process": "tt",
                           "voltage_v": 1.8, "temperature_c": 25.0,
                           "activity_basis": "VECTORLESS"},
                 "reason": ("the flow's only power session links "
                            "phase2/stage2/synth/spm_synth.v and reads no SPEF, "
                            "so its number is a PRE-place-and-route number. It "
                            "is published in this arm's records at its true "
                            "stage='synth' and WITHHELD from a post-route basis "
                            "rather than restamped.")}
    checks, verdict = feas_checks(t)
    return {
        "flow": label, "role": role,
        "design": {"spec_sha256": problem, "pdk": "sky130A",
                   "clock_target_ns": 10.0, "corners": ["ss", "tt", "ff"]},
        "contract": {"sha256": problem, "source": str(d / "contract.json")},
        "measurement_basis": "post_route_sta",
        "config_source": config_source,
        "tuned_by_this_project": tuned,
        "ppa": {"area_um2": metric_block(area),
                "timing_wns_ns": metric_block(timing),
                "power_mw": metric_block(power, unit_override="mW", scale=1000.0,
                                         force=force)},
        "feasibility": {"checks": checks},
        "tuning": {"supported": False},
        "_trial": t, "_feasibility_verdict": verdict,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--baseline-label", default="pnr-only-winner")
    ap.add_argument("--subject-label", default="cross-layer")
    ap.add_argument("--baseline-source", required=True)
    ap.add_argument("--subject-source", required=True)
    ap.add_argument("--power", choices=("shipped", "withheld", "diagnostic"),
                    default="shipped")
    ap.add_argument("--timing-corner", default="ss",
                    help="process corner the setup axis is taken at. `ss` is "
                         "the governing sign-off corner; `tt` is the only one "
                         "whose scope `_ppa/timing.py` completes.")
    ap.add_argument("--baseline-tuned", action="store_true",
                    help="declare that THIS project chose the baseline's "
                         "configuration. It is a fact about the run, not a "
                         "convenience: the gate refuses a baseline we tuned.")
    a = ap.parse_args(argv)
    # REFUSED AT WRITE TIME, and this is where it always could have been.
    # `--baseline-tuned` is this project stating, in its own invocation, that it
    # chose the baseline's configuration -- and the flag's own help text says
    # the gate refuses a baseline we tuned. So the producer knew the document it
    # was about to write could not be a head-to-head, wrote it anyway into the
    # head-to-head corpus, and left the contradiction to be found months later
    # by `ppa_head_to_head_check` over a comparison that had already been
    # published (BASELINE_TUNED_BY_US on `h2h_F`).
    #
    # THE COMPARISON IS NOT THE PROBLEM. Ranking two configurations we both
    # chose is an ablation, and an informative one: it isolates what the
    # cross-layer search adds over a place-and-route-only search. What it is not
    # is a head-to-head, whose entire claim is "against an opponent we did not
    # tune". `vibeic.ppa.comparison.v2` carries that claim, so this tool refuses
    # to stamp it on an ablation. Filing the ablation needs a document kind that
    # does not carry the claim, and no schema for one exists yet -- naming that
    # is the honest disposition, not writing the wrong kind in the meantime.
    if a.baseline_tuned:
        raise SystemExit(
            "[REFUSE] --baseline-tuned means THIS project chose the baseline's "
            "configuration, and `vibeic.ppa.comparison.v2` is the document kind "
            "whose claim is a comparison against a baseline we did NOT tune. "
            "ppa_head_to_head_check refuses exactly this record "
            "(BASELINE_TUNED_BY_US) and the schema's `arm.allOf` clause now "
            "states it too, so writing one here only defers the refusal past "
            "the point where the number gets quoted. What you have is a "
            "WITHIN-PROJECT ABLATION; file it as one. No schema for that "
            "document kind ships yet -- that is the first landable step, and it "
            "is a record schema, not a number.")
    b = arm(a.baseline, a.baseline_label, "baseline", a.baseline_source,
            a.baseline_tuned, a.power, a.timing_corner)
    s = arm(a.subject, a.subject_label, "subject", a.subject_source,
            True, a.power, a.timing_corner)
    doc = {"schema": "vibeic.ppa.comparison.v2", "arms": [b, s]}
    out = ROOT / "records" / f"{a.tag}.json"
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    r = subprocess.run([PY_, str(PROGRAMS / "ppa_head_to_head_check.py"),
                        str(out), "--json",
                        str(ROOT / "records" / f"{a.tag}_report.json")],
                       capture_output=True, text=True, cwd=str(PROGRAMS),
                       timeout=600)
    print("=" * 74)
    print(f"### {a.tag}   ({a.baseline} -> {a.subject}, power={a.power})")
    print(r.stdout.strip())
    if r.stderr.strip():
        print(r.stderr.strip())
    print(f"ppa_head_to_head_check rc={r.returncode}")
    # PROPAGATE THE GATE'S VERDICT INTO THE EXIT STATUS. This was `return 0`,
    # unconditionally, so a caller that checks the exit status of the tool that
    # WROTE this corpus was told success over a refusal.
    #
    # SCOPED HONESTLY, because the first draft of this comment overstated it:
    # the verdict is NOT thrown away. `--json records/<tag>_report.json` above
    # persists the checker's full report beside the record, and those reports do
    # carry `"ok": false` with the refusal -- h2h_A_report.json was checked. So
    # the defect is the EXIT STATUS alone, not the disclosure. That is still
    # worth repairing: an exit code is what an orchestrator reads, and a build
    # step that reports success having just been told rc 1 is misreporting to
    # its caller whatever it wrote to disk.
    #
    # The record file is deliberately LEFT ON DISK when refused: a refused
    # record is the evidence needed to fix it, and unlinking it would trade one
    # silent outcome for another. What changes is only that this tool stops
    # reporting success over a verdict it was given.
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
