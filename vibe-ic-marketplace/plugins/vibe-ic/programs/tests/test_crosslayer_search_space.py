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
