#!/usr/bin/env python3
"""#511 — a gate that examined NOTHING must not render as PASS.

THE MEASUREMENT THAT OPENED THIS
=================================
A deterministic sample of 41 of the 481 `programs/*_check.py`, each driven
against a structurally empty project (`input/docs/` and `reports/` created,
nothing in them), found two whose ENTIRE output was one line:

    [PASS] analog_flow_compliance_check
    [PASS] analog_netlist_include_order_check

rc 0, no report file written, no count, no reason. `analog_netlist_include_
order_check` printed the SAME line over a real corpus project carrying two
SPICE decks, so "the include order is correct" and "there was no netlist" were
byte-identical to every consumer of either channel.

WHAT IS PINNED HERE
====================
1. Both gates now disclose, and the empty case is rc 2 / VACUOUS_PASS with a
   `_gate_denominator` denominator on stdout, on stderr and in the report.
2. `dead_plugin_path_check`'s zero grew a denominator — the decision #511 asked
   for, recorded in the program and pinned here.
3. THE STANDING CHECK: `gate_discloses_denominator_check --population project`
   drives EVERY `*_check.py` against an empty project. Its dated inventory is
   its own denominator, and this file proves the ratchet fires in BOTH
   directions — a new silent gate cannot be absorbed, and a fixed one cannot
   stay on the list.
4. NO GATE GOT QUIETER: every rejection the three gates made before, they still
   make.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = PROGRAMS.parent
STANDING = PROGRAMS / "gate_discloses_denominator_check.py"
FLOW = PROGRAMS / "analog_flow_compliance_check.py"
ORDER = PROGRAMS / "analog_netlist_include_order_check.py"
DEAD = PROGRAMS / "dead_plugin_path_check.py"

sys.path.insert(0, str(PROGRAMS))
import gate_discloses_denominator_check as GD  # noqa: E402
import _gate_denominator as GDEN  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────

def _empty_project(tmp_path: Path, name: str = "proj") -> Path:
    """A structurally empty project: the two directories a run scaffolds, and
    nothing else in them."""
    proj = tmp_path / name
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)
    return proj


def _run(prog: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Drive a gate and capture its exit code DIRECTLY. Never through a pipe:
    a piped rc is the pipe's, not the gate's."""
    return _pr.run([sys.executable, str(prog), *args],
                          cwd=str(cwd), capture_output=True, text=True)


# ── 1. the two measured instances: empty project ───────────────────────────

@pytest.mark.parametrize("prog,gate", [
    (FLOW, "analog_flow_compliance_check"),
    (ORDER, "analog_netlist_include_order_check"),
])
def test_bare_pass_on_empty_project_is_now_a_disclosed_skip(
        tmp_path, prog, gate):
    """The exact reproduction from the issue, inverted."""
    proj = _empty_project(tmp_path, gate)
    r = _run(prog, proj, ".")

    # It is no longer a PASS: rc 2 is this repo's NOT-CHECKED tier.
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    # The verdict line is not the old bare one, and it is not `[PASS]`.
    first = r.stdout.strip().splitlines()[0]
    assert first.startswith(f"[VACUOUS_PASS] {gate}:"), first
    assert first != f"[PASS] {gate}"
    # The line CARRIES the denominator; pointing at a report nobody opens is
    # what the issue rejected.
    assert "examined 0" in first, first
    # …and a written reason, on the line and on the rc-independent channel.
    assert "NOT a sign-off" in first, first
    assert r.stderr.strip().startswith("VACUOUS_PASS:"), r.stderr


@pytest.mark.parametrize("prog,gate", [
    (FLOW, "analog_flow_compliance_check"),
    (ORDER, "analog_netlist_include_order_check"),
])
def test_empty_project_report_carries_a_compliant_denominator(
        tmp_path, prog, gate):
    """The machine channel obeys `_gate_denominator`'s contract too — a zero
    with no written reason is what `disclosure_violations` exists to name."""
    proj = _empty_project(tmp_path, gate)
    out = proj / "r.json"
    r = _run(prog, proj, ".", "--json", str(out))
    assert r.returncode == 2, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "VACUOUS_PASS"
    assert GDEN.disclosure_violations(rep["summary"]) == []
    denom = rep["summary"][GDEN.DENOMINATOR_KEY]
    assert denom["examined"] == 0
    assert denom["unit"].strip()
    assert denom["not_applicable_reason"].strip()
    # Even with --json, where stdout is deliberately empty, the text channel
    # is not silence.
    assert "VACUOUS_PASS:" in r.stderr


# ── 2. no gate got quieter: the populated cases ────────────────────────────

def _analog_project_with_blocks(tmp_path: Path, blocks) -> Path:
    proj = _empty_project(tmp_path, "analog")
    bl = proj / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps(list(blocks)))
    return proj


def test_flow_gate_still_fails_a_project_with_a_missing_a_step(tmp_path):
    """The rule the gate exists for, unchanged: a declared block with no A-step
    artefact is rc 1 with nine MISSING findings."""
    proj = _analog_project_with_blocks(tmp_path, ["osc"])
    out = proj / "r.json"
    r = _run(FLOW, proj, ".", "--json", str(out))
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["passed"] is False
    assert rep["summary"]["total_missing"] == 9
    assert {f["rule"] for f in rep["findings"]} >= {"ANALOG_A1_MISSING"}


def test_flow_gate_pass_now_states_how_many_obligations_stood_behind_it(
        tmp_path):
    """A real clean run and a run over nothing must not print the same line."""
    proj = _analog_project_with_blocks(tmp_path, ["ldo"])
    ad = proj / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "spec.json").write_text("{}")
    (ad / "topology.md").write_text("# LDO\n")
    (ad / "ldo.sp").write_text(".title LDO\n.end\n")
    # WAS `{}`. This test asserts a whole-project A1-A9 PASS, and with an
    # empty object in it the A4 cell was signing off a corner artefact that
    # declares no corners, no provenance and no statement of what circuit it
    # measured. The A4 cell delegates to the A4 gate's own certification
    # predicates, so the fixture carries what a signed-off A4 looks like; the
    # denominator disclosure this file is about is untouched by it.
    (ad / "corner_results.json").write_text(json.dumps({
        "netlist_provenance": "a3_netlist",
        "design_content": "structure_and_geometry",
        "corners": [{"name": "tt_27c", "simulator_run": True, "vout_v": 1.8}],
        "spec_results": [{"name": "vout", "status": "PASS", "target": None}],
    }))
    (ad / "layout.mag").write_text("magic\n")
    (ad / "drc_clean.flag").write_text("violations: 0\n")
    (ad / "lvs_match.flag").write_text("lvs: match\n")
    (ad / "pre_vs_post.json").write_text("{}")
    hm = proj / "phase3" / "analog" / "hardmacro" / "ldo"
    hm.mkdir(parents=True)
    (hm / "ldo.lef").write_text("MACRO ldo\nEND ldo\n")
    cd = proj / "phase3" / "mixed_signal" / "cosim"
    cd.mkdir(parents=True, exist_ok=True)
    (cd / "ldo_cosim_results.json").write_text("{}")

    r = _run(FLOW, proj, ".")
    assert r.returncode == 0, r.stdout + r.stderr
    first = r.stdout.strip().splitlines()[0]
    assert first.startswith("[PASS] analog_flow_compliance_check:")
    # 1 block x 9 A-steps.
    assert "examined 9" in first, first
    # The discriminator the standing check uses agrees.
    assert GD.discloses(r.stdout)


def test_fpga_stub_waiver_still_promotes_a_real_fail(tmp_path):
    """`--allow-fpga-stub` promotes exactly what it promoted before: a FAIL
    with missing per-block artefacts."""
    proj = _analog_project_with_blocks(tmp_path, ["osc"])
    out = proj / "r.json"
    r = _run(FLOW, proj, ".", "--allow-fpga-stub", "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS_WITH_WAIVERS"
    assert rep["summary"]["fpga_stub_waiver_applied"] is True


def test_fpga_stub_waiver_does_not_dress_a_vacuous_run_as_waived(tmp_path):
    """…and NOT what it never could: the waiver guard used to read
    `not result.passed`, and #511 made a vacuous run's `passed` False. Keyed on
    the VERDICT instead, so an unexamined project cannot come out wearing
    PASS_WITH_WAIVERS — there was nothing to waive."""
    proj = _empty_project(tmp_path, "stub_vacuous")
    out = proj / "r.json"
    r = _run(FLOW, proj, ".", "--allow-fpga-stub", "--json", str(out))
    assert r.returncode == 2, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "VACUOUS_PASS"
    assert "fpga_stub_waiver_applied" not in rep["summary"]


def test_order_gate_still_fails_lib_before_include(tmp_path):
    """The ordering rule, unchanged: rc 1 and the same finding."""
    proj = _empty_project(tmp_path, "order_bad")
    d = proj / "analog" / "amp"
    d.mkdir(parents=True)
    (d / "amp.sp").write_text(
        "* deck\n"
        ".lib /pdk/libs.tech/ngspice/sm141064.ngspice typical\n"
        ".include /pdk/libs.tech/ngspice/design.ngspice\n")
    out = proj / "r.json"
    r = _run(ORDER, proj, ".", "--json", str(out))
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL"
    assert "LIB_BEFORE_DESIGN_INCLUDE" in {f["rule"] for f in rep["findings"]}


def test_order_gate_pass_now_states_how_many_decks_it_read(tmp_path):
    """The sharpest half of #511: the clean case used to print the SAME line as
    the empty case. Two decks read must be visible as two."""
    proj = _empty_project(tmp_path, "order_ok")
    d = proj / "analog" / "amp"
    d.mkdir(parents=True)
    good = ("* deck\n"
            ".include /pdk/libs.tech/ngspice/design.ngspice\n"
            ".lib /pdk/libs.tech/ngspice/sm141064.ngspice typical\n")
    (d / "a.sp").write_text(good)
    (d / "b.sp").write_text(good)

    r = _run(ORDER, proj, ".")
    assert r.returncode == 0, r.stdout + r.stderr
    first = r.stdout.strip().splitlines()[0]
    assert first.startswith("[PASS] analog_netlist_include_order_check:")
    assert "examined 2" in first, first
    # The empty-project line for the same gate must not be a prefix of this
    # one: distinguishability is the whole point.
    empty = _run(ORDER, _empty_project(tmp_path, "order_empty"), ".")
    assert empty.stdout.strip() != r.stdout.strip()
    assert empty.returncode != r.returncode


def test_order_gate_non_directory_still_exits_2(tmp_path):
    r = _run(ORDER, tmp_path, str(tmp_path / "nope"))
    assert r.returncode == 2


# ── 3. dead_plugin_path_check: the recorded decision ───────────────────────

def test_dead_plugin_gate_still_rejects_a_retired_token(tmp_path):
    """The rejection this gate exists for, untouched."""
    sk = tmp_path / "skills" / "demo"
    sk.mkdir(parents=True)
    import dead_plugin_path_check as DP  # noqa: E402
    (sk / "SKILL.md").write_text(
        "see plugins/" + DP.RETIRED_PLUGIN_TOKEN + "/_shared/x.py\n")
    r = _run(DEAD, tmp_path, str(tmp_path))
    assert r.returncode == 1
    assert "FAIL — 1 retired-plugin reference(s)" in r.stdout
    # A FAIL states its denominator too: the finding is not the only number.
    assert "examined" in r.stdout


def test_dead_plugin_gate_scanning_nothing_is_no_longer_a_pass(tmp_path):
    """THE DECISION: this zero is NOT meaningful without a denominator. A root
    carrying none of skills/ programs/ _shared/ scanned zero files and printed
    the same sentence as a full clean sweep."""
    r = _run(DEAD, tmp_path, str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert r.stdout.strip().splitlines()[0].startswith(
        "[VACUOUS_PASS] dead_plugin_path_check:")
    assert "examined 0" in r.stdout
    assert "NOT a clean-bundle verdict" in r.stdout
    assert r.stderr.strip().startswith("VACUOUS_PASS:")


def test_dead_plugin_gate_on_the_real_bundle_passes_and_says_how_much(
        tmp_path):
    """And the live invocation `tools/ci/repo_hygiene_gates.sh` makes — the one
    that must not change — still passes, now with its scan size stated."""
    r = _run(DEAD, PLUGIN_ROOT, ".")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("PASS — 0 retired-plugin reference(s);")
    hits, stats = __import__("dead_plugin_path_check").scan(str(PLUGIN_ROOT))
    assert hits == []
    assert stats["files_scanned"] > 100, stats
    assert stats["subtrees_present"] == 3, stats


# ── 4. the disclosure predicate: the underscore-boundary repair ────────────

@pytest.mark.parametrize("text", [
    # THE BOUNDARY REPAIR, isolated: token only, no prose and no digit, so the
    # other alternatives in the pattern cannot cover for it. `\bVACUOUS\b` does
    # NOT match `VACUOUS_PASS` and `\bSKIP\b` does NOT match `PASS_SKIP`,
    # because `_` is a word character — these two cases fail on the
    # pre-repair pattern and pass on the repaired one.
    "VACUOUS_PASS",
    "PASS_SKIP",
    # …and the same tokens as a gate actually emits them.
    "VACUOUS_PASS: no analog blocks declared",
    "PASS_SKIP — no CRC module found",
    '{"verdict": "NOT_APPLICABLE", "reason": "step did not run"}',
    "manifest_leak_check: no manifest files found",
    "[SKIP] gate: nothing to do",
    "NOT_CHECKED: could not read the artefact",
])
def test_disclosure_predicate_recognises_the_repos_own_tokens(text):
    """Every token below is how a gate in THIS repo says it examined nothing."""
    assert GD.discloses(text), text


@pytest.mark.parametrize("text", [
    "[PASS] analog_block_coverage_check",
    "PASS: clean-room run dir (no inherited samples / scores)",
    "",
])
def test_disclosure_predicate_still_rejects_silence(text):
    """The other direction, and the reason the nothing-statement is not a bare
    `no`: the clean-room sentence describes the FINDING, and is exactly as true
    of a scan that read nothing."""
    assert not GD.discloses(text), text


# ── 5. the standing check itself ───────────────────────────────────────────

def test_standing_check_drives_every_gate_and_passes(tmp_path):
    """Drives the program, not a re-implementation of it.

    Runtime measured on the authoring host: ~2.5s for all 481 gates at 8
    workers, one throwaway project each.
    """
    out = tmp_path / "pop.json"
    r = _run(STANDING, PROGRAMS,
             "--population", "project", "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["findings"] == []

    # The census is real: the population is the whole registry, not a sample.
    #
    # WAS `len(PROGRAMS.glob("*_check.py"))`, and that line was the second half
    # of the #511 defect: it agreed with the check because BOTH said the
    # registry was one filename. `analog_netlist_path_lint` — a gate the A3
    # producer drives beside two `*_check.py` — printed the same bare `[PASS]`
    # over a clean deck and over nothing for as long as this check existed, and
    # neither the check nor this test could see it. The expectation is now
    # DERIVED the same way the population is, from the two sources in the tree.
    on_disk = len(GD.project_check_programs(PROGRAMS))
    assert rep["gates_probed"] == on_disk
    assert rep["gates_probed"] > 400, rep["gates_probed"]
    # …and it is strictly wider than the filename it used to be, so a run that
    # silently fell back to that glob would fail here rather than look clean.
    assert on_disk > len(list(PROGRAMS.glob("*_check.py"))), on_disk
    defn = rep["population_definition"]
    assert defn["degraded"] is False, defn
    assert defn["by_suffix"] and defn["by_behaviour"], defn
    assert rep["rc_zero"] > 0
    assert (rep["rc_zero_disclosing"] + rep["rc_zero_silent"]
            == rep["rc_zero"])
    # Every silent gate is on ONE of the two dated exemption lists and nowhere
    # else — exact-set equality in both directions, which is the mechanism: a
    # new silent gate cannot be absorbed and a fixed one cannot stay listed.
    # The second list arrived with the derived population: a population chosen
    # by RELATION reaches programs a project fixture cannot address at all, and
    # those are a different fact about the program from "it went silent".
    exempt = set(rep["inventory"]) | set(rep["not_project_driven"])
    assert set(rep["silent_gates"]) == exempt, (rep["silent_gates"], exempt)
    assert not (set(rep["inventory"])
                & set(rep["not_project_driven"])), (
        "a program on both lists has two different reasons on the record")


def test_number_only_disclosure_passes_and_is_published_not_hidden(tmp_path):
    """THE DECISION, made explicitly rather than by omission: a gate that
    discloses with a bare COUNT passes this check — a count IS a denominator,
    and it is the line the CI population has drawn since #447. What the count
    does not buy is silence about how many gates rely on it, so the residual is
    a published number.

    MEASURED 2026-07-28 over all 481: 202 rc-0 before this change, of which 151
    stated a reason, 34 disclosed with a number only, 17 disclosed nothing.
    """
    out = tmp_path / "pop.json"
    r = _run(STANDING, PROGRAMS, "--population", "project", "--json", str(out))
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert (rep["rc_zero_reasoned"] + rep["rc_zero_number_only"]
            == rep["rc_zero_disclosing"])
    assert rep["rc_zero_number_only"] > 0, (
        "if this is 0 the distinction has stopped being measured")
    # The residual is NAMED, not just counted.
    assert len(rep["number_only_gates"]) == rep["rc_zero_number_only"]
    assert rep["rc_zero_number_only_decision"]
    # …and visible without opening the JSON.
    assert "number-only" in (r.stdout + r.stderr)


def test_a_hit_count_alone_is_still_accepted_by_the_predicate(tmp_path):
    """The honest limit of the machine bar, pinned so it is not mistaken for a
    stronger claim: `0 widget(s) found` and `0 widget(s) of 1239 scanned` are
    both accepted, because text alone cannot say which integer is the
    denominator. That is why `_gate_denominator` makes a gate NAME its unit —
    and why `dead_plugin_path_check`, which printed a HIT count, was fixed by
    hand in this change rather than by the predicate."""
    assert GD.discloses("PASS — 0 widget(s)")
    assert GD.discloses("PASS — 0 widget(s) of 1239 scanned")
    # The stricter predicate separates neither, and is reported, not enforced.
    assert not GD.discloses_a_reason("PASS — 0 widget(s)")


def test_rc_outside_the_convention_is_recorded_not_folded_in(tmp_path):
    """Three gates exit 3 over an empty project. That is not a disclosure
    defect and this check does not judge it — but the census must have no
    unexplained residue, so they are named."""
    out = tmp_path / "pop.json"
    r = _run(STANDING, PROGRAMS, "--population", "project", "--json", str(out))
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    odd = rep["rc_outside_convention"]
    assert odd, "the recorded case has gone empty — re-measure before deleting"
    assert all(e["rc"] not in (0, 1, 2) and e["note"] for e in odd)
    assert "OUTSIDE THE 0/1/2 CONVENTION" in (r.stdout + r.stderr)


def test_standing_check_publishes_its_inventory_on_a_passing_run(tmp_path):
    """The exemption list IS the denominator, so it is visible whether or not
    anything failed. A count nobody sees until something breaks is the shape
    that lets a list grow."""
    r = _run(STANDING, PROGRAMS, "--population", "project")
    assert r.returncode == 0
    text = r.stdout + r.stderr
    assert "KNOWN-SILENT INVENTORY (this check's own denominator)" in text
    for gate, meta in GD._EMPTY_PROJECT_SILENT_PASS.items():
        assert gate in text, gate
        assert meta["measured"] in text
    assert "rc 0:" in text and "silent:" in text


def test_inventory_entries_are_dated_and_reasoned():
    """No undated, unreasoned entry may exist — an exemption whose reason is
    absent is not reviewable, which is the only thing that keeps a list from
    becoming permanent."""
    assert GD._EMPTY_PROJECT_SILENT_PASS, "the inventory must not be empty " \
        "while the class is open — an empty one would make the ratchet vacuous"
    for gate, meta in GD._EMPTY_PROJECT_SILENT_PASS.items():
        assert (PROGRAMS / f"{gate}.py").is_file(), gate
        assert meta["reason"].strip(), gate
        # ISO date, so "when was this last true" is answerable.
        assert len(meta["measured"]) == 10 and meta["measured"][4] == "-", gate


def _fake_programs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "fake_programs"
    d.mkdir()
    return d


def _write_gate(d: Path, name: str, body: str) -> None:
    (d / f"{name}.py").write_text(
        "#!/usr/bin/env python3\nimport sys\n" + body + "\n")


def test_inventory_cannot_grow_silently(tmp_path):
    """THE DEFECT THIS CHECK EXISTS TO CATCH, injected.

    A NEW gate that answers a bare PASS over an empty project must fail the
    check by name — it must not be quietly absorbed."""
    d = _fake_programs_dir(tmp_path)
    _write_gate(d, "brand_new_silent_check",
                'print("[PASS] brand_new_silent_check")\nsys.exit(0)')
    out = tmp_path / "r.json"
    r = _run(STANDING, tmp_path, "--population", "project",
             "--programs-dir", str(d), "--json", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    kinds = {(f["gate"], f["kind"]) for f in rep["findings"]}
    assert ("brand_new_silent_check", "PASS_WITHOUT_DENOMINATOR") in kinds
    assert "brand_new_silent_check" in r.stderr


def test_a_disclosing_gate_is_not_flagged(tmp_path):
    """The check must not fire on legitimate state: a gate that DOES disclose
    over an empty project passes. Without this the previous test would also
    pass for a check that simply rejects everything."""
    d = _fake_programs_dir(tmp_path)
    _write_gate(d, "brand_new_disclosing_check",
                'print("[VACUOUS_PASS] brand_new_disclosing_check: examined 0 '
                'widget(s) — no widget in this project")\nsys.exit(0)')
    out = tmp_path / "r.json"
    r = _run(STANDING, tmp_path, "--population", "project",
             "--programs-dir", str(d), "--json", str(out))
    rep = json.loads(out.read_text())
    flagged = {f["gate"] for f in rep["findings"]
               if f["kind"] == "PASS_WITHOUT_DENOMINATOR"}
    assert "brand_new_disclosing_check" not in flagged


def test_inventory_cannot_keep_an_entry_that_no_longer_applies(tmp_path):
    """The other direction of the same ratchet: an inventoried gate that now
    discloses must fail the check with `delete the entry`, so the list can only
    ever be made shorter by a visible edit."""
    d = _fake_programs_dir(tmp_path)
    fixed = sorted(GD._EMPTY_PROJECT_SILENT_PASS)[0]
    _write_gate(d, fixed,
                f'print("[VACUOUS_PASS] {fixed}: examined 0 block(s) — none '
                f'declared")\nsys.exit(0)')
    out = tmp_path / "r.json"
    r = _run(STANDING, tmp_path, "--population", "project",
             "--programs-dir", str(d), "--json", str(out))
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    stale = {f["gate"] for f in rep["findings"]
             if f["kind"] == "STALE_INVENTORY_ENTRY"}
    assert fixed in stale


def test_standing_check_refuses_an_empty_population(tmp_path):
    """Its own denominator: a run that found no gate to probe must not report a
    clean result — that is the very defect it exists to catch."""
    d = _fake_programs_dir(tmp_path)
    r = _run(STANDING, tmp_path, "--population", "project",
             "--programs-dir", str(d))
    assert r.returncode == 2
    assert "NOTHING_SCANNED" in r.stderr


def _synthetic_ci_repo(tmp_path: Path, lines) -> Path:
    """A repo root carrying only a `tools/ci/repo_hygiene_gates.sh` with the
    given `run` lines.

    Driving the CI population against the REAL script takes ~57s (it re-runs
    every repo-hygiene gate, worktree probes included) and, because that set is
    currently clean, it can only ever prove the PASS branch. A synthetic script
    exercises the same parse → expand → drive → classify path in milliseconds
    AND can prove the FAIL branch, which the real one cannot.
    """
    root = tmp_path / "repo"
    (root / "tools" / "ci").mkdir(parents=True)
    (root / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        "#!/usr/bin/env bash\n" + "\n".join(lines) + "\n")
    return root


def test_ci_population_still_flags_a_silent_gate(tmp_path):
    """The first population's rule, still enforced, and now proven on the
    branch the real gate set cannot reach."""
    probe = tmp_path / "silent_probe.py"
    probe.write_text("print('[PASS] silent_probe')\n")
    root = _synthetic_ci_repo(
        tmp_path, [f'run "silent probe" "$PLUGIN" python3 {probe}'])
    out = tmp_path / "ci.json"
    r = _run(STANDING, tmp_path, str(root), "--json", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["population"] == "ci"
    assert [f["kind"] for f in rep["findings"]] == ["PASS_WITHOUT_DENOMINATOR"]


def test_ci_population_accepts_a_disclosing_gate(tmp_path):
    """…and does not fire on legitimate state, which is what keeps the
    previous test from passing for a check that rejects everything."""
    probe = tmp_path / "disclosing_probe.py"
    probe.write_text("print('PASS — examined 0 file(s): none present')\n")
    root = _synthetic_ci_repo(
        tmp_path, [f'run "disclosing probe" "$PLUGIN" python3 {probe}'])
    out = tmp_path / "ci.json"
    r = _run(STANDING, tmp_path, str(root), "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["gates_probed"] == 1
