#!/usr/bin/env python3
"""Regression for #2110 — the class profile for `serial_peripheral_protocol`.

THE DEFECT, MEASURED ON THE CLASS'S OWN CORPUS. #2094 named every registered
ic_class in the expert DB, twelve of them `null` — a DECLARED gap, so those
classes kept the unconfined phrase ranking. `serial_peripheral_protocol` is the
class the corpus supports best after the two already profiled: the shipped
classifier puts 22 corpus doc-sets in it, 11 of which carry a design INPUT the
retrieval can read. On pristine main, 10 of those 11 packs were led by an entry
from another design family — `serial-parallel-multiplier` on nine of them (the
same literal-phrase collision #2094 was opened for: a serial peripheral's own
prose says "serial", and the entry that owns that word is about a multiplier),
plus `axi-stream`, `axi-stream-width-downsizer`, `axi-mmio-cdc-datapath`,
`apb-csr-shift-register`, `priority-interrupt-controller`,
`line-buffer-window-extract` and `sipo-multiblock-crc-ecc-datapath`.

THE SELECTION IS DERIVED, NOT CHOSEN. Every db_class in the profile answers at
least one of the six structural features
`ic_class_profile._SERIAL_PROTO_FEATURES` uses to ASSIGN this class, and every
one of those six features has craft in the profile. `test_every_selected_db_
class_answers_a_feature_the_classifier_uses` pins that map in both directions:
an entry answering no feature carries knowledge with no referent in the class,
and a feature with no entry leaves a defining part of the class uncovered — and
the second is the half nobody notices.

WHAT IS NOT IN IT, AND WHY (both stated so a later reader does not have to
re-derive them): the DB's line-coding family — `line-encoder`,
`line-code-decoder`, `serial-line-encoder-mux`, `parallel-lfsr-prbs` — is real
craft that several designs of this class genuinely need, and it answers NONE of
the six features, so the derivation excludes it. `apb-csr-shift-register`
matches the shift-register feature on its NAME and is about an APB control/status
wrapper, which is another class's craft.

chip-AGNOSTIC: every fixture below is synthetic. The one real-corpus fact used
is the SENTENCE SHAPE of the collision, which names no chip, vendor, SKU or node.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import ic_expert_backup_pack as PACK          # noqa: E402
import ic_expert_db_query as Q                # noqa: E402
import ic_class_profile as ICP                # noqa: E402

_DB = _PROGRAMS.parent / "agents" / "ic_expert_db" / "ic_expert_db.json"

_CLASS = "serial_peripheral_protocol"

# A serial-peripheral brief reduced to its shape: the class's own structural
# vocabulary, plus the three neighbouring families whose words its prose
# unavoidably uses — a stream, a memory-mapped status register, an interrupt,
# and a checksum multiplier that forms partial products "in a serial-parallel
# fashion". Synthetic; no design, vendor or node named.
_SERIAL_PROMPT = (
    "Implement a synchronous serial peripheral that acts as either the "
    "controller or the target on a four-wire bus: a clock line, a data line in "
    "each direction, and a select line held low for the whole frame. The "
    "controller shifts one bit out per generated bit-clock edge and the target "
    "shifts the same frame in on the opposite edge. Each frame carries a start "
    "bit, eight data bits, a parity bit and a stop bit, and the receiver raises "
    "a framing error when the stop bit is not seen. Received frames are pushed "
    "into an AXI stream so the host can read them through a memory-mapped "
    "status register, and the payload checksum multiplier forms its partial "
    "products in a serial-parallel fashion while the frame streams past. An "
    "interrupt is raised to the host on each completed frame."
)

# The six features `_SERIAL_PROTO_FEATURES` tests for -> the DB entries whose
# craft answers each one. A LIST per feature, because two features of this class
# are answered by two entries and two others share one: the map states what is
# true, it is not forced into a bijection it does not have.
_FEATURE_TO_DB_CLASSES = {
    "role_pair": ["serial-parity-link"],
    "shift_register": ["serial-to-parallel-deserializer", "serial-in-parallel-out"],
    "serial_concept": ["serial-link-serdes"],
    "clock_baud_control": ["integer-clock-divider"],
    # a two-to-four wire surface IS one serial line plus a strobe or select
    "small_pin_count": ["serial-link-serdes", "spi-serializer-fsm"],
    "dedicated_function_pin": ["spi-serializer-fsm"],
}


def _db() -> dict:
    return json.loads(_DB.read_text())


def _profile() -> dict:
    p = _db()["registered_class_profiles"].get(_CLASS)
    assert isinstance(p, dict), f"{_CLASS!r} is not profiled in the expert DB"
    return p


def _null_profile_db(tmp_path: Path) -> Path:
    """The DB with this class back at its declared-gap `null` — the MUTATION
    arm. Reverting the profile, not deleting the name, is the right mutation:
    deleting it would also break the declared-gap invariant and the two effects
    would be impossible to tell apart."""
    db = _db()
    db["registered_class_profiles"][_CLASS] = None
    p = tmp_path / "db_null.json"
    p.write_text(json.dumps(db))
    return p


# ── 1. the profile, both directions ────────────────────────────────────────

def test_a_serial_peripheral_brief_gets_an_all_in_class_pack():
    allowed = set(_profile()["db_classes"])
    hits = Q.query(_SERIAL_PROMPT, k=5, ic_class=_CLASS)
    assert hits, "class-first retrieval returned nothing at all"
    got = {h["ic_class"] for h in hits}
    assert got <= allowed, f"out-of-class entries leaked in: {sorted(got - allowed)}"


def test_mutation_reverting_the_profile_brings_the_out_of_class_pack_back(tmp_path):
    """THE NEGATIVE CONTROL, on the SAME prompt. With this class back at `null`
    the identical brief retrieves an image-frame stream processor, a stream
    resizer, a serial-parallel MULTIPLIER and an APB CSR wrapper — the shape the
    real corpus measured. A fixture whose two arms agree proves nothing about
    the confinement, so this asserts they are DISJOINT, not merely different."""
    allowed = set(_profile()["db_classes"])
    got = {h["ic_class"] for h in
           Q.query(_SERIAL_PROMPT, k=5, db_path=_null_profile_db(tmp_path),
                   ic_class=_CLASS)}
    assert got, "the mutation arm retrieved nothing at all"
    assert not (got & allowed), (
        f"the mutation did not reproduce the defect — it still returned "
        f"in-class entries {sorted(got & allowed)}, so the positive assertion "
        f"above proves nothing about the profile")
    assert "serial-parallel-multiplier" in got, (
        "the collision this class was profiled for is not in the mutation arm; "
        "re-take the fixture against the corpus shape")


def test_the_class_decides_membership_not_the_phrase():
    """Every in-class entry is offered even when the brief never uses its words
    — membership is the CLASS's decision, and the ranking only orders it."""
    allowed = set(_profile()["db_classes"])
    assert {h["ic_class"] for h in Q.query("a design.", k=99, ic_class=_CLASS)} == allowed


def test_related_graph_cannot_reopen_this_class_boundary():
    """`integer-clock-divider` has no `related` links, but two of this class's
    entries do sit in the DB's concept graph. The expansion walks the CONFINED
    entries, so an out-of-class target resolves to nothing and is skipped."""
    allowed = set(_profile()["db_classes"])
    got = {h["ic_class"] for h in
           Q.query(_SERIAL_PROMPT, k=5, ic_class=_CLASS, expand_related=True)}
    assert got <= allowed, f"the related graph leaked {sorted(got - allowed)}"
    # the control: unconfined, the same call does NOT stay inside the class
    assert not {h["ic_class"] for h in
                Q.query(_SERIAL_PROMPT, k=5, expand_related=True)} <= allowed


def test_the_profiled_classes_select_disjoint_knowledge():
    """Two classes must not hand their designs the same entry. Pinned as
    MEMBERSHIP over EVERY profiled class, so the invariant keeps holding as the
    remaining null classes are profiled one landing at a time."""
    prof = _db()["registered_class_profiles"]
    named = {k: set(v["db_classes"]) for k, v in prof.items()
             if not k.startswith("_") and isinstance(v, dict)}
    assert len(named) >= 2, "only one class is profiled; this control is empty"
    items = sorted(named.items())
    for i, (a, sa) in enumerate(items):
        for b, sb in items[i + 1:]:
            assert not (sa & sb), f"profiles {a} and {b} share db_classes {sorted(sa & sb)}"


# ── 2. the selection is DERIVED from the classifier, not asserted ──────────

def test_every_selected_db_class_answers_a_feature_the_classifier_uses():
    """Both directions of the derivation, against the classifier's own table."""
    selected = set(_profile()["db_classes"])
    features = {name for name, _ in ICP._SERIAL_PROTO_FEATURES}
    assert features == set(_FEATURE_TO_DB_CLASSES), (
        f"the classifier's feature set moved to {sorted(features)}; the "
        f"profile's derivation has to be re-taken against it")
    for feat, entries in _FEATURE_TO_DB_CLASSES.items():
        assert entries, f"feature {feat!r} has no craft in the profile"
    mapped = {c for v in _FEATURE_TO_DB_CLASSES.values() for c in v}
    assert mapped == selected, (
        f"selected-but-unmapped {sorted(selected - mapped)} / "
        f"mapped-but-unselected {sorted(mapped - selected)}")


def test_the_profile_names_only_entries_the_db_carries():
    present = {e["ic_class"] for e in _db()["entries"]}
    for c in _profile()["db_classes"]:
        assert c in present, f"profile names {c!r}, entries[] does not carry it"


def test_the_line_coding_family_is_excluded_on_purpose_and_still_exists():
    """The exclusion is a DECISION, so it is pinned. These four entries are real
    craft for several designs of this class and answer none of the six features;
    if a later landing wants them, it must add the feature they answer, not
    quietly widen the list."""
    excluded = {"line-encoder", "line-code-decoder", "serial-line-encoder-mux",
                "parallel-lfsr-prbs", "apb-csr-shift-register"}
    present = {e["ic_class"] for e in _db()["entries"]}
    assert excluded <= present, "one of the deliberately-excluded entries is gone"
    assert not (excluded & set(_profile()["db_classes"]))


# ── 3. the pack, both directions ───────────────────────────────────────────

def test_the_pack_carries_the_class_contract(tmp_path):
    h = PACK.assemble(_SERIAL_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    cf = h["class_first"]
    assert h["interface_contract"] == "contract.md"
    assert cf["contract_kind"] == "class_integration_contract_md"
    assert cf["db_class_selection"] == "CLASS_CONFINED"
    body = (tmp_path / "contract.md").read_text()
    for req in _profile()["integration_contract"]:
        assert req in body, f"the contract document drops a requirement: {req[:60]}…"


def test_a_brief_that_names_no_top_module_is_INCOMPLETE_not_refused(tmp_path):
    """THE MIDDLE STATE, and for this class it is the NORMAL one. Measured on the
    corpus: none of the 11 readable designs of this class states a top module in
    its own input — they are protocol specifications, not chip projects, so no
    module name exists to recover. That pack carries the class contract and the
    class's craft and is INCOMPLETE, never NOT_ASSEMBLED; calling it empty would
    make the refusal's own words ("contributed no class knowledge") false."""
    h = PACK.assemble(_SERIAL_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    cf = h["class_first"]
    assert h["target_module"] is None
    assert cf["assembly_status"] == "ASSEMBLED_INCOMPLETE"
    assert cf["missing_fields"] == ["target_module"]
    assert "not_assembled_reason" not in cf
    assert cf["db_classes_in_pack"], "the pack really does carry class knowledge"


def test_a_recovered_target_completes_the_same_pack(tmp_path):
    """The other direction of the state above: hand the same class a brief that
    DOES name its module and the identical code stamps ASSEMBLED, so the status
    is computed rather than constant for this class."""
    h = PACK.assemble(_SERIAL_PROMPT + " The module `serdev` has the following "
                      "hardware interfaces defined.", None, None, [], ["gate"],
                      tmp_path, output_target="l_doc_expectations.json",
                      ic_class=_CLASS)
    assert h["target_module"] == "serdev"
    assert h["class_first"]["assembly_status"] == "ASSEMBLED"


def test_the_digest_the_agent_reads_agrees_with_the_declared_selection(tmp_path):
    """THE ARTEFACT, NOT THE NOTE ABOUT IT — `ic_expert_db.md` is what the
    author actually reads."""
    allowed = set(_profile()["db_classes"])
    h = PACK.assemble(_SERIAL_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    named = set(re.findall(r"^- \*\*\[([^\]]+)\]\*\*",
                           (tmp_path / "ic_expert_db.md").read_text(), re.M))
    assert named, "the rendered digest names no ic_class at all"
    assert named <= allowed, f"out-of-class entries in the digest: {sorted(named - allowed)}"
    assert named == {x["ic_class"] for x in h["db_classes"]}


def test_mutation_the_unprofiled_pack_is_the_DECLARED_GAP_state(tmp_path, monkeypatch):
    """The mutation arm must land on a NAMED state, not merely "different"."""
    monkeypatch.setattr(Q, "_DEFAULT_DB", _null_profile_db(tmp_path))
    h = PACK.assemble(_SERIAL_PROMPT, None, None, [], ["gate"], tmp_path / "pack",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert "class_first" not in h
    assert h["target_module"] is None and h["interface_contract"] is None
    assert not (tmp_path / "pack" / "contract.md").exists()
    d = PACK.class_first_disposition(_CLASS)
    assert d["profile"] == "NOT_PROFILED" and d["registered"] is True
    assert d["db_class_selection"] == "LEXICAL_UNCONFINED"


def test_a_design_of_another_class_is_byte_identical(tmp_path):
    """THE CONTROL. Without it, "the serial-peripheral packs changed" cannot be
    told apart from "every pack changed"."""
    other = next(k for k, v in _db()["registered_class_profiles"].items()
                 if not k.startswith("_") and v is None)
    prompt = ("A serial-parallel multiplier: the multiplicand is applied in "
              "parallel and the multiplier one bit per clock, with a "
              "clock-divided strobe advancing the accumulation.")
    one = PACK.assemble(prompt, None, None, [], ["gate"], tmp_path / "a",
                        output_target="l_doc_expectations.json")
    two = PACK.assemble(prompt, None, None, [], ["gate"], tmp_path / "b",
                        output_target="l_doc_expectations.json", ic_class=other)
    assert one == two and "class_first" not in two
    names = sorted(q.name for q in (tmp_path / "a").iterdir())
    assert names == sorted(q.name for q in (tmp_path / "b").iterdir())
    for n in names:
        assert (tmp_path / "a" / n).read_bytes() == (tmp_path / "b" / n).read_bytes()
