"""Unit tests for `erc_density_check.py` (Step-31 ERC + density substance).

Covers the anti-fabrication contract:
  * PASS fixture   — real density artefact + clean ERC (substance good).
  * FAIL fixtures  — (a) a metal layer outside the foundry 20-80% CMP window
                     (the silicon failure the gate guards), and
                     (b) an ERC-dirty report with floating nets.
  * Honesty edges  — missing / empty / provenance-less / metric-less density
                     artefact => honest FAIL (rc=1), never a vacuous pass; and
                     "examined nothing" => FAIL CLOSED (rc=1), never rc=2.
                     No project CONTENT reaches a NOT-CHECKED exit; rc=2 is
                     reserved for "project_dir is not a directory".
  * NON-fabrication — std-cell row utilization of 14% (the real OpenROAD
                     filler_placement metric) must NOT be mis-flagged as
                     out-of-range against the 20-80% per-LAYER rule.
"""
import importlib
import json

mod = importlib.import_module("erc_density_check")


# ── fixture helpers ─────────────────────────────────────────────────

def _reports(tmp_path):
    r = tmp_path / "reports"
    r.mkdir(parents=True, exist_ok=True)
    (r / "phase3").mkdir(parents=True, exist_ok=True)
    return r


def _write_density_json(tmp_path, payload):
    r = _reports(tmp_path)
    (r / "density.json").write_text(json.dumps(payload))


def _write_density_rpt(tmp_path, text):
    r = _reports(tmp_path)
    (r / "density.rpt").write_text(text)


def _write_erc(tmp_path, text):
    r = _reports(tmp_path)
    (r / "phase3" / "erc.rpt").write_text(text)


_REAL_DENSITY_RPT = (
    "# Metal-fill / density report — OpenROAD filler_placement\n"
    "# (Step 34). Tool: openroad.\n"
    "# filler instances placed: 0\n"
    "# std-cell row utilization (post-fill): 14.0%\n"
    "# Note: per-metal-layer CMP density (20-80% rule) is screened by\n"
    "# the KLayout met_min_ca_density deck at sign-off DRC.\n"
)

_CLEAN_ERC = (
    "# Electrical Rule Check (ERC) — OpenROAD open-source path. Tool: openroad.\n"
    "ERC floating nets: 0\n"
    "ERC clean: YES\n"
    "=== ERC: floating nets ===\n"
    "[INFO] no floating nets.\n"
)

_DIRTY_ERC = (
    "# Electrical Rule Check (ERC) — OpenROAD. Tool: openroad.\n"
    "ERC floating nets: 2\n"
    "ERC clean: NO (review floating nets)\n"
    "[WARNING RSZ-0020] found 2 floating nets.\n"
)


# ── PASS fixture: substance good ────────────────────────────────────

class TestPass:
    def test_row_util_plus_clean_erc_passes(self, tmp_path):
        _write_density_rpt(tmp_path, _REAL_DENSITY_RPT)
        _write_erc(tmp_path, _CLEAN_ERC)
        rc = mod.main([str(tmp_path)])
        assert rc == 0

    def test_per_layer_in_window_passes(self, tmp_path):
        # All metal layers inside [20%, 80%] — foundry-acceptable.
        _write_density_json(tmp_path, {
            "tool": "klayout met_min_ca_density",
            "layers": [
                {"name": "met1", "density_pct": 45.0},
                {"name": "met2", "density_pct": 38.5},
                {"name": "met3", "density_pct": 71.2},
            ],
        })
        _write_erc(tmp_path, _CLEAN_ERC)
        findings, stats = mod.audit(tmp_path)
        assert stats["per_layer_density"] is True
        assert stats["layers_ok"] == 3
        assert stats["layers_bad"] == 0
        assert mod.build_report(findings, stats, str(tmp_path))["summary"]["pass"]

    def test_row_util_14pct_not_mis_flagged(self, tmp_path):
        # The non-fabrication guard: 14% row utilization is a normal
        # std-cell metric, NOT subject to the 20-80% per-LAYER CMP rule.
        _write_density_rpt(tmp_path, _REAL_DENSITY_RPT)
        findings, stats = mod.audit(tmp_path)
        assert stats["row_utilization_pct"] == 14.0
        assert stats["layers_bad"] == 0
        # No DENSITY_OOB finding may be raised against row utilization.
        assert not any(f.category == "DENSITY_OOB" for f in findings)


# ── FAIL fixture: the silicon / anti-fab failure the gate guards ────

class TestFailDensity:
    def test_layer_below_window_fails(self, tmp_path):
        _write_density_json(tmp_path, {
            "tool": "klayout met_min_ca_density",
            "layers": [
                {"name": "met1", "density_pct": 45.0},
                {"name": "met2", "density_pct": 12.0},   # < 20% → CMP reject
            ],
        })
        rc = mod.main([str(tmp_path)])
        assert rc == 1
        findings, stats = mod.audit(tmp_path)
        assert stats["layers_bad"] == 1
        assert any(f.category == "DENSITY_OOB" and "met2" in f.message
                   for f in findings)

    def test_layer_above_window_fails(self, tmp_path):
        _write_density_json(tmp_path, {
            "tool": "openroad",
            "layers": [{"name": "met4", "density_pct": 92.3}],   # > 80%
        })
        rc = mod.main([str(tmp_path)])
        assert rc == 1

    def test_per_layer_density_in_rpt_text_oob_fails(self, tmp_path):
        rpt = (
            "# density report. Tool: klayout met_min_ca_density\n"
            "met1 density 45.0%\n"
            "met2 density 9.5%\n"   # out of window
        )
        _write_density_rpt(tmp_path, rpt)
        rc = mod.main([str(tmp_path)])
        assert rc == 1


class TestFailErc:
    def test_floating_nets_fail(self, tmp_path):
        _write_density_rpt(tmp_path, _REAL_DENSITY_RPT)  # density OK
        _write_erc(tmp_path, _DIRTY_ERC)                 # ERC dirty
        rc = mod.main([str(tmp_path)])
        assert rc == 1
        findings, _ = mod.audit(tmp_path)
        assert any(f.category == "ERC_DIRTY" for f in findings)

    def test_clean_no_with_zero_count_still_fails(self, tmp_path):
        _write_density_rpt(tmp_path, _REAL_DENSITY_RPT)
        _write_erc(tmp_path, "Tool: openroad\nERC clean: NO\n")
        assert mod.main([str(tmp_path)]) == 1


# ── honesty edges: missing / empty / provenance-less / metric-less ──

class TestHonestyEdges:
    def test_missing_density_artefact_fails(self, tmp_path):
        # density report absent but ERC present → DENSITY_MISSING ERROR,
        # honest FAIL (never a vacuous pass on absence).
        _write_erc(tmp_path, _CLEAN_ERC)
        rc = mod.main([str(tmp_path)])
        assert rc == 1
        findings, _ = mod.audit(tmp_path)
        assert any(f.category == "DENSITY_MISSING" for f in findings)

    def test_empty_density_rpt_fails(self, tmp_path):
        _write_density_rpt(tmp_path, "")
        assert mod.main([str(tmp_path)]) == 1

    def test_bad_json_fails(self, tmp_path):
        r = _reports(tmp_path)
        (r / "density.json").write_text("{ not valid json ")
        assert mod.main([str(tmp_path)]) == 1

    def test_no_tool_provenance_fails(self, tmp_path):
        # Hand-faked file with a number but no recognizable tool signature.
        _write_density_rpt(tmp_path, "the answer is 42 percent\n")
        rc = mod.main([str(tmp_path)])
        assert rc == 1
        findings, _ = mod.audit(tmp_path)
        assert any(f.category == "DENSITY_NO_PROVENANCE" for f in findings)

    def test_provenance_but_no_metric_fails(self, tmp_path):
        # Has a tool signature but no per-layer density and no row util.
        _write_density_json(tmp_path, {"tool": "openroad", "status": "done"})
        rc = mod.main([str(tmp_path)])
        assert rc == 1
        findings, _ = mod.audit(tmp_path)
        assert any(f.category == "DENSITY_NO_METRIC" for f in findings)

    def test_insane_row_utilization_fails(self, tmp_path):
        _write_density_json(tmp_path, {
            "tool": "openroad-filler_placement",
            "row_utilization_pct": 250.0,
        })
        assert mod.main([str(tmp_path)]) == 1

    def test_nothing_to_check_skips(self, tmp_path):
        # No density artefact AND no ERC report at all → explicit SKIP,
        # but DENSITY_MISSING is still recorded so it is NOT a vacuous pass.
        # Per the contract, a recorded ERROR forces rc=1, not SKIP, so the
        # only true rc=2 path is when audit() examined nothing and recorded
        # nothing — exercised here by stubbing the density sub-check away.
        _reports(tmp_path)  # empty reports/ dir, no artefacts

        # When density artefact is missing the checker records DENSITY_MISSING
        # (ERROR) → rc=1 (honest FAIL on absence for a required check).
        rc = mod.main([str(tmp_path)])
        assert rc == 1

    def test_empty_project_is_a_fail_not_a_skip(self, tmp_path):
        """The exit-code contract, DRIVEN on the shape the comment describes.

        A comment in `main` used to claim rc=2 was reachable "when the program
        is invoked directly with literally nothing to check". Invoked directly
        on a bare project directory, this is what it actually does.
        """
        assert mod.main([str(tmp_path)]) == 1

    def test_examining_nothing_fails_closed(self, tmp_path):
        """No real input reaches "examined nothing without an ERROR" —
        `_check_density` records DENSITY_MISSING on every absent artefact. This
        forces the state anyway (an inert density sub-check, as a future quiet
        "not applicable" early return would produce) and pins that it is a
        FAIL: not rc=0 (vacuous PASS) and not rc=2 (NOT CHECKED). This gate has
        no not-applicable verdict to offer.
        """
        import erc_density_check as m
        orig = m._check_density
        try:
            m._check_density = lambda *a, **k: None  # examine nothing, say nothing
            rc = m.main([str(tmp_path)])  # no erc.rpt either
            assert rc == 1
        finally:
            m._check_density = orig

    def test_no_input_shape_reaches_a_not_checked_exit(self, tmp_path):
        """rc=2 is reserved for "not a directory"; no project CONTENT reaches
        it. Enumerated over the absence states the density sub-check can be in."""
        shapes = {
            "bare": lambda p: None,
            "empty_reports": lambda p: _reports(p),
            "empty_density_rpt": lambda p: _write_density_rpt(p, ""),
            "erc_only": lambda p: _write_erc(p, _CLEAN_ERC),
        }
        for name, setup in shapes.items():
            proj = tmp_path / name
            proj.mkdir()
            setup(proj)
            assert mod.main([str(proj)]) != 2, (
                f"{name} exited NOT CHECKED; absence must be an honest FAIL")


# ── CLI contract: --json writes the report shape ────────────────────

class TestCliContract:
    def test_json_output_written(self, tmp_path):
        _write_density_rpt(tmp_path, _REAL_DENSITY_RPT)
        _write_erc(tmp_path, _CLEAN_ERC)
        out = tmp_path / "out.json"
        rc = mod.main([str(tmp_path), "--json", str(out)])
        assert rc == 0
        report = json.loads(out.read_text())
        assert report["program"] == "erc_density_check"
        assert "summary" in report and "findings" in report
        assert report["summary"]["pass"] is True

    def test_not_a_directory_returns_2(self, tmp_path):
        missing = tmp_path / "nope"
        assert mod.main([str(missing)]) == 2
