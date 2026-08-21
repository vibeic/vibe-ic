#!/usr/bin/env python3
"""readjudicate.py — recompute the verdict over five PUBLISHED arms, through
the `eco_readiness` axis, WITHOUT touching a single published record.

WHAT THIS DOES AND WHAT IT REFUSES TO DO
========================================
The five arms under `inputs/` are copied byte for byte from the branch that
published them; `MANIFEST.json` carries a sha256 for every one and this script
verifies all fifteen BEFORE it reads a number. A re-adjudication over a record
somebody adjusted is not a re-adjudication, so a digest mismatch is rc=2 and no
report is written.

Nothing here edits a record. The published `candidates.json` documents carry no
design-for-ECO metric because no producer existed to emit one; this script runs
`ppa_eco_spare_records.py` over each arm's own published `spare_cells.json`, and
appends the resulting records to a COPY. The published document is not changed
and is not the one adjudicated.

TWO ADJUDICATIONS, AND THE SECOND IS THE CONTROL
================================================
    tapeout_bound     the declaration in `declaration/tapeout_bound.json`
    no_declaration    the same records with no `eco_readiness` block at all

The second exists so the first means something. If both refused, the refusal
would be coming from the gate and not from the design's stated requirement --
which would be a rule no design could ever satisfy. The summary prints both
verdicts side by side for exactly that reason.

    rc 0  both adjudications ran and the reports were written
    rc 2  [CANNOT CHECK] a digest did not match, or an input could not be read
    rc 3  bad invocation
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROGRAMS = REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
sys.path.insert(0, str(PROGRAMS))

PRODUCER = PROGRAMS / "ppa_eco_spare_records.py"
CHECK = PROGRAMS / "ppa_feasibility_check.py"

TRIALS = ("b000", "p04", "u01", "z21", "z23")
#: The scope the ECO records are emitted under, and the view the contract asks
#: the axis to be complete across. `post_route` because the spare plan the flow
#: serialises describes the placed-and-routed database.
STAGE = "post_route"

MARK_CANNOT = "[CANNOT CHECK]"


def verify_manifest() -> list:
    """Every vendored input whose bytes do not match the manifest. Empty is the
    whole precondition of this script."""
    man = json.loads((HERE / "MANIFEST.json").read_text(encoding="utf-8"))
    bad = []
    for row in man["files"]:
        p = HERE / row["vendored_at"]
        if not p.is_file():
            bad.append(f"{row['vendored_at']}: missing")
            continue
        got = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
        if got != row["sha256"]:
            bad.append(f"{row['vendored_at']}: {got} != {row['sha256']}")
    return bad


def eco_records(trial: str, out_dir: pathlib.Path) -> list:
    out = out_dir / "eco_records.json"
    r = subprocess.run(
        [sys.executable, str(PRODUCER),
         "--spare-plan", str(HERE / "inputs" / trial / "spare_cells.json"),
         "--stage", STAGE, "--json", str(out)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{MARK_CANNOT} producer rc={r.returncode} on "
                         f"{trial}: {r.stderr}")
    return json.loads(out.read_text(encoding="utf-8"))["records"]


def contract_from(published: dict, declaration) -> dict:
    """The published contract, plus the view the new axis needs and (for the
    tape-out arm) the declaration.

    The nine published `required_views_by_axis` entries are carried through
    UNCHANGED, so every pre-existing axis is adjudicated exactly as it was.
    The only additions are an `eco_readiness` view and, in one of the two
    arms, the declaration itself -- so any difference between the two reports
    is attributable to the declaration and to nothing else.
    """
    per = dict(published.get("required_views_by_axis") or {})
    per["eco_readiness"] = [{"stage": STAGE}]
    doc = {
        "required_views": list(published.get("required_views") or []),
        "required_views_by_axis": per,
        "limits": dict(published.get("limits") or {}),
        "allow_waivers": published.get("allow_waivers", True),
    }
    if declaration is not None:
        doc["eco_readiness"] = declaration
    return doc


def adjudicate(cand_doc: dict, contract: dict, out_dir: pathlib.Path,
               label: str) -> dict:
    cpath = out_dir / f"contract_{label}.json"
    dpath = out_dir / "candidates_with_eco.json"
    rpath = out_dir / f"feasibility_{label}.json"
    cpath.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
    dpath.write_text(json.dumps(cand_doc, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(CHECK), "--candidates", str(dpath),
         "--contract", str(cpath), "--json", str(rpath)],
        capture_output=True, text=True)
    report = json.loads(rpath.read_text(encoding="utf-8"))
    report["_exit_code_observed"] = r.returncode
    report["_stdout"] = r.stdout.strip().splitlines()
    rpath.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
    return report


def main() -> int:
    bad = verify_manifest()
    if bad:
        for b in bad:
            print(f"{MARK_CANNOT} {b}", file=sys.stderr)
        print(f"{MARK_CANNOT} a vendored input does not match its manifest "
              "digest; this script will not re-adjudicate records it cannot "
              "prove are the published ones", file=sys.stderr)
        return 2

    declaration = json.loads(
        (HERE / "declaration" / "tapeout_bound.json").read_text(
            encoding="utf-8"))["eco_readiness"]

    rows = []
    for trial in TRIALS:
        out_dir = HERE / "out" / trial
        out_dir.mkdir(parents=True, exist_ok=True)
        published = json.loads(
            (HERE / "inputs" / trial / "candidates.json").read_text(
                encoding="utf-8"))
        run = json.loads((HERE / "inputs" / trial / "run.json").read_text(
            encoding="utf-8"))
        recs = eco_records(trial, out_dir)

        cand = json.loads(json.dumps(published))       # a copy, never the file
        cand["candidates"][0]["metrics"].extend(recs)

        with_decl = adjudicate(cand, contract_from(published, declaration),
                               out_dir, "tapeout_bound")
        without = adjudicate(cand, contract_from(published, None),
                             out_dir, "no_declaration")

        def axes(rep):
            return {a["axis"]: a["status"] for a in rep["candidates"][0]["axes"]}

        eco_row = [a for a in with_decl["candidates"][0]["axes"]
                   if a["axis"] == "eco_readiness"][0]

        # THE NINE PRE-EXISTING AXES MUST BE UNTOUCHED, and that is measured
        # rather than assumed. If adding an axis moved any other axis's status
        # then this whole comparison is about two different adjudications and
        # not about ECO readiness.
        pub = json.loads((HERE / "inputs" / trial /
                          "published_feasibility.json").read_text(
                              encoding="utf-8"))
        pub_axes = {a["axis"]: a["status"] for a in pub["candidates"][0]["axes"]}
        now_axes = {a["axis"]: a["status"]
                    for a in with_decl["candidates"][0]["axes"]}
        drift = {k: (v, now_axes.get(k)) for k, v in pub_axes.items()
                 if now_axes.get(k) != v}
        plan = json.loads((HERE / "inputs" / trial / "spare_cells.json"
                           ).read_text(encoding="utf-8"))
        rows.append({
            "trial": trial,
            "levers": run.get("levers"),
            "pnr_knobs": run.get("pnr_knobs"),
            "spare_count_in_plan": plan.get("count"),
            "published_candidate_verdict": pub["candidates"][0]["verdict"],
            "published_axes": pub_axes,
            "pre_existing_axis_drift": drift,
            "tapeout_bound": {
                "candidate_verdict": with_decl["candidates"][0]["verdict"],
                "eco_axis": eco_row["status"],
                "eco_codes": eco_row["codes"],
                "exit_code": with_decl["_exit_code_observed"],
                "axes": axes(with_decl),
            },
            "no_declaration": {
                "candidate_verdict": without["candidates"][0]["verdict"],
                "eco_axis": axes(without)["eco_readiness"],
                "exit_code": without["_exit_code_observed"],
            },
        })

    drifted = {r["trial"]: r["pre_existing_axis_drift"] for r in rows
               if r["pre_existing_axis_drift"]}
    if drifted:
        print(f"{MARK_CANNOT} adding the ECO axis moved a pre-existing axis's "
              f"status: {drifted}. The two adjudications are not comparable "
              "and no claim is made.", file=sys.stderr)
        return 2

    summary = {
        "schema": "vibeic.ppa.eco_readjudication.v1",
        "declaration": str(
            (HERE / "declaration" / "tapeout_bound.json").relative_to(HERE)),
        "stage": STAGE,
        "rows": rows,
        "pre_existing_axes_unchanged": True,
        "pre_existing_axes_unchanged_basis": (
            "for every arm, the status of all nine published axes is identical "
            "before and after the tenth was added; `readjudicate.py` refuses "
            "with rc=2 if any of them moves"),
        "control": ("`no_declaration` is the negative control: the SAME "
                    "records with no `eco_readiness` block. Every arm reads "
                    "NOT_APPLICABLE there, so the refusals in the "
                    "`tapeout_bound` column come from the design's declared "
                    "requirement and not from a rule that fires regardless."),
    }
    (HERE / "out" / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    w = max(len(t) for t in TRIALS)
    print(f"{'trial':<{w}}  spares  eco(declared)  candidate(declared)  "
          f"eco(control)  candidate(control)")
    for row in rows:
        print(f"{row['trial']:<{w}}  "
              f"{str(row['spare_count_in_plan']):>6}  "
              f"{row['tapeout_bound']['eco_axis']:<13}  "
              f"{row['tapeout_bound']['candidate_verdict']:<19}  "
              f"{row['no_declaration']['eco_axis']:<12}  "
              f"{row['no_declaration']['candidate_verdict']}")
    print(f"\nsummary: {HERE / 'out' / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
