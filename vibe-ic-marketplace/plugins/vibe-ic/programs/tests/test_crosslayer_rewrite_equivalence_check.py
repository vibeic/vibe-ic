"""Unit tests for `crosslayer_rewrite_equivalence_check.py` — the judge half of
the rewrite-fidelity gate."""
import importlib
import json

mod = importlib.import_module("crosslayer_rewrite_equivalence_check")


def rep(**kw):
    base = {"status": "PASS", "compared_points": 162, "unproven_points": 0,
            "latency_offset_cycles": 0, "latency_freedom_evidence": None}
    base.update(kw)
    return base


class TestJudge:
    def test_proven_equivalent_passes(self):
        ok, st, _ = mod.judge(rep(), baseline_present=True,
                              report_readable=True)
        assert (ok, st) == (True, "PASS")

    def test_a_baseline_with_no_report_is_refused_and_says_why(self):
        # MEASURED: deleting this clause still refuses the case, via
        # CLX_REPORT_MISSING. It is the clause that gives the refusal an
        # actionable reason, not the clause that does the refusing — the test
        # asserts the diagnosis, and the test below asserts the refusal.
        ok, st, why = mod.judge(None, baseline_present=True,
                                report_readable=False)
        assert (ok, st) == (False, "CLX_BASELINE_PRESENT_NO_REPORT")
        assert "skips its own filter" in why

    def test_a_rewrite_with_no_report_is_refused_however_it_is_diagnosed(self):
        for present in (True, False):
            ok, _st, _ = mod.judge(None, baseline_present=present,
                                   report_readable=False)
            assert ok is False

    def test_an_undeclared_search_is_NOT_APPLICABLE_and_that_is_a_known_limit(
            self):
        # A driver that rewrote the RTL and declared NOTHING leaves a tree
        # indistinguishable from a design that ran no search. The gate reads
        # artefacts; it cannot see a rewrite nobody recorded. Pinned as a test
        # so the limit is documented behaviour rather than a surprise.
        ok, st, _ = mod.judge(None, baseline_present=False,
                              report_readable=False)
        assert (ok, st) == (False, "CLX_REPORT_MISSING")

    def test_unparseable_report_is_not_a_pass(self):
        ok, st, _ = mod.judge(None, baseline_present=True,
                              report_readable=True)
        assert (ok, st) == (False, "CLX_REPORT_UNPARSEABLE")

    def test_measured_non_equivalence_is_refused(self):
        ok, st, _ = mod.judge(rep(status="NOT_EQUIVALENT", unproven_points=31),
                              baseline_present=True, report_readable=True)
        assert (ok, st) == (False, "CLX_NOT_EQUIVALENT")

    def test_unproven_is_refused_and_is_not_called_wrong(self):
        ok, st, why = mod.judge(
            rep(status="NOT_PROVEN_EQUIVALENT", unproven_points=31),
            baseline_present=True, report_readable=True)
        assert (ok, st) == (False, "CLX_NOT_PROVEN")
        assert "Unproven is not proven" in why

    def test_not_measured_is_refused(self):
        ok, st, _ = mod.judge(rep(status="NOT_MEASURED", compared_points=0),
                              baseline_present=True, report_readable=True)
        assert (ok, st) == (False, "CLX_NOT_MEASURED")

    def test_pass_with_zero_compared_points_is_vacuous(self):
        # The same hole step 13's own judge closes. A second copy of a boolean
        # is not evidence, so the counts are re-derived here.
        ok, st, _ = mod.judge(rep(compared_points=0), baseline_present=True,
                              report_readable=True)
        assert (ok, st) == (False, "CLX_VACUOUS_CLAIM")

    def test_pass_that_still_carries_unproven_points_is_refused(self):
        ok, st, _ = mod.judge(rep(unproven_points=3), baseline_present=True,
                              report_readable=True)
        assert (ok, st) == (False, "CLX_NOT_PROVEN")

    def test_an_uncited_latency_offset_is_refused_even_on_a_PASS(self):
        ok, st, why = mod.judge(rep(latency_offset_cycles=2),
                                baseline_present=True, report_readable=True)
        assert (ok, st) == (False, "CLX_UNCITED_LATENCY_OFFSET")
        assert "cheat, not a mode" in why

    def test_a_cited_latency_offset_passes_and_says_so(self):
        ok, st, why = mod.judge(
            rep(latency_offset_cycles=2,
                latency_freedom_evidence={"path": "d.md", "line": 65,
                                          "literal": "不指定 latency cycle 數"}),
            baseline_present=True, report_readable=True)
        assert (ok, st) == (True, "PASS")
        assert "2-cycle latency offset" in why

    def test_an_unrecognised_status_is_never_read_as_a_proof(self):
        ok, st, _ = mod.judge(rep(status="LOOKS_FINE"), baseline_present=True,
                              report_readable=True)
        assert (ok, st) == (False, "CLX_NOT_MEASURED")


class TestMain:
    def test_a_design_that_ran_no_search_is_NOT_APPLICABLE_not_silently_clean(
            self, tmp_path):
        rc = mod.main([str(tmp_path)])
        assert rc == 0
        p = tmp_path / "reports/crosslayer/rewrite_equivalence_check.json"
        payload = json.loads(p.read_text(encoding="utf-8"))
        assert payload["status"] == "NOT_APPLICABLE"

    def test_a_baseline_snapshot_with_no_report_fails(self, tmp_path):
        (tmp_path / "reports/crosslayer/baseline_rtl").mkdir(parents=True)
        assert mod.main([str(tmp_path)]) == 1
        payload = json.loads(
            (tmp_path / "reports/crosslayer/rewrite_equivalence_check.json")
            .read_text(encoding="utf-8"))
        assert payload["status"] == "CLX_BASELINE_PRESENT_NO_REPORT"

    def test_a_clean_report_passes_end_to_end(self, tmp_path):
        d = tmp_path / "reports/crosslayer"
        (d / "baseline_rtl").mkdir(parents=True)
        (d / "rewrite_equivalence.json").write_text(
            json.dumps(rep()), encoding="utf-8")
        assert mod.main([str(tmp_path)]) == 0
