#!/usr/bin/env python3
"""Smoke tests for l18_interconnect_topology_factuality_check (layergate-6).

NEGATIVE CONTROL IS THE POINT. Every rail is asserted in BOTH directions on the
same rail: a deliberately-gutted layer produces the ERROR finding, a well-formed
one does not.

L18 ADVISES rather than blocks (it has no downstream consumer), so the verdict
under test is the FINDING SET plus the `--strict` exit code — asserting only
the default exit code would be a test that cannot fail.

All fixtures are SYNTHESIZED neutral data. No real design's files are copied
and no design/PDK/vendor/protocol name appears.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l18_interconnect_topology_factuality_check.py")


def _run(project: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project), *extra],
        capture_output=True, text=True)


def _cats(cp: subprocess.CompletedProcess) -> set[str]:
    return {f["category"] for f in json.loads(cp.stdout)["findings"]}


def _errs(cp: subprocess.CompletedProcess) -> set[str]:
    return {f["category"] for f in json.loads(cp.stdout)["findings"]
            if f["severity"] == "ERROR"}


# ---------------------------------------------------------------------------
# Fixture builders — synthesized, neutral
# ---------------------------------------------------------------------------
def _mk(tmp: Path, l18: dict, *, schema_l18: str | None = None) -> tuple:
    proj = tmp / "run"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    # The design's own declared entities — the universe every L18 claim must
    # resolve against.
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "widget_top",
        "ports": [{"name": "core_clk", "direction": "input"},
                  {"name": "bus_id_out", "direction": "output"},
                  {"name": "bus_len_out", "direction": "output"}]}))
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps({
        "fields": {"channels": [
            {"name": "bus_port", "signals": [{"name": "bus_id_out"},
                                             {"name": "bus_len_out"}]}]}}))
    (gd / "L18_INTERCONNECT_TOPOLOGY.json").write_text(json.dumps(l18))
    schema = tmp / "schema_stub.py"
    schema.write_text(
        "LAYER_FILE_NAMES = {\n"
        f"    \"L18\": \"{schema_l18 or 'L18_INTERCONNECT_TOPOLOGY.json'}\",\n"
        "}\n")
    return proj, schema


_WELL_FORMED = {
    "extraction_status": "EXTRACTED",
    "extraction_evidence": [{"line": 91, "quote": "…"}],
    "fields": {
        "interconnect_rules": [
            {"rule": "the fabric must not reorder responses within one id",
             "line": 91}],
        # Every key is a signal this design declares; every value is a value.
        "default_signal_values": {"bus_id_out": "All zeros",
                                  "bus_len_out": "Length 1"},
        "typical_topologies": ["point-to-point"],
        "multi_copy_atomicity": {},
        "id_routing": {"description":
                       "bus_id_out is widened by the fabric",
                       "evidence": [{"line": 93, "quote": "…"}]},
    },
}

# The observed hazard: a case-insensitive regex harvested English function
# words as "signal names", and scraped rendered-table debris as their
# "default values" — while extraction_status said EXTRACTED and no consumer
# existed to contradict it.
_GARBAGE_HARVEST = {
    "extraction_status": "EXTRACTED",
    "fields": {
        "interconnect_rules": [],
        "default_signal_values": {
            "always": "6'b0.                                     |",
            "which": "40 bit wide counters",
            "being": "indicate the cause of"},
        "typical_topologies": [],
        "multi_copy_atomicity": {},
        "id_routing": {},
    },
}


# ---------------------------------------------------------------------------
# RAIL: default_signal_values keys must be entities this design declares.
# NEGATIVE CONTROL PAIR.
# ---------------------------------------------------------------------------
def test_NEGATIVE_default_value_keys_are_not_design_entities(tmp_path):
    proj, schema = _mk(tmp_path, _GARBAGE_HARVEST)
    r = _run(proj, "--schema-file", str(schema))
    assert "DEFAULT_VALUE_KEY_IS_NOT_A_DESIGN_ENTITY" in _errs(r), r.stdout


def test_POSITIVE_default_value_keys_that_resolve_pass(tmp_path):
    proj, schema = _mk(tmp_path, _WELL_FORMED)
    r = _run(proj, "--schema-file", str(schema))
    assert _errs(r) == set(), r.stdout


# ---------------------------------------------------------------------------
# RAIL: values scraped out of a rendered table. NEGATIVE CONTROL PAIR.
# ---------------------------------------------------------------------------
def test_NEGATIVE_default_value_is_a_harvest_artifact(tmp_path):
    proj, schema = _mk(tmp_path, _GARBAGE_HARVEST)
    r = _run(proj, "--schema-file", str(schema))
    assert "DEFAULT_VALUE_IS_A_HARVEST_ARTIFACT" in _errs(r), r.stdout


def test_POSITIVE_clean_default_values_are_not_flagged(tmp_path):
    proj, schema = _mk(tmp_path, _WELL_FORMED)
    r = _run(proj, "--schema-file", str(schema))
    assert "DEFAULT_VALUE_IS_A_HARVEST_ARTIFACT" not in _cats(r), r.stdout


# ---------------------------------------------------------------------------
# RAIL: status vs payload. NEGATIVE CONTROL PAIR.
# ---------------------------------------------------------------------------
def test_NEGATIVE_status_claims_success_with_empty_payload(tmp_path):
    proj, schema = _mk(tmp_path, {"extraction_status": "EXTRACTED",
                                  "fields": {"interconnect_rules": [],
                                             "default_signal_values": {},
                                             "id_routing": {}}})
    r = _run(proj, "--schema-file", str(schema))
    assert "STATUS_CONTRADICTS_PAYLOAD" in _errs(r), r.stdout


def test_NEGATIVE_template_content_the_producer_never_extracted(tmp_path):
    """found-nothing status + populated narrative => a template leak."""
    proj, schema = _mk(tmp_path, {
        "extraction_status": "EXTRACTION_FOUND_NOTHING",
        "fields": {"interconnect_rules": [], "default_signal_values": {},
                   "id_routing": {"description":
                                  "the fabric widens GHOST_ID on the way out",
                                  "compliance_note": "returns the wider value"}}
    })
    r = _run(proj, "--schema-file", str(schema))
    assert "TEMPLATE_WITHOUT_EXTRACTION" in _errs(r), r.stdout


def test_POSITIVE_honest_empty_passes(tmp_path):
    proj, schema = _mk(tmp_path, {
        "extraction_status": "EXTRACTION_FOUND_NOTHING",
        "fields": {"interconnect_rules": [], "default_signal_values": {},
                   "typical_topologies": [], "multi_copy_atomicity": {},
                   "id_routing": {}}})
    r = _run(proj, "--schema-file", str(schema))
    assert _errs(r) == set(), r.stdout
    assert "HONEST_EMPTY" in _cats(r)


# ---------------------------------------------------------------------------
# RAIL: narrative corroboration (WARNING-only by design). NEGATIVE PAIR.
# ---------------------------------------------------------------------------
def test_NEGATIVE_narrative_names_nothing_this_design_has(tmp_path):
    gutted = json.loads(json.dumps(_WELL_FORMED))
    gutted["fields"]["id_routing"] = {
        "description": "GHOST_ID is widened; slave-side GHOST_WIDTH is larger",
        "evidence": [{"line": 5, "quote": "…"}]}
    proj, schema = _mk(tmp_path, gutted)
    r = _run(proj, "--schema-file", str(schema))
    assert "NARRATIVE_UNCORROBORATED" in _cats(r), r.stdout
    # It is a WARNING on purpose — identifying entities inside prose is
    # approximate, so it must never carry the verdict.
    assert "NARRATIVE_UNCORROBORATED" not in _errs(r)


def test_POSITIVE_corroborated_narrative_is_not_flagged(tmp_path):
    proj, schema = _mk(tmp_path, _WELL_FORMED)
    assert "NARRATIVE_UNCORROBORATED" not in _cats(
        _run(proj, "--schema-file", str(schema)))


# ---------------------------------------------------------------------------
# RAIL: schema filename contract. NEGATIVE CONTROL PAIR.
# ---------------------------------------------------------------------------
def test_NEGATIVE_schema_maps_l18_to_a_file_that_does_not_exist(tmp_path):
    proj, schema = _mk(tmp_path, _WELL_FORMED,
                       schema_l18="L18_SOMETHING_ELSE.json")
    r = _run(proj, "--schema-file", str(schema))
    assert "CANONICAL_FILENAME_CONTRACT_SPLIT" in _cats(r), r.stdout


def test_POSITIVE_schema_filename_agrees_with_disk(tmp_path):
    proj, schema = _mk(tmp_path, _WELL_FORMED)
    r = _run(proj, "--schema-file", str(schema))
    assert "CANONICAL_FILENAME_CONTRACT_SPLIT" not in _cats(r), r.stdout


# ---------------------------------------------------------------------------
# Verdict mode: ADVISES by default, BLOCKS under --strict.
# ---------------------------------------------------------------------------
def test_advises_by_default_and_blocks_under_strict(tmp_path):
    proj, schema = _mk(tmp_path, _GARBAGE_HARVEST)
    advis = _run(proj, "--schema-file", str(schema))
    strict = _run(proj, "--schema-file", str(schema), "--strict")
    assert advis.returncode == 0, "L18 must ADVISE by default (no consumer)"
    assert strict.returncode == 1, "--strict must be able to block"
    assert _cats(advis) == _cats(strict)
    assert json.loads(advis.stdout)["verdict_mode"] == "ADVISES"
    assert json.loads(strict.stdout)["verdict_mode"] == "BLOCKS"


def test_strict_on_a_well_formed_layer_still_passes(tmp_path):
    """--strict must not be a blanket fail — the negative control's mirror."""
    proj, schema = _mk(tmp_path, _WELL_FORMED)
    assert _run(proj, "--schema-file", str(schema),
                "--strict").returncode == 0


def test_skips_cleanly_when_layer_absent(tmp_path):
    proj = tmp_path / "empty"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    assert _run(proj).returncode == 2


def test_layer_cannot_corroborate_itself(tmp_path):
    """L18's own keys must never enter the universe its claims resolve in."""
    gutted = json.loads(json.dumps(_GARBAGE_HARVEST))
    # Give L18 a `name` field echoing its own bogus key. If the universe were
    # built from L18 too, the bogus key would self-corroborate and the gate
    # would go quiet — a check that lies.
    gutted["fields"]["interconnect_rules"] = [{"name": "always",
                                               "rule": "x", "line": 1}]
    proj, schema = _mk(tmp_path, gutted)
    r = _run(proj, "--schema-file", str(schema))
    assert "DEFAULT_VALUE_KEY_IS_NOT_A_DESIGN_ENTITY" in _errs(r), r.stdout


# ---------------------------------------------------------------------------
# RAIL: the SCOPE of the status-vs-payload verdict.
#
# STATUS_CONTRADICTS_PAYLOAD has two producing branches that emit the SAME
# category, so asserting the category alone cannot tell them apart and cannot
# tell a correctly-scoped verdict from an overreaching one. Every test below
# therefore asserts the BRANCH, identified by evidence the branches do not
# share, never by the category name.
# ---------------------------------------------------------------------------
def _finding(cp: subprocess.CompletedProcess, cat: str) -> dict | None:
    for f in json.loads(cp.stdout)["findings"]:
        if f["category"] == cat:
            return f
    return None


def _branch(cp: subprocess.CompletedProcess) -> str | None:
    """Which STATUS_CONTRADICTS_PAYLOAD branch fired, or None.

    The empty-payload branch carries only the status; the all-failed branch
    additionally carries the populated set it is making a claim about. That
    difference is what distinguishes them — the category string does not.
    """
    f = _finding(cp, "STATUS_CONTRADICTS_PAYLOAD")
    if f is None:
        return None
    return "ALL_FAILED" if "populated" in f["evidence"] else "EMPTY_PAYLOAD"


# A document whose only fact-bearing content is a failed harvest: the universal
# claim IS true here, so the verdict must survive. This is the shape the repair
# must not delete.
_ONLY_FACT_BEARING_FIELD_FAILED = {
    "extraction_status": "EXTRACTED",
    "fields": {
        "default_signal_values": {"always": "6'b0.            |",
                                  "which": "40 bit wide counters"},
        # Narrative only — approximate, so it can neither convict nor acquit.
        "id_routing": {"description": "the fabric widens the id on the way out"},
    },
}

# The same failure, in a document that ALSO populated substantive containers
# the gate was never told about. The failure is identical; the universal claim
# is now false.
_FAILED_FIELD_BESIDE_SURVIVING_CONTENT = {
    "extraction_status": "EXTRACTED",
    "fields": {
        "default_signal_values": {"always": "6'b0.            |",
                                  "which": "40 bit wide counters"},
        "id_routing": {"description": "the fabric widens the id on the way out"},
        # Container names this gate has never enumerated, holding real content.
        "supported_topologies": [{"name": "point to point",
                                  "description": "two endpoints, no arbiter"},
                                 {"name": "shared bus",
                                  "description": "many endpoints, one arbiter"}],
        "role_summary": [{"role": "initiator", "description": "issues requests"}],
        "ordering_guarantees": {"per_stream": "responses keep request order"},
    },
}


def test_NEGATIVE_verdict_stands_when_the_only_fact_bearing_field_failed(tmp_path):
    """The universal claim is true here, so the ERROR must still fire."""
    proj, schema = _mk(tmp_path, _ONLY_FACT_BEARING_FIELD_FAILED)
    r = _run(proj, "--schema-file", str(schema))
    assert _branch(r) == "ALL_FAILED", r.stdout
    assert "STATUS_PARTIALLY_EARNED" not in _cats(r), r.stdout


def test_POSITIVE_verdict_is_scoped_down_when_other_content_survived(tmp_path):
    """Same failure, but content the verdict never tested also exists.

    The failure itself must still be reported; what must NOT be reported is a
    verdict over the whole layer.
    """
    proj, schema = _mk(tmp_path, _FAILED_FIELD_BESIDE_SURVIVING_CONTENT)
    r = _run(proj, "--schema-file", str(schema))
    assert _branch(r) is None, "overreaching verdict survived: " + r.stdout
    # The genuine sub-finding is untouched — this is a scoping fix, not a
    # deletion.
    assert "DEFAULT_VALUE_KEY_IS_NOT_A_DESIGN_ENTITY" in _errs(r), r.stdout
    w = _finding(r, "STATUS_PARTIALLY_EARNED")
    assert w is not None and w["severity"] == "WARNING", r.stdout
    assert w["evidence"]["failed"] == ["default_signal_values"], w
    assert set(w["evidence"]["surviving"]) == {
        "supported_topologies", "role_summary", "ordering_guarantees"}, w


def test_payload_window_counts_containers_the_gate_never_enumerated(tmp_path):
    """The regression guard for the defect class itself.

    The payload was identified by an allow-list of container names that matched
    exactly ONE producer's fixed schema, so containers written by every other
    producer were invisible and the verdict's scope claim covered fields it had
    never looked at. Identification is now by subtracting the closed envelope,
    so an unrecognised container counts as payload by default.
    """
    proj, schema = _mk(tmp_path, {
        "extraction_status": "EXTRACTED",
        "fields": {"a_container_no_list_anticipates": [{"k": "v"}],
                   "another_one_entirely": {"k": "v"}}})
    info = json.loads(_run(proj, "--schema-file", str(schema)).stdout)["info"]
    assert set(info["payload_fields_populated"]) == {
        "a_container_no_list_anticipates", "another_one_entirely"}, info


def test_envelope_is_never_mistaken_for_payload(tmp_path):
    """Schema bookkeeping must not acquit a layer.

    Producers copy identity keys down into the payload container, so subtracting
    the envelope has to happen wherever the key sits. If bookkeeping counted as
    surviving payload, a document with nothing but a failed harvest would look
    partly earned.
    """
    doc = json.loads(json.dumps(_ONLY_FACT_BEARING_FIELD_FAILED))
    doc["fields"]["ic_name"] = "widget_top"
    doc["fields"]["schema_version"] = "v0.0.0"
    doc["fields"]["_private_bookkeeping"] = {"merged": True}
    proj, schema = _mk(tmp_path, doc)
    r = _run(proj, "--schema-file", str(schema))
    assert _branch(r) == "ALL_FAILED", r.stdout
    info = json.loads(r.stdout)["info"]
    assert "ic_name" not in info["payload_fields_populated"], info
    assert "_private_bookkeeping" not in info["payload_fields_populated"], info


def test_narrative_content_alone_cannot_acquit_the_status(tmp_path):
    """W1's rule applied symmetrically.

    Prose may not carry the verdict against the layer; it equally may not carry
    the verdict for it. A document whose only non-failed content is narrative
    has still earned nothing.
    """
    doc = json.loads(json.dumps(_ONLY_FACT_BEARING_FIELD_FAILED))
    doc["fields"]["typical_topologies"] = ["a shared bus with one arbiter"]
    doc["fields"]["multi_copy_atomicity"] = {"note": "single copy only"}
    proj, schema = _mk(tmp_path, doc)
    r = _run(proj, "--schema-file", str(schema))
    assert _branch(r) == "ALL_FAILED", r.stdout


def test_empty_payload_branch_is_distinguishable_from_all_failed(tmp_path):
    """Both branches remain reachable and are told apart by their evidence."""
    proj, schema = _mk(tmp_path, {"extraction_status": "EXTRACTED",
                                  "fields": {"interconnect_rules": [],
                                             "default_signal_values": {},
                                             "id_routing": {}}})
    assert _branch(_run(proj, "--schema-file", str(schema))) == "EMPTY_PAYLOAD"


def test_a_clean_layer_gets_neither_verdict(tmp_path):
    """The mirror: no failure, so neither the verdict nor its scoped sibling."""
    proj, schema = _mk(tmp_path, _WELL_FORMED)
    r = _run(proj, "--schema-file", str(schema))
    assert _branch(r) is None, r.stdout
    assert "STATUS_PARTIALLY_EARNED" not in _cats(r), r.stdout


def test_no_design_or_vendor_literal_in_the_gate():
    src = PROG.read_text()
    body = src.split('"""', 2)[-1]
    banned = ("sky130", "gf180", "ihp-sg13", "nangate", "ibex", "AXI",
              "ARVALID", "ACLK", "VDD", "VSS", "spm", "subservient")
    for tok in banned:
        assert tok not in body, f"design/PDK literal {tok!r} leaked into gate"
