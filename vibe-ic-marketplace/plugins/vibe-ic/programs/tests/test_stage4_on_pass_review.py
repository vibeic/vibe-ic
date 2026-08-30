#!/usr/bin/env python3
"""The stage-4 ON-PASS review — and the control that stops it manufacturing
confidence in either direction.

WHAT STAGE 4 OWNS THAT NO EARLIER STAGE DOES
============================================
Stage 2 checks the netlist against the RTL. Stage 3 checks the layout against
the netlist and the PDK. Both are INTERNAL comparisons: each asks whether an
artefact agrees with the artefact one rung below it, and both are satisfied by
a self-consistent stack built around the wrong subject. Stage 4 is where the
run stops comparing and starts SHIPPING — step 37 streams
`phase3/stage4/gds/*.gds`, step 38 hands it to a foundry — so the question that
appears exactly here is whether the file in the die slot is the design the
INTENT asked for.

Nothing in the flow asks it. Step 37's four blocking clauses are
`gds_size_check` (bytes), `gds_substance_check` (elements vs the DEF's placed
instances), `gds_port_label_check` (a label per placed DEF pin) and
`provenance_check` (a real streamer wrote it); every one is satisfied by a
well-formed layout of ANY design. `gds_topcell_name_check` does compare a name,
but it must be TOLD that name (`--top-name`) and appears in no `gate:` in
`flow/phase1_phase2_phase3.yaml` at all — a check that is handed the answer
cannot read the intent.

THE KNOWN-BAD IS REAL AND WAS NOT INVENTED HERE
===============================================
`ic/u_hawaii_adc/v1.9.86_sky130A` publishes `Verdict: PASS` with
`flow_compliance_check --strict -> PASS=8 FAIL=0 MISSING=0, Overall PASS,
exit 0` and `run_output_completeness_check -> COMPLETE, exit 0`. Its die slot
holds `phase3/stage4/gds/ldo.gds`, hierarchy root `ldo`, seven structures — that
block plus primitive devices — and the file is byte-identical (sha256
369719cf…) to the block deliverable the same run published at
`phase3/analog/hardmacro/ldo/ldo.gds`. `u_hawaii_adc` is defined nowhere in it.
The first party to notice was an external shuttle's own precheck.

BOTH DIRECTIONS, ON REAL ARTEFACTS
==================================
A reviewer that never rejects is WORSE than none — it manufactures confidence
in every artefact it looks at. One that rejects everything is worse still. So
every case below asserts BOTH, on published bytes:

  ACCEPT  `fixtures/stage4_on_pass_review/accept_spm_ihp` — verbatim from
          `ic/spm/v1.5.58_ihp-sg13g2`, whose die's hierarchy root IS the module
          its L9 names, with `no_top_module_in_input: false`.
  REJECT  `fixtures/stage4_on_pass_review/reject_hawaii_ldo` — verbatim from
          the cell above.

`fixtures/.../PROVENANCE.json` pins each source file's sha256 and
`test_the_fixture_is_the_published_bytes_and_not_a_paraphrase` re-measures it
after materialising the tree, so "verbatim" is asserted rather than promised.

WHY THE ACCEPT SET HAS TWO MEMBERS
==================================
A die's hierarchy root is legitimately either the module the intent names or
the flow's own chip-top wrapper (`canonical_top_wrapper:` in the declaration) —
the module `design_one_shot_runner` auto-emits around a design, and the
placeholder `canonical_chip_top_sentinel` publishes. MEASURED over every
published cell carrying a stage-4 die (10): 3 roots equal the intent's
`top_module`, 6 are the wrapper, 1 is neither. Requiring equality with the
intent alone would reject 5 of 10, four of them ordinary FLATTENED runs whose
design is correctly inside the wrapper. That is the difference between a
detector and one that fires on half its subjects, and
`test_dropping_the_wrapper_allowance_would_reject_half_the_corpus` measures it
rather than asserting it.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
PROG = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
FIX = Path(__file__).resolve().parent / "fixtures" / "stage4_on_pass_review"
PROVENANCE = json.loads((FIX / "PROVENANCE.json").read_text(encoding="utf-8"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _published_corpus as _pc  # noqa: E402
except Exception:  # pragma: no cover
    _pc = None

yaml = pytest.importorskip("yaml")


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def run(project, *extra, flow=None, emit=None, stage="stage4"):
    """Invoke the review exactly as the flow declares it.

    A rejection WRITES the run's own regression INTO the run tree, so every
    test that can provoke one runs against `tree()`, a per-test materialisation.
    Nothing here ever writes into the shipped fixture.
    """
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    argv = [sys.executable, str(PROG), str(project), "--stage", stage,
            "--flow-def", str(flow or FLOW)]
    if emit is not None:
        argv += ["--emit-test", str(emit)]
    return subprocess.run(argv + list(extra), capture_output=True, text=True,
                          env=env)


def tree(tmp_path, which):
    """A writable run tree materialised from PROVENANCE.json.

    The layouts are shipped gzipped (a sign-off die is ~0.8-1.6 MB); everything
    else is the published file as-is. `source` is decompressed to its published
    path — and `reject_hawaii_ldo` names ONE source at TWO published paths,
    because that byte-identity is the published fact the rejection cites.
    """
    d = tmp_path / which
    if d.exists():
        return d
    spec = PROVENANCE["trees"][which]
    for rel, entry in spec["files"].items():
        dest = d / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if "source" in entry:
            dest.write_bytes(gzip.decompress((FIX / entry["source"]).read_bytes()))
        else:
            dest.write_bytes((FIX / which / rel).read_bytes())
    return d


def declaration(flow=FLOW, stage="stage4"):
    doc = yaml.safe_load(Path(flow).read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == stage:
            return st.get("on_pass_review")
    raise AssertionError(f"{stage} is not declared")


def flow_with(tmp_path, **override):
    """A copy of the canonical flow with stage4's on_pass_review patched."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == "stage4":
            st["on_pass_review"] = {**st["on_pass_review"], **override}
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


def _rec(rtype: int, dtype: int, body: bytes = b"") -> bytes:
    return struct.pack(">HBB", len(body) + 4, rtype, dtype) + body


def _name(s: str) -> bytes:
    b = s.encode("ascii")
    return b + (b"\x00" if len(b) % 2 else b"")


def minimal_gds(cell: str) -> bytes:
    """A valid, minimal GDSII stream defining exactly one structure.

    THIS IS THE REPAIR STIMULUS, NOT A KNOWN-BAD. The defective artefact in
    this file is never authored — it is the published cell's own bytes. What is
    authored here is the REPAIRED state, because a test that could not pass
    would block every repair it asks for, and no published cell can supply a
    die whose root is another cell's module.
    """
    return b"".join([
        _rec(0x00, 0x02, struct.pack(">h", 600)),          # HEADER
        _rec(0x01, 0x02, b"\x00" * 24),                    # BGNLIB
        _rec(0x02, 0x06, _name("REPAIR.DB")),              # LIBNAME
        _rec(0x03, 0x05, b"\x00" * 16),                    # UNITS
        _rec(0x05, 0x02, b"\x00" * 24),                    # BGNSTR
        _rec(0x06, 0x06, _name(cell)),                     # STRNAME
        _rec(0x07, 0x00),                                  # ENDSTR
        _rec(0x04, 0x00),                                  # ENDLIB
    ])


def emitted_path(run_dir: Path, report: Path) -> Path:
    rec = json.loads(report.read_text(encoding="utf-8"))
    assert len(rec["rejections"]) == 1, rec["rejections"]
    return run_dir / rec["rejections"][0]["test"]


# ─────────────────────────────────────────────────────────────────────────────
# the declaration is in the flow, and nowhere else
# ─────────────────────────────────────────────────────────────────────────────
def test_stage4_declares_an_on_pass_review_naming_a_verification_tier_skill():
    d = declaration()
    assert d is not None, "stage4 declares no on_pass_review"
    assert d["fires_on"] == "stage_pass"
    assert d["verdict"] in ("advisory", "blocking"), (
        "BLOCKING vs ADVISORY must be declared, and declared HERE — whether a "
        "rejection stops the flow is the flow's decision, not the reviewer's")
    tier = json.loads((PLUGIN / "skills" / "_classification.json")
                      .read_text(encoding="utf-8"))["tiers"]["verification"]["skills"]
    assert d["skill"] in tier, (
        f"{d['skill']!r} is not a member of the verification tier {tier}")
    assert (PLUGIN / "skills" / d["skill"] / "SKILL.md").is_file()


def test_the_four_required_parts_and_the_wrapper_are_declared_by_the_flow():
    d = declaration()
    assert d["rejection_requires"] == ["intent", "artefact", "contradiction", "test"]
    assert d["canonical_top_wrapper"], (
        "the accept set's second member must be DECLARED; a wrapper name only "
        "the program knows is a rule nobody can review")


def test_the_declaration_is_not_a_second_membership_roster():
    """`flow_stage_membership_single_declaration_check` P1 discovers a roster by
    SHAPE, not by key name: any stage key whose value is a list naming declared
    step ids is a second membership declaration."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    step_ids = {str(s["id"]) for s in doc["steps"]}
    for key, val in declaration().items():
        if isinstance(val, list):
            named = {str(v) for v in val} & step_ids
            assert not named, f"on_pass_review.{key} names step id(s) {named}"


def test_the_skill_is_placed_by_the_flow_and_not_declared_a_second_time():
    """P4 of `skill_stage_membership_check`: once the flow names a skill its
    stage is DERIVED, and a surviving `stage_axis` entry is the second premise
    that check exists to forbid. Wiring stage4 without this removal turned that
    program red — measured, before the removal."""
    cj = json.loads((PLUGIN / "skills" / "_classification.json")
                    .read_text(encoding="utf-8"))
    skill = declaration()["skill"]
    for bucket in ("stages", "stage_all", "off_flow"):
        assert skill not in (cj["stage_axis"].get(bucket) or {}), (
            f"{skill} is named by the flow AND declared under "
            f"stage_axis.{bucket}; one premise, one place")


# ─────────────────────────────────────────────────────────────────────────────
# the fixture is the published bytes
# ─────────────────────────────────────────────────────────────────────────────
def test_the_fixture_is_the_published_bytes_and_not_a_paraphrase(tmp_path):
    """Every file the review reads is re-hashed AFTER materialisation. Without
    this the docstring's word `verbatim` would be the entire guarantee — and a
    fixture quietly edited to make the rule bite would look exactly the same."""
    for which, spec in PROVENANCE["trees"].items():
        d = tree(tmp_path, which)
        for rel, entry in spec["files"].items():
            got = hashlib.sha256((d / rel).read_bytes()).hexdigest()
            assert got == entry["sha256"], f"{which}/{rel} is not the published file"
            assert (d / rel).stat().st_size == entry["bytes"]


def test_the_two_published_paths_of_the_known_bad_really_are_one_file(tmp_path):
    """The corroboration the rejection cites, asserted rather than quoted: in
    the published cell the die slot and the block deliverable carry the SAME
    bytes."""
    d = tree(tmp_path, "reject_hawaii_ldo")
    a = hashlib.sha256((d / "phase3/stage4/gds/ldo.gds").read_bytes()).hexdigest()
    b = hashlib.sha256(
        (d / "phase3/analog/hardmacro/ldo/ldo.gds").read_bytes()).hexdigest()
    assert a == b


# ─────────────────────────────────────────────────────────────────────────────
# BOTH DIRECTIONS, ON REAL ARTEFACTS
# ─────────────────────────────────────────────────────────────────────────────
def test_a_real_known_good_die_is_accepted(tmp_path):
    r = run(tree(tmp_path, "accept_spm_ihp"), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ACCEPT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == []
    assert rec["not_checked"] == []


def test_a_real_die_that_is_a_block_and_not_the_design_is_rejected(tmp_path):
    run_dir = tree(tmp_path, "reject_hawaii_ldo")
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REJECT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert len(rec["rejections"]) == 1
    f = rec["rejections"][0]
    assert f["rule"] == "R4_DIE_IS_NOT_THE_DESIGN"
    # the INTENT it read
    assert f["intent"]["field"] == "top_module"
    assert f["intent"]["value"] == "u_hawaii_adc"
    assert f["intent"]["no_top_module_in_input"] is False, (
        "this intent CLAIMS it read a top out of the design input; a finding "
        "against a disclosed placeholder would be a different argument")
    # the ARTEFACT fact it read
    assert f["artefact"]["top_cells"] == ["ldo"]
    assert f["artefact"]["structures_defined"] == 7
    assert f["artefact"]["intent_top_defined_anywhere_in_die"] is False
    assert f["artefact"]["canonical_top_wrapper"] == "chip_top"
    # the CONTRADICTION, and the corroboration
    assert "u_hawaii_adc" in f["contradiction"] and "ldo" in f["contradiction"]
    assert f["also_published_as"], "the byte-identical block deliverable was not found"
    assert f["also_published_as"][0]["block_deliverable"] == \
        "phase3/analog/hardmacro/ldo/ldo.gds"
    assert "byte-identical" in r.stdout
    # the TEST — a path that EXISTS, written by this run of the review
    assert f["test"], "the rejection carries no test"
    assert (run_dir / f["test"]).is_file(), f["test"]


def test_the_accept_control_does_not_move_when_the_reject_case_is_measured(tmp_path):
    """Both directions in ONE invocation shape. A rule that started refusing
    everything would take the accept case with it; a rule that stopped biting
    would take the reject case with it. Neither may move alone."""
    good = run(tree(tmp_path, "accept_spm_ihp"), "--stage-verdict", "PASS")
    bad = run(tree(tmp_path, "reject_hawaii_ldo"), "--stage-verdict", "PASS")
    assert (good.returncode, bad.returncode) == (0, 1), (
        f"good={good.returncode} bad={bad.returncode}\n"
        f"{good.stdout}\n---\n{bad.stdout}")


def test_the_rejection_is_caused_by_the_die_and_nothing_else(tmp_path):
    """The negative control for the rejection itself: the REAL reject tree,
    with the design's own die streamed into the slot beside the block. Same L9,
    same block deliverable, same cell — only the die slot gains what it was
    always supposed to hold. It must flip to ACCEPT, which is what proves the
    finding is about the artefact rather than about that cell."""
    before = run(tree(tmp_path, "reject_hawaii_ldo"), "--stage-verdict", "PASS")
    repaired = tree(tmp_path / "repaired", "reject_hawaii_ldo")
    (repaired / "phase3/stage4/gds/u_hawaii_adc.gds").write_bytes(
        minimal_gds("u_hawaii_adc"))
    after = run(repaired, "--stage-verdict", "PASS")
    assert before.returncode == 1
    assert after.returncode == 0, after.stdout + after.stderr


def test_a_die_rooted_in_the_flows_own_wrapper_is_accepted(tmp_path):
    """The second member of the accept set, driven directly. Four published
    cells ship exactly this shape — a design FLATTENED into the wrapper, whose
    own module name is nowhere in the layout — and calling that a contradiction
    is the over-firing this allowance exists to prevent."""
    d = tree(tmp_path, "reject_hawaii_ldo")
    (d / "phase3/stage4/gds/ldo.gds").unlink()
    (d / "phase3/stage4/gds/chip_top.gds").write_bytes(minimal_gds("chip_top"))
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_wrapper_allowance_is_read_from_the_declaration_not_hardcoded(tmp_path):
    """And it must be able to say no: declare a different wrapper and the same
    tree that just passed is refused. A test that only proved the acceptance
    would pass against a program that accepted every root."""
    d = tree(tmp_path, "reject_hawaii_ldo")
    (d / "phase3/stage4/gds/ldo.gds").unlink()
    (d / "phase3/stage4/gds/chip_top.gds").write_bytes(minimal_gds("chip_top"))
    other = flow_with(tmp_path, canonical_top_wrapper="not_the_wrapper")
    assert run(d, "--stage-verdict", "PASS", flow=other).returncode == 1
    assert run(d, "--stage-verdict", "PASS").returncode == 0


# ─────────────────────────────────────────────────────────────────────────────
# the emitted test is the thing that blocks, so it has to discriminate
# ─────────────────────────────────────────────────────────────────────────────
def test_the_emitted_test_fails_today_and_passes_when_the_run_is_repaired(tmp_path):
    """The doctrine, executable. `an AI rejection must be proven by a
    prompt-derived executable test before repair` is only wired if the test the
    rejection names actually discriminates. So: run the EMITTED file against
    the defective run (must fail), then stream the die its intent names and run
    THE SAME FILE again (must pass)."""
    run_dir = tree(tmp_path, "reject_hawaii_ldo")
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout
    emitted = emitted_path(run_dir, tmp_path / "r.json")

    before = subprocess.run([sys.executable, str(emitted)],
                            capture_output=True, text=True)
    assert before.returncode == 1, (
        "the emitted test does not fail on the artefact it was emitted from:\n"
        + before.stdout + before.stderr)
    assert "u_hawaii_adc" in before.stdout

    (run_dir / "phase3/stage4/gds/u_hawaii_adc.gds").write_bytes(
        minimal_gds("u_hawaii_adc"))
    after = subprocess.run([sys.executable, str(emitted)],
                           capture_output=True, text=True)
    assert after.returncode == 0, (
        "the emitted test still fails after the repair it asks for:\n"
        + after.stdout + after.stderr)


def test_the_emitted_test_refuses_an_absent_die_rather_than_passing(tmp_path):
    """The emitted test carries the same rule its emitter does: an absent
    artefact refutes nothing and certifies nothing. Deleting the layout must
    not be a way to make the run's own regression go green."""
    run_dir = tree(tmp_path, "reject_hawaii_ldo")
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    emitted = emitted_path(run_dir, tmp_path / "r.json")
    (run_dir / "phase3/stage4/gds/ldo.gds").unlink()
    out = subprocess.run([sys.executable, str(emitted)],
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert "holds no layout" in out.stdout


def test_the_emitted_test_is_a_pytest_module_too(tmp_path):
    """It is emitted into the RUN, where it is collected by whatever runs that
    run's regressions. `python3 <file>` and pytest must give the same answer."""
    run_dir = tree(tmp_path, "reject_hawaii_ldo")
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    emitted = emitted_path(run_dir, tmp_path / "r.json")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               PYTEST_ADDOPTS="-p no:pytest_ethereum")
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", str(emitted),
                          "--basetemp", str(tmp_path / "pt"), "-p", "no:cacheprovider"],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "1 failed" in out.stdout


# ─────────────────────────────────────────────────────────────────────────────
# an absent or unreadable die certifies nothing
# ─────────────────────────────────────────────────────────────────────────────
def test_an_empty_die_slot_is_not_an_acceptance(tmp_path):
    d = tree(tmp_path, "reject_hawaii_ldo")
    (d / "phase3/stage4/gds/ldo.gds").unlink()
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "published no layout" in r.stdout


def test_a_layout_with_no_structures_is_not_an_acceptance(tmp_path):
    """150 KB of bytes behind a GDSII header is the shape `gds_size_check`
    signed off as `pass: true`. It is NOT CHECKED here, never ACCEPT."""
    d = tree(tmp_path, "reject_hawaii_ldo")
    (d / "phase3/stage4/gds/ldo.gds").write_bytes(
        struct.pack(">HBB", 6, 0x00, 0x02) + struct.pack(">h", 600))
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "defines a single GDSII structure" in r.stdout


def test_an_intent_with_no_top_module_is_not_an_acceptance(tmp_path):
    d = tree(tmp_path, "reject_hawaii_ldo")
    l9 = d / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    doc = json.loads(l9.read_text())
    doc["top_module"] = None
    l9.write_text(json.dumps(doc))
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "declares no `top_module`" in r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# it fires on SUCCESS, and only on an ESTABLISHED success
# ─────────────────────────────────────────────────────────────────────────────
def test_the_review_does_not_run_on_a_stage_that_failed(tmp_path):
    r = run(tree(tmp_path, "reject_hawaii_ldo"), "--stage-verdict", "FAIL")
    assert r.returncode == 2, r.stdout
    assert "did not pass" in r.stdout


def test_an_unestablished_verdict_is_not_a_pass(tmp_path):
    r = run(tree(tmp_path, "reject_hawaii_ldo"))
    assert r.returncode == 2, r.stdout
    assert "unestablished" in r.stdout


def test_a_compliance_report_supplies_the_verdict(tmp_path):
    """And BOTH ways: a green stage-4 row reaches the rules, a red one does
    not. A test that only proved the refusal would pass against a program that
    refuses every compliance report it is given."""
    green = tmp_path / "green.json"
    green.write_text(json.dumps({"steps": [
        {"id": 37, "stage": "stage4", "status": "PASS"},
        {"id": 9, "stage": "stage2", "status": "FAIL"}]}))
    red = tmp_path / "red.json"
    red.write_text(json.dumps({"steps": [
        {"id": 37, "stage": "stage4", "status": "PASS"},
        {"id": 38, "stage": "stage4", "status": "FAIL"}]}))
    assert run(tree(tmp_path, "reject_hawaii_ldo"),
               "--compliance", str(green)).returncode == 1
    assert run(tree(tmp_path, "accept_spm_ihp"),
               "--compliance", str(green)).returncode == 0
    assert run(tree(tmp_path / "red", "reject_hawaii_ldo"),
               "--compliance", str(red)).returncode == 2


# ─────────────────────────────────────────────────────────────────────────────
# §4.05 — the reviewer reads the design INPUT
# ─────────────────────────────────────────────────────────────────────────────
def test_a_denied_intent_path_is_refused_rather_than_read(tmp_path):
    flow = flow_with(tmp_path, intent=[
        "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
        "benchmark/oracle/expected_ports.json"])
    r = run(tree(tmp_path, "reject_hawaii_ldo"), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 2, r.stdout
    assert "4.05" in r.stdout and "oracle" in r.stdout


def test_the_denial_is_a_list_not_a_hardcode_and_an_allowed_path_still_reads(tmp_path):
    """The control for the guard: same shape, a path carrying no denied
    segment, and the review reaches its rules and rejects as before."""
    flow = flow_with(tmp_path, intent=[
        "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
        "phase1/generated_docs/L2_FRS.json"])
    r = run(tree(tmp_path, "reject_hawaii_ldo"), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 1, r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# a rejection carries evidence or it is not a rejection
# ─────────────────────────────────────────────────────────────────────────────
def test_an_unproven_rejection_is_not_emitted_as_a_rejection(tmp_path):
    """Raise the evidence bar to something this finding does not carry. It must
    NOT come out as rc 1 with a missing part, and must NOT be quietly
    downgraded to a pass: it is NOT CHECKED, naming the missing part."""
    flow = flow_with(tmp_path, rejection_requires=[
        "intent", "artefact", "contradiction", "test", "waiver_reference"])
    r = run(tree(tmp_path, "reject_hawaii_ldo"), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"), flow=flow)
    assert r.returncode == 2, r.stdout
    assert "could not be proven" in r.stdout
    assert "waiver_reference" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == [], "an unproven finding was emitted anyway"
    assert rec["unproven_rejections"][0]["missing_evidence"] == ["waiver_reference"]


def test_a_stage_that_declares_no_review_is_not_checked(tmp_path):
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        st.pop("on_pass_review", None)
    p = tmp_path / "bare.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    r = run(tree(tmp_path, "reject_hawaii_ldo"), "--stage-verdict", "PASS", flow=p)
    assert r.returncode == 2, r.stdout
    assert "declares no" in r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# the live corpus: the whole partition, pinned
# ─────────────────────────────────────────────────────────────────────────────
#: MEASURED on benchmark-data, 2026-08-30, over every published run carrying a
#: stage-4 die (10). The single rejection is a verified true positive: its own
#: RESULT.md publishes `Verdict: PASS`, and its die is byte-identical to a block
#: deliverable in the same run.
_CORPUS_REJECTS = {"ic/u_hawaii_adc/v1.9.86_sky130A"}


def _corpus_runs(root):
    return sorted({p.parents[2] for p in root.rglob("phase3/stage4/gds")
                   if p.is_dir() and (p.parents[2] / "phase1" / "generated_docs"
                                      / "L9_INTEGRATION_SPEC.json").is_file()})


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_the_partition_over_the_published_corpus_does_not_move():
    """Pins BOTH sides on the live corpus. The reject set is named run by run
    so a rule that widened shows up as an extra NAME rather than as a count
    nobody reads; the accept side is required to be non-empty so a rule that
    stopped biting cannot pass by rejecting everything."""
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    runs = _corpus_runs(root)
    if not runs:
        pytest.skip("the corpus publishes no stage-4 die")
    scratch = Path(tempfile.mkdtemp(prefix="on_pass_stage4_"))
    rejects, accepts, other = set(), set(), {}
    for i, cell in enumerate(runs):
        rc = run(cell, "--stage-verdict", "PASS", emit=scratch / f"c{i}").returncode
        rel = str(cell.relative_to(root))
        if rc == 1:
            rejects.add(rel)
        elif rc == 0:
            accepts.add(rel)
        else:
            other[rel] = rc
    assert rejects == _CORPUS_REJECTS & {str(c.relative_to(root)) for c in runs}, (
        f"the rejection set moved: {sorted(rejects)}")
    assert accepts, "every run was refused; a reviewer that rejects all is none"
    assert not other, f"runs the review could not put the question to: {other}"


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_dropping_the_wrapper_allowance_would_reject_half_the_corpus():
    """WHY THE ACCEPT SET HAS TWO MEMBERS, measured instead of asserted. With
    the wrapper allowance declared away, the same rule over the same runs goes
    from 1 rejection to 5 — four of them ordinary flattened runs. This is the
    stage-1 lesson in its own terms: a disarm that is narrowed on evidence is
    the difference between a detector and one that fires on half its subjects."""
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    runs = _corpus_runs(root)
    if len(runs) < 4:
        pytest.skip(f"only {len(runs)} published stage-4 die(s); the comparison "
                    f"is about a population")
    scratch = Path(tempfile.mkdtemp(prefix="on_pass_stage4_wrapper_"))
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == "stage4":
            # A name no GDSII structure can carry: the allowance is present and
            # can never match, which is exactly "declared away".
            st["on_pass_review"]["canonical_top_wrapper"] = "\x00 not a cell name"
    narrow = scratch / "narrow.yaml"
    narrow.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")

    def rejects(flow):
        return {str(c.relative_to(root)) for i, c in enumerate(runs)
                if run(c, "--stage-verdict", "PASS", flow=flow,
                       emit=scratch / f"{flow.name}_{i}").returncode == 1}

    with_wrapper = rejects(FLOW)
    without = rejects(narrow)
    assert with_wrapper < without, (
        "removing the wrapper allowance changed nothing, so the allowance is "
        "untested by this corpus and the two-member accept set is unjustified")
    assert len(without) >= 4 * len(with_wrapper), (
        f"measured {len(with_wrapper)} -> {len(without)}: the allowance is "
        f"what keeps this a detector rather than a rule that fires on half "
        f"its subjects")
