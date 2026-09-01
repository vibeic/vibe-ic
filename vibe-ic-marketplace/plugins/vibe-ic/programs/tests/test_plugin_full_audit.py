"""Tests for plugin_full_audit (deterministic D1 + D2 of the have-full-test audit).

Pins: D1 flags an untested non-synth program but NOT an overlay-covered synth;
D2 flags a file-presence-only gate WITHOUT a by-design note but NOT one WITH it,
and flags a dangling program_exit_zero target.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plugin_full_audit as A  # noqa: E402


def _mk_plugin(tmp_path, programs, tests, flow_yaml=None):
    plug = tmp_path / "plug"
    (plug / "programs" / "tests").mkdir(parents=True)
    (plug / "flow").mkdir(parents=True)
    for name, body in programs.items():
        (plug / "programs" / f"{name}.py").write_text(body or "x = 1\n")
    for name, body in tests.items():
        (plug / "programs" / "tests" / f"{name}.py").write_text(body or "")
    (plug / "flow" / "phase1_phase2_phase3.yaml").write_text(
        flow_yaml if flow_yaml is not None else "steps: []\n")
    return plug


# ---- D1 ----
def test_d1_untested_nonsynth_is_a_gap(tmp_path):
    plug = _mk_plugin(tmp_path, {"foo_check": None}, {})  # no test for foo_check
    d1 = A.audit_d1(plug)
    assert d1["passed"] is False
    assert "foo_check" in d1["untested_gaps"]


def test_d1_tested_program_passes(tmp_path):
    plug = _mk_plugin(tmp_path, {"foo_check": None},
                      {"test_foo_check": "import foo_check\n"})
    d1 = A.audit_d1(plug)
    assert d1["passed"] is True
    assert d1["untested_gaps"] == []


def test_d1_synth_without_test_is_overlay_covered_not_gap(tmp_path):
    plug = _mk_plugin(tmp_path, {"zigbee_protocol_synth": None}, {})
    d1 = A.audit_d1(plug)
    assert d1["passed"] is True
    assert "zigbee_protocol_synth" in d1["synth_overlay_covered"]
    assert d1["untested_gaps"] == []


# ---- D2 ----
_FLOW_PRESENCE_ONLY = """\
steps:
  - id: 1
    name: "Bare presence gate"
    gate:
      files_exist: ["out/x.def"]
"""

_FLOW_PRESENCE_BY_DESIGN = """\
steps:
  - id: 1
    name: "Documented presence gate"
    # AUDIT NOTE (by-design, not a gap): substance verified downstream.
    gate:
      files_exist: ["out/x.def"]
"""

_FLOW_DANGLING = """\
steps:
  - id: 1
    name: "Dangling checker"
    gate:
      program_exit_zero: "does_not_exist_check . --json r.json"
"""


def test_d2_presence_only_without_note_is_gap(tmp_path):
    plug = _mk_plugin(tmp_path, {}, {}, flow_yaml=_FLOW_PRESENCE_ONLY)
    d2 = A.audit_d2(plug)
    assert d2["passed"] is False
    assert any(f["check"] == "file_presence_only_gate" for f in d2["findings"])


def test_d2_presence_only_with_by_design_note_passes(tmp_path):
    plug = _mk_plugin(tmp_path, {}, {}, flow_yaml=_FLOW_PRESENCE_BY_DESIGN)
    d2 = A.audit_d2(plug)
    assert not any(f["check"] == "file_presence_only_gate" for f in d2["findings"])


def test_d2_dangling_gate_target_is_gap(tmp_path):
    plug = _mk_plugin(tmp_path, {}, {}, flow_yaml=_FLOW_DANGLING)
    d2 = A.audit_d2(plug)
    assert any(f["check"] == "dangling_gate_target" for f in d2["findings"])


# ---- canonical: the shipped plugin passes D1 (no non-synth untested) + D2 ----
def test_shipped_plugin_d1_clean():
    plugin = Path(__file__).resolve().parent.parent.parent
    d1 = A.audit_d1(plugin)
    assert d1["passed"], d1["untested_gaps"]


def test_shipped_plugin_d2_clean():
    plugin = Path(__file__).resolve().parent.parent.parent
    d2 = A.audit_d2(plugin)
    assert d2["passed"], d2["findings"]


# ── vibe-ic#1208: the one-pass word index must answer the SAME question ──────
#
# `audit_d1` used to re-scan a 23.5 MB concatenation of every test file with up
# to three regexes PER PROGRAM. `\b<s>\b` asks exactly "is s a maximal run of
# word characters in the blob", so that population is now collected in one pass
# and answered by set membership. These pin the two places where the set is NOT
# a drop-in for the regex, because those are the only ways the speedup could
# have changed a verdict.


def test_d1_a_name_matched_only_as_a_dot_py_suffix_is_still_referenced(tmp_path):
    """`{s}\\.py\\b` has NO leading boundary, so it matches INSIDE a longer word.

    `foo_check` appears in the blob only as `myfoo_check.py`. The word form
    `\\bfoo_check\\b` does NOT match there (it is preceded by `y`), and the word
    INDEX does not contain it either — the only maximal runs are `myfoo_check`
    and `py`. So this program is referenced solely through the `.py` pattern,
    and it is why that pattern is kept as a separate search rather than folded
    into the index. Fold it in and this test goes red.
    """
    plug = _mk_plugin(tmp_path, {"foo_check": None},
                      {"test_other": "path = 'tools/myfoo_check.py'\n"})
    d1 = A.audit_d1(plug)
    assert d1["untested_gaps"] == [], d1
    assert d1["passed"] is True


def test_d1_a_stem_with_a_non_word_character_falls_back_to_the_search(tmp_path):
    """The index equivalence holds only for word-characters-only names.

    A stem like `foo-bar` is not a single `\\w+` run, so `'foo-bar' in words` is
    FALSE however often the name appears — the index splits it into `foo` and
    `bar`. Answering from the index there would report a referenced program as
    an untested gap. The guarded fall-back to the original search is what keeps
    it exact; remove the guard and this test goes red.

    Measured on the shipped tree when this landed: 0 of 1138 stems contain a
    non-word character, so this case is latent — which is precisely why it
    needs a test rather than an assumption.
    """
    plug = _mk_plugin(tmp_path, {"foo-bar": None},
                      {"test_other": "# exercises foo-bar directly\n"})
    d1 = A.audit_d1(plug)
    assert d1["untested_gaps"] == [], d1


def test_d1_a_name_that_appears_nowhere_is_still_a_gap(tmp_path):
    """PAIRED GUARD: the fast path must not turn every program green.

    A one-pass index that answered YES too readily would empty
    `untested_gaps` and the whole dimension would stop measuring anything.
    `lonely_check` appears in no test file in any form.
    """
    plug = _mk_plugin(tmp_path, {"lonely_check": None},
                      {"test_other": "import something_else\n"})
    d1 = A.audit_d1(plug)
    assert d1["untested_gaps"] == ["lonely_check"], d1
    assert d1["passed"] is False


def test_d1_a_substring_of_a_longer_word_is_NOT_a_reference(tmp_path):
    """The index must preserve the WORD boundary, not degrade to `in`.

    `foo` occurs inside `foobar_check` and inside `myfoo`, and in neither place
    is it a reference. A `s in test_blob` shortcut — the obvious cheap fix, and
    the one I measured first — would call this referenced and silently drop a
    real gap.
    """
    plug = _mk_plugin(tmp_path, {"foo": None},
                      {"test_other": "import foobar_check\nx = 'myfoo'\n"})
    d1 = A.audit_d1(plug)
    assert d1["untested_gaps"] == ["foo"], d1
