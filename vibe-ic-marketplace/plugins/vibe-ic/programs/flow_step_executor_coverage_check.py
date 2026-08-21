#!/usr/bin/env python3
"""flow_step_executor_coverage_check.py — "every step has an executor that runs it".

The COMPANION to flow_step_execution_coverage_check.py. That gate confirms a step
COMPLETED (produced output, in order). THIS gate confirms a step CAN run at all:
every canonical flow step must have a real EXECUTOR wired into a runner that will
produce its `required_outputs`. A step that is DEFINED + AUDITED but has no runner
producing its outputs is structurally orphaned — it can only ever be MISSING, and
that is the root cause of "middle steps silently skipped".

Detection (static, deterministic): for each step, derive SIGNALS from its
`required_outputs` (a distinctive path fragment) and its declared `mcp_tools`
(the executor that does the work). Search the runner sources for those signals.
A step is:
  - WIRED           : some runner references the step's output path or its
                      mcp_tool → an executor produces it.
  - SKILL-ONLY-AI   : no mcp_tool / program, but declares `skills` → an AI
                      authoring step the runner WAIVES to by design (spec-to-rtl,
                      analog authoring). Not an orphan.
  - ORPHANED        : has required_outputs but NO runner references its outputs or
                      any executor for it → can never run. THIS is the gap.

The runner set is the closed list of "things that actually run a step":
vibe_ic / phase1 / phase2 / phase3 / design / analog one-shot runners +
phase3_backend_step. Gate/checker programs are NOT runners (they read outputs,
they don't produce them), so they are deliberately excluded from the search.

Usage:
    python3 flow_step_executor_coverage_check.py [--flow-def <yaml>] [--json <out>]
                                                 [--strict]
    exit 0 = every applicable step has a wired executor (or is SKILL-ONLY-AI)
    exit 1 = one or more ORPHANED steps  (only with --strict; default is advisory
             exit 0 so the gate can ship before every orphan is wired, while still
             printing the gap list)
"""
import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_FLOW = _HERE.parent / "flow" / "phase1_phase2_phase3.yaml"

# The closed set of RUNNERS — the only modules that actually drive a step and
# write its outputs. Checker/gate programs are excluded on purpose.
_RUNNER_FILES = [
    "vibe_ic_one_shot_runner.py",
    "phase1_one_shot_runner.py",
    "phase2_one_shot_runner.py",
    "design_one_shot_runner.py",
    "phase3_one_shot_runner.py",
    "phase3_backend_step.py",
    "analog_one_shot_runner.py",
]


def _load_runner_text() -> str:
    parts = []
    for f in _RUNNER_FILES:
        p = _HERE / f
        if p.is_file():
            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def _iter_steps(doc):
    out = []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and ("name" in o or "required_outputs" in o):
                out.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return out


# Basenames / directory leaves so common that finding them ALONE in a runner is
# NOT evidence a specific step is wired (they belong to many steps). A step is
# only WIRED by the DISTINCTIVE last-two-component form, never a bare generic.
_GENERIC_TOKENS = {
    "results.json", "coverage.json", "pass.flag", "results.log", "results.xml",
    "summary.json", "report.json", "report.rpt", "netlist.v", "top.gds",
    "done.flag", "reports", "stage1", "stage2", "stage3", "stage4", "phase1",
    "phase2", "phase3", "sta", "sim", "synth", "gds", "pnr", "src", "output",
}


def _output_signals(required_outputs):
    """Distinctive search fragments for a step's required_outputs.

    The DISCRIMINATING signal is the last two path components joined
    (e.g. 'dft/coverage.json', 'formal/results.json') — a bare basename like
    'coverage.json' is too generic and false-matched a DIFFERENT coverage.json
    (the exact bug that made this gate call step 11-DFT WIRED when its real
    signals — scan_netlist / atpg / eda_dft — appear 0× in any runner). A bare
    basename is only kept as a fallback when it is NOT in _GENERIC_TOKENS and
    the path has a single component."""
    sigs = set()
    for ro in required_outputs or []:
        # a required_output may list acceptable ALTERNATIVES joined by ' OR '
        # (e.g. 'spice/*.sp OR sim_spice/*.sp') — each alternative is its own
        # candidate path; the step is wired if ANY alternative is produced.
        for alt in re.split(r"\s+OR\s+", str(ro).strip()):
            alt = alt.strip()
            if not alt:
                continue
            raw = [p for p in alt.split("/") if p]
            if not raw:
                continue
            leaf_is_glob = "*" in raw[-1]
            nonglob = [p for p in raw if "*" not in p]
            if not nonglob:
                continue
            # A DISTINCTIVE basename is a valid signal — runner paths are built
            # with `dir / "leaf"` (Path join), so the literal 'dir/leaf'
            # substring rarely appears even for a genuinely-wired step (that
            # over-strictness false-ORPHANed steps 10/23/27/28). Excluded when:
            #  - the raw leaf was a GLOB ('*.sp') → the surviving 'nonglob[-1]'
            #    is only the directory ('spice'), NOT a real basename; matching
            #    a bare dir word anywhere false-WIRES (the step-30 'spice' bug).
            #  - the basename is GENERIC ('coverage.json') → would false-WIRE by
            #    matching a different file with the same leaf (step-11 DFT bug).
            if not leaf_is_glob and nonglob[-1] not in _GENERIC_TOKENS:
                sigs.add(nonglob[-1])
            # the dir+leaf pair is an additional (stronger) signal
            if len(nonglob) >= 2:
                sigs.add("/".join(nonglob[-2:]))
    return sigs


def _skip_anchors(required_outputs):
    """Distinctive tokens under which a CONSCIOUS skip-sentinel would live for
    this step — the parent directory leaf (if non-generic) else the basename
    stem. Used to detect a DISCLOSED-SKIP: a runner that writes
    '<anchor>...(_not_run|_skipped).json' has consciously not-run the step with
    a recorded reason (formal_not_run.json, sdf_sim_skipped.json) — honest, not
    a silent orphan."""
    anchors = set()
    for ro in required_outputs or []:
        parts = [p for p in str(ro).split("/") if p and "*" not in p]
        if not parts:
            continue
        # immediate parent dir leaf, e.g. 'formal', 'sim_postlayout'
        if len(parts) >= 2 and parts[-2] not in _GENERIC_TOKENS:
            anchors.add(parts[-2])
        # basename stem, e.g. 'lec' from 'lec.rpt'
        stem = parts[-1].split(".")[0]
        if stem and stem not in _GENERIC_TOKENS and len(stem) >= 3:
            anchors.add(stem)
    return anchors


def _has_disclosed_skip(anchors, runner_text):
    """True if a runner writes a conscious skip-sentinel for this step:
    a token '<anchor>...(_not_run|_skipped|_skip).<ext>' or bare '<anchor>_not_run'."""
    for a in anchors:
        if re.search(rf"{re.escape(a)}[A-Za-z0-9_/]*?(?:_not_run|_skipped|_skip\b)",
                     runner_text):
            return True
    return False


def classify(doc, runner_text: str):
    steps = _iter_steps(doc)
    rows = []
    for s in steps:
        sid = str(s.get("id"))
        # umbrella/stage container rows carry no required_outputs of their own
        ro = s.get("required_outputs") or []
        mcp = s.get("mcp_tools") or []
        progs = s.get("programs") or []
        skills = s.get("skills") or []
        if not ro and str(s.get("stage", "")).startswith("stage_") is False \
                and sid.lower().startswith("stage") is False and not mcp \
                and not progs and not skills:
            # bare container / grouping node — skip
            continue
        out_sigs = _output_signals(ro)
        wired_by = None
        matched = None
        # 1) does a runner reference this step's OUTPUT?
        for sig in sorted(out_sigs, key=len, reverse=True):
            if sig and sig in runner_text:
                wired_by, matched = "output", sig
                break
        # 2) or invoke its EXECUTOR (mcp tool)?
        if not wired_by:
            for t in mcp:
                if t and t in runner_text:
                    wired_by, matched = "mcp_tool", t
                    break
        stage = str(s.get("stage", ""))
        is_mfg = stage == "stage5_manufacturing" or sid in {
            "40", "41", "42", "43", "44"}
        is_cond_track = (re.fullmatch(r"[AM]\d+", sid) is not None
                         or stage in ("stage_analog", "stage_mixed_signal"))
        disclosed_skip = (not wired_by
                          and _has_disclosed_skip(_skip_anchors(ro), runner_text))
        if wired_by:
            cls = "WIRED"
        elif not ro:
            cls = "CONTAINER"
        elif is_mfg:
            # post-silicon: fab/sort/package/test/qual happen at the foundry/lab.
            # There is no software executor by nature — only an ATTESTATION gate.
            cls = "SILICON-EXTERNAL"
        elif is_cond_track:
            # analog / mixed-signal track: runs only when that track is active;
            # no digital runner drives it. A real gap for A/M designs, but
            # conditional — surfaced separately, not a digital-main-track orphan.
            cls = "CONDITIONAL-TRACK"
        elif disclosed_skip:
            # NO real producer, BUT a runner consciously writes a skip-sentinel
            # naming the capability gap (formal_not_run.json, sdf_sim_skipped.json).
            # This is HONEST — the step is not silently dropped; the compliance
            # gate maps it to SKIPPED-CONDITION. Acceptable, NOT an orphan.
            cls = "DISCLOSED-SKIP"
        elif (skills and not progs and not mcp
              and any(sk and sk in runner_text for sk in skills)):
            # A genuine AI-authoring handoff: the step declares ONLY skills AND
            # a runner actually WAIVES to one of them (references the skill name,
            # e.g. spec-to-rtl @ 12 refs). A step that merely LISTS a skill no
            # runner ever invokes (step 12 post-DFT lists synth-doctor, 0 refs)
            # is NOT a real handoff — it falls through to ORPHANED below.
            cls = "SKILL-ONLY-AI"
        else:
            # THE DISEASE: a digital main-track step whose output NO runner
            # produces AND which is not even consciously skipped — it can only
            # ever be MISSING (silent skip). Steps 11 DFT / 12 post-DFT /
            # 13 LEC / 30 post-layout SPICE. Wire an executor or a skip-sentinel.
            cls = "ORPHANED"
        rows.append({
            "id": sid, "name": s.get("name", ""),
            "required_outputs": ro, "mcp_tools": mcp,
            "skills": skills, "classification": cls,
            "wired_by": wired_by, "matched_signal": matched,
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--flow-def", default=str(_DEFAULT_FLOW))
    ap.add_argument("--json")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any ORPHANED step (default: advisory exit 0)")
    args = ap.parse_args()

    import yaml
    doc = yaml.safe_load(Path(args.flow_def).read_text())
    rows = classify(doc, _load_runner_text())

    def _by(c):
        return [r for r in rows if r["classification"] == c]
    orphaned = _by("ORPHANED")
    skill_ai = _by("SKILL-ONLY-AI")
    wired = _by("WIRED")
    silicon = _by("SILICON-EXTERNAL")
    cond = _by("CONDITIONAL-TRACK")
    disclosed = _by("DISCLOSED-SKIP")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "counts": {"total": len(rows), "wired": len(wired),
                       "skill_only_ai": len(skill_ai), "orphaned": len(orphaned),
                       "silicon_external": len(silicon),
                       "conditional_track": len(cond),
                       "disclosed_skip": len(disclosed)},
            "orphaned": orphaned, "conditional_track": cond,
            "disclosed_skip": disclosed, "rows": rows,
        }, indent=2, ensure_ascii=False))

    print("=== flow step-executor coverage ===")
    print(f"steps={len(rows)}  WIRED={len(wired)}  SKILL-ONLY-AI={len(skill_ai)}"
          f"  DISCLOSED-SKIP={len(disclosed)}  CONDITIONAL-TRACK={len(cond)}"
          f"  SILICON-EXTERNAL={len(silicon)}  ORPHANED={len(orphaned)}")
    if disclosed:
        print("\nDISCLOSED-SKIP (no real producer, but a runner consciously "
              "writes a skip-sentinel naming the gap — honest, not silent):")
        for r in disclosed:
            print(f"  [{r['id']}] {r['name'][:56]}")
    if orphaned:
        print("\nORPHANED (digital main-track step whose output NO runner "
              "produces — can only ever be MISSING; wire an executor):")
        for r in orphaned:
            ex = ",".join(r["mcp_tools"]) or ",".join(r["skills"]) or "(none)"
            print(f"  [{r['id']}] {r['name'][:52]:52} executor={ex}")
    if cond:
        print("\nCONDITIONAL-TRACK (analog/mixed — no digital runner drives it; "
              "a real gap for A/M designs):")
        for r in cond:
            print(f"  [{r['id']}] {r['name'][:56]}")
    verdict = "PASS" if not orphaned else ("FAIL" if args.strict else "ADVISORY")
    print(f"\nVERDICT: {verdict}")
    return 1 if (orphaned and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
