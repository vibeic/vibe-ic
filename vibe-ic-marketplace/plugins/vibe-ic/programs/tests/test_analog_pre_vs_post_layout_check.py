#!/usr/bin/env python3
"""Tests for analog_pre_vs_post_layout_check.py — pre/post-layout comparison gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_pre_vs_post_layout_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _run_console(tmp_path: Path) -> subprocess.CompletedProcess:
    """WITHOUT `--json` — the human path, which is the only one that prints the
    verdict WORD the tier travels on."""
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


#: What the corner artefact this comparison is measured against says its
#: circuit contains. Both PASS fixtures below now carry it, because this gate
#: stopped certifying the post-layout step when nothing on the tree names the
#: circuit that was compared — and a fixture that omitted it would be
#: asserting that silence still certifies.
DESIGN_BOUND = "structure_and_geometry"


def _corner(block_dir: Path, design_content=DESIGN_BOUND) -> None:
    """The pre-layout baseline `pre_vs_post.json` is a comparison AGAINST.
    `design_content=None` builds the pre-disclosure shape: the field simply
    absent, which is what a stale artefact looks like."""
    doc = {"block": block_dir.name, "_provenance": "real_ngspice",
           "corners": [{"name": "tt_27c_1v8", "simulator_run": True}]}
    if design_content is not None:
        doc["design_content"] = design_content
    (block_dir / "corner_results.json").write_text(json.dumps(doc))


def test_skip_no_analog_dir(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_dir"


def test_skip_no_pre_vs_post(tmp_path):
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True)
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_pre_vs_post_data"


def test_pass_acceptable_degradation(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    _corner(ad)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "comparisons": [
            {"name": "vout", "pre_layout": 3.30, "post_layout": 3.25},
            {"name": "iq", "pre_layout": 50e-6, "post_layout": 52e-6},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["specs_compared"] == 2
    assert rpt["summary"]["design_bound_blocks"] == ["ldo"]
    assert rpt["summary"]["verdict_tier"] == "PASS"


def test_fail_severe_degradation(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "comparisons": [
            {"name": "vout", "pre_layout": 3.30, "post_layout": 2.0},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("LAYOUT_SEVERE_DEGRADATION" in f["rule"] for f in errors)


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# ── the gate and the skill that feeds it must agree on the schema ─────────
# `skills/analog-extraction-resim/SKILL.md` is the instruction an authoring
# agent follows to produce pre_vs_post.json. Its example used the container
# key "comparison" (singular); this gate has only ever read "comparisons" or
# "specs". Measured: a file built EXACTLY from the documented example was
# scored as zero comparable specs and FAILed PRE_VS_POST_ZERO_COMPARED — a
# correct result rejected for following its own instructions.

SKILL_MD = (Path(__file__).resolve().parents[2]
            / "skills" / "analog-extraction-resim" / "SKILL.md")


def _documented_pre_vs_post_example() -> dict:
    """The first ```json block in SKILL.md's `pre_vs_post.json` section."""
    text = SKILL_MD.read_text(encoding="utf-8")
    marker = "### `analog/<block>/pre_vs_post.json`"
    assert marker in text, f"SKILL.md lost its pre_vs_post.json section"
    tail = text.split(marker, 1)[1]
    assert "```json" in tail, "SKILL.md documents no JSON example"
    body = tail.split("```json", 1)[1].split("```", 1)[0]
    return json.loads(body)


def test_documented_schema_is_the_schema_the_gate_parses(tmp_path):
    """THE discriminator. Write the skill's own documented example verbatim and
    require the gate to actually COMPARE its metrics. The example carries a
    deliberate 33% regression, so the verdict is FAIL — but it must be a FAIL
    ABOUT THE CIRCUIT, never 'zero specs compared'."""
    example = _documented_pre_vs_post_example()
    ad = tmp_path / "phase3" / "analog" / "ldo_1v8"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps(example))
    _run(tmp_path)
    rpt = _load_report(tmp_path)
    rules = {f["rule"] for f in rpt["findings"]}
    assert "PRE_VS_POST_ZERO_COMPARED" not in rules, (
        "the documented example parses as zero comparisons — SKILL.md and "
        f"analog_pre_vs_post_layout_check have drifted apart: {rpt}")
    assert rpt["summary"]["specs_compared"] == 3, rpt["summary"]


def test_documented_example_still_flags_its_severe_regression(tmp_path):
    """The non-weakening half of the same discriminator (it too fails against
    the pre-fix doc, because nothing was parsed there to judge): making the
    documented schema READABLE must not make it PASS. The example's ugb_mhz
    drops 33%, which is an ERROR band, so the verdict stays rc=1."""
    example = _documented_pre_vs_post_example()
    ad = tmp_path / "phase3" / "analog" / "ldo_1v8"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps(example))
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = {f["rule"] for f in _load_report(tmp_path)["findings"]}
    assert "LAYOUT_SEVERE_DEGRADATION" in rules


def test_guard_specs_container_and_pre_layout_keys_still_read(tmp_path):
    """Direction-1 guard: the alternative spellings the gate has always
    accepted (`specs` container, `pre_layout`/`post_layout` values) keep
    working — the doc fix must not have narrowed the parser."""
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    _corner(ad)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "specs": [{"name": "vout", "pre_layout": 3.30, "post_layout": 3.25}]
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert _load_report(tmp_path)["summary"]["specs_compared"] == 1


# ── the step's DECLARED gate answers the same question as the step gate ────
# `flow/phase1_phase2_phase3.yaml` declares THIS program for the post-layout
# step; `analog_a7_post_layout_resim_check` — which the A-track runner runs
# over the same artefact — appears nowhere in that YAML. Measured, before
# these three: this gate returned rc 0 with a byte-identical console and a
# byte-identical `--json` on a design-bound tree, a disclosed-library-default
# tree and a silent one, while the step gate read PASS /
# PASS_STRUCTURE_ONLY / FAIL. The cross-gate agreement lives in
# `test_two_gates_over_one_artefact_cannot_disagree`; these are this gate's
# own three answers.

def test_a_comparison_that_names_no_circuit_does_not_certify(tmp_path):
    """Everything a value rule could catch is clean — 1.5 % drift, well inside
    the floor — so the only thing this can fail on is the certification."""
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    _corner(ad, design_content=None)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "comparisons": [{"name": "vout", "pre_layout": 3.30,
                         "post_layout": 3.25}]}))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    rpt = _load_report(tmp_path)
    assert "PRE_VS_POST_DESIGN_CONTENT_UNDECLARED" in {
        f["rule"] for f in rpt["findings"]}
    assert rpt["summary"]["undisclosed_blocks"] == ["ldo"]


def test_a_disclosed_library_default_still_certifies_in_its_own_tier(
        tmp_path):
    """Only silence costs. A comparison whose baseline records a library
    default still certifies — in the structure-only tier, never as a
    design-bound pass — because failing an honest ceiling teaches the next run
    to stop being honest.

    Asserted through the VERDICT WORD and the exit code, not a JSON key: the
    tier has to reach the one line a reader reads.
    """
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    _corner(ad, design_content="structure_only")
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "comparisons": [{"name": "vout", "pre_layout": 3.30,
                         "post_layout": 3.25}]}))
    r = _run_console(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS_STRUCTURE_ONLY]" in r.stdout, r.stdout
    assert "STRUCTURE_ONLY:" in r.stderr, r.stderr


def test_the_disclosure_is_emitted_on_the_json_path_the_flow_uses(tmp_path):
    """The flow runs this gate as `... --json reports/phase2/gates/
    pre_vs_post.json`, which suppresses the console verdict entirely. A
    disclosure printed only on the console path is one the flow auditor never
    sees."""
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    _corner(ad, design_content="structure_only")
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "comparisons": [{"name": "vout", "pre_layout": 3.30,
                         "post_layout": 3.25}]}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert any(l.lstrip().startswith("STRUCTURE_ONLY:")
               for l in (r.stdout + r.stderr).splitlines()), (
        r.stdout + r.stderr)


def test_unrecognised_container_key_names_the_schema_drift(tmp_path):
    """A gate that measured nothing must say WHY. The zero-compared finding
    now names the keys it looked for and the keys the file actually had, so a
    schema drift is diagnosable instead of reading as 'the sim produced no
    data'."""
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "block_name": "ldo",
        "comparison": {"gain_db": {"pre": 62.3, "post": 58.1}},
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    zero = [f for f in _load_report(tmp_path)["findings"]
            if f["rule"] == "PRE_VS_POST_ZERO_COMPARED"]
    assert zero, "an uncomparable file must still FAIL"
    msg = zero[0]["message"]
    assert "comparison" in msg and "comparisons" in msg, msg


def test_guard_genuinely_empty_comparison_set_still_fails(tmp_path):
    """Direction-1 guard: a file using the RIGHT key with nothing in it stays
    a FAIL. A comparison gate must never PASS having compared nothing."""
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps({"comparisons": []}))
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = {f["rule"] for f in _load_report(tmp_path)["findings"]}
    assert "PRE_VS_POST_ZERO_COMPARED" in rules


# ---------------------------------------------------------------------------
# D9 — SELF-CONSISTENCY. The gate read `pre`/`post` and never read the `delta`
# stated beside them, so every number in the artefact could move and the
# verdict stayed PASS. These are the content mutants for that criterion.
# ---------------------------------------------------------------------------

def _pvp(tmp_path: Path, specs: list) -> Path:
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True, exist_ok=True)
    _corner(ad)
    (ad / "pre_vs_post.json").write_text(json.dumps({"specs": specs}))
    return ad


def test_a_delta_that_agrees_with_its_own_pair_PASSES(tmp_path):
    """THE POSITIVE ARM, and it comes first.

    Without it this rule is only shown to be able to refuse, and a rule that
    refuses every artefact is a ban rather than a check.
    """
    _pvp(tmp_path, [{"name": "vout", "pre_value": 1.2069,
                     "post_value": 1.20781, "delta_pct": 0.0754}])
    assert _run(tmp_path).returncode == 0


def test_a_delta_that_does_NOT_describe_its_own_pair_is_an_ERROR(tmp_path):
    """THE CONTENT MUTANT. `pre` and `post` untouched; only the stated delta
    moves. A gate that never read the delta cannot see this."""
    _pvp(tmp_path, [{"name": "vout", "pre_value": 1.2069,
                     "post_value": 1.20781, "delta_pct": 42.0}])
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    rpt = _load_report(tmp_path)
    rules = [f["rule"] for f in rpt["findings"]]
    assert "PRE_VS_POST_DELTA_INCONSISTENT" in rules, rules


def test_scaling_EVERY_number_is_caught_even_though_each_stays_plausible(tmp_path):
    """The census's own generic corruption, as a permanent test.

    Every value is scaled by the same rule, so each number remains individually
    plausible and only the RELATION between them breaks. This is the mutation
    that scored step A7 EXISTENCE-ONLY before the criterion existed.
    """
    scale = lambda x: -(x * 3 + 7)
    _pvp(tmp_path, [{"name": "vout", "pre_value": scale(1.2069),
                     "post_value": scale(1.20781), "delta_pct": scale(0.0754)}])
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PRE_VS_POST_DELTA_INCONSISTENT" in [
        f["rule"] for f in _load_report(tmp_path)["findings"]]


def test_an_artefact_that_states_NO_delta_is_untouched(tmp_path):
    """The rule may only read what the document offers.

    Demanding a `delta_pct` that was never part of the schema would fail every
    artefact written before it, which is a new requirement wearing a
    consistency check's clothes.
    """
    _pvp(tmp_path, [{"name": "vout", "pre_value": 3.30, "post_value": 3.25}])
    assert _run(tmp_path).returncode == 0


def test_rounding_is_not_an_inconsistency(tmp_path):
    """The tolerance is wide on purpose: this rule catches a delta that does
    not describe its pair at all, never a rounded one."""
    _pvp(tmp_path, [{"name": "vout", "pre_value": 1.2069,
                     "post_value": 1.20781, "delta_pct": 0.08}])
    assert _run(tmp_path).returncode == 0
