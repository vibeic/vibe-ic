"""Deleting a producer must change an answer somewhere.

Measured on the 68x9 matrix (mutation probe, plugin v1.12.33): 122 of
dimension D3's 166 entries ask whether a run tree committed into
`benchmark-data` still carries a file matching the declared glob. So the probe
deleted the WRITER of step A8's declared `.gds` and D3 stayed green in every
configuration -- the artefact was still in the corpus.

The gate under test asks the other question: does the SOURCE still write it.
The can-fail arm below is that same deletion, performed on a producer this
repo really ships.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import declared_output_has_a_live_producer_check as D

_PROGRAMS = Path(D.__file__).resolve().parent
_ROOT = _PROGRAMS.parents[3]


# ---------------------------------------------------------------- can FAIL --
def test_deleting_the_only_producer_downgrades_the_answer():
    """MUT-B1, on a live single-producer path: the writer goes, the answer moves."""
    before = D.audit(_ROOT)
    singles = [(p, r["producers"][0]) for p, r in before["rows"].items()
               if r["state"] == "WRITE-SITE" and len(r["producers"]) == 1]
    assert singles, "no single-producer declared output to delete"
    path, producer = sorted(singles)[0]
    after = D.audit(_ROOT, exclude_modules=[producer])
    assert before["rows"][path]["state"] == "WRITE-SITE"
    assert after["rows"][path]["state"] != "WRITE-SITE", (
        f"{producer} was the only writer of {path}, and removing it changed "
        f"nothing — the check is reading something other than the producer")


def test_a_declaration_cannot_prove_itself():
    """The flow's own `required_outputs` list is not evidence of a producer."""
    flow = ("steps:\n"
            "  - id: '1'\n"
            "    required_outputs:\n"
            "      - reports/only_declared.json\n"
            "    command: echo hi\n")
    kept = D._flow_commands(flow)
    assert "only_declared.json" not in kept
    assert "command: echo hi" in kept


# ---------------------------------------------------------------- can PASS --
def test_the_repo_has_no_untraceable_declared_output():
    """A guard that fires on the state it ships with is a bug, not a guard."""
    out = subprocess.run(
        [sys.executable, str(_PROGRAMS / "declared_output_has_a_live_producer_check.py"),
         "--root", str(_ROOT), "--strict"],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stdout[-3000:]


def test_an_unresolved_destination_matches_nothing():
    """`*/` alone is a variable this scanner could not read, not a producer."""
    assert not D._matches("*", "phase3/gds/chip.gds")
    assert not D._matches("*/*", "phase3/gds/chip.gds")


def test_a_glob_declaration_matches_a_computed_destination():
    assert D._matches("*/hardmacro/*/*.gds", "phase3/analog/hardmacro/*/*.gds")
    assert not D._matches("*/lessons.md", "phase3/analog/hardmacro/*/*.gds")


def test_an_extension_only_glob_falls_back_to_its_directory():
    assert D._tokens("sim_spice/*.sp") == {"sim_spice"}
    assert "perc_sweep.json" in D._tokens("reports/phase3/perc_sweep.json")


def test_a_missing_flow_is_cannot_check_not_pass():
    rc = D.main(["--root", "/nonexistent-root-for-this-test"])
    assert rc == 2


# ─────────────────────────────────────────────────────────────────────────────
# THE REAL MUTATION, after the synthetic fixture said the gate worked and a
# real tree said it did not. MEASURED 2026-08-29: deleting the sole writer of
# `phase2/stage1/formal/*.sby` left this gate at rc 0 PASS, because it blocked
# only on NO-TRACE — and NO-TRACE is unreachable here. Using the gate's own
# `exclude_modules` hook to delete the ENTIRE sole producer of all 34
# single-producer paths, not one reached NO-TRACE; every one landed in
# TOKEN-TRACE, because the path's name is still written in the source by its
# READERS.
# ─────────────────────────────────────────────────────────────────────────────
def test_deleting_a_sole_producer_moves_the_strict_verdict():
    """What this test has always been about: delete the ONLY module that
    writes a declared output and the strict verdict must move.

    It used to say that by counting how many such deletions land in NO-TRACE
    and asserting the count is ZERO. That was a snapshot of a living graph,
    and the graph moved: on 7903c1972305 one of them —
    `phase2/stage1/formal/formal_not_applicable.json`, sole producer
    `design_one_shot_runner.py` — now does land there. Relaxing `== 0` to
    `<= 1`, or whitelisting that path, would launder "the world changed" into
    "a tolerance", and the next reader would believe the tolerance.

    WHERE it lands is not the subject. `main` computes
    `bad = len(no_trace) + len(regressed)` and `regressed` is any baselined
    path whose state is no longer WRITE-SITE — so a demotion to NO-TRACE and a
    demotion to TOKEN-TRACE are the same finding. Asserting the demotion is
    both what the program means and still falsifiable the next time the graph
    moves."""
    before = D.audit(_ROOT)
    singles = [(p, r["producers"][0]) for p, r in before["rows"].items()
               if r["state"] == "WRITE-SITE" and len(r["producers"]) == 1]
    assert singles, "no single-producer path to reason about"
    survived = []
    landings = {}
    for path, producer in singles:
        after = D.audit(_ROOT, exclude_modules=[producer])
        state = after["rows"][path]["state"]
        landings[state] = landings.get(state, 0) + 1
        if state == "WRITE-SITE":
            survived.append((path, producer))
    assert not survived, (
        f"{len(survived)} of {len(singles)} paths kept their write site after "
        f"their ONLY producer was deleted, so the strict verdict would not "
        f"move for them: {survived}")
    # reported, not asserted: which state they land in is the graph's business
    assert sum(landings.values()) == len(singles), landings


def test_losing_a_write_site_is_the_blocking_condition(tmp_path):
    """The real defect: a path this tree resolved to a writer stops having one."""
    before = D.audit(_ROOT)
    live = sorted(p for p, r in before["rows"].items() if r["state"] == "WRITE-SITE")
    assert live, "no write site to lose"
    victim = live[0]
    # ALL of the row's producers, not just the first. The behaviour under test
    # is "a path loses its write site", and a path with two writers does not
    # lose it when one is deleted — MEASURED: `live[0]` is
    # `phase2/analog/*/*.sp`, written by BOTH `analog_a3_netlist_emit.py` and
    # `pdk_analog_characterize.py` since `fdcbf3ac91`, so excluding
    # `producers[0]` left the state at WRITE-SITE and this test failed on a
    # row that was behaving correctly.
    #
    # The narrowing fix — pick the victim only from single-producer rows —
    # would shrink the predicate to exactly the shape that makes the one
    # failure disappear, and would quietly stop testing every path that grows
    # a second writer. Deleting the whole producer set keeps the population
    # whole.
    producers = before["rows"][victim]["producers"]
    assert producers, victim
    after = D.audit(_ROOT, exclude_modules=producers)
    assert after["rows"][victim]["state"] != "WRITE-SITE", (
        f"{victim} kept its write site after all {len(producers)} of its "
        f"producers were excluded: {producers}")

    # the baseline says it WAS resolved; the gate must call that a regression
    inv = tmp_path / "baseline.json"
    inv.write_text(json.dumps({"write_site": live}), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(_PROGRAMS / "declared_output_has_a_live_producer_check.py"),
         "--root", str(_ROOT), "--inventory", str(inv), "--strict"],
        capture_output=True, text=True)
    assert out.returncode == 0, ("the unmutated tree must satisfy its own "
                                 "baseline\n" + out.stdout[-1500:])


def test_a_synthetic_fixture_is_not_a_producer():
    """MEASURED: one gate-mutation fixture was the SOLE credited producer of 23
    declared flow outputs — drc_signoff.rpt, lvs.rpt, erc.rpt, ir_drop.rpt among
    them. A fixture writes those paths to BUILD a subject tree; nothing in the
    flow is thereby shown to write them."""
    walked = [str(f) for f in D._venue_files(_ROOT)]
    assert not [f for f in walked if "gate_fixtures" in f], \
        "a gate fixture is being walked as a production venue"
    report = D.audit(_ROOT)
    credited = {m for r in report["rows"].values() for m in (r.get("producers") or [])}
    assert not [m for m in credited if "fixture" in m or m.startswith("test_")], \
        sorted(credited)


def test_an_unreadable_baseline_is_refused_not_treated_as_empty(tmp_path):
    """An empty baseline would silently forgive every regression."""
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(_PROGRAMS / "declared_output_has_a_live_producer_check.py"),
         "--root", str(_ROOT), "--inventory", str(bad), "--strict"],
        capture_output=True, text=True)
    assert out.returncode == 2, out.stdout + out.stderr
    assert "never treated as empty" in out.stderr


# ─────────────────────────────────────────────────────────────────────────────
# THE BASELINE IS AN INPUT, SO IT COMES FROM THE SUBJECT.
#
# `repo_hygiene_gates.sh:1821` runs this gate as
# `$PG/declared_output_has_a_live_producer_check.py --root "$ROOT" --strict`.
# `$PG` is pinned to the RUNTIME tree because it names the EXECUTABLE; `$ROOT`
# is `VIBEIC_SUBJECT_ROOT` because it names the INPUT. While the write-site
# baseline was resolved beside the program, the audit followed that redirect
# and the baseline did not, so every path the runtime tree had resolved was
# looked up in the subject's flow and reported as a regression.
#
# MEASURED on ae4dbc091, driving this gate's own fixture pair: BOTH directions
# returned rc 1 carrying the same 18 `[LOST WRITE SITE]` lines, not one of
# which is about the subject —
# `test_gate_fixtures_discriminate::test_fixture_pair_discriminates[a_declared_output_has_a_live_producer]`
# was red on the CAN-PASS direction. A gate that refuses every input is not
# discriminating for exactly the reason one that accepts every input is not.
# ─────────────────────────────────────────────────────────────────────────────
_SUBJECT_FLOW = (
    "steps:\n"
    "  - id: '1'\n"
    "    name: synthetic step one\n"
    "    required_outputs:\n"
    "      - reports/subject_only_report.json\n")

_SUBJECT_PRODUCER = (
    "from pathlib import Path\n"
    "\n"
    "\n"
    "def emit(project):\n"
    '    (Path(project) / "reports" / "subject_only_report.json").write_text("{}")\n')


def _subject_tree(tmp_path, baseline):
    """A tree that shares NOTHING with the runtime repo but its layout."""
    root = tmp_path / "subject"
    flow = root / D.FLOW_REL
    flow.parent.mkdir(parents=True, exist_ok=True)
    flow.write_text(_SUBJECT_FLOW, encoding="utf-8")
    programs = root / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "subject_report_emit.py").write_text(_SUBJECT_PRODUCER,
                                                     encoding="utf-8")
    if baseline is not None:
        # The relative path is SPELLED OUT rather than read from
        # `D._INVENTORY_REL`, so that these three tests still RUN against a
        # tree that predates that constant. A control that dies of
        # AttributeError on the old code has observed nothing about the old
        # code; this one lets it answer, and answer wrongly.
        (root / "vibe-ic-marketplace/plugins/vibe-ic/programs"
              / "declared_output_write_site_baseline.json").write_text(
                  json.dumps(baseline), encoding="utf-8")
    return root


def _run(*argv):
    return subprocess.run(
        [sys.executable,
         str(_PROGRAMS / "declared_output_has_a_live_producer_check.py"), *argv],
        capture_output=True, text=True)


def test_the_baseline_is_read_from_the_subject_not_from_beside_the_program(tmp_path):
    """The subject satisfies its OWN baseline, so the verdict is PASS."""
    root = _subject_tree(tmp_path, {"write_site": ["reports/subject_only_report.json"]})
    out = _run("--root", str(root), "--strict")
    assert out.returncode == 0, out.stdout + out.stderr
    # and specifically: not one path from the runtime tree's own baseline
    # reached the verdict. That set is non-empty, so this is a real denominator.
    runtime = json.loads((_PROGRAMS / "declared_output_write_site_baseline.json")
                         .read_text(encoding="utf-8"))["write_site"]
    assert runtime, "the runtime baseline is empty, so this control proves nothing"
    for path in runtime:
        assert path not in out.stdout, (
            f"the verdict over a synthetic subject names {path!r}, which only "
            f"the runtime tree declares — the gate is reading two trees")


def test_a_demotion_in_the_subject_is_what_blocks(tmp_path):
    """Same tree, producer's destination moved: rc 1, naming that path."""
    root = _subject_tree(tmp_path, {"write_site": ["reports/subject_only_report.json"]})
    producer = root / "vibe-ic-marketplace/plugins/vibe-ic/programs/subject_report_emit.py"
    producer.write_text(
        _SUBJECT_PRODUCER.replace("subject_only_report.json", "scratch_note.json"),
        encoding="utf-8")
    out = _run("--root", str(root), "--strict")
    assert out.returncode == 1, out.stdout + out.stderr
    assert "[LOST WRITE SITE] reports/subject_only_report.json" in out.stdout, out.stdout


def test_an_absent_baseline_is_refused_not_read_as_nothing_to_compare(tmp_path):
    """The other half of the same defect.

    Resolving the baseline under `--root` and leaving its absence silent would
    convert a gate that refused every redirected subject into one that
    ACCEPTED every redirected subject: the only condition this gate blocks on
    is the demotion, and a demotion is a comparison against that file. Refused
    for the same reason the unreadable case above is refused."""
    root = _subject_tree(tmp_path, None)
    out = _run("--root", str(root), "--strict")
    assert out.returncode == 2, out.stdout + out.stderr
    assert "no write-site baseline at" in out.stderr, out.stderr
    # NOT a silent pass, and not the demotion verdict either.
    assert "PASS" not in out.stdout, out.stdout
