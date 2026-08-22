"""Unit tests for `crosslayer_search_space.py`.

Each test below corresponds to a way the search space could quietly authorise
a lever nobody authorised. The two `test_measured_*` cases are the two rules I
got WRONG first and fixed from a measurement, and they are pinned here so the
next author cannot lose them by simplifying the classifier.
"""
import importlib
import json

mod = importlib.import_module("crosslayer_search_space")


class TestClassifyLine:
    def test_freedom_sentence_frees_the_named_lever_only(self):
        got = mod.classify_line("- ❌ 不指定 FSM state 數量或編碼")
        assert got["state_encoding"]["status"] == mod.STATUS_FREE
        assert "pipelining" not in got

    def test_english_freedom_sentence(self):
        got = mod.classify_line(
            "The pipeline depth is not specified and is left to the "
            "implementation.")
        assert got["pipelining"]["status"] == mod.STATUS_FREE

    def test_a_marker_with_no_lever_word_authorises_nothing(self):
        # The single most dangerous false positive: a blanket "the plugin may
        # choose" sentence must not free every lever in the design at once.
        assert mod.classify_line("實作細節由 Plugin 自選。") == {}

    def test_a_lever_word_with_no_marker_says_nothing(self):
        assert mod.classify_line("The pipeline has three stages of logic.") == {}

    def test_measured_modal_without_a_value_is_NOT_a_pin(self):
        # MEASURED on a real specification: this sentence states a
        # well-formedness requirement and names no latency, yet the same
        # document says "不指定 latency cycle 數". Reading the modal as a pin
        # refused the lever the document had explicitly freed.
        line = ("- 但**必須**:`y` 第 `i` 個位元給入後,在有限且確定的 cycle 數內,"
                "`p` 對應位元被輸出")
        got = mod.classify_line(line)
        assert got.get("pipelining", {}).get("status") != mod.STATUS_PINNED

    def test_modal_with_a_concrete_value_IS_a_pin(self):
        got = mod.classify_line("The pipeline depth shall be exactly 3 stages.")
        assert got["pipelining"]["status"] == mod.STATUS_PINNED

    def test_measured_ceiling_is_BOUNDED_and_carries_its_number(self):
        # A sentence that frees the structure AND caps it. Calling it PINNED
        # refuses a lever the spec opened; calling it FREE drops the cap.
        line = "- ❌ 不指定 pipeline 深度與精確 latency(僅上限 4096 cycles)"
        got = mod.classify_line(line)
        assert got["pipelining"]["status"] == mod.STATUS_BOUNDED
        assert got["pipelining"]["bound"] == 4096


class TestPolarity:
    """vibe-ic#712 — a sentence that DENIES its own status marker asserts
    nothing. Every case here is red against the classifier as it shipped in
    v1.11.15, which read only the marker and never its polarity."""

    def test_a_denied_pin_does_not_pin(self):
        line = "The pipeline depth must not be exactly 3 stages."
        assert mod.classify_line(line).get(
            "pipelining", {}).get("status") != mod.STATUS_PINNED
        assert mod.marker_denials(line)["pin"] == "not"

    def test_a_denied_pin_loses_to_a_freedom_sentence_elsewhere(self):
        """The whole point. Precedence is PINNED > FREE, so a denied pin that
        still counted would go on refusing a lever the document freed — the
        defect `_PINNING_MARKERS` already records once, with the denial now
        spelled out in the sentence itself."""
        hits = mod.scan_document(
            "- The pipeline depth shall NOT be exactly 3 stages.\n"
            "- ❌ 不指定 pipeline 深度\n", "d.md")
        v = mod.resolve_levers(hits)
        assert v["pipelining"]["status"] == mod.STATUS_FREE

    def test_a_denied_freedom_does_not_free(self):
        got = mod.classify_line(
            "The implementation is never free to choose the FSM encoding.")
        assert "state_encoding" not in got

    def test_a_denied_ceiling_does_not_bound(self):
        got = mod.classify_line(
            "There is no upper bound of 4096 cycles on the latency.")
        assert got.get("pipelining", {}).get("status") != mod.STATUS_BOUNDED

    def test_a_negative_vocabulary_marker_is_not_its_own_denial(self):
        """NEGATIVE CONTROL, and the reason the consult blanks the markers.
        Half this file's vocabulary is negative by construction; a consult that
        read `不指定` or `not specified` as a denial would fire on EVERY
        freedom sentence and admit no lever at all."""
        assert mod.marker_denials("- ❌ 不指定 FSM state 數量或編碼") == {}
        assert mod.marker_denials(
            "The pipeline depth is not specified.") == {}
        assert mod.marker_denials(
            "latency of no more than 4096 cycles") == {}
        # …and the classification that depends on it still stands.
        assert (mod.classify_line("- ❌ 不指定 FSM state 數量或編碼")
                ["state_encoding"]["status"] == mod.STATUS_FREE)

    def test_one_markers_built_in_negation_is_not_anothers_denial(self):
        """MEASURED while writing the consult: blanking only the marker under
        test let `不指定` (a FREEDOM marker) lend its `不` to the bound marker
        `上限` four words later, and the 4096 ceiling vanished."""
        line = "- ❌ 不指定 pipeline 深度與精確 latency(僅上限 4096 cycles)"
        assert mod.marker_denials(line) == {}
        assert mod.classify_line(line)["pipelining"]["bound"] == 4096

    def test_a_denial_in_a_LATER_sentence_does_not_reach_back(self):
        """The reach is `_prose_polarity.sentence_scope`, so one sentence does
        not lend its polarity to another on the same line."""
        line = ("The pipeline depth shall be exactly 3 stages. "
                "The reset polarity is not relevant here.")
        assert mod.classify_line(line)["pipelining"]["status"] == \
            mod.STATUS_PINNED

    def test_a_suppressed_statement_is_published_not_dropped(self):
        """"No sentence said this" and "a sentence said it and was denied" are
        opposite findings; a silent suppression would make them one."""
        refusals = []
        mod.scan_document(
            "- The pipeline depth must not be exactly 3 stages.\n", "d.md",
            refusals)
        assert len(refusals) == 1
        assert refusals[0]["marker"] == "pin"
        assert refusals[0]["path"] == "d.md" and refusals[0]["line"] == 1
        assert refusals[0]["denial"]

    def test_a_denied_line_with_no_lever_word_is_not_published(self):
        refusals = []
        mod.scan_document(
            "- The die area must not be exactly 1200 um.\n", "d.md", refusals)
        assert refusals == []


class TestResolveLevers:
    def _hit(self, lever, status, line=1, bound=None):
        return {"lever": lever, "status": status, "bound": bound,
                "path": "d.md", "line": line, "literal": "x"}

    def test_pinned_anywhere_beats_free_everywhere(self):
        v = mod.resolve_levers([
            self._hit("pipelining", mod.STATUS_FREE, 1),
            self._hit("pipelining", mod.STATUS_PINNED, 9),
            self._hit("pipelining", mod.STATUS_FREE, 12)])
        assert v["pipelining"]["status"] == mod.STATUS_PINNED

    def test_bound_survives_a_freedom_sentence_elsewhere(self):
        v = mod.resolve_levers([
            self._hit("pipelining", mod.STATUS_FREE, 1),
            self._hit("pipelining", mod.STATUS_BOUNDED, 5, bound=4096)])
        assert v["pipelining"]["status"] == mod.STATUS_BOUNDED
        assert v["pipelining"]["bound"] == 4096

    def test_tightest_ceiling_binds(self):
        v = mod.resolve_levers([
            self._hit("pipelining", mod.STATUS_BOUNDED, 1, bound=4096),
            self._hit("pipelining", mod.STATUS_BOUNDED, 7, bound=64)])
        assert v["pipelining"]["bound"] == 64


class TestBuildSpace:
    def test_undeclared_lever_is_refused_not_admitted(self):
        space = mod.build_space({})
        refused = [l for l in space["levers"] if not l["admitted"]]
        assert {l["lever"] for l in refused} == {
            "pipelining", "state_encoding", "arithmetic_architecture",
            "module_hierarchy"}
        assert all(l["status"] == mod.STATUS_UNDECLARED for l in refused)

    def test_synthesis_strategy_needs_no_permission_but_states_why(self):
        space = mod.build_space({})
        s = [l for l in space["levers"] if l["lever"] == "synthesis_strategy"][0]
        assert s["admitted"] is True
        assert s["justification_kind"] == mod.KIND_NO_DESIGN_CHANGE
        assert s["citations"] == []

    def test_pnr_levers_are_excluded_on_purpose_and_say_so(self):
        space = mod.build_space({})
        assert "core_utilisation" in space["pnr_levers_excluded_on_purpose"]
        assert space["pnr_exclusion_reason"]

    def test_admitted_free_lever_carries_its_citation(self):
        cite = {"lever": "pipelining", "status": mod.STATUS_FREE, "bound": None,
                "path": "input/docs/L2.md", "line": 46, "literal": "不指定 latency"}
        space = mod.build_space(mod.resolve_levers([cite]))
        p = [l for l in space["levers"] if l["lever"] == "pipelining"][0]
        assert p["admitted"] is True
        assert p["citations"][0]["line"] == 46


class TestAuditSpace:
    def test_clean_space_audits_clean(self):
        cite = {"lever": "pipelining", "status": mod.STATUS_FREE, "bound": None,
                "path": "d.md", "line": 1, "literal": "不指定 latency"}
        assert mod.audit_space(mod.build_space(mod.resolve_levers([cite]))) == []

    def test_admitted_lever_with_no_citation_is_caught(self):
        # This is the defect the whole program exists to prevent, so the
        # program asserts against it rather than trusting itself.
        space = mod.build_space({})
        space["levers"].append({
            "lever": "pipelining", "admitted": True,
            "status": mod.STATUS_FREE,
            "justification_kind": mod.KIND_SPEC_SENTENCE, "citations": []})
        problems = mod.audit_space(space)
        assert any("ZERO citations" in p for p in problems)

    def test_a_lever_falsely_claiming_no_design_change_is_caught(self):
        space = mod.build_space({})
        space["levers"].append({
            "lever": "pipelining", "admitted": True,
            "status": mod.STATUS_NO_DESIGN_CHANGE,
            "justification_kind": mod.KIND_NO_DESIGN_CHANGE, "citations": []})
        assert any("no_design_change" in p for p in mod.audit_space(space))

    def test_a_space_with_no_levers_list_is_not_silently_clean(self):
        assert mod.audit_space({}) != []


class TestNotMeasuredIsNotClean:
    def test_no_readable_document_is_NOT_an_empty_space(self, tmp_path):
        rc = mod.main([str(tmp_path), "--json", "reports/space.json"])
        assert rc == 2
        payload = json.loads(
            (tmp_path / "reports/space.json").read_text(encoding="utf-8"))
        assert payload["status"] == "NOT_MEASURED"
        assert "levers" not in payload

    def test_a_read_document_that_frees_nothing_IS_an_empty_space(self, tmp_path):
        d = tmp_path / "input" / "docs"
        d.mkdir(parents=True)
        (d / "L2.md").write_text("The design has a pipeline.\n", encoding="utf-8")
        rc = mod.main([str(tmp_path), "--json", "reports/space.json"])
        assert rc == 0
        payload = json.loads(
            (tmp_path / "reports/space.json").read_text(encoding="utf-8"))
        assert payload["status"] == "MEASURED"
        # only the lever that needs no permission
        assert payload["admitted_levers"] == ["synthesis_strategy"]

    def test_require_nonempty_does_not_fire_on_a_read_document(self, tmp_path):
        # `synthesis_strategy` is always admitted, so --require-nonempty must
        # not be mistaken for "the spec freed something".
        d = tmp_path / "input" / "docs"
        d.mkdir(parents=True)
        (d / "L2.md").write_text("nothing relevant\n", encoding="utf-8")
        assert mod.main([str(tmp_path), "--json", "reports/space.json",
                         "--require-nonempty"]) == 0


class TestVerifyMode:
    def test_a_citation_that_no_longer_says_what_was_quoted_is_caught(
            self, tmp_path):
        d = tmp_path / "input" / "docs"
        d.mkdir(parents=True)
        doc = d / "L2.md"
        doc.write_text("intro\n- ❌ 不指定 pipeline 深度\n", encoding="utf-8")
        assert mod.main([str(tmp_path), "--json", "reports/space.json"]) == 0
        assert mod.main([str(tmp_path), "--verify", "reports/space.json"]) == 0
        doc.write_text("intro\nsomething else entirely\n", encoding="utf-8")
        assert mod.main([str(tmp_path), "--verify", "reports/space.json"]) == 1

    def test_verifying_a_missing_file_is_NOT_MEASURED(self, tmp_path):
        assert mod.main([str(tmp_path), "--verify", "nope.json"]) == 2


# ---------------------------------------------------------------------------
# DELEGATION IS NOT UNCONDITIONAL, AND THE HANDOFF ROW HAS TO SAY SO
# ---------------------------------------------------------------------------
"""This program withholds the place-and-route knobs and names the owner that
emits a space for them. One of those knobs -- the design-for-ECO spare-cell
density -- is admitted by that owner only BOUNDED BELOW once a design declares a
spare/ECO requirement, because zero deletes the cells that make a bug found
after tape-out fixable by a metal-only ECO instead of a base-layer respin.

Listing it beside ten unconditional knobs reads as "freely searchable,
elsewhere", and a reader who follows that record into the owner without a
declaration gets exactly the unbounded lever that produced a published candidate
with every spare deleted. So the conditional levers are named separately -- and
MEASURED from the owner's own table, never re-typed here.
"""
import pathlib as _pathlib  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402
import sys  # noqa: E402

_PROGRAMS = _pathlib.Path(__file__).resolve().parents[1]


def _exclusion():
    return mod._pnr_exclusion()


# --- POSITIVE ---------------------------------------------------------------
def test_the_handoff_names_the_lever_that_carries_a_precondition():
    row = _exclusion()
    assert row["pnr_owner"] == mod.PNR_OWNER
    assert row["pnr_levers_delegated_with_a_precondition"] == [
        "spare_cell_density"]
    assert "metal-only ECO" in row["pnr_precondition_reason"]
    # and it is still one of the delegated levers, not moved out of the list
    assert "spare_cell_density" in row["pnr_levers_excluded_on_purpose"]


# --- NEGATIVE / MUTATION ----------------------------------------------------
def test_M_the_precondition_list_is_MEASURED_not_typed_here(monkeypatch):
    """THE MUTATION ARM. A list re-typed in this file stops being true the
    first time the owner changes, and would go on claiming a precondition that
    had been removed -- or missing one that had been added. Both directions are
    driven here, so the detector is shown to follow the owner rather than a
    constant that happens to agree today.
    """
    import ppa_pnr_search_space as pnr

    # (a) the owner drops the flag -> this file must stop claiming it
    stripped = tuple({k: v for k, v in l.items() if k != "eco_bounded"}
                     for l in pnr.LEVERS)
    monkeypatch.setattr(pnr, "LEVERS", stripped)
    row = _exclusion()
    assert row["pnr_levers_delegated_with_a_precondition"] == []
    assert "pnr_precondition_reason" not in row, (
        "a reason was published for a precondition no lever carries")

    # (b) the owner marks a DIFFERENT lever -> this file must follow it there
    moved = tuple({**l, "eco_bounded": l["lever"] == "cell_padding"}
                  if l["lever"] in ("cell_padding", "spare_cell_density")
                  else l for l in pnr.LEVERS)
    monkeypatch.setattr(pnr, "LEVERS", moved)
    assert _exclusion()["pnr_levers_delegated_with_a_precondition"] == [
        "cell_padding"]


# --- VACUOUS ----------------------------------------------------------------
def test_vacuous_an_absent_owner_claims_no_precondition_it_could_not_measure(
        monkeypatch, tmp_path):
    """With the owner gone this program cannot know which levers carry a
    precondition, and the honest row says nothing rather than repeating a
    fallback. The same discipline the owner-name sentence already has: an
    unowned lever is reported as unowned, not as delegated."""
    monkeypatch.setattr(mod, "PNR_OWNER", "no_such_owner_program.py")
    row = _exclusion()
    assert row["pnr_owner"] is None
    assert row.get("pnr_levers_delegated_with_a_precondition", []) == []
    assert "pnr_precondition_reason" not in row
    assert "UNOWNED" in row["pnr_exclusion_reason"]


# --- BAD INVOCATION ---------------------------------------------------------
def test_bad_invocation_is_never_a_pass(tmp_path):
    """Whatever else it does, a misspelled flag must not exit 0."""
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "crosslayer_search_space.py"),
         str(tmp_path), "--this-flag-does-not-exist"],
        capture_output=True, text=True)
    assert r.returncode != 0, (
        "a bad invocation exited 0, so a typo'd flag reads as a clean space")


@pytest.mark.xfail(
    strict=True,
    reason="PRE-EXISTING, and a published-interface change I am not making "
           "unasked. `crosslayer_search_space.py` exits 2 -- argparse's own "
           "convention -- on an unrecognised flag, and 2 is this program's "
           "NOT_MEASURED code. A caller that treats 2 as 'nothing to check "
           "here, carry on' therefore reads a typo as a step that measured "
           "nothing, which is exactly the confusion `_ppa/cli_exit.py` was "
           "written to end (it measured 12 of 14 shipped ppa_* programs with "
           "it). The one-line fix is `cli_exit.parse_or_refuse`, already in "
           "the tree. I am not applying it here because this program is not a "
           "`ppa_*` CLI -- the layer sweep never reaches it, no strict pin "
           "covers it -- and its own docstring declares a three-code contract "
           "with no 3 in it, so introducing one changes a published "
           "interface. Recorded rather than fixed, and named in RESULT.md.")
def test_bad_invocation_is_3_not_2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "crosslayer_search_space.py"),
         str(tmp_path), "--this-flag-does-not-exist"],
        capture_output=True, text=True)
    assert r.returncode == 3
