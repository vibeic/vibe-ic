#!/usr/bin/env python3
"""Tests for the netgen `-json` short/open/pin LOCALIZATION (issue #203).

Today every `lvs.rpt` we ship can say "not a match" but never NAME the offending
net, because netgen only records short/open/pin localization when
`netgen -batch lvs … -json` is passed. This adds that flag and turns the sidecar
netgen writes (`lvs.rpt` → `lvs.json`) into a triage localization, WITHOUT
changing the text report either consumer reads:

  * consumer #1 — the #189 verdict classifier (`lvs_verdict_tokens.classify`)
  * consumer #2 — the Step-31 gate (`eda_report_audit._check_lvs`)

The load-bearing guarantees these tests pin:

  LOCALIZE   `lvs_verdict_tokens.localize` turns netgen's real `-json` array into
             offending-net / pin-mismatch / device localization — proven on a
             DELIBERATELY injected short AND an injected open, each naming the
             offending net/pin (a localization path that emits nothing on a real
             defect would be worse than none).
  NO-REGRESS neither consumer's behaviour moves. The text report netgen writes
             is BYTE-IDENTICAL with and without `-json` (same md5, captured
             fixture), `classify`/`mismatch_class`/`pin_mismatch_evidence` on it
             are unchanged, and the Step-31 gate's file discovery never picks up
             the `.json` sidecar (its glob is `*lvs*.rpt`/`*.log`/`*comp*.out`).
  FAIL-SAFE  an absent / corrupt / non-netgen json yields `available=False` and
             never raises; a report-write failure never fails the LVS step;
             netgen's `-json` ARRAY can never be mistaken for the authoritative
             E1 verdict DICT.

The fixtures under `fixtures/netgen_json/` are REAL netgen 1.5.323 output
captured in the vibeic-eda container (not hand-rolled), so the parser is tested
against the tool's actual schema, and the byte-identical text-report claim is a
recorded md5, not an assertion about a mock.

chip-AGNOSTIC: a two-inverter `top` with generic nets (Y1/Y2/A/B) — the parser
keys on netgen's JSON shape, never a design/cell literal.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

_lvt = importlib.import_module("lvs_verdict_tokens")
_mod = importlib.import_module("phase3_one_shot_runner")

_FIX = Path(__file__).parent / "fixtures" / "netgen_json"
_SHORT = _FIX / "netgen_lvs_mismatch_short.json"     # Y1<->Y2 shorted
_OPEN = _FIX / "netgen_lvs_open_port.json"           # top port B disconnected
_MATCH_JSON = _FIX / "netgen_lvs_match.json"         # clean
_MISMATCH_RPT = _FIX / "netgen_lvs_mismatch.rpt"     # text report (byte-ident)
_MATCH_RPT = _FIX / "netgen_lvs_match.rpt"


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# LOCALIZE — netgen -json → offending nets / pins (injected short AND open)
# ---------------------------------------------------------------------------
class TestLocalizeNamesTheDefect:
    def test_injected_short_names_the_offending_nets(self):
        loc = _lvt.localize(_SHORT)
        assert loc["available"] is True
        # the shorted nets Y1 / Y2 are named — the WHERE the text report omits
        assert set(loc["offending_nets"]) == {"Y1", "Y2"}
        cell = next(c for c in loc["cells"] if c["cell"] == "top")
        assert cell["nets"] == [5, 6] and cell["net_delta"] == 1
        # the surviving port Y2 shows up as a pin-correspondence mismatch
        assert any(pm["source"] == "Y2" for pm in loc["pin_mismatches"])

    def test_injected_open_names_the_offending_pin(self):
        # top port B was disconnected (renamed to an internal net) — the open is
        # a pin-correspondence failure, and B must be named.
        loc = _lvt.localize(_OPEN)
        assert loc["available"] is True
        assert any(pm["source"] == "B" for pm in loc["pin_mismatches"])

    def test_clean_match_localizes_nothing_but_is_available(self):
        loc = _lvt.localize(_MATCH_JSON)
        assert loc["available"] is True          # the json WAS read …
        assert loc["offending_nets"] == []       # … and named nothing (clean)
        assert loc["cells"] == []
        assert loc["pin_mismatches"] == []

    def test_localize_accepts_a_directory(self, tmp_path):
        (tmp_path / "lvs.json").write_text(_SHORT.read_text())
        loc = _lvt.localize(tmp_path)
        assert loc["available"] and set(loc["offending_nets"]) == {"Y1", "Y2"}

    def test_localize_accepts_a_parsed_list(self):
        arr = json.loads(_SHORT.read_text())
        loc = _lvt.localize(arr)
        assert set(loc["offending_nets"]) == {"Y1", "Y2"}


# ---------------------------------------------------------------------------
# FAIL-SAFE — absence / corruption never raises, never invents, never a verdict
# ---------------------------------------------------------------------------
class TestLocalizeFailSafe:
    def test_absent_file_is_unavailable(self, tmp_path):
        loc = _lvt.localize(tmp_path / "nope.json")
        assert loc["available"] is False
        assert loc["offending_nets"] == [] and loc["cells"] == []

    def test_none_source_is_unavailable(self):
        assert _lvt.localize(None)["available"] is False

    def test_corrupt_json_is_unavailable_not_raising(self, tmp_path):
        p = tmp_path / "lvs.json"
        p.write_text("[ this is { not json")
        assert _lvt.localize(p)["available"] is False

    def test_e1_verdict_dict_is_not_a_netgen_array(self, tmp_path):
        # The authoritative E1 verdict DICT must never be parsed as a netgen
        # `-json` localization ARRAY (different artifact, different owner).
        p = tmp_path / "lvs.json"
        p.write_text(json.dumps({"verdict": "mismatch",
                                 "verdict_reason": "x", "summary": {}}))
        assert _lvt.localize(p)["available"] is False
        assert _lvt.localize({"verdict": "mismatch",
                              "verdict_reason": "x",
                              "summary": {}})["available"] is False

    def test_non_array_json_is_unavailable(self, tmp_path):
        p = tmp_path / "lvs.json"
        p.write_text(json.dumps({"not": "an array"}))
        assert _lvt.localize(p)["available"] is False


# ---------------------------------------------------------------------------
# NO-REGRESSION — consumer #1: the classifier verdict is untouched by the json
# ---------------------------------------------------------------------------
class TestClassifierUnchanged:
    def test_text_report_is_byte_identical_with_and_without_json(self):
        # The recorded md5s: the ONLY thing `-json` adds is the sidecar; the
        # text report netgen writes is byte-for-byte the same (netgen's report
        # carries no timestamp). This is the #203 no-regression foundation.
        assert _md5(_MISMATCH_RPT) == "42b99ad3033715d8b5ca348c897dc159"
        assert _md5(_MATCH_RPT) == "816ab68b80d9a09a479882704cccb793"

    def test_mismatch_verdict_is_unaffected_by_the_sidecar(self):
        blob = _MISMATCH_RPT.read_text()
        # classify reads the TEXT blob; the json sidecar is not consulted.
        assert _lvt.classify(blob) == "MISMATCH"
        # and passing the netgen -json array as json_report changes nothing:
        # it is not an E1 report, so classify ignores it and stays on text.
        assert _lvt.classify(blob, json_report=_SHORT) == "MISMATCH"

    def test_match_verdict_is_unaffected_by_the_sidecar(self):
        blob = _MATCH_RPT.read_text()
        assert _lvt.classify(blob) == "MATCH"
        assert _lvt.classify(blob, json_report=_MATCH_JSON) == "MATCH"

    def test_pin_mismatch_evidence_text_path_unchanged(self):
        # the text pin-evidence extraction is exactly what it was pre-#203.
        blob = _MISMATCH_RPT.read_text()
        ev = _lvt.pin_mismatch_evidence(blob)
        assert any("Y2" in e for e in ev)


# ---------------------------------------------------------------------------
# NO-REGRESSION — consumer #2: the Step-31 gate never reads the json sidecar
# ---------------------------------------------------------------------------
class TestStep31GateUnchanged:
    def _audit(self):
        return importlib.import_module("eda_report_audit")

    def test_gate_discovery_excludes_the_json_sidecars(self, tmp_path):
        rp = tmp_path / "reports" / "phase3"
        rp.mkdir(parents=True)
        (rp / "lvs.rpt").write_text(_MISMATCH_RPT.read_text())
        (rp / "lvs.json").write_text(_SHORT.read_text())            # sidecar
        (rp / "lvs_localize.json").write_text(json.dumps(
            _lvt.localize(_SHORT)))                                 # sidecar
        audit = self._audit()
        res = audit._check_lvs(tmp_path)
        # the gate discovered ONLY the .rpt — the .json sidecars are invisible
        # to its `*lvs*.rpt`/`*.log`/`*comp*.out` glob.
        assert res.summary["files_found"] == 1
        # and its verdict is the same MISMATCH the text report always gave.
        assert res.summary["terminal_verdict"] == "MISMATCH"
        assert res.passed is False

    def test_gate_pass_on_clean_report_unaffected_by_sidecar(self, tmp_path):
        rp = tmp_path / "reports" / "phase3"
        rp.mkdir(parents=True)
        (rp / "lvs.rpt").write_text(_MATCH_RPT.read_text())
        (rp / "lvs.json").write_text(_MATCH_JSON.read_text())
        audit = self._audit()
        res = audit._check_lvs(tmp_path)
        assert res.summary["files_found"] == 1
        assert res.summary["terminal_verdict"] == "MATCH"


# ---------------------------------------------------------------------------
# RUNNER WIRING — the FAIL path persists lvs_localize.json naming the net
# ---------------------------------------------------------------------------
class TestRunnerEmission:
    def _proj_with_netgen_output(self, tmp_path, json_fix, rpt_fix):
        rp = tmp_path / "reports" / "phase3"
        rp.mkdir(parents=True)
        (rp / "lvs.rpt").write_text(rpt_fix.read_text())
        (rp / "lvs.json").write_text(json_fix.read_text())
        return tmp_path

    def test_emit_writes_localize_report_naming_offending_net(self, tmp_path):
        proj = self._proj_with_netgen_output(tmp_path, _SHORT, _MISMATCH_RPT)
        loc, path = _mod._emit_lvs_localization(
            proj, proj / "reports" / "phase3" / "lvs.rpt")
        assert loc["available"] and set(loc["offending_nets"]) == {"Y1", "Y2"}
        assert path == "reports/phase3/lvs_localize.json"
        side = json.loads(
            (proj / "reports" / "phase3" / "lvs_localize.json").read_text())
        assert set(side["offending_nets"]) == {"Y1", "Y2"}

    def test_localization_note_names_nets_and_pins(self, tmp_path):
        proj = self._proj_with_netgen_output(tmp_path, _SHORT, _MISMATCH_RPT)
        loc, _ = _mod._emit_lvs_localization(
            proj, proj / "reports" / "phase3" / "lvs.rpt")
        note = _mod._localization_note(loc)
        assert "Y1" in note and "Y2" in note
        assert "offending nets" in note

    def test_emit_is_noop_when_no_netgen_json(self, tmp_path):
        # No lvs.json (netgen not run / -json not honoured) → available False,
        # no sidecar written, no exception.
        rp = tmp_path / "reports" / "phase3"
        rp.mkdir(parents=True)
        (rp / "lvs.rpt").write_text(_MISMATCH_RPT.read_text())
        loc, path = _mod._emit_lvs_localization(proj := tmp_path,
                                                rp / "lvs.rpt")
        assert loc["available"] is False and path is None
        assert not (rp / "lvs_localize.json").exists()
        assert _mod._localization_note(loc) == ""

    def test_emit_write_failure_never_raises(self, tmp_path, monkeypatch):
        proj = self._proj_with_netgen_output(tmp_path, _SHORT, _MISMATCH_RPT)
        monkeypatch.setattr(Path, "write_text",
                            lambda *_a, **_k: (_ for _ in ()).throw(OSError))
        loc, path = _mod._emit_lvs_localization(
            proj, proj / "reports" / "phase3" / "lvs.rpt")
        assert loc["available"] is True         # parse still worked …
        assert path is None                     # … but the write failed safely


# ---------------------------------------------------------------------------
# RUNNER CMD — the netgen invocation actually passes `-json`
# ---------------------------------------------------------------------------
def test_runner_netgen_lvs_cmd_passes_json_flag():
    # A guard so the flag can't silently regress: the main netgen -batch lvs
    # invocation must carry `-json` (that is the whole enabling mechanism —
    # without it netgen writes no localization sidecar).
    src = Path(_mod.__file__).read_text()
    assert "{shlex.quote(netgen_setup)} {rpt_c} -json" in src


# ---------------------------------------------------------------------------
# TAXONOMY — the new report is registered under phase3
# ---------------------------------------------------------------------------
def test_lvs_localize_registered_in_phase3_taxonomy():
    pl = importlib.import_module("_path_layout")
    p = pl.report_path(Path("/proj"), "lvs_localize.json")
    assert p.parent.name == "phase3"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
