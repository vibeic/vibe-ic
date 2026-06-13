"""Unit tests for `phase3_verify_aggregate.py`."""
import importlib

mod = importlib.import_module("phase3_verify_aggregate")


class TestParseDrcCount:
    def test_parses_total_violations(self, tmp_path):
        rpt = tmp_path / "drc.rpt"
        rpt.write_text("Total violations: 42\n")
        assert mod.parse_drc_count(rpt) == 42

    def test_parses_drc_errors_found(self, tmp_path):
        rpt = tmp_path / "drc.rpt"
        rpt.write_text("Number of DRC errors found: 7\n")
        assert mod.parse_drc_count(rpt) == 7

    def test_missing_file_returns_minus_one(self, tmp_path):
        assert mod.parse_drc_count(tmp_path / "missing.rpt") == -1


class TestParseStaMargins:
    def test_parses_wns_tns(self, tmp_path):
        rpt = tmp_path / "sta.rpt"
        rpt.write_text("wns -1.5\ntns -7.0\n")
        wns, tns = mod.parse_sta_margins(rpt)
        assert wns == -1.5
        assert tns == -7.0

    def test_missing_returns_zero(self, tmp_path):
        wns, tns = mod.parse_sta_margins(tmp_path / "missing")
        assert wns == 0.0 and tns == 0.0


class TestAggregator:
    def _c(self, ec):
        return mod.CheckResult(name="x", exit_code=ec, stdout_tail="")

    def _present_all(self):
        return [mod.ArtifactPresence(name=n, path=f"/x/{r}", present=True)
                for n, r in mod.REQUIRED_FILES]

    def test_clean_silicon_passes(self):
        rep = mod.aggregate(mod.Path("/x"), self._present_all(),
                             [self._c(0)], drc_violations=0,
                             wns=0.5, tns=0.0)
        assert rep.verdict == "PASS"

    def test_drc_violations_fails(self):
        rep = mod.aggregate(mod.Path("/x"), self._present_all(),
                             [self._c(0)], drc_violations=10,
                             wns=0.5, tns=0.0)
        assert rep.verdict == "FAIL"

    def test_negative_wns_fails(self):
        rep = mod.aggregate(mod.Path("/x"), self._present_all(),
                             [self._c(0)], drc_violations=0,
                             wns=-0.1, tns=0.0)
        assert rep.verdict == "FAIL"

    def test_missing_artifact_fails(self):
        arts = [mod.ArtifactPresence(name="final_gds", path="/x/g",
                                       present=False)]
        rep = mod.aggregate(mod.Path("/x"), arts, [self._c(0)],
                             drc_violations=0, wns=0.5, tns=0.0)
        assert rep.verdict == "FAIL"

    def test_unknown_drc_count_does_not_fail(self):
        rep = mod.aggregate(mod.Path("/x"), self._present_all(),
                             [self._c(0)], drc_violations=-1,
                             wns=0.5, tns=0.0)
        # drc=-1 = file not present / not parseable; not a failure here
        assert rep.verdict == "PASS"

    def test_attribution(self):
        rep = mod.aggregate(mod.Path("/x"), [], [],
                             drc_violations=0, wns=0, tns=0)
        d = rep.as_dict()
        assert "v0.1.50" in d["emitted_by"]
