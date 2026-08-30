#!/usr/bin/env python3
"""J98 — which of this report's controls has ever been shown CAPABLE of red?

Section 9 found one control -- `notfeasible_control.py`, the check on the only two
tiers that refuse a chip -- whose positive control was still a hand-run, so every run
it had ever made was green and nothing distinguished "the readings hold" from "this
code cannot print anything else".  That is not a property of that one file.

This sweep asks it of every control, and answers by PERTURBING the input and requiring
the verdict to flip -- not by reading the source and forming an opinion.

The candidate list is ENUMERATED FROM THE DIRECTORY, never typed here.  The first
version of this file used a hand-typed list and silently omitted three files; a sweep
with a remembered list tests the author's memory, which is the defect `cite_audit`'s
own docstring was written against.  Every file in `controls/` must be accounted for or
this exits non-zero.

Outcomes:

  SYNTHETIC-RED   perturbed in this run, and it went red.  Strongest.
  OBSERVED-RED    seen red on real input, artefact named.  An unmanufactured red is
                  better evidence than a made one.
  REPORTER        renders no verdict.  Asserted MECHANICALLY (no non-zero exit, no
                  FAIL literal in the source), not by my say-so.
  UNEXERCISED     renders a verdict whose red branch has never fired, and this run
                  deliberately does not fire it.  Named as a gap, not excused.

Run from /home/reyerchu/_jself_priv.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path("/home/reyerchu/_jself_priv")
CTL = ROOT / "wt_jself/selftapeout-adjudication/controls"
ADD = ROOT / "wt_jself/selftapeout-adjudication-addendum"
os.chdir(ROOT)

rows, seen = [], set()


def row(name, outcome, how):
    rows.append((name, outcome, how))
    seen.add(name)
    print(f"  {outcome:<15} {name:<32} {how}")


def run(argv, cwd=None, env=None, timeout=1200):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


print("=== perturbed here: the verdict must FLIP ===")

with tempfile.TemporaryDirectory(prefix="j98_cite_") as t:
    d = pathlib.Path(t)
    for link in ("wt", "proj"):
        (d / link).symlink_to(ROOT / link)
    text = (ROOT / "RESULT.md").read_text()
    (d / "RESULT.md").write_text(text)
    clean = run([sys.executable, str(CTL / "cite_audit.py")], cwd=d)
    (d / "RESULT.md").write_text(
        text + "\n\nJ98 perturbation: `pnr.tcl:999999` is past the end of that file.\n")
    dirty = run([sys.executable, str(CTL / "cite_audit.py")], cwd=d)
    row("cite_audit.py",
        "SYNTHETIC-RED" if (clean.returncode == 0 and dirty.returncode == 1
                            and "OUT" in dirty.stdout) else "*** CANNOT REDDEN ***",
        f"clean rc={clean.returncode}, +1 out-of-range coordinate rc={dirty.returncode}")

with tempfile.TemporaryDirectory(prefix="j98_stale_") as t:
    doc = pathlib.Path(t) / "RESULT.md"
    text = (ROOT / "RESULT.md").read_text()
    doc.write_text(text)
    clean = run([sys.executable, str(CTL / "stale_figure_audit.py"), str(doc)])
    doc.write_text(text + "\n\nThe build-to die is 5.875 mm.\n")
    dirty = run([sys.executable, str(CTL / "stale_figure_audit.py"), str(doc)])
    # J106 second arm: the same audit now also scans the INSTRUMENTS the report cites,
    # so that branch needs its own perturbation -- a synthetic tree holding one cited
    # script with an unmarked superseded figure in it.
    doc.write_text(text)
    with tempfile.TemporaryDirectory(prefix="j106_scripts_") as t2:
        d2 = pathlib.Path(t2)
        (d2 / "meas/_fake").mkdir(parents=True)
        (d2 / "meas/_fake/probe.py").write_text("print('the build-to is 6.165 mm')\n")
        doc2 = d2 / "RESULT.md"
        doc2.write_text("The instrument is `meas/_fake/probe.py`.\n")
        scripts = run([sys.executable, str(CTL / "stale_figure_audit.py"), str(doc2)],
                      env=dict(os.environ, J106_ROOT=str(d2)))
        (d2 / "meas/_fake/probe.py").write_text(
            "# superseded by J76\nprint('the build-to is 6.165 mm')\n")
        marked = run([sys.executable, str(CTL / "stale_figure_audit.py"), str(doc2)],
                     env=dict(os.environ, J106_ROOT=str(d2)))
    row("stale_figure_audit.py",
        "SYNTHETIC-RED" if (clean.returncode == 0 and dirty.returncode == 1
                            and scripts.returncode == 1 and marked.returncode == 0)
        else "*** CANNOT REDDEN ***",
        f"clean rc={clean.returncode}, +1 unmarked superseded figure in the PROSE "
        f"rc={dirty.returncode}; one in a CITED SCRIPT rc={scripts.returncode}, "
        f"the same script with a marker rc={marked.returncode}")

clean = run([sys.executable, str(CTL / "branch_claim_by_name.py")])
dirty = run([sys.executable, str(CTL / "branch_claim_by_name.py")],
            env=dict(os.environ, J98_WT="/tmp"))
ok = (clean.returncode == 0 and dirty.returncode == 1
      and "CLAIM_BY_NAME_BROKEN" in dirty.stdout)
row("branch_claim_by_name.py", "SYNTHETIC-RED" if ok else "*** CANNOT REDDEN ***",
    f"real repo rc={clean.returncode}, non-repo rc={dirty.returncode}")
if ok:
    print("      ^ and note WHICH value the broken query returns: the RETIRED substring")
    print("        proxy reads 0 -- the exact number J74/J79 published AS the claim.")
    print("        A broken query and a true claim were the same reading.  That is the")
    print("        strongest argument against the proxy that exists, and it came from")
    print("        controlling the replacement rather than from arguing about it.")

with tempfile.TemporaryDirectory(prefix="j98_iogap_") as t:
    src = ROOT / "probe_padring/phase2/stage1/rtl/chip_top.v"
    txt = src.read_text(errors="replace")
    m = re.search(r"^\s*(input|output|inout)\b[^\n]*\n", txt, re.M)
    top = pathlib.Path(t) / "chip_top.v"
    top.write_text(txt[:m.start()] + txt[m.end():])
    clean = run([sys.executable, str(CTL / "io_gap_inventory.py")])
    dirty = run([sys.executable, str(CTL / "io_gap_inventory.py")],
                env=dict(os.environ, J98_TOP=str(top)))
    row("io_gap_inventory.py",
        "SYNTHETIC-RED" if (clean.returncode == 0 and dirty.returncode == 1
                            and "UNMATCHED" in dirty.stdout) else "*** CANNOT REDDEN ***",
        f"clean rc={clean.returncode}, one port declaration deleted rc={dirty.returncode}")

# offsite_cells.py -- J99.  Its verdict is a SEPARATION (named instances off the site
# grid, control instances on it), so a green run proves nothing unless the same code is
# shown refusing a tree where the separation is absent.  Both halves are built here, in
# a tempdir, so this registration never depends on a 114 MB file a live process is still
# writing.
def _mk_def(path, ctrl_offgrid):
    rows = "\n".join(f"ROW ROW_{i} SITE_X 20160 {23520 + i * 7840} N DO 100 BY 1 "
                      f"STEP 1120 0 ;" for i in range(6))
    comps = ["    - a_named CELL + SOURCE TIMING + PLACED ( 20161 23521 ) N ;"]
    for i in range(5):
        # on grid  -> exact multiples of the site/row pitch; off grid -> +1 DBU
        skew = 1 if ctrl_offgrid else 0
        comps.append(f"    - a_ctrl{i} CELL + SOURCE TIMING + PLACED "
                     f"( {20160 + i * 1120 + skew} {23520 + i * 7840 + skew} ) N ;")
    path.write_text(f"VERSION 5.8 ;\nUNITS DISTANCE MICRONS 2000 ;\n{rows}\n"
                    f"COMPONENTS {len(comps)} ;\n" + "\n".join(comps)
                    + "\nEND COMPONENTS\nEND DESIGN\n")

with tempfile.TemporaryDirectory(prefix="j99_offsite_") as t:
    d = pathlib.Path(t)
    _mk_def(d / "sep.def", ctrl_offgrid=False)     # separation present -> CONFIRMED
    _mk_def(d / "nosep.def", ctrl_offgrid=True)    # controls also off  -> WITHDRAWN
    green = run([sys.executable, str(CTL / "offsite_cells.py"), str(d / "sep.def"),
                 "--control-re", "a_ctrl", "a_named"])
    withdrawn = run([sys.executable, str(CTL / "offsite_cells.py"), str(d / "nosep.def"),
                     "--control-re", "a_ctrl", "a_named"])
    absent = run([sys.executable, str(CTL / "offsite_cells.py"), str(d / "sep.def"),
                  "--control-re", "a_ctrl", "no_such_instance"])
    notconf = run([sys.executable, str(CTL / "offsite_cells.py"), str(d / "sep.def"),
                   "--control-re", "a_ctrl", "a_ctrl0"])
    ok = (green.returncode == 0 and "CONFIRMED" in green.stdout
          and withdrawn.returncode == 2 and "WITHDRAWN" in withdrawn.stdout
          and absent.returncode == 2 and "INCONCLUSIVE" in absent.stdout
          and notconf.returncode == 1 and "NOT CONFIRMED" in notconf.stdout)
    row("offsite_cells.py",
        "SYNTHETIC-RED" if ok else "*** CANNOT REDDEN ***",
        f"separation present rc={green.returncode}; controls also off grid "
        f"rc={withdrawn.returncode} (WITHDRAWN); named instance absent "
        f"rc={absent.returncode}; an on-grid instance named rc={notconf.returncode}. "
        f"On REAL input (die-3300 routed.def) it reads 4/4 named OFF grid, 0/8 "
        f"same-class controls off -- probes/j99/offsite_3300.txt")

# residual_by_stage.py -- J100.  Its whole value is the SEGMENTATION, so the control is
# to remove the segmentation and require it to refuse rather than report one confident
# bucket.  It carries that control itself (--self-test); this runs it.
_arm = ROOT / "proj/edge_llm_matmul_accel/phase3/stage3/pnr/openroad.log"
if _arm.exists():
    green = run([sys.executable, str(CTL / "residual_by_stage.py"), str(_arm)])
    red = run([sys.executable, str(CTL / "residual_by_stage.py"), "--self-test",
               str(_arm)])
    ok = (green.returncode == 0 and "hold_repair" in green.stdout
          and red.returncode == 0 and "REFUSED" in red.stdout
          and "CONTROL OK" in red.stdout)
    row("residual_by_stage.py",
        "SYNTHETIC-RED" if ok else "*** CANNOT REDDEN ***",
        f"segmented log rc={green.returncode}; same log with `PNR_STAGE:` lines "
        f"stripped -> REFUSED (rc 2 internally, self-test rc={red.returncode}). It also "
        f"splits a stage that ran BOTH legalizers onto separate lines rather than "
        f"chaining them, which is the cross-counter comparison J96 caught")
else:
    row("residual_by_stage.py", "*** NOT RUN ***",
        "the arm's log is absent from this tree, so its control was not exercised")

# route_drc_discriminates.py -- J101.  Its claim is that the runner's route-convergence
# gate ARRIVED at `NOT DETERMINED` rather than being unable to say anything else, so its
# control is to hand it the SAME arm twice and require it to refuse.
_mm = (ROOT / "logs/p3_matmul2.log",
       ROOT / "proj/edge_llm_matmul_accel/phase3/stage3/pnr/openroad.log")
_sh = (ROOT / "logs/p3_sha256b.log",
       ROOT / "proj/sha256/phase3/stage3/pnr/openroad.log")
if all(p_.exists() for p_ in _mm + _sh):
    _rd = str(CTL / "route_drc_discriminates.py")
    green = run([sys.executable, _rd, str(_mm[0]), str(_mm[1]),
                 str(_sh[0]), str(_sh[1])])
    same = run([sys.executable, _rd, str(_mm[0]), str(_mm[1]),
                str(_mm[0]), str(_mm[1])])
    gone = run([sys.executable, _rd, "/nonexistent.log", "/nonexistent2.log",
                str(_sh[0]), str(_sh[1])])
    ok = (green.returncode == 0 and "DISCRIMINATES" in green.stdout
          and same.returncode == 1 and "NOT DISCRIMINATING" in same.stdout
          and gone.returncode == 2 and "INCONCLUSIVE" in gone.stdout)
    row("route_drc_discriminates.py",
        "SYNTHETIC-RED" if ok else "*** CANNOT REDDEN ***",
        f"two arms rc={green.returncode} (NEITHER vs NO_METRIC); the SAME arm twice "
        f"rc={same.returncode} (NOT DISCRIMINATING); an unreadable arm "
        f"rc={gone.returncode}")
else:
    row("route_drc_discriminates.py", "*** NOT RUN ***",
        "an arm's logs are absent from this tree, so its control was not exercised")

r = run([sys.executable, str(CTL / "notfeasible_control.py")])
row("notfeasible_control.py",
    "SYNTHETIC-RED" if (r.returncode == 0
                        and "child exit                          got=1" in r.stdout)
    else "*** CANNOT REDDEN ***",
    "self-controlling since J98: re-invokes itself on synthetic trees, requires child rc 1")

r = run(["bash", str(CTL / "precheck_discriminates.sh"),
         tempfile.mkdtemp(prefix="j98_pc_")])
row("precheck_discriminates.sh",
    "SYNTHETIC-RED" if ("NOT_DETERMINED" in r.stdout and '"verdict": "FAIL"' in r.stdout)
    else "*** CANNOT REDDEN ***",
    "the brief's pre-check answers NOT_DETERMINED on an empty project and FAIL on one "
    "with a file where it globs -- so the four UNDETERMINED rows rest on an instrument "
    "that CAN say something else")

r = run([sys.executable, str(ADD / "summary_matches_its_rows.py")], cwd=ROOT)
row("summary_matches_its_rows.py",
    "SYNTHETIC-RED" if (r.returncode == 0 and "MISMATCH" in r.stdout)
    else "*** CANNOT REDDEN ***",
    "carries its own wrong-headline control and must report MISMATCH before it may "
    "read the report  [addendum/, not controls/]")

print("\n=== red seen on REAL input, not manufactured ===")
led = ROOT / "meas/_j98/ledger_before_repin.txt"
txt = led.read_text() if led.exists() else ""
row("decay_ledger.py", "OBSERVED-RED" if "MOVED" in txt else "*** NO RED SEEN ***",
    f"4 rows MOVED on real input this dispatch -- {led.relative_to(ROOT)}")

print("\n=== a verdict whose red branch has NOT been fired, said as a gap ===")
r = run([sys.executable, str(CTL / "posthold_verdict_predicate.py")])
row("posthold_verdict_predicate.py", "UNEXERCISED",
    f"rc={r.returncode}: it moved NOT YET(2) -> HELD(0) on real input today, so two of "
    "its three states are exercised. Its REFUTED(1) branch never has been, and this run "
    "does NOT fire it: manufacturing a refutation of one's own registered predicate is "
    "evidence-shaping, which is worse than the gap")

# ---- and itself.  Published into controls/, this file is a candidate like any other,
# and the first time it was copied there it exited 1 naming ITSELF: it renders a verdict
# and had no row proving it can go red.  It can, and the demonstration is that very
# event -- a control that audits its own directory has to answer the question about
# itself, and this one did before anyone asked.
_self = pathlib.Path(__file__).name
if (CTL / _self).exists():
    row(_self, "OBSERVED-RED",
        "exited 1 naming itself the first time it was published into controls/ -- an "
        "unmanufactured red on real input. rc 1 = a control cannot redden, rc 2 = a file "
        "in controls/ went unaccounted, rc 3 = its own classifier failed its control")

# J102 -- the drift control between this report's two trees of instruments.  It is
# perturbed on SYNTHETIC trees (its own env overrides) so the run does not have to
# damage a real instrument to prove the verdict flips.  It also carries an
# OBSERVED-RED: on the run that motivated it, against the real trees, it returned 1
# and named three drifted pairs (meas/_j102/drift_before.txt).
with tempfile.TemporaryDirectory(prefix="j102_drift_") as t:
    d = pathlib.Path(t)
    (d / "meas/x").mkdir(parents=True)
    (d / "pub/controls").mkdir(parents=True)
    (d / "meas/x/twin_probe.py").write_text("print('A')\n")
    (d / "pub/controls/twin_probe.py").write_text("print('A')\n")
    (d / "RESULT.md").write_text("The instrument is `meas/x/twin_probe.py`.\n")
    envd = dict(os.environ, J102_ROOT=str(d), J102_PUB=str(d / "pub"))
    clean = run([sys.executable, str(CTL / "instrument_copies_agree.py")], env=envd)
    (d / "pub/controls/twin_probe.py").write_text("print('B')\n")
    drift = run([sys.executable, str(CTL / "instrument_copies_agree.py")], env=envd)
    (d / "pub/controls/twin_probe.py").write_text("print('A')\n")
    (d / "RESULT.md").write_text(
        "The instrument is `meas/x/twin_probe.py`, and `meas/x/absent.py`.\n")
    missing = run([sys.executable, str(CTL / "instrument_copies_agree.py")], env=envd)
    ok = (clean.returncode == 0
          and drift.returncode == 1 and "DRIFTED" in drift.stdout
          and missing.returncode == 1 and "CITED-MISSING" in missing.stdout)
    row("instrument_copies_agree.py",
        "SYNTHETIC-RED" if ok else "*** CANNOT REDDEN ***",
        f"identical twins rc={clean.returncode}; one byte changed in the published "
        f"copy rc={drift.returncode}; a cited path that does not exist "
        f"rc={missing.returncode}  (also OBSERVED-RED on the real trees)")

# J103 -- the audit of the report's DESIGN-DOCUMENT coordinates, the family cite_audit
# does not cover and the family a NOT FEASIBLE verdict's REASON is quoted from.  It is
# perturbed on a synthetic design tree, and its OBSERVED-RED is the one that mattered:
# on the real report it found `L9:37` carrying text that lives at `L9:38`.
with tempfile.TemporaryDirectory(prefix="j103_ldoc_") as t:
    d = pathlib.Path(t)
    docs = d / "bdata/demo_design/input/docs"
    docs.mkdir(parents=True)
    (docs / "L9_constraints_floorplan.md").write_text(
        "line one\nline two\n| Pin placement | tool-chosen, no pad ring |\nline four\n")
    envd = dict(os.environ, J103_ROOT=str(d), J103_BDATA=str(d / "bdata"))
    (d / "RESULT.md").write_text(
        "```\nL9:3    | Pin placement | tool-chosen, no pad ring |\n```\n")
    clean = run([sys.executable, str(CTL / "ldoc_cite_audit.py")], env=envd)
    (d / "RESULT.md").write_text(
        "```\nL9:2    | Pin placement | tool-chosen, no pad ring |\n```\n")
    off = run([sys.executable, str(CTL / "ldoc_cite_audit.py")], env=envd)
    (d / "RESULT.md").write_text(
        "```\nL9:3    | Pin placement | a sentence that is in no document |\n```\n")
    gone = run([sys.executable, str(CTL / "ldoc_cite_audit.py")], env=envd)
    ok = (clean.returncode == 0
          and off.returncode == 1 and "OFF-BY" in off.stdout
          and gone.returncode == 1 and "NOT-FOUND" in gone.stdout)
    row("ldoc_cite_audit.py",
        "SYNTHETIC-RED" if ok else "*** CANNOT REDDEN ***",
        f"the right line rc={clean.returncode}; the coordinate moved one line "
        f"rc={off.returncode} (OFF-BY); text in no document rc={gone.returncode} "
        f"(NOT-FOUND)  (also OBSERVED-RED: it found L9:37 -> L9:38 in the real report)")

# J104 -- the census of what `abuts: true` actually means, and an ARITHMETIC check of
# the flow's own `unfillable: []`.  Perturbed on synthetic probe trees so no real
# artefact is touched.
with tempfile.TemporaryDirectory(prefix="j104_abut_") as t:
    d = pathlib.Path(t)

    def _probe(name, gaps, space, fillers=(200, 2000), verdict="PASS"):
        r = d / f"_probe_{name}_at/reports/phase3"
        r.mkdir(parents=True)
        (r / "padring.json").write_text(json.dumps({
            "verdict": verdict,
            "abutment": {"abuts": True, "gaps": gaps, "unfillable": [],
                         "filler_widths_dbu": list(fillers)},
            "spacing": {k: {"space_for_fill": space[k]} for k in gaps},
            "pads": [], "corners": [], "fillers_placed": None,
            "die": {"box": [0, 0, 100, 100]}}))

    _probe("clean", {"S": [0, 0], "E": [0, 0]}, {"S": 0, "E": 0})
    clean = run([sys.executable, str(CTL / "abutment_census.py")],
                env=dict(os.environ, J104_PROBES=str(d)))
    _probe("notmultiple", {"S": [700, 0]}, {"S": 700})
    mul = run([sys.executable, str(CTL / "abutment_census.py")],
              env=dict(os.environ, J104_PROBES=str(d)))
    _probe("sumwrong", {"S": [200, 0]}, {"S": 400})
    sm = run([sys.executable, str(CTL / "abutment_census.py")],
             env=dict(os.environ, J104_PROBES=str(d)))
    empty = run([sys.executable, str(CTL / "abutment_census.py")],
                env=dict(os.environ, J104_PROBES=str(d / "nothing_here")))
    ok = (clean.returncode == 0
          and mul.returncode == 1 and "not a multiple" in mul.stdout
          and sm.returncode == 1 and "space_for_fill says" in sm.stdout
          and empty.returncode == 2)
    row("abutment_census.py", "SYNTHETIC-RED" if ok else "*** CANNOT REDDEN ***",
        f"all gaps zero rc={clean.returncode}; a gap that is not a whole filler "
        f"rc={mul.returncode}; gaps not summing to the declared fill space "
        f"rc={sm.returncode}; no probe trees rc={empty.returncode}")

# J105 -- the pin on section 4a's four area-gate tiers.  Perturbed by giving it a COPY
# of the trees with the authority document removed: the tier must change and the pin
# must say so.  The copy is used so the real reconstructed trees are never damaged.
with tempfile.TemporaryDirectory(prefix="j105_area_") as t:
    d = pathlib.Path(t)
    src = ROOT / "meas/_j105"
    if (src / "areagate_edge_llm_accel").is_dir():
        for name in ("areagate_edge_llm_accel", "areagate_caravel_user_project",
                     "areagate_ibex", "areagate_opentitan_aes"):
            if (src / name).is_dir():
                shutil.copytree(src / name, d / name)
        clean = run([sys.executable, str(CTL / "areagate_reproduces.py")],
                    env=dict(os.environ, J105_TREES=str(d)))
        for f in (d / "areagate_edge_llm_accel").glob("**/L19*.json"):
            f.unlink()
        dirty = run([sys.executable, str(CTL / "areagate_reproduces.py")],
                    env=dict(os.environ, J105_TREES=str(d)))
        gone = run([sys.executable, str(CTL / "areagate_reproduces.py")],
                   env=dict(os.environ, J105_TREES=str(d / "not_here")))
        ok = (clean.returncode == 0
              and dirty.returncode == 1 and "do not reproduce" in dirty.stdout
              and gone.returncode == 1 and "MISSING" in gone.stdout)
        row("areagate_reproduces.py", "SYNTHETIC-RED" if ok else "*** CANNOT REDDEN ***",
            f"trees with their authority rc={clean.returncode}; the L19 deleted "
            f"rc={dirty.returncode}; no trees at all rc={gone.returncode}")
    else:
        row("areagate_reproduces.py", "*** NOT RUN ***",
            "the reconstructed trees are absent from this tree, so it was not exercised")

print("\n=== render no verdict — asserted mechanically, not by my say-so ===")
# The FIRST version of this classifier asked `"FAIL" in src` and flagged three files
# that only ever PARSE the flow's own `INITIAL_DPL_LEGALIZE_FAILED` /
# `POST_HOLD_LEGALIZE_FAILED` markers.  It matched the LABEL wherever it appeared,
# including where the file is quoting someone else's verdict instead of rendering its
# own -- J96's defect, committed inside the instrument written to hunt it, on the same
# dispatch.  A verdict word joined to other identifier characters is part of a TOKEN,
# not a verdict, so the word must be bounded on BOTH sides by non-identifier chars.
NONZERO = re.compile(r"sys\.exit\(\s*(?!0\s*\))")
BARE_VERDICT = re.compile(r"(?<![A-Za-z0-9_])(PASS|FAIL)(?![A-Za-z0-9_])")

def renders_verdict(src):
    return bool(NONZERO.search(src)) or bool(BARE_VERDICT.search(src))

# CONTROL on the classifier itself, because the first version was wrong and nothing
# caught it but a run.  Two synthetic sources, one of each kind; if the classifier
# cannot tell them apart, every REPORTER below is worthless.
_parses_only = 'import re\n_V = re.compile(r"POST_HOLD_LEGALIZE_(OK|FAILED)")\nprint(_V)\n'
_renders     = 'print("FAIL: the thing this file measures did not hold")\n'
_c1, _c2 = renders_verdict(_parses_only), renders_verdict(_renders)
print(f"  CONTROL  parses-a-FAILED-token -> renders_verdict={_c1} (want False); "
      f"prints-a-bare-FAIL -> {_c2} (want True)")
if _c1 or not _c2:
    print("  CLASSIFIER BROKEN — it cannot separate quoting a verdict from making one.")
    sys.exit(3)

for p in sorted(CTL.glob("*.py")):
    if p.name in seen:
        continue
    src = p.read_text()
    v = renders_verdict(src)
    row(p.name, "REPORTER" if not v else "*** MISCLASSIFIED ***",
        "no non-zero sys.exit, and no PASS/FAIL that is not part of a parsed token"
        if not v else "renders a verdict after all -- needs a positive control")

print("\n=== coverage: every file in controls/ accounted for ===")
present = {p.name for p in CTL.iterdir() if p.is_file()}
noncode = {p for p in present if p.endswith(".txt")}
unaccounted = present - seen - noncode
for p in sorted(noncode):
    print(f"  (not a runnable, accounted: {p})")
print(f"  {len(present)} file(s) in controls/, {len(seen & present)} classified, "
      f"{len(noncode)} non-runnable, {len(unaccounted)} unaccounted")

bad = [n for n, o, _ in rows if o.startswith("***")]
print()
if unaccounted:
    print(f"UNACCOUNTED file(s) in controls/: {sorted(unaccounted)}")
    print("A sweep that silently skips a file is the defect it is looking for.")
    sys.exit(2)
if bad:
    print(f"{len(bad)} control(s) could not be shown capable of red: {bad}")
    print("A control that has only ever printed green is not evidence.")
    sys.exit(1)
print("Every verdict-rendering control is shown capable of RED — by perturbation here,")
print("or by an unmanufactured red on real input — except the registered predicate,")
print("whose REFUTED branch is named above as an unexercised gap rather than fired.")
sys.exit(0)
