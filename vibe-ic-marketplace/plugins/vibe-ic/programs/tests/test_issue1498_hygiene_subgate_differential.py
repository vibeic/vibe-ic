"""vibe-ic#1498 — the hygiene tier is subtracted GATE BY GATE, not as one word.

THE DEFECT
==========
`gatekeeper-land.sh` printed ONE line for every repo-hygiene gate:

    FAIL  repo hygiene gates

`landing_merge_verdict.decide` refuses a candidate's failing gate labels that do
not appear in the base's. With one label for the tier that subtraction cannot
discriminate, so the moment the tier was red on the base — as it was for six
rebuilt batches over 135 PRs — a candidate could introduce ANY hygiene finding
and the difference stayed empty.

:func:`test_the_umbrella_label_waives_a_new_hygiene_finding` is the defect,
asserted rather than described: it drives the REAL `decide` with the REAL
`parse_land_log` over the log shape the script used to emit, and asserts it
LANDS. It is the red arm, kept green forever so the repair cannot be undone by
reverting the emitter and leaving the tests passing.

Every other test here drives the same `decide` over the log shape the script
emits NOW, and they are the reason the repair is not a leniency: an inherited
finding is excused BY NAME, a new one refuses BY NAME, and a base-red gate the
candidate stops asking refuses too.

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_ROOT = _PROGRAMS.parents[3]
sys.path.insert(0, str(_PROGRAMS))

import landing_merge_verdict as L  # noqa: E402

PREFIX = L._HYGIENE_SUBGATE_PREFIX
_HOST_DEP = "gates are host-independent"
_JSON_YAML = "tracked JSON/YAML parses"

# Every subprocess here is bounded well under the 180 s pytest-timeout the
# landing harness runs with, so a hang fails THIS test instead of the session.
_BOUND_S = 30


def _land_log(*, hygiene_umbrella, subgates=None):
    """A gatekeeper-land.sh log, in the shape the script printf's.

    `printf '  PASS  %s\\n'` / `printf '  FAIL  %s\\n'` — two spaces, the word,
    two spaces, the label. `subgates` is None for the pre-#1498 shape (the tier
    reported as one word) and a {label: word} map for the shape it emits now.
    """
    lines = ["=== gatekeeper landing gates — base=origin/main ===",
             "  PASS  marketplace <-> plugin version sync",
             "  PASS  targeted tests (12 file(s))",
             f"  {hygiene_umbrella}  repo hygiene gates"]
    for label, word in (subgates or {}).items():
        lines.append(f"  {word}  {PREFIX}{label}")
    lines.append("  PASS  plugin full audit")
    return "\n".join(lines) + "\n"


def _decide(base_text, cand_text):
    """`decide` with every tier but the gate differential held neutral."""
    return L.decide(
        rebase_status="ok", expected_tree="t" * 40, verified_tree="t" * 40,
        github_tree=None, land=L.parse_land_log(cand_text),
        delta=L.Delta(base_total=40, candidate_total=40),
        verified_sha="c" * 40, truncated=False, dropped_files=[],
        selection_size=3, replayed_tree="t" * 40,
        base_land=L.parse_land_log(base_text),
        verification_tier=L.TIER_MERGE_TREE)


def _refusals_about(v, needle):
    return [r for r in v.reasons if needle in r]


# --------------------------------------------------------------- the defect

def test_the_umbrella_label_waives_a_new_hygiene_finding():
    """THE RED ARM. One label for the whole tier, and a new finding lands.

    Both arms are red on the tier. The base is red because of one sub-gate; the
    candidate is red because of that one AND a second it introduced. Reported
    as one word, the two logs are identical and the difference is empty.
    """
    base = _land_log(hygiene_umbrella="FAIL")
    cand = _land_log(hygiene_umbrella="FAIL")
    v = _decide(base, cand)
    assert v.ok, ("this is the #1498 defect; if it now refuses, the umbrella "
                  "label alone has become discriminating and this test should "
                  "be re-derived rather than deleted")
    assert any("not this branch's" in n for n in v.notes)


# ------------------------------------------- the repair, in both directions

def test_a_new_hygiene_sub_gate_failure_refuses_the_landing():
    """GREEN ARM. Same two trees, published gate by gate: the landing refuses."""
    base = _land_log(hygiene_umbrella="FAIL",
                     subgates={_HOST_DEP: "FAIL", _JSON_YAML: "PASS"})
    cand = _land_log(hygiene_umbrella="FAIL",
                     subgates={_HOST_DEP: "FAIL", _JSON_YAML: "FAIL"})
    v = _decide(base, cand)
    assert not v.ok
    named = _refusals_about(v, _JSON_YAML)
    assert named, f"the new sub-gate is not named in {v.reasons}"
    assert "PASSED ON THE BASE" in named[0]
    # and the INHERITED one is still excused, by name — the whole point of a
    # differential is that it does not refuse what the base carries.
    assert not _refusals_about(v, _HOST_DEP)
    assert any(_HOST_DEP in n and "not this branch's" in n for n in v.notes)


def test_an_inherited_hygiene_finding_alone_still_lands():
    """The other direction: the tier is red on both arms for the SAME gate."""
    sub = {_HOST_DEP: "FAIL", _JSON_YAML: "PASS"}
    v = _decide(_land_log(hygiene_umbrella="FAIL", subgates=sub),
                _land_log(hygiene_umbrella="FAIL", subgates=dict(sub)))
    assert v.ok, v.reasons
    assert any(_HOST_DEP in n and "not this branch's" in n for n in v.notes)


def test_repairing_a_sub_gate_is_reported_as_a_fix_not_a_failure():
    v = _decide(_land_log(hygiene_umbrella="FAIL", subgates={_HOST_DEP: "FAIL"}),
                _land_log(hygiene_umbrella="PASS", subgates={_HOST_DEP: "PASS"}))
    assert v.ok, v.reasons
    assert any(_HOST_DEP in n and "now passes" in n for n in v.notes)


def test_a_base_red_sub_gate_that_merely_refuses_here_is_not_a_repair():
    """rc 2 must not launder rc 1: NOT_CHECKED reaches the log as SKIP."""
    v = _decide(_land_log(hygiene_umbrella="FAIL", subgates={_HOST_DEP: "FAIL"}),
                _land_log(hygiene_umbrella="PASS", subgates={_HOST_DEP: "SKIP"}))
    assert not v.ok
    assert _refusals_about(v, "SILENCED RATHER THAN FIXED")


def test_a_candidate_that_publishes_no_sub_gates_against_a_base_that_does():
    """The unreadable-record path, and any other way of publishing nothing.

    `hygiene_land_lines` prints NO lines when it cannot read the record. Against
    a base that published its roster, every base-red sub-gate is missing — the
    existing silencing clause refuses, with no cooperation from the emitter.
    """
    v = _decide(_land_log(hygiene_umbrella="FAIL", subgates={_HOST_DEP: "FAIL"}),
                _land_log(hygiene_umbrella="FAIL"))
    assert not v.ok
    assert _refusals_about(v, "SILENCED RATHER THAN FIXED")


# --------------------------------------------------- the one degraded case

def test_a_base_arm_predating_the_publication_degrades_and_says_so():
    """Arm A2 runs the BASE tree's land.sh, and may reuse a cached log.

    A base that names only the umbrella cannot be subtracted from a candidate
    that names each one — every candidate sub-gate would read as new. The
    comparison
    falls back to the umbrella for that tier and DISCLOSES it; the switch is
    read off the base arm, which a branch cannot edit into existence.
    """
    v = _decide(_land_log(hygiene_umbrella="FAIL"),
                _land_log(hygiene_umbrella="FAIL",
                          subgates={_HOST_DEP: "FAIL", _JSON_YAML: "FAIL"}))
    assert v.ok, v.reasons
    assert "HYGIENE_SUBGATE_COMPARISON_UNAVAILABLE" in v.disclosures
    assert any("degraded to the umbrella" in n for n in v.notes)


def test_the_degradation_is_not_reachable_from_the_candidate_side():
    """A branch cannot buy it by publishing sub-gates the base also publishes."""
    v = _decide(_land_log(hygiene_umbrella="FAIL", subgates={_HOST_DEP: "FAIL"}),
                _land_log(hygiene_umbrella="FAIL",
                          subgates={_HOST_DEP: "FAIL", _JSON_YAML: "FAIL"}))
    assert "HYGIENE_SUBGATE_COMPARISON_UNAVAILABLE" not in v.disclosures
    assert not v.ok
    assert _refusals_about(v, _JSON_YAML)


# ------------------------------------------- the two programs agree on shape

def test_the_emitted_lines_are_the_lines_the_verdict_parses():
    """Drive the REAL emitter and feed its stdout to the REAL parser.

    A fixture that only LOOKS like the emitter's output would let the two drift
    the day either changes its spacing, which is the whole failure mode
    `_LAND_LINE` is exposed to.
    """
    import json
    import tempfile
    rec = {"listed_only": False, "declared": 3, "gates": [
        {"label": "chip-AGNOSTIC source guard", "state": "PASS", "seconds": 6},
        {"label": _HOST_DEP, "state": "FAIL", "seconds": 225},
        {"label": "macro OBS not crossed (cell)", "state": "NOT_CHECKED",
         "seconds": 0}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(rec, fh)
        path = fh.name
    try:
        out = subprocess.run(
            [sys.executable, str(_ROOT / "tools/ci/hygiene_land_lines.py"),
             path], capture_output=True, text=True, timeout=_BOUND_S)
    finally:
        Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    log = L.parse_land_log(
        "=== gatekeeper landing gates — base=origin/main ===\n" + out.stdout)
    assert log.passed == [PREFIX + "chip-AGNOSTIC source guard"]
    assert log.failed == [PREFIX + _HOST_DEP]
    assert log.skipped == [PREFIX + "macro OBS not crossed (cell)"]


@pytest.mark.parametrize("record,why", [
    ({"listed_only": True, "declared": 2, "gates": [
        {"label": "a", "state": "LISTED", "seconds": 0},
        {"label": "b", "state": "LISTED", "seconds": 0}]}, "a --list roster"),
    ({"listed_only": False, "declared": 0, "gates": []}, "nothing declared"),
    ({"listed_only": False, "declared": 3, "gates": [
        {"label": "a", "state": "PASS", "seconds": 0}]}, "declared != carried"),
    ({"listed_only": False, "declared": 2, "gates": [
        {"label": "a", "state": "PASS", "seconds": 0},
        {"label": "a", "state": "FAIL", "seconds": 0}]}, "one label twice"),
    ({"listed_only": False, "declared": 1, "gates": [
        {"label": "a", "state": "NEW_STATE", "seconds": 0}]}, "unknown state"),
])
def test_a_record_that_cannot_be_graded_publishes_nothing(tmp_path, record, why):
    """An empty result is not a zero: every refusal prints NO verdict line."""
    import json
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(_ROOT / "tools/ci/hygiene_land_lines.py"),
         str(path)], capture_output=True, text=True, timeout=_BOUND_S)
    assert out.returncode == 2, f"{why}: rc={out.returncode}"
    assert out.stdout.strip() == "", f"{why}: it published {out.stdout!r}"
    assert "NOT CHECKED" in out.stderr
