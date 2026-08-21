#!/usr/bin/env python3
"""vibe-ic#991 — a field that is PRESENT in an unreadable shape is REFUSED,
never counted as a zero.

WHAT EVERY TEST HERE ASSERTS, in one sentence: driving the SAME program with a
field ABSENT and with the SAME field carrying REAL CONTENT in a shape the
consumer does not read must not produce the same answer.

THE ASSERTIONS ARE WRITTEN ON LITERALS AND ORDERED FIRST, deliberately. Against
`origin/main` each one has to fail on BEHAVIOUR — `assert 0 != 0`,
`assert 'SKIP' != 'SKIP'` — and not on an AttributeError from a helper that
does not exist there yet, because a test that only proves the code is new
proves nothing about whether it bites.

FOUR TESTS PASS IN BOTH ARMS ON PURPOSE (`*_unchanged`). They assert only
behaviour this change does NOT move: an absent field still passes, a
well-formed input still reaches the same verdict, and a well-formed
attribution record is byte-identical. Without them, "every test in this file
fails on origin/main" would be equally explained by the file simply not
importing there.

chip-AGNOSTIC: every fixture is synthesised from neutral parts. No design, PDK,
vendor, SKU or process token appears in the source, the test names or the
fixtures.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _run(prog: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_PROGRAMS / prog), *args],
                          capture_output=True, text=True)


# ===========================================================================
# l14_protocol_versioning_contract_check — the MEASURED site.
# Absent `versions` and a `versions` object carrying two real rows produced
# byte-identical stdout, exit code and JSON report: `[PASS]`, rc 0.
# ===========================================================================
_L14 = "l14_protocol_versioning_contract_check.py"

# The dominant real shape in this repo's own corpus (122 of 197 shipped L14
# docs). It is what makes the coerced zero dangerous: it is indistinguishable
# from the commonest HONEST state.
_L14_BASE = {"doc_class": "L14", "extraction_status": "EXTRACTION_FOUND_NOTHING"}
# Two real version rows with deltas and section anchors — keyed BY VERSION
# instead of listed as rows.
_L14_ROWS_AS_OBJECT = {
    "gen-a": {"delta": "baseline behaviour", "section": "3.1"},
    "gen-b": {"delta": "field widened; readers of the earlier generation break",
              "section": "3.4"},
}


def _l14_project(tmp_path: Path, fields: dict) -> Path:
    d = tmp_path / "proj"
    (d / "phase1" / "generated_docs").mkdir(parents=True)
    (d / "phase1" / "generated_docs" / "L14_PROTOCOL_VERSIONING.json").write_text(
        json.dumps(dict(_L14_BASE, fields=fields)))
    return d


def test_l14_a_malformed_row_container_is_not_a_pass(tmp_path):
    d = _l14_project(tmp_path, {"versions": _L14_ROWS_AS_OBJECT})
    rep = tmp_path / "r.json"
    p = _run(_L14, str(d), "--json", str(rep))
    body = json.loads(rep.read_text())
    # LITERALS FIRST. On origin/main this is `assert 'PASS' != 'PASS'`.
    assert body.get("verdict") != "PASS", body
    assert p.returncode != 0, p.stdout
    assert body["pass"] is False
    assert "[PASS]" not in p.stdout


def test_l14_b_malformed_and_absent_do_not_produce_the_same_answer(tmp_path):
    absent = _l14_project(tmp_path / "a", {})
    malformed = _l14_project(tmp_path / "m", {"versions": _L14_ROWS_AS_OBJECT})
    a = _run(_L14, str(absent))
    m = _run(_L14, str(malformed))
    # On origin/main both are `[PASS] ...\n` with rc 0 — byte-identical.
    assert (a.returncode, a.stdout) != (m.returncode, m.stdout)
    assert a.returncode == 0
    assert m.returncode != 0


def test_l14_c_the_refusal_names_what_arrived(tmp_path):
    d = _l14_project(tmp_path, {"versions": _L14_ROWS_AS_OBJECT})
    rep = tmp_path / "r.json"
    _run(_L14, str(d), "--json", str(rep))
    body = json.loads(rep.read_text())
    refused = body.get("refused_containers") or []
    assert [r["field"] for r in refused] == ["versions"], body
    # NAMING THE KEYS is the whole point: "no versions list" sends a reader
    # nowhere; the keys send them to where the content actually is.
    assert refused[0]["keys"] == ["gen-a", "gen-b"]
    assert refused[0]["json_type"] == "object"
    assert refused[0]["entries_not_examined"] == 2
    msg = " ".join(f["message"] for f in body["findings"])
    assert "gen-a" in msg and "gen-b" in msg


def test_l14_d_a_row_rule_does_not_report_content_it_never_read(tmp_path):
    """The MISNAMING half. With `versions` refused and the status claiming
    EXTRACTED, `total == 0` is this gate's own coercion — so the rule that
    says "the document carries zero rows" must NOT fire, because that is a
    false statement about a document whose rows were never read."""
    d = tmp_path / "proj"
    (d / "phase1" / "generated_docs").mkdir(parents=True)
    (d / "phase1" / "generated_docs" / "L14_PROTOCOL_VERSIONING.json").write_text(
        json.dumps({"doc_class": "L14", "extraction_status": "EXTRACTED",
                    "fields": {"versions": _L14_ROWS_AS_OBJECT}}))
    rep = tmp_path / "r.json"
    _run(_L14, str(d), "--json", str(rep))
    rules = [f["rule"] for f in json.loads(rep.read_text())["findings"]]
    assert "l14_status_matches_content" not in rules, rules
    assert "l14_row_container_shape" in rules


def test_l14_e_every_verdict_line_discloses_its_denominator(tmp_path):
    """House rule: `gate_discloses_denominator_check` — a PASS must say how
    much it looked at. On origin/main the pass line is the bare
    `[PASS] l14_protocol_versioning_contract_check`."""
    d = _l14_project(tmp_path, {"versions": []})
    p = _run(_L14, str(d))
    assert p.returncode == 0
    assert "examined 0 row(s)" in p.stdout, p.stdout


def test_l14_f_an_absent_container_still_passes_unchanged(tmp_path):
    """PASSES IN BOTH ARMS. A zero denominator over a layer that WAS READ and
    is honestly empty stays a pass — 122 of the 197 shipped L14 docs are
    exactly this, and refusing them would replace one silent pass with a wall
    of false findings."""
    d = _l14_project(tmp_path, {})
    p = _run(_L14, str(d))
    assert p.returncode == 0
    assert "[PASS]" in p.stdout


# ===========================================================================
# l17_channel_catalog_consumer_contract_check
# ===========================================================================
_L17 = "l17_channel_catalog_consumer_contract_check.py"

_L17_CHANNELS_AS_OBJECT = {
    "ing": {"name": "ing", "direction_master": "in", "purpose": "inbound",
            "signals": [{"name": "ing_dat", "direction": "in", "width": 8}]},
    "egr": {"name": "egr", "direction_master": "out", "purpose": "outbound",
            "signals": [{"name": "egr_dat", "direction": "out", "width": 8}]},
}


def _l17_project(tmp_path: Path, doc: dict) -> Path:
    d = tmp_path / "proj"
    (d / "phase1" / "generated_docs").mkdir(parents=True)
    (d / "phase1" / "generated_docs" / "L17_CHANNEL_CATALOG.json").write_text(
        json.dumps(doc))
    return d


def test_l17_a_a_malformed_catalog_container_is_not_a_pass(tmp_path):
    d = _l17_project(tmp_path, {"doc_class": "L17",
                                "extraction_status": "EXTRACTION_FOUND_NOTHING",
                                "channels": _L17_CHANNELS_AS_OBJECT})
    p = _run(_L17, str(d))
    body = json.loads(p.stdout)
    # On origin/main: `{'pass': True, 'error_count': 0, ...}`, rc 0.
    assert body["summary"]["pass"] is not True, body["summary"]
    assert p.returncode != 0
    assert "CATALOG_CONTAINER_SHAPE_UNREADABLE" in [
        f["category"] for f in body["findings"]]


def test_l17_b_malformed_and_absent_do_not_produce_the_same_report(tmp_path):
    base = {"doc_class": "L17", "extraction_status": "EXTRACTION_FOUND_NOTHING"}
    a = _run(_L17, str(_l17_project(tmp_path / "a", dict(base))))
    m = _run(_L17, str(_l17_project(
        tmp_path / "m", dict(base, channels=_L17_CHANNELS_AS_OBJECT))))
    assert (a.returncode, a.stdout) != (m.returncode, m.stdout)
    assert a.returncode == 0 and m.returncode != 0


def test_l17_c_the_refusal_names_the_entries_it_did_not_examine(tmp_path):
    d = _l17_project(tmp_path, {"doc_class": "L17",
                                "extraction_status": "EXTRACTION_FOUND_NOTHING",
                                "channels": _L17_CHANNELS_AS_OBJECT})
    body = json.loads(_run(_L17, str(d)).stdout)
    info = body["info"]
    assert info["catalog_containers_refused"] == ["channels"], info
    assert info["catalog_entries_not_examined"] == 2
    assert info["catalog_entries_examined"] == 0
    msg = " ".join(f["message"] for f in body["findings"])
    assert "egr" in msg and "ing" in msg


def test_l17_d_an_absent_catalog_still_passes_unchanged(tmp_path):
    """PASSES IN BOTH ARMS."""
    p = _run(_L17, str(_l17_project(
        tmp_path, {"doc_class": "L17",
                   "extraction_status": "EXTRACTION_FOUND_NOTHING"})))
    assert p.returncode == 0
    assert json.loads(p.stdout)["summary"]["pass"] is True


# ===========================================================================
# analog_sigma_delta_gain_floor_check — the sharpest measured flip:
# a real FAIL (rc 1) became `[SKIP]` (rc 0).
# ===========================================================================
_ASD = "analog_sigma_delta_gain_floor_check.py"

_SPECS_AS_LIST = [{"name": "converter_type", "value": "sigma-delta modulator"},
                  {"name": "osr", "target": 64}]
_SPECS_AS_OBJECT = {"converter_type": {"value": "sigma-delta modulator"},
                    "osr": {"target": 64}}
# 30 dB against a 20*log10(64) = 36.1 dB floor — a 6.1 dB deficit.
_CORNERS = {"corners": [{"name": "c0", "ota_dc_gain_db": 30.0}]}


def _asd_project(tmp_path: Path, name: str, specs) -> Path:
    d = tmp_path / name
    b = d / "phase3" / "analog" / "blk"
    b.mkdir(parents=True)
    spec = {"block": "blk"}
    if specs is not None:
        spec["specs"] = specs
    (b / "spec.json").write_text(json.dumps(spec))
    (b / "corner_results.json").write_text(json.dumps(_CORNERS))
    return d


def test_analog_a_an_unreadable_spec_is_not_not_applicable(tmp_path):
    d = _asd_project(tmp_path, "m", _SPECS_AS_OBJECT)
    rep = tmp_path / "r.json"
    p = _run(_ASD, str(d), "--json", str(rep))
    verdict = json.loads(rep.read_text())["verdict"]
    # On origin/main: `assert 'SKIP' != 'SKIP'` and `assert 0 != 0`.
    assert verdict != "SKIP", verdict
    assert p.returncode != 0, p.stdout
    assert verdict == "UNMEASURED"
    assert p.returncode == 2


def test_analog_b_malformed_and_absent_do_not_produce_the_same_answer(tmp_path):
    a = _run(_ASD, str(_asd_project(tmp_path, "a", None)))
    m = _run(_ASD, str(_asd_project(tmp_path, "m", _SPECS_AS_OBJECT)))
    assert (a.returncode, a.stdout) != (m.returncode, m.stdout)
    assert a.returncode == 0 and m.returncode == 2


def test_analog_c_the_refusal_says_applicability_is_undecided(tmp_path):
    d = _asd_project(tmp_path, "m", _SPECS_AS_OBJECT)
    rep = tmp_path / "r.json"
    _run(_ASD, str(d), "--json", str(rep))
    blocks = json.loads(rep.read_text())["blocks"]
    assert [b["reason"] for b in blocks] == ["spec_container_unreadable"], blocks
    assert blocks[0]["refused"]["keys"] == ["converter_type", "osr"]
    assert "UNDECIDED" in blocks[0]["detail"]


def test_analog_d_a_well_formed_violation_still_fails_unchanged(tmp_path):
    """PASSES IN BOTH ARMS. The same three facts as a list of rows must still
    reach the FAIL this gate exists to produce — the fix must not have bought
    its refusal by breaking the readable path."""
    d = _asd_project(tmp_path, "w", _SPECS_AS_LIST)
    rep = tmp_path / "r.json"
    p = _run(_ASD, str(d), "--json", str(rep))
    assert p.returncode == 1
    assert json.loads(rep.read_text())["verdict"] == "FAIL"


# ===========================================================================
# ip_catalog_query — a declared dependency silently vanished.
# ===========================================================================
_CORE_MANIFEST = (
    "ip_name: dep_core\n" 'ip_version: "1.0"\n' "ip_class: leaf\n"
    "license: ISC\n" "canonical_url: https://example.invalid/dep_core\n"
    "description: a leaf\n" "implements:\n  architecture: leaf\n"
    "matches_when:\n  - \"L2 mentions 'zzq_leaf_token'\"\n"
    "interface:\n  ports:\n    - name: clk\n      dir: in\n"
    "rtl_files:\n  - dep_core.v\n")


def _top_manifest(depends_on: str) -> str:
    return ("ip_name: top_ip\n" 'ip_version: "1.0"\n' "ip_class: soc\n"
            "license: ISC\n" "canonical_url: https://example.invalid/top_ip\n"
            "description: a top\n" "implements:\n  architecture: soc\n"
            "matches_when:\n  - \"L2 mentions 'zzq_top_token'\"\n"
            "interface:\n  ports:\n    - name: clk\n      dir: in\n"
            "rtl_files:\n  - top_ip.v\n" + depends_on)


def _catalog_query(tmp_path: Path, name: str, depends_on: str):
    import ip_catalog_query as mod
    cat = tmp_path / name / "cat"
    for sub, body in (("top_ip", _top_manifest(depends_on)),
                      ("dep_core", _CORE_MANIFEST)):
        (cat / "cpu" / sub).mkdir(parents=True)
        (cat / "cpu" / sub / "manifest.yaml").write_text(body)
    proj = tmp_path / name / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L2_ARCHITECTURE.json").write_text(
        '{"note": "this design needs a zzq_top_token block"}')
    return mod.query_catalog(proj, catalog_dir=cat, min_confidence=0.4)


def test_ipcatalog_a_a_manifest_with_an_unreadable_list_is_not_offered(tmp_path):
    ms = _catalog_query(tmp_path, "m",
                        "depends_on:\n  dep_core: required for integration\n")
    # On origin/main: `top_ip` IS offered, with `depends_on == []`, and
    # `dep_core` is silently absent — so this is `assert ['top_ip'] == []`.
    assert sorted(m.ip_name for m in ms) == [], [m.ip_name for m in ms]


def test_ipcatalog_b_the_refusal_is_recorded_on_the_match(tmp_path):
    import ip_catalog_query as mod
    m = mod._manifest_to_match(
        {"ip_name": "x", "depends_on": {"d": "why"},
         "rtl_files": ["a.v"]}, "p", 1.0)
    assert [r["field"] for r in m.shape_refusals] == ["depends_on"]
    assert m.shape_refusals[0]["keys"] == ["d"]
    assert "d" in (mod._refuse_unreadable_shape(m) or "")


def test_ipcatalog_c_a_well_formed_dependency_is_still_auto_included(tmp_path):
    """PASSES IN BOTH ARMS. The refusal must not have been bought by breaking
    the transitive auto-include the readable path depends on."""
    ms = _catalog_query(tmp_path, "w", "depends_on:\n  - dep_core\n")
    assert sorted(m.ip_name for m in ms) == ["dep_core", "top_ip"]


# ===========================================================================
# gds_ip_attribution — no verdict anywhere; the harm is a FALSE STATEMENT in
# a tape-out deliverable.
# ===========================================================================
def _ip_line(files) -> str:
    import gds_ip_attribution as mod
    ip = {"ip_name": "ip_a", "version": "1", "license": "ISC",
          "canonical_commit": "c0ffee", "canonical_url": "u"}
    if files is not None:
        ip["files_copied"] = files
    return mod.build_attribution_blob(
        {"ip_catalog_used": [ip]}).splitlines()[1]


def test_gds_a_an_unreadable_file_list_is_not_reported_as_zero_files(tmp_path):
    line = _ip_line({"a.v": {"sha256": "aa"}, "b.v": {"sha256": "bb"}})
    # On origin/main: `assert 'files=0' not in 'IP ip_a 1 ISC files=0 ...'`.
    assert "files=0" not in line, line
    assert "files=REFUSED" in line


def test_gds_b_no_aggregate_hash_is_published_over_a_file_set_never_read(tmp_path):
    """`e3b0c44298fc1c14` is the head of SHA-256 of the EMPTY STRING. On
    origin/main it was printed as this IP's aggregate file digest — a
    plausible 16-hex-digit attestation over content the emitter never read,
    embedded in the foundry handoff GDS."""
    line = _ip_line({"a.v": {"sha256": "aa"}, "b.v": {"sha256": "bb"}})
    assert "e3b0c44298fc1c14" not in line, line
    assert "sha256_agg:REFUSED" in line


def test_gds_c_the_refusal_appears_in_the_record_itself(tmp_path):
    import gds_ip_attribution as mod
    blob = mod.build_attribution_blob(
        {"ip_catalog_used": {"ip_a": {"ip_name": "ip_a"}}})
    # The OUTER container unread used to emit a record with no `IP` line at
    # all — indistinguishable from a design that reused no catalog IP, which
    # is the exact claim a licence auditor reads this record to check.
    assert any(ln.startswith("REFUSED ") for ln in blob.splitlines()), blob
    assert "ip_catalog_used" in blob


def test_gds_d_a_well_formed_record_is_byte_identical_unchanged(tmp_path):
    """PASSES IN BOTH ARMS. This blob is embedded in a tape-out deliverable,
    so the readable path's bytes are pinned, not merely its meaning."""
    assert _ip_line([{"sha256": "aa"}, {"sha256": "bb"}]) == (
        "IP ip_a 1 ISC files=2 sha256_agg:486b34250bd4400c "
        "url:u commit:c0ffee")
    assert _ip_line(None) == (
        "IP ip_a 1 ISC files=0 sha256_agg:n/a url:u commit:c0ffee")


# ===========================================================================
# run_status — `step 'None' (0 done)` for a plan that was never read.
# ===========================================================================
def _run_status_report(tmp_path: Path, name: str, steps, present: bool):
    import run_status as rs
    d = tmp_path / name
    rep = d / "reports" / "orchestrator"
    rep.mkdir(parents=True)
    body = {}                      # no `verdict` -> the in-flight case
    if present:
        body["steps"] = steps
    f = rep / "phase3_one_shot.json"
    f.write_text(json.dumps(body))
    logs = rep / "logs"
    logs.mkdir(parents=True)
    lf = logs / "phase3.log"
    lf.write_text("working\n")
    old = time.time() - 700        # 700s of silence
    for p in (lf, f):
        os.utime(p, (old, old))
    (d / "run.pid").write_text(str(os.getpid()))
    os.utime(d / "run.pid", (old, old))
    return rs.status(d, "phase3"), rs


_PLAN = [{"name": n, "status": "PASS"} for n in ("a", "b", "c")] + \
        [{"name": "lvs", "status": "RUNNING"}]


def test_runstatus_a_an_unreadable_plan_is_not_zero_steps_done(tmp_path):
    rep, rs = _run_status_report(tmp_path, "m", {s["name"]: s for s in _PLAN},
                                 True)
    # On origin/main there is no such key: `assert None is not None`.
    assert rep.get("plan_unreadable") is not None, rep
    assert rep["plan_unreadable"]["entries_not_examined"] == 4
    assert "PLAN UNREADABLE" in rs.summarize(rep)


def test_runstatus_b_malformed_and_absent_do_not_produce_the_same_report(tmp_path):
    a, rs = _run_status_report(tmp_path, "a", None, False)
    m, _ = _run_status_report(tmp_path, "m", {s["name"]: s for s in _PLAN},
                              True)
    for r in (a, m):
        for k in ("pid", "heartbeat_log", "silence_s", "reason",
                  "last_log_line"):
            r.pop(k, None)
    assert a != m, a
    # Both still report `steps_completed: 0` — that is WHY a separate key is
    # needed, and asserting it here stops a later edit from "fixing" the
    # collapse by inventing a count nobody measured.
    assert a["steps_completed"] == 0 and m["steps_completed"] == 0
    assert a.get("plan_unreadable") is None


def test_runstatus_c_a_readable_plan_is_unchanged(tmp_path):
    """PASSES IN BOTH ARMS."""
    rep, _ = _run_status_report(tmp_path, "w", _PLAN, True)
    assert rep["current_step"] == "lvs"
    assert rep["steps_completed"] == 3
    assert rep["state"] == "RUNNING_ON_TIME"


# ===========================================================================
# bit_level_full_stack_tb_oracle_check — this one FAILS CLOSED and MISNAMES.
# Reclassified out of #991's fail-open list by measurement: rule 1 already
# refuses a non-list, so absent and malformed BOTH exit 1. Only the sentence
# was wrong.
# ===========================================================================
_BL = "bit_level_full_stack_tb_oracle_check.py"


def _bl(tmp_path: Path, name: str, per_vector, present: bool):
    d = tmp_path / name
    d.mkdir(parents=True)
    body = {"vectors_total": 16, "vectors_passed": 16, "vectors_failed": 0}
    if present:
        body["per_vector"] = per_vector
    r = d / "results.json"
    r.write_text(json.dumps(body))
    rep = d / "rep.json"
    p = _run(_BL, str(d), "--results-json", str(r), "--json", str(rep))
    return p, json.loads(rep.read_text())


_VECTORS = {f"v{i}": {"name": f"v{i}", "verdict": "PASS",
                      "expected_bytes": [1, i, 0]} for i in range(16)}


def test_bitlevel_a_a_present_but_unreadable_vector_set_is_not_called_missing(
        tmp_path):
    p, body = _bl(tmp_path, "m", _VECTORS, True)
    rules = [f["rule"] for f in body["findings"]]
    # On origin/main: `assert 'PER_VECTOR_MISSING' not in [...]` — it says the
    # results lack the array, over a file carrying 16 vectors.
    assert "PER_VECTOR_MISSING" not in rules, rules
    assert "PER_VECTOR_SHAPE_UNREADABLE" in rules
    msg = next(f["message"] for f in body["findings"]
               if f["rule"] == "PER_VECTOR_SHAPE_UNREADABLE")
    assert "16 key(s)" in msg


def test_bitlevel_b_an_absent_vector_set_still_says_missing_unchanged(tmp_path):
    """PASSES IN BOTH ARMS — and it is the control that keeps the two states
    distinguishable in the OTHER direction."""
    p, body = _bl(tmp_path, "a", None, False)
    assert p.returncode == 1
    assert "PER_VECTOR_MISSING" in [f["rule"] for f in body["findings"]]


# ===========================================================================
# The helper's own guard rail. A module that refused absent / [] / null would
# replace one silent pass with a wall of false findings — the failure mode
# `gate_zero_denominator_refuses_check` records as having flipped
# 182/159/94/42 of 182 tracked run dirs before being reverted.
# ===========================================================================
@pytest.mark.parametrize("doc,key", [
    ({}, "k"),                      # absent
    ({"k": []}, "k"),               # a declared empty list
    ({"k": None}, "k"),             # an explicit null
    ({"k": ["a"]}, "k"),            # a well-formed list
    ("not an object", "k"),         # the caller's own outer shape problem
])
def test_helper_a_a_real_zero_is_never_a_refusal(doc, key):
    import _shape_refusal as sr
    _, mismatch = sr.read_list_from(doc, key)
    assert mismatch is None, (doc, mismatch)


def test_helper_b_a_refusal_names_the_type_and_the_content():
    import _shape_refusal as sr
    _, m = sr.read_list_from({"k": {"a": 1, "b": 2}}, "k")
    assert m["json_type"] == "object"
    assert m["keys"] == ["a", "b"]
    assert m["entries_not_examined"] == 2
    s = sr.sentence(m, "somewhere")
    assert "somewhere" in s and "'a'" in s and "NOT a reading of zero" in s
    # A boolean must not describe itself as a number: `isinstance(True, int)`.
    _, mb = sr.read_list_from({"k": True}, "k")
    assert mb["json_type"] == "boolean"
