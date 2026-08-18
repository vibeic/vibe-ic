"""Unit tests for `phase2_verify_aggregate.py`."""
import importlib

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("phase2_verify_aggregate")


class TestArtifactScan:
    def test_missing_returns_false(self, tmp_path):
        out = mod.scan_artifacts(tmp_path)
        assert all(not a.present for a in out)

    def test_present_returns_true(self, tmp_path):
        d = tmp_path / "phase2" / "stage1" / "rtl"
        d.mkdir(parents=True)
        out = mod.scan_artifacts(tmp_path)
        rtl = [a for a in out if a.name == "rtl"][0]
        assert rtl.present


class TestAggregator:
    def _c(self, name, ec):
        return mod.CheckResult(name=name, exit_code=ec, stdout_tail="")

    def _a(self, name, present):
        return mod.ArtifactPresence(name=name, path=f"/x/{name}",
                                      present=present)

    def test_clean_run(self):
        artifacts = [self._a("rtl", True), self._a("sof", True), self._a("tb", True)]
        rep = mod.aggregate(mod.Path("/x"), artifacts, [self._c("a", 0)])
        assert rep.verdict == "PASS"

    def test_missing_artifact_fails(self):
        artifacts = [self._a("rtl", False), self._a("sof", True), self._a("tb", True)]
        rep = mod.aggregate(mod.Path("/x"), artifacts, [self._c("a", 0)])
        assert rep.verdict == "FAIL"

    def test_failed_check_fails(self):
        artifacts = [self._a("rtl", True), self._a("sof", True), self._a("tb", True)]
        rep = mod.aggregate(mod.Path("/x"), artifacts, [self._c("a", 1)])
        assert rep.verdict == "FAIL"

    def test_attribution(self):
        rep = mod.aggregate(mod.Path("/x"), [], [])
        d = rep.as_dict()
        assert d["emitted_by"] == \
            f"phase2_verify_aggregate v{shipped_plugin_version()}"
