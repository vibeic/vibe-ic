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

import json
import sys
from pathlib import Path

import pytest

# Every test marked below applies a draft-2020-12 JSON Schema, directly or
# through `ppa_contract_check.py`. On a jsonschema too old to carry
# `Draft202012Validator` the schema is NOT applied and the honest verdict is a
# named SKIP -- see `_ppa_jsonschema.py`. Before this marker existed those
# tests reported a FAILURE, which made "I could not look" indistinguishable
# from "I looked and it was broken".

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from _ppa import contract as C, identity as ident, provenance as prov  # noqa: E402


# ---------------------------------------------------------------------------
# positive
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# negative -- each is the base fixture with ONE field changed
# ---------------------------------------------------------------------------















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

















# ---------------------------------------------------------------------------
# the schema is enforceable, not decorative
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# the evidence manifest — two ways a citation can be worthless
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# authority order — opt-in, and never silent
# ---------------------------------------------------------------------------













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














def test_an_unregistered_finding_code_is_refused():
    """The registry only works if it cannot be bypassed. Positive control for
    the guard itself: the registered code is accepted in the same breath."""
    with pytest.raises(ValueError, match="unregistered finding code"):
        C.finding("PPA-C-999", C.SEV_FAIL, "invented out of nowhere")
    ok = C.finding("PPA-C-001", C.SEV_FAIL, "a registered one still works")
    assert ok["code"] == "PPA-C-001"
    with pytest.raises(ValueError, match="unknown severity"):
        C.finding("PPA-C-001", "PROBABLY_BAD", "severity is a closed set too")
