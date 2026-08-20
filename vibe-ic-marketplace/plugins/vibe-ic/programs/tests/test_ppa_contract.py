#!/usr/bin/env python3
"""The four fixtures for `ppa_contract_build` / `ppa_contract_check`.

    positive   green when it should be green
    negative   RED when it should be red -- and each red case here is the
               SAME base fixture with one field changed, so "the gate refuses
               everything" cannot pass for "the gate discriminates"
    vacuous    absent input gives rc=2 with a printed marker, never 0, never 1
    mutation   see RESULT.md: reverting a named clause reddens a named test,
               run both ways

WHAT THE VACUOUS CASES ARE ACTUALLY DEFENDING
=============================================
rc=1 in these programs means a claim about a design: "these two runs were not
solving the same problem", "this power number was computed from an assumption".
A run that never opened its input must not be able to make that claim, and a
run that never opened its input must not report clean either. Both halves are
asserted below, on the exit code AND on the printed marker, because a rc nobody
prints is invisible in a log.

chip-AGNOSTIC throughout: synthetic bytes and declared policy only.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_ppa_contract_fixtures import (  # noqa: E402
    BUILD, CHECK, FAKE_IMAGE, INTEGRITY, SCHEMA_DIR,
    base_declaration, build_contract, codes, make_run_tree, run_cli,
    write_json,
)

from _ppa import contract as C, identity as ident, provenance as prov  # noqa: E402


# ---------------------------------------------------------------------------
# positive
# ---------------------------------------------------------------------------

def test_a_clean_declaration_builds_and_validates(tmp_path):
    built = build_contract(tmp_path, base_declaration())
    assert built.returncode == 0, built.stderr
    assert "[PASS]" in (built.stdout + built.stderr) or built.returncode == 0
    document = json.loads((tmp_path / "contract.json").read_text())
    assert document["schema"] == C.CONTRACT_SCHEMA
    for kind in ident.IDENTITY_KINDS:
        record = document["identities"][kind]
        assert record["status"] == "MEASURED", (kind, record.get("reason"))
        assert record["digest"].startswith("sha256:")
    checked = run_cli(CHECK, "--contract", str(tmp_path / "contract.json"))
    assert checked.returncode == 0, checked.stderr
    assert "[PASS]" in checked.stdout


def test_the_contract_hashes_to_its_own_stated_digest(tmp_path):
    build_contract(tmp_path, base_declaration())
    document = json.loads((tmp_path / "contract.json").read_text())
    assert document["contract_digest"] == C.contract_digest_of(document)


# ---------------------------------------------------------------------------
# negative -- each is the base fixture with ONE field changed
# ---------------------------------------------------------------------------

def test_sdc_and_l19_disagreement_is_refused_and_NAMED(tmp_path):
    """The canonical conflict. rc=1, and the message must carry both values and
    both sources -- a refusal that says only "sources disagree" leaves the
    reader to diff two trees by hand, which is where the answer stops being
    used."""
    decl = base_declaration()
    decl["problem"]["facts"][1]["value"] = 8.0          # L19 now says 8.0
    built = build_contract(tmp_path, decl)
    assert built.returncode == 1, (
        f"a disagreeing SDC and spec layer must be rc=1, got "
        f"{built.returncode}\n{built.stdout}\n{built.stderr}")
    text = built.stdout + built.stderr
    assert "PPA-C-003" in text
    assert "constraints.clk.period_ns" in text
    for token in ("sdc", "l19_spec", "10.0", "8.0",
                  "spec/constraints.sdc", "spec/L19.json"):
        assert token in text, f"the refusal does not name {token!r}:\n{text}"


def test_the_identity_refuses_to_hash_a_conflict_independently(tmp_path):
    """The SECOND detector, and it shares no code with the first.

    `contract._check_conflicts` reports the conflict; `identity` refuses to
    produce a digest for a key with two values. Either alone could be silenced
    by an edit; both being red is what makes the finding hard to lose."""
    decl = base_declaration()
    decl["problem"]["facts"][1]["value"] = 8.0
    build_contract(tmp_path, decl)
    document = json.loads((tmp_path / "contract.json").read_text())
    problem = document["identities"]["problem"]
    assert problem["status"] == "NOT_MEASURED"
    assert "digest" not in problem, (
        "a conflicting problem identity must carry NO digest -- a digest over "
        "one of two disputed values buries the conflict where nothing "
        "downstream can see it")
    assert any(c["key"] == "constraints.clk.period_ns"
               for c in problem["conflicts"])


def test_a_floating_verdict_bearing_image_is_refused(tmp_path):
    decl = base_declaration()
    decl["toolchain"]["images"][0]["ref"] = "ghcr.io/vibeic-test/img:latest"
    built = build_contract(tmp_path, decl)
    assert built.returncode == 1, built.stdout + built.stderr
    assert "PPA-C-002" in codes(built)


def test_a_floating_image_that_carries_no_verdict_is_not_refused(tmp_path):
    """The green twin. Without it, `PPA-C-002` would also pass for a rule that
    refuses every tag, which is a different and much less useful rule.

    A SECOND, digest-pinned image is present on purpose. Two separate rules
    apply to a tag and this test is about only one of them: the tag is not
    REFUSED because it carries no verdict (PPA-C-002), while the toolchain
    still has to be IDENTIFIABLE from something (a tag contributes no digest,
    so on its own it leaves the toolchain identity NOT_MEASURED). Keeping the
    two apart is what makes each of them falsifiable on its own."""
    decl = base_declaration()
    decl["toolchain"]["images"] = [
        {"role": "docs", "ref": "ghcr.io/vibeic-test/img:latest",
         "verdict_bearing": False},
        {"role": "eda", "ref": FAKE_IMAGE, "verdict_bearing": True},
    ]
    built = build_contract(tmp_path, decl)
    assert built.returncode == 0, built.stdout + built.stderr
    assert "PPA-C-002" not in codes(built)


def test_a_toolchain_known_only_by_a_tag_cannot_be_identified(tmp_path):
    """The other half, split out from the test above.

    A tag contributes no digest, so a run whose only toolchain evidence is a
    tag has not said WHICH tools ran — even when nothing about that image
    carries a verdict. rc=2 UNDETERMINED, never 0."""
    decl = base_declaration()
    decl["toolchain"]["images"] = [
        {"role": "docs", "ref": "ghcr.io/vibeic-test/img:latest",
         "verdict_bearing": False}]
    built = build_contract(tmp_path, decl, name="tag_only.json")
    assert built.returncode == 2, built.stdout + built.stderr
    assert "PPA-C-007" in codes(built)
    document = json.loads((tmp_path / "tag_only.json").read_text())
    assert document["identities"]["toolchain"]["status"] == "NOT_MEASURED"


def test_an_unread_image_label_is_a_note_and_not_a_verdict(tmp_path):
    """NOT_MEASURED, printed, and rc stays 0.

    The digest already pins the bytes a verdict rests on; the OCI label is the
    human convenience beside it. Making an unread label UNDETERMINED would
    produce a gate that can never be green on a host without a registry, and
    rc=2 may never be mapped to PASS -- so it would wedge."""
    built = build_contract(tmp_path, base_declaration())
    assert built.returncode == 0
    assert "PPA-C-014" in codes(built)
    document = json.loads((tmp_path / "contract.json").read_text())
    version = document["run_manifest"]["images"][0]["version"]
    assert version["status"] == "NOT_MEASURED"
    assert "value" not in version, (
        "an unread label must not carry a version -- a remembered number here "
        "is the exact guess the OCI-label rule exists to forbid")
    assert version["label"] == prov.IMAGE_VERSION_LABEL


def test_the_image_version_is_read_from_the_label_when_it_can_be(tmp_path):
    """The label path itself, with the reader injected.

    The CLI runs `--no-image-labels` everywhere else so no test depends on a
    registry. That would leave the reading branch unmeasured, so it is measured
    here at the library seam."""
    record = prov.image_record(
        {"role": "eda", "ref": FAKE_IMAGE, "verdict_bearing": True},
        reader=lambda ref: "1.2.3")
    assert record["version"] == {
        "status": "MEASURED", "value": "1.2.3",
        "label": prov.IMAGE_VERSION_LABEL, "source": "oci_label"}
    unread = prov.image_record(
        {"role": "eda", "ref": FAKE_IMAGE, "verdict_bearing": True},
        reader=lambda ref: None)
    assert unread["version"]["status"] == "NOT_MEASURED"
    assert "value" not in unread["version"]


def test_the_image_version_is_never_read_off_a_floating_reference(tmp_path):
    """Even if a reader would answer. A label read off a tag records the
    version of whatever the tag pointed at at that moment, which is the
    floating value the whole rule refuses."""
    record = prov.image_record(
        {"role": "eda", "ref": "ghcr.io/vibeic-test/img:latest",
         "verdict_bearing": True},
        reader=lambda ref: "9.9.9")
    assert record["version"]["status"] == "NOT_MEASURED"
    assert "9.9.9" not in json.dumps(record)


@pytest.mark.parametrize("target,expect_rc", [
    ("constraints.clk.period_ns", 1),   # forbidden outright
    ("pdk.metal_stack", 1),             # forbidden outright
    ("synth.effort", 1),                # simply not in the allow-list
    ("pnr.density", 0),                 # IN the allow-list -- the green twin
    ("synth.strategy", 0),              # exact allow-list entry
])
def test_candidate_mutations_are_checked_against_a_closed_allow_list(
        tmp_path, target, expect_rc):
    decl = base_declaration()
    decl["candidate"]["mutations"] = [{"target": target, "from": 1, "to": 2}]
    built = build_contract(tmp_path, decl)
    assert built.returncode == expect_rc, (
        f"mutation {target!r} expected rc={expect_rc}, got "
        f"{built.returncode}\n{built.stdout}\n{built.stderr}")
    if expect_rc == 1:
        assert "PPA-C-005" in codes(built)


def test_an_absent_allow_list_is_undetermined_and_an_empty_one_refuses(tmp_path):
    """The distinction this whole package is built on, at the policy layer.

    ABSENT means the check could not see what was permitted -> rc=2.
    EMPTY means nothing was permitted -> rc=1.
    Collapsing them would make "I could not read the policy" and "the policy
    forbids this" the same output."""
    absent = base_declaration()
    absent["candidate"]["mutations"] = [{"target": "pnr.density"}]
    absent["policy"].pop("mutation_allow_list")
    built = build_contract(tmp_path, absent, name="absent.json")
    assert built.returncode == 2, built.stdout + built.stderr
    assert "PPA-C-011" in codes(built)

    empty = base_declaration()
    empty["candidate"]["mutations"] = [{"target": "pnr.density"}]
    empty["policy"]["mutation_allow_list"] = []
    built2 = build_contract(tmp_path, empty, name="empty.json")
    assert built2.returncode == 1, built2.stdout + built2.stderr
    assert "PPA-C-005" in codes(built2)


@pytest.mark.parametrize("policy,expect_rc", [
    ("REFUSE", 1),
    ("UNDETERMINED", 2),
])
def test_a_power_metric_without_an_activity_basis_follows_declared_policy(
        tmp_path, policy, expect_rc):
    decl = base_declaration()
    decl["policy"]["missing_power_basis"] = policy
    decl["metrics"].append({
        "schema": "vibeic.ppa.metric.v1", "metric": "power.total_mw",
        "status": "MEASURED", "value": 1.2, "unit": "mW",
        "scope": {"stage": "post_route_extracted"},
        "source": {"path": "sta/setup.rpt"}})
    built = build_contract(tmp_path, decl)
    assert built.returncode == expect_rc, built.stdout + built.stderr
    assert "PPA-C-004" in codes(built)


def test_a_power_metric_WITH_an_activity_basis_is_clean(tmp_path):
    """The green twin: the rule is about the missing basis, not about power."""
    decl = base_declaration()
    decl["metrics"].append({
        "schema": "vibeic.ppa.metric.v1", "metric": "power.total_mw",
        "status": "MEASURED", "value": 1.2, "unit": "mW",
        "scope": {"stage": "post_route_extracted", "activity_basis": "vcd"},
        "source": {"path": "sta/setup.rpt"}})
    built = build_contract(tmp_path, decl)
    assert built.returncode == 0, built.stdout + built.stderr


def test_an_undeclared_power_policy_picks_neither_answer(tmp_path):
    decl = base_declaration()
    decl["policy"].pop("missing_power_basis")
    decl["metrics"].append({
        "schema": "vibeic.ppa.metric.v1", "metric": "power.total_mw",
        "status": "MEASURED", "value": 1.2, "unit": "mW",
        "scope": {}, "source": {"path": "sta/setup.rpt"}})
    built = build_contract(tmp_path, decl)
    assert built.returncode == 2, built.stdout + built.stderr
    assert "PPA-C-011" in codes(built)


@pytest.mark.parametrize("metric,why", [
    ({"metric": "area.core_um2", "status": "NOT_MEASURED", "value": 0,
      "reason": "extraction did not run"},
     "a 0 on a NOT_MEASURED row is a sentinel that reads as data"),
    ({"metric": "area.core_um2", "status": "NOT_MEASURED", "value": -1,
      "reason": "extraction did not run"},
     "-1 is the same sentinel wearing a different number"),
    ({"metric": "area.core_um2", "status": "NOT_MEASURED"},
     "NOT_MEASURED without a reason cannot be acted on"),
    ({"metric": "area.core_um2", "status": "ESTIMATED", "value": 1234.0},
     "ESTIMATED is outside final PPA entirely"),
    ({"metric": "area.core_um2", "status": "DERIVED", "value": 1234.0},
     "DERIVED with no formula cannot be recomputed by a reader"),
    ({"metric": "area.core_um2", "status": "MEASURED"},
     "MEASURED with no value is a row that measured nothing"),
])
def test_no_invented_number_survives(tmp_path, metric, why):
    decl = base_declaration()
    metric = dict(metric)
    metric.setdefault("schema", "vibeic.ppa.metric.v1")
    metric.setdefault("source", {"path": "sta/setup.rpt"})
    decl["metrics"].append(metric)
    built = build_contract(tmp_path, decl)
    assert built.returncode == 1, f"{why}\n{built.stdout}\n{built.stderr}"
    assert "PPA-C-006" in codes(built)


def test_a_declared_default_is_a_refusal(tmp_path):
    decl = base_declaration()
    decl["policy"]["defaults_used"] = ["power.activity_basis=0.2"]
    built = build_contract(tmp_path, decl)
    assert built.returncode == 1, built.stdout + built.stderr
    assert "PPA-C-006" in codes(built)


def test_an_assumed_fact_may_not_enter_an_identity(tmp_path):
    decl = base_declaration()
    decl["analysis"]["facts"].append(
        {"key": "analysis.voltage_v", "value": 1.62, "source": "runner",
         "origin": "default"})
    built = build_contract(tmp_path, decl)
    assert built.returncode == 1, built.stdout + built.stderr
    assert "PPA-C-006" in codes(built)


def test_a_metric_citing_an_artefact_outside_the_evidence_manifest_refuses(
        tmp_path):
    decl = base_declaration()
    decl["metrics"][0]["source"]["path"] = "sta/some_other_report.rpt"
    built = build_contract(tmp_path, decl)
    assert built.returncode == 1, built.stdout + built.stderr
    assert "PPA-C-008" in codes(built)


def test_a_contract_edited_after_it_was_built_is_refused(tmp_path):
    """The digest is what makes the document tamper-evident, so the tamper
    must actually be caught rather than merely made possible."""
    build_contract(tmp_path, base_declaration())
    path = tmp_path / "contract.json"
    document = json.loads(path.read_text())
    document["metrics"][0]["value"] = -0.001      # a much nicer WNS
    path.write_text(json.dumps(document))
    checked = run_cli(CHECK, "--contract", str(path))
    assert checked.returncode == 1, checked.stdout + checked.stderr
    assert "PPA-C-001" in codes(checked)


def test_a_declared_artefact_that_is_absent_makes_its_identity_not_measured(
        tmp_path):
    decl = base_declaration()
    decl["implementation"]["artefacts"].append(
        {"role": "netlist", "path": "synth/never_written.v"})
    built = build_contract(tmp_path, decl)
    assert built.returncode == 2, built.stdout + built.stderr
    assert "PPA-C-007" in codes(built)
    document = json.loads((tmp_path / "contract.json").read_text())
    impl = document["identities"]["implementation"]
    assert impl["status"] == "NOT_MEASURED"
    assert "digest" not in impl, (
        "an identity with an unreadable member must carry NO digest: a hash "
        "over 'everything except the file I could not open' is a confident "
        "value that silently means something narrower than it claims")


def test_an_artefact_outside_the_declared_root_is_not_followed(tmp_path):
    decl = base_declaration()
    decl["problem"]["artefacts"].append(
        {"role": "escape", "path": "../declaration.json"})
    built = build_contract(tmp_path, decl)
    assert built.returncode == 2, built.stdout + built.stderr
    document = json.loads((tmp_path / "contract.json").read_text())
    rows = {r["role"]: r for r in document["run_manifest"]["artefacts"]}
    assert rows["escape"]["status"] == "NOT_MEASURED"
    assert "escapes" in rows["escape"]["reason"]


# ---------------------------------------------------------------------------
# the rule-9 distinction, at the layer it is easiest to lose
# ---------------------------------------------------------------------------

def test_an_empty_file_and_an_absent_file_are_different_records(tmp_path):
    """"I could not read it" and "I read it and it was empty" must never
    produce the same verdict. An empty file has a real sha256 and a real size
    of zero; an absent one has neither and carries a reason instead."""
    root = tmp_path / "run"
    root.mkdir()
    (root / "empty.rpt").write_text("")
    empty = prov.artefact_ref(root, "empty.rpt", "r")
    absent = prov.artefact_ref(root, "gone.rpt", "r")
    assert empty["status"] == prov.MEASURED
    assert empty["sha256"] == prov.EMPTY_FILE_SHA256
    assert empty["bytes"] == 0
    assert absent["status"] == prov.NOT_MEASURED
    assert absent["reason"] == "absent"
    assert "sha256" not in absent and "bytes" not in absent
    assert empty != absent


def test_two_identities_that_each_failed_to_read_something_are_not_the_same(
        tmp_path):
    left = ident.identity("problem", [
        {"role": "a", "path": "a", "status": prov.NOT_MEASURED,
         "reason": "absent"}])
    right = ident.identity("problem", [
        {"role": "b", "path": "b", "status": prov.NOT_MEASURED,
         "reason": "absent"}])
    verdict = ident.compare(left, right)
    assert verdict["verdict"] == "UNDETERMINED", (
        "two runs that each failed to measure a DIFFERENT thing are not "
        "thereby the same run")


# ---------------------------------------------------------------------------
# vacuous
# ---------------------------------------------------------------------------

def test_build_on_an_absent_declaration_cannot_check(tmp_path):
    built = run_cli(BUILD, "--declaration", str(tmp_path / "nope.json"),
                    "--root", str(tmp_path), "--out", str(tmp_path / "c.json"))
    assert built.returncode == 2, (
        f"an absent declaration must be rc=2, not {built.returncode}; rc=1 "
        f"would be a claim about a design nobody looked at")
    assert "[CANNOT CHECK]" in built.stderr
    assert not (tmp_path / "c.json").exists()


def test_build_on_a_missing_root_cannot_check(tmp_path):
    decl = write_json(tmp_path / "d.json", base_declaration())
    built = run_cli(BUILD, "--declaration", str(decl),
                    "--root", str(tmp_path / "no_such_dir"),
                    "--out", str(tmp_path / "c.json"))
    assert built.returncode == 2
    assert "[CANNOT CHECK]" in built.stderr


def test_build_on_unparseable_json_cannot_check(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json")
    built = run_cli(BUILD, "--declaration", str(bad), "--root", str(tmp_path),
                    "--out", str(tmp_path / "c.json"))
    assert built.returncode == 2
    assert "[CANNOT CHECK]" in built.stderr


def test_check_on_an_absent_contract_cannot_check(tmp_path):
    checked = run_cli(CHECK, "--contract", str(tmp_path / "nope.json"))
    assert checked.returncode == 2
    assert "[CANNOT CHECK]" in checked.stderr


def test_check_without_a_readable_schema_does_not_report_clean(tmp_path):
    """A validator that could not load its schema has established nothing.

    Reporting on the remaining clauses and exiting 0 would make "I could not
    apply the schema" and "the schema found nothing" the same output -- the
    defect this package exists to remove, reappearing in the tool that
    removes it."""
    build_contract(tmp_path, base_declaration())
    checked = run_cli(CHECK, "--contract", str(tmp_path / "contract.json"),
                      "--schema-dir", str(tmp_path / "no_schemas_here"))
    assert checked.returncode == 2, (
        f"expected rc=2 with no schema, got {checked.returncode}\n"
        f"{checked.stdout}\n{checked.stderr}")
    assert "PPA-C-010" in codes(checked)
    assert "[CANNOT CHECK]" in checked.stderr


def test_check_refuses_a_document_that_is_not_a_contract(tmp_path):
    path = write_json(tmp_path / "other.json", {"schema": "something.else.v1"})
    checked = run_cli(CHECK, "--contract", str(path))
    assert checked.returncode == 2
    assert "PPA-C-010" in codes(checked)


def test_no_program_in_this_lane_writes_a_report_nobody_asked_for(tmp_path):
    """A read-only validator must not deposit a file at a path the caller did
    not name. `--json` is the only way anything is written."""
    build_contract(tmp_path, base_declaration())
    before = sorted(p.name for p in tmp_path.iterdir())
    run_cli(CHECK, "--contract", str(tmp_path / "contract.json"))
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_the_json_report_is_written_when_it_is_asked_for(tmp_path):
    build_contract(tmp_path, base_declaration())
    out = tmp_path / "report.json"
    checked = run_cli(CHECK, "--contract", str(tmp_path / "contract.json"),
                      "--json", str(out))
    assert checked.returncode == 0
    report = json.loads(out.read_text())
    assert report["program"] == "ppa_contract_check"
    assert report["rc"] == 0
    assert isinstance(report["findings"], list)


# ---------------------------------------------------------------------------
# the schema is enforceable, not decorative
# ---------------------------------------------------------------------------

def test_the_shipped_schemas_are_valid_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    for name in ("contract.v1.schema.json", "run_manifest.v1.schema.json"):
        path = SCHEMA_DIR / name
        assert path.exists(), f"{path} is not in the tree"
        jsonschema.Draft202012Validator.check_schema(
            json.loads(path.read_text()))


def test_the_schema_and_the_validator_agree_on_a_clean_contract(tmp_path):
    """Two independent statements of the same rules must not drift apart."""
    jsonschema = pytest.importorskip("jsonschema")
    build_contract(tmp_path, base_declaration())
    document = json.loads((tmp_path / "contract.json").read_text())
    schema = json.loads((SCHEMA_DIR / "contract.v1.schema.json").read_text())
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(document))
    assert not errors, [e.message for e in errors]
    assert C.validate(document) == [] or all(
        f["severity"] == C.SEV_NOTE for f in C.validate(document))


def test_the_schema_refuses_a_sentinel_on_a_not_measured_metric():
    """The no-sentinel rule is stated declaratively as well as in code, so a
    consumer that only has the schema still gets it."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((SCHEMA_DIR / "contract.v1.schema.json").read_text())
    metric_schema = {"$defs": schema["$defs"], **schema["$defs"]["metric"]}
    validator = jsonschema.Draft202012Validator(metric_schema)
    bad = {"metric": "area.core_um2", "status": "NOT_MEASURED", "value": 0,
           "reason": "x"}
    assert list(validator.iter_errors(bad)), (
        "contract.v1 accepts a NOT_MEASURED metric carrying a value")
    good = {"metric": "area.core_um2", "status": "NOT_MEASURED", "reason": "x"}
    assert not list(validator.iter_errors(good))


# ---------------------------------------------------------------------------
# the evidence manifest — two ways a citation can be worthless
# ---------------------------------------------------------------------------

def test_a_declared_evidence_role_set_that_matches_nothing_is_not_everything(
        tmp_path):
    """ABSENT means "everything the run read". PRESENT-and-matching-nothing
    means NOTHING backs the verdict, and every citation is then unbacked.

    A `or all_artefacts` fallback would turn a filter that matched nothing into
    a filter over everything, silently — the same absent/empty collapse this
    package refuses at the file and policy layers."""
    decl = base_declaration()
    decl["verdict_evidence_roles"] = ["a_role_no_artefact_has"]
    built = build_contract(tmp_path, decl)
    assert built.returncode == 1, built.stdout + built.stderr
    assert "PPA-C-008" in codes(built)
    document = json.loads((tmp_path / "contract.json").read_text())
    assert document["evidence_manifest"]["artefacts"] == []

    narrowed = base_declaration()
    narrowed["verdict_evidence_roles"] = ["sta_setup"]
    ok = build_contract(tmp_path, narrowed, name="narrowed.json")
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_a_metric_read_from_an_unhashable_artefact_is_refused(tmp_path):
    """The number exists; the file behind it does not hash. Nothing can
    confirm the number came from this run."""
    decl = base_declaration()
    decl["analysis"]["artefacts"].append(
        {"role": "power_rpt", "path": "sta/power_never_written.rpt"})
    decl["metrics"].append({
        "schema": "vibeic.ppa.metric.v1", "metric": "power.total_mw",
        "status": "MEASURED", "value": 1.2, "unit": "mW",
        "scope": {"stage": "post_route_extracted", "activity_basis": "vcd"},
        "source": {"path": "sta/power_never_written.rpt"}})
    built = build_contract(tmp_path, decl)
    assert built.returncode == 1, built.stdout + built.stderr
    assert "PPA-C-008" in codes(built)
    assert "NOT_MEASURED" in (built.stdout + built.stderr)


# ---------------------------------------------------------------------------
# authority order — opt-in, and never silent
# ---------------------------------------------------------------------------

def test_an_opted_in_key_is_resolved_by_authority_and_the_loser_is_NAMED(
        tmp_path):
    """The default is refusal. Opting a key in buys a winner, and the price is
    that the resolution is PRINTED: which source won, what it said, and what
    every overridden source said. A resolution applied silently destroys the
    one fact a reader needs."""
    decl = base_declaration()
    decl["problem"]["facts"][1]["value"] = 8.0      # l19_spec disagrees
    decl["policy"]["resolvable_fact_keys"] = ["constraints.clk.period_ns"]
    built = build_contract(tmp_path, decl)
    assert built.returncode == 0, built.stdout + built.stderr
    text = built.stdout + built.stderr
    assert "PPA-C-015" in text
    assert "PPA-C-003" not in text
    for token in ("sdc=10.0", "l19_spec=8.0"):
        assert token in text, f"the resolution does not name {token!r}:\n{text}"

    document = json.loads((tmp_path / "contract.json").read_text())
    resolution = document["resolutions"][0]
    assert resolution["key"] == "constraints.clk.period_ns"
    assert resolution["winner"]["source"] == "sdc"
    assert resolution["winner"]["value"] == 10.0
    assert resolution["overridden"][0]["value"] == 8.0


def test_a_resolved_key_lets_its_identity_be_measured_again(tmp_path):
    """The authority order exists so an identity has ONE value for a key. If
    the losing claims stayed in the fact list, `identity` would refuse to hash
    the key it had just been told how to settle and the opt-in would do
    nothing."""
    decl = base_declaration()
    decl["problem"]["facts"][1]["value"] = 8.0
    decl["policy"]["resolvable_fact_keys"] = ["constraints.clk.period_ns"]
    build_contract(tmp_path, decl)
    document = json.loads((tmp_path / "contract.json").read_text())
    problem = document["identities"]["problem"]
    assert problem["status"] == "MEASURED"
    facts = {f["key"]: f["value"] for f in problem["members"]["facts"]}
    assert facts["constraints.clk.period_ns"] == 10.0, (
        "the identity took the losing value, or took neither")


def test_the_resolved_identity_differs_from_the_unconflicted_one(tmp_path):
    """A resolution is not a no-op: settling a disputed key to the SDC's value
    must not silently produce the same identity as a run where nobody ever
    disagreed, because those are different runs and one of them has a spec
    that says something else."""
    clean = build_contract(tmp_path, base_declaration(), name="clean.json")
    assert clean.returncode == 0
    decl = base_declaration()
    decl["problem"]["facts"][1]["value"] = 8.0
    decl["policy"]["resolvable_fact_keys"] = ["constraints.clk.period_ns"]
    build_contract(tmp_path, decl, name="resolved.json")
    a = json.loads((tmp_path / "clean.json").read_text())
    b = json.loads((tmp_path / "resolved.json").read_text())
    assert a["identities"]["problem"]["digest"] == \
        b["identities"]["problem"]["digest"], (
        "the resolved value IS the problem, so the problem identity should "
        "match; if this ever needs to differ it is a v2 decision, not a drift")
    assert a["contract_digest"] != b["contract_digest"], (
        "the contract as a whole must still record that a source was "
        "overridden — otherwise the override is invisible downstream")


def test_an_unrankable_source_is_not_resolved_arbitrarily(tmp_path):
    """No winner can be picked, so none is. The alternative is whichever claim
    happened to be first, which is a coin toss wearing a policy's clothes."""
    decl = base_declaration()
    decl["problem"]["facts"][1]["value"] = 8.0
    decl["problem"]["facts"][1]["source"] = "a_source_nobody_ranked"
    decl["policy"]["resolvable_fact_keys"] = ["constraints.clk.period_ns"]
    built = build_contract(tmp_path, decl)
    assert built.returncode == 2, built.stdout + built.stderr
    assert "PPA-C-009" in codes(built)
    document = json.loads((tmp_path / "contract.json").read_text())
    assert document["resolutions"] == []
    assert document["identities"]["problem"]["status"] == "NOT_MEASURED"


def test_a_declared_authority_order_overrides_the_default(tmp_path):
    """The order is data, not a constant nothing reads."""
    decl = base_declaration()
    decl["problem"]["facts"][1]["value"] = 8.0
    decl["policy"]["resolvable_fact_keys"] = ["constraints.clk.period_ns"]
    decl["policy"]["authority_order"] = ["l19_spec", "sdc"]   # reversed
    built = build_contract(tmp_path, decl)
    assert built.returncode == 0, built.stdout + built.stderr
    document = json.loads((tmp_path / "contract.json").read_text())
    assert document["resolutions"][0]["winner"]["source"] == "l19_spec"
    assert document["resolutions"][0]["winner"]["value"] == 8.0


def test_two_images_with_one_label_version_get_two_toolchain_identities(
        tmp_path):
    """MEASURED on this host, 2026-08-21, and it is why the version is not in
    the digest.

        docker image inspect ghcr.io/vibeic/vibeic-eda:0.3.18 :0.3.19 \\
            --format '{{.Id}} {{index .Config.Labels
                              "org.opencontainers.image.version"}}'
        sha256:f34af8763eb0…  2026.06
        sha256:c86afee96458…  2026.06

    Two different releases of the composed EDA image carry the SAME
    `org.opencontainers.image.version`, because the label is inherited from the
    upstream base rather than set by the fork. So the label cannot tell two of
    our toolchains apart, and a toolchain identity built on it would give two
    different toolchains ONE identity — which is exactly the failure the
    contract exists to prevent.

    The DIGEST is what distinguishes them, so the digest is what is hashed and
    the label rides alongside as provenance. This test is synthetic and offline;
    it pins the RULE, not the two tags, so it keeps holding after the next
    release."""
    def build_with(ref):
        decl = base_declaration()
        decl["toolchain"]["images"][0]["ref"] = ref
        name = ref.split(":")[-1][:12] + ".json"
        proc = build_contract(tmp_path, decl, name=name)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return json.loads((tmp_path / name).read_text())

    repo = "ghcr.io/vibeic-test/eda"
    older = build_with(f"{repo}@sha256:{'a' * 64}")
    newer = build_with(f"{repo}@sha256:{'b' * 64}")
    assert (older["identities"]["toolchain"]["digest"]
            != newer["identities"]["toolchain"]["digest"]), (
        "two images with different digests produced ONE toolchain identity; "
        "a comparison across them would report the tools as unchanged")
    assert older["identities"]["problem"]["digest"] == \
        newer["identities"]["problem"]["digest"], (
        "moving the image moved the PROBLEM identity too, so the two "
        "identities are not actually separable")


def test_a_tag_is_refused_before_any_registry_is_consulted(tmp_path):
    """Also measured on this host: `imagetools inspect` on a TAG failed with
    `pull access denied … insufficient_scope`, while the SAME image by DIGEST
    answered. A tag is not merely unstable, it is not even reliably readable —
    one more reason `PPA-C-002` refuses one that carries a verdict.

    The refusal does not depend on the network: no reader is consulted for a
    reference that does not pin bytes."""
    consulted = []

    def reader(ref):
        consulted.append(ref)
        return "should never be used"

    record = prov.image_record(
        {"role": "eda", "ref": "ghcr.io/vibeic-test/eda:latest",
         "verdict_bearing": True}, reader=reader)
    assert consulted == [], (
        "a registry was consulted for a floating reference; the refusal must "
        "hold on a host with no network at all")
    assert record["floating"] is True
    assert record["version"]["status"] == "NOT_MEASURED"


def test_a_symlink_out_of_the_declared_root_is_not_followed(tmp_path):
    """`provenance._relative_within` checks the declared text AND the resolved
    path, and the docstring claims the second catches what the first cannot.

    A claim in a docstring that no test drives is prose. This drives it: the
    declaration reads as an innocent relative path and the FILESYSTEM is what
    leaves the root."""
    root = tmp_path / "run"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("content nobody else can reproduce\n")
    (root / "innocent.rpt").symlink_to(outside)

    row = prov.artefact_ref(root, "innocent.rpt", "sneaky")
    assert row["status"] == prov.NOT_MEASURED, (
        "a symlink leaving the declared root was hashed; the reference is not "
        "reproducible by anyone who does not also have that file")
    assert "escapes" in row["reason"]
    assert "sha256" not in row

    # The green twin: the same shape, staying inside the root, IS measured.
    inside = root / "real.txt"
    inside.write_text("content nobody else can reproduce\n")
    (root / "fine.rpt").symlink_to(inside)
    ok = prov.artefact_ref(root, "fine.rpt", "fine")
    assert ok["status"] == prov.MEASURED
    assert ok["sha256"].startswith("sha256:")


def test_a_dangling_symlink_is_not_the_same_as_an_absent_file(tmp_path):
    """Both are unreadable and they fail for different reasons, so they say
    different things. A reader chasing 'absent' looks for a producer that never
    ran; a reader chasing 'dangling symlink' looks for one that ran and was
    cleaned up underneath them."""
    root = tmp_path / "run"
    root.mkdir()
    (root / "dangling.rpt").symlink_to(root / "never_existed.rpt")
    dangling = prov.artefact_ref(root, "dangling.rpt", "r")
    absent = prov.artefact_ref(root, "not_there.rpt", "r")
    assert dangling["status"] == prov.NOT_MEASURED
    assert absent["status"] == prov.NOT_MEASURED
    assert dangling["reason"] != absent["reason"]
    assert dangling["reason"] == "dangling symlink"


def test_the_embedded_run_manifest_is_validated_against_its_own_schema(
        tmp_path):
    """`run_manifest.v1.schema.json` ships; something must APPLY it.

    `contract.v1` types the embedded manifest only as `object`, so before this
    the file was a schema nothing enforced — which states a rule that is not in
    force and is worse than no schema, because a reader believes it.

    The red case is the manifest's own load-bearing rule: an artefact row that
    is NOT_MEASURED must not also carry a hash. If it could, "I could not read
    it" and "I read it and it was empty" would be indistinguishable at the
    schema layer even though the code keeps them apart."""
    build_contract(tmp_path, base_declaration())
    path = tmp_path / "contract.json"
    document = json.loads(path.read_text())
    document["run_manifest"]["artefacts"].append({
        "role": "smuggled", "path": "sta/setup.rpt",
        "status": "NOT_MEASURED", "reason": "could not read",
        "sha256": "sha256:" + "0" * 64, "bytes": 0})
    document["contract_digest"] = C.contract_digest_of(document)   # re-seal it
    path.write_text(json.dumps(document))

    checked = run_cli(CHECK, "--contract", str(path))
    assert checked.returncode == 1, (
        f"a NOT_MEASURED artefact carrying a hash passed the schema layer "
        f"(rc={checked.returncode})\n{checked.stdout}\n{checked.stderr}")
    text = checked.stdout + checked.stderr
    assert "run_manifest.v1" in text, (
        f"the finding does not say WHICH schema was violated:\n{text}")
    assert "run_manifest/" in text


def test_a_clean_contract_passes_both_schemas(tmp_path):
    """The green twin: adding the second schema must not start refusing the
    documents this lane itself produces."""
    built = build_contract(tmp_path, base_declaration())
    assert built.returncode == 0
    checked = run_cli(CHECK, "--contract", str(tmp_path / "contract.json"))
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_an_unreadable_run_manifest_schema_does_not_report_clean(tmp_path):
    build_contract(tmp_path, base_declaration())
    only_contract = tmp_path / "half_schemas"
    only_contract.mkdir()
    (only_contract / "contract.v1.schema.json").write_text(
        (SCHEMA_DIR / "contract.v1.schema.json").read_text())
    checked = run_cli(CHECK, "--contract", str(tmp_path / "contract.json"),
                      "--schema-dir", str(only_contract))
    assert checked.returncode == 2, (
        f"a missing run-manifest schema reported clean (rc="
        f"{checked.returncode})\n{checked.stdout}\n{checked.stderr}")
    assert "PPA-C-010" in codes(checked)


def test_an_identity_with_no_members_is_not_an_identity(tmp_path):
    """MEASURED before the rule existed: `identity('problem', [], [])` returned
    MEASURED with a perfectly good digest, and two such identities compared
    `SAME` — so two runs that had each declared NOTHING about the problem would
    be reported comparable.

    That is the empty-set-reports-clean defect arriving inside the module
    written to prevent it, and it is the worst shape here because the output
    looks like agreement rather than like a gap."""
    empty = ident.identity("problem", [], [])
    assert empty["status"] == prov.NOT_MEASURED
    assert "digest" not in empty
    assert "no members were declared" in empty["reason"]
    assert ident.compare(empty, ident.identity("problem", [], []))["verdict"] \
        == "UNDETERMINED"


def test_a_kind_with_nothing_to_say_must_say_so_rather_than_stay_silent(
        tmp_path):
    """The green twin, and the doctrine: you cannot get an identity by silence,
    only by declaration. One declared fact is enough — and it is a fact a
    reviewer can read, unlike an empty block."""
    silent = base_declaration()
    silent["agent_execution"] = {"facts": []}
    built = build_contract(tmp_path, silent, name="silent.json")
    assert built.returncode == 2, built.stdout + built.stderr
    assert "PPA-C-007" in codes(built)

    spoken = base_declaration()
    spoken["agent_execution"] = {
        "facts": [{"key": "agent.autonomy", "value": "none",
                   "source": "declared"}]}
    ok = build_contract(tmp_path, spoken, name="spoken.json")
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_two_runs_that_declared_nothing_are_not_reported_comparable(tmp_path):
    """The end-to-end consequence, driven through the real CLI. Without the
    rule this pair exits 0 and a reader is told the arms are comparable."""
    hollow = base_declaration()
    hollow["problem"] = {"artefacts": [], "facts": []}
    a = build_contract(tmp_path, hollow, name="a.json")
    b = build_contract(tmp_path, hollow, name="b.json")
    assert a.returncode == 2 and b.returncode == 2
    verdict = run_cli(INTEGRITY, "--baseline", str(tmp_path / "a.json"),
                      "--candidate", str(tmp_path / "b.json"))
    assert verdict.returncode == 2, (
        f"two runs that declared nothing about the problem were reported "
        f"comparable (rc={verdict.returncode})\n{verdict.stdout}\n"
        f"{verdict.stderr}")
    assert "PPA-C-007" in codes(verdict)


def test_a_clean_verdict_discloses_what_it_examined(tmp_path):
    """`0 finding(s)` over an empty contract and over a full one print the same
    zero, and only the denominator tells them apart. A contract is exactly the
    document that can be trivially clean by being trivially empty."""
    build_contract(tmp_path, base_declaration())
    checked = run_cli(CHECK, "--contract", str(tmp_path / "contract.json"),
                      "--json", str(tmp_path / "report.json"))
    assert checked.returncode == 0, checked.stderr
    text = checked.stdout
    assert "5/5 identities MEASURED" in text, text
    assert "4/4 declared artefacts hashed" in text, text
    assert "1 image(s) (1 verdict-bearing)" in text, text
    assert "1 metric(s), 1 carrying a value, 0 of them power" in text, text

    report = json.loads((tmp_path / "report.json").read_text())
    assert report["examined"]["identities_measured"] == 5
    assert report["examined"]["artefacts_declared"] == 4


def test_the_disclosure_moves_with_the_document(tmp_path):
    """A denominator that never changes is decoration. This is the positive
    control for the disclosure itself: add a metric and an artefact and the
    printed counts must follow."""
    decl = base_declaration()
    decl["analysis"]["artefacts"].append(
        {"role": "sta_hold", "path": "sta/setup.rpt"})
    decl["metrics"].append({
        "schema": "vibeic.ppa.metric.v1", "metric": "power.total_mw",
        "status": "MEASURED", "value": 1.2, "unit": "mW",
        "scope": {"activity_basis": "vcd"},
        "source": {"path": "sta/setup.rpt"}})
    build_contract(tmp_path, decl, name="fuller.json")
    checked = run_cli(CHECK, "--contract", str(tmp_path / "fuller.json"))
    assert checked.returncode == 0, checked.stderr
    assert "5/5 declared artefacts hashed" in checked.stdout, checked.stdout
    assert "2 metric(s), 2 carrying a value, 1 of them power" in checked.stdout


def test_the_disclosure_is_printed_on_a_refusal_too(tmp_path):
    """A reader triaging a red verdict needs the denominator most: it is how
    they tell 'one bad row out of forty' from 'the only row there was'."""
    decl = base_declaration()
    decl["toolchain"]["images"][0]["ref"] = "ghcr.io/vibeic-test/img:latest"
    build_contract(tmp_path, decl, name="red.json")
    checked = run_cli(CHECK, "--contract", str(tmp_path / "red.json"))
    assert checked.returncode != 0
    assert "examined:" in checked.stderr, checked.stderr


def test_every_finding_code_is_registered_and_documented():
    """A report carrying an identifier no document explains cannot be acted on.

    MEASURED while this was written: `ppa_contract_check`'s docstring had
    drifted TWO codes behind the code that emits them (`PPA-C-014`,
    `PPA-C-015`). Prose that lists codes rots silently, so the registry is the
    source and this is the check that keeps the prose attached to it."""
    programs_dir = Path(__file__).resolve().parents[1]
    docs = "\n".join(
        (programs_dir / name).read_text()
        for name in ("ppa_contract_build.py", "ppa_contract_check.py",
                     "ppa_problem_integrity_check.py"))
    undocumented = [c for c in sorted(C.FINDING_CODES) if c not in docs]
    assert not undocumented, (
        f"finding code(s) {undocumented} are emitted and named in no CLI "
        f"docstring")
    for code, meaning in C.FINDING_CODES.items():
        assert len(meaning) > 20, f"{code} has no usable one-line meaning"


def test_an_unregistered_finding_code_is_refused():
    """The registry only works if it cannot be bypassed. Positive control for
    the guard itself: the registered code is accepted in the same breath."""
    with pytest.raises(ValueError, match="unregistered finding code"):
        C.finding("PPA-C-999", C.SEV_FAIL, "invented out of nowhere")
    ok = C.finding("PPA-C-001", C.SEV_FAIL, "a registered one still works")
    assert ok["code"] == "PPA-C-001"
    with pytest.raises(ValueError, match="unknown severity"):
        C.finding("PPA-C-001", "PROBABLY_BAD", "severity is a closed set too")


def test_every_registered_code_is_actually_reachable():
    """A registry is also a place for a code nobody emits to hide. Each entry
    must appear in the source that produces findings, not only in prose."""
    programs_dir = Path(__file__).resolve().parents[1]
    emitters = "\n".join(
        (programs_dir / name).read_text()
        for name in ("_ppa/contract.py", "ppa_contract_check.py",
                     "ppa_problem_integrity_check.py"))
    for code in sorted(C.FINDING_CODES):
        # the registry entry itself is one occurrence; an emitted code has two
        assert emitters.count(f'"{code}"') >= 2, (
            f"{code} is registered but nothing emits it — a dead code in a "
            f"registry reads as a rule that is in force")
