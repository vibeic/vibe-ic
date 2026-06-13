"""Tests for wafer_map_pattern_classify.py — the yield-diagnostic
spatial-signature -> root-cause spec lookup table.

Covers: PASS (each spec class), the real FAIL (bad/empty data, missing class),
and missing-data honesty (no vacuous PASS).
"""
import importlib
import json

import pytest

mod = importlib.import_module("wafer_map_pattern_classify")


class TestSpecTable:
    def test_four_classes_complete(self):
        for c in mod.SPATIAL_CLASSES:
            assert c in mod.CLASS_TO_ROOT_CAUSE
            assert mod.CLASS_TO_ROOT_CAUSE[c] in mod.ROOT_CAUSE_DESC

    def test_edge_is_process(self):
        # verbatim spec: "Edge ring = process"
        assert mod.CLASS_TO_ROOT_CAUSE["edge"] == "process"

    def test_cluster_is_defects(self):
        # verbatim spec: "Clusters = defects"
        assert mod.CLASS_TO_ROOT_CAUSE["cluster"] == "defects"

    def test_uniform_is_design_marginality(self):
        # verbatim spec: "Uniform = design marginality"
        assert mod.CLASS_TO_ROOT_CAUSE["uniform"] == "design_marginality"

    def test_random_indeterminate(self):
        assert mod.CLASS_TO_ROOT_CAUSE["random"] == "indeterminate"


class TestNormalize:
    def test_aliases(self):
        assert mod.normalize_class("Edge Ring") == "edge"
        assert mod.normalize_class("clustered") == "cluster"
        assert mod.normalize_class("GLOBAL") == "uniform"
        assert mod.normalize_class("scatter") == "random"

    def test_bad_class_none(self):
        assert mod.normalize_class("banana") is None
        assert mod.normalize_class(None) is None


class TestLookup:
    def test_lookup_payload(self):
        lk = mod.lookup_root_cause("cluster")
        assert lk["root_cause"] == "defects"
        assert "spatial_class" in lk and lk["spatial_class"] == "cluster"


# ---------- CLI: PASS ----------
class TestCliPass:
    def test_pass_direct_class(self, capsys):
        rc = mod.main(["--spatial-class", "edge"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "process" in out

    def test_pass_alias(self):
        assert mod.main(["--spatial-class", "edge_ring"]) == 0

    def test_pass_json_output(self, tmp_path):
        op = tmp_path / "out.json"
        rc = mod.main(["--spatial-class", "uniform", "--json", str(op)])
        assert rc == 0
        d = json.loads(op.read_text())
        assert d["verdict"] == "PASS"
        assert d["root_cause"] == "design_marginality"

    def test_pass_reads_class_from_json_artefact(self, tmp_path):
        art = tmp_path / "yd.json"
        art.write_text(json.dumps({"spatial_class": "cluster"}))
        rc = mod.main([str(art)])
        assert rc == 0

    def test_pass_with_real_wafer_map_features(self, tmp_path):
        # build a small map; supply class explicitly (no fabricated auto-class)
        rows = ["x,y,bin"]
        for y in range(3):
            for x in range(3):
                # fail the corners (edge), pass interior
                b = "2" if (x in (0, 2) and y in (0, 2)) else "1"
                rows.append(f"{x},{y},{b}")
        d = tmp_path / "phase3" / "stage5_manufacturing"
        d.mkdir(parents=True)
        (d / "wafer_map.csv").write_text("\n".join(rows) + "\n")
        op = tmp_path / "out.json"
        rc = mod.main([str(tmp_path), "--spatial-class", "edge",
                       "--json", str(op)])
        assert rc == 0
        rep = json.loads(op.read_text())
        feats = rep["wafer_map_features"]
        assert feats["total_die"] == 9
        assert feats["fail_die"] == 4          # the 4 corners
        # corners are on the perimeter -> all fails are edge fails
        assert feats["edge_fail_die"] == 4
        assert feats["interior_fail_die"] == 0


# ---------- CLI: the real FAIL ----------
class TestCliFail:
    def test_fail_no_class_no_fabrication(self, capsys):
        # No class given and none readable: honest FAIL, NOT vacuous PASS.
        rc = mod.main([])
        assert rc == 1
        assert "NO_SPATIAL_CLASS" in capsys.readouterr().out

    def test_fail_bad_class(self, capsys):
        rc = mod.main(["--spatial-class", "banana"])
        assert rc == 1
        assert "BAD_SPATIAL_CLASS" in capsys.readouterr().out

    def test_fail_empty_wafer_map(self, tmp_path):
        d = tmp_path / "phase3" / "stage5_manufacturing"
        d.mkdir(parents=True)
        (d / "wafer_map.csv").write_text("x,y,bin\n")   # header only, no dies
        rc = mod.main([str(tmp_path), "--spatial-class", "edge"])
        assert rc == 1   # supplied map is bad -> honest FAIL even with a class

    def test_fail_garbage_wafer_map(self, tmp_path):
        d = tmp_path / "phase3" / "stage5_manufacturing"
        d.mkdir(parents=True)
        (d / "wafer_map.csv").write_text("x,y,bin\nnotanumber,foo,1\n")
        rc = mod.main([str(tmp_path), "--spatial-class", "edge"])
        assert rc == 1

    def test_fail_unparseable_json(self, tmp_path):
        art = tmp_path / "bad.json"
        art.write_text("{not json")
        assert mod.main([str(art)]) == 1


# ---------- missing-data honesty ----------
class TestHonesty:
    def test_skip_on_missing_path(self):
        rc = mod.main(["/no/such/path/xyz"])
        assert rc == 2   # operational skip, not a fabricated pass

    def test_no_vacuous_pass_on_empty_dir(self, tmp_path):
        # empty project dir, no class anywhere -> FAIL, never PASS
        rc = mod.main([str(tmp_path)])
        assert rc == 1
