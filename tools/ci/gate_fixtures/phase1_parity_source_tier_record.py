"""`phase1 parity source-tier record` — a published count that drifted from its data.

THE GATE'S OWN CLAIM, from its docstring, is that a parity sweep's tier record
"cannot silently rot". It asserts three things of a parity root, and the second
is the one this fixture exercises:

    (2) PUBLICATION — every RESULT markdown under the parity root that publishes
        tier counts publishes counts that MATCH the data.

That is the gate's DOCUMENTED defect, and it is the escape it was written for: a
sweep publishes ONE uniform parity number over N protocols whose sources are not
uniform, the per-tier split is the reader's only way to weigh it, and a split
that no longer matches the record still reads exactly like a measurement.

HOW THE SUBJECT IS AIMED
========================
The declaration names the parity root RELATIVE (`protocol_parity`) and is
dispatched with cwd `$ROOT`, which the engine sets to the subject. So a subject
carrying `protocol_parity/` IS the parity root, with no argv invented and no
environment steered. The gate's own code stays the real `$PG` copy.

WHAT THE PASSING SPECIMEN PRESENTS  (it is NOT accepted for finding nothing)
===========================================================================
Every one of the gate's three dimensions is presented with a real denominator
rather than evaded:

    (1) COVERAGE     2 protocol directories, BOTH tiered, both tiers known,
                     both carrying an evidence string; the tier file's own
                     `counts` block and its `protocols_total` agree with its
                     `protocols` block.
    (2) PUBLICATION  1 RESULT markdown carrying `<!-- source-tier-counts -->`
                     — so `result_md_checked` is 1, not 0 — publishing both
                     non-zero tiers, and publishing them correctly.
    (3) CITATION     2 `input/docs/<doc>` citations, one per protocol, lifted
                     out of real L-doc `evidence` pointers; both RESOLVE
                     because both documents are in the tree.

A tree with no protocols, or a markdown with no marker, would clear the gate by
giving it nothing to judge. This one clears it by being right.

THE MUTATION BREAKS EXACTLY ONE THING
=====================================
One integer, in the markdown: `specification` goes from 1 to 2. Nothing else
differs between the two trees.

    BROKEN:      the published `specification` count no longer equals the count
                 the tier record holds.
    LEFT INTACT: the same 2 protocol directories, so `protocols_total` is
                 still 2 and the denominator is unchanged; the same
                 `source_tier.json`, byte for byte, so dimension (1) still
                 passes and the failure cannot be a coverage finding wearing a
                 publication finding's name; the same 2 citations, both still
                 RESOLVING, so dimension (3) is silent; the marker is still
                 present, so the markdown is still CHECKED rather than ignored
                 — an unmarked markdown is skipped, and deleting the marker
                 would prove only that the gate can be switched off.

DIRECTION, stated because getting it backwards is the usual way one of these
certifies nothing: the gate FAILS on a published count that disagrees with the
data, so the mutation MOVES a published count. Removing the markdown, the
marker, or a protocol would each make the gate quieter, not louder.

So the refusal is rc 1 for one attributable reason and the fixture pins it: the
expected fragment is that violation line, which no other outcome of this gate
prints.

chip-AGNOSTIC / PDK-AGNOSTIC: the two protocol names are placeholders and name
no bus, vendor, foundry, process node, SKU or chip. The tree is SYNTHETIC and
its records say so: no sweep stands behind it and it must never be read as
evidence of one.
"""
from pathlib import Path
import json

GATE = "phase1 parity source-tier record"

#: The parity root, spelled exactly as the declaration spells it — relative to
#: the cwd the dispatcher gives this gate, which the engine sets to the subject.
_ROOT_REL = "protocol_parity"

#: Two protocols, one per tier the specimen publishes. `_is_protocol_dir`
#: accepts a directory carrying `input/docs/` or `phase1/`; these carry both,
#: which is also what makes the citation dimension non-empty.
_PROTOCOLS = {
    "alpha": ("specification", "alpha_source.txt"),
    "beta": ("encyclopedia", "beta_source.txt"),
}

_SYNTHETIC = ("a gate fixture, not a sweep: no protocol parity measurement "
              "stands behind this record")


def _tree(work: Path, name: str, published_specification: int) -> Path:
    root = work / name
    parity = root / _ROOT_REL
    entries = {}
    for proto, (tier, doc) in _PROTOCOLS.items():
        d = parity / proto
        (d / "input" / "docs").mkdir(parents=True, exist_ok=True)
        (d / "input" / "docs" / doc).write_text(_SYNTHETIC + "\n",
                                                encoding="utf-8")
        gen = d / "phase1" / "generated_docs"
        gen.mkdir(parents=True, exist_ok=True)
        # The citation the gate follows is an L-doc `evidence` pointer of the
        # shape `input/docs/<doc>`; it resolves here, in both arms.
        (gen / "L1_overview.json").write_text(json.dumps({
            "layer": "L1",
            "synthetic": True,
            "note": _SYNTHETIC,
            "fields": {"overview": {"evidence": f"input/docs/{doc}"}},
        }, indent=2) + "\n", encoding="utf-8")
        entries[proto] = {
            "tier": tier,
            "evidence": _SYNTHETIC,
            "input_documents": [doc],
        }

    counts = {"specification": 0, "encyclopedia": 0, "vendor_document": 0,
              "reconstructed_text": 0, "unknown": 0}
    for rec in entries.values():
        counts[rec["tier"]] += 1

    (parity / "source_tier.json").write_text(json.dumps({
        "_comment": _SYNTHETIC,
        "protocols_total": len(entries),
        "counts": counts,
        "protocols": entries,
    }, indent=2) + "\n", encoding="utf-8")

    (parity / "RESULT_fixture_sweep.md").write_text(
        "# Synthetic parity sweep\n\n"
        f"{_SYNTHETIC}.\n\n"
        "<!-- source-tier-counts -->\n"
        f"- **specification** — {published_specification} protocol(s)\n"
        f"- **encyclopedia** — {counts['encyclopedia']} protocol(s)\n",
        encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """2 tiered protocols, 1 marked RESULT md, 2 resolving citations: rc 0."""
    return _tree(work, "subject_pass", _PROTOCOLS_SPEC_COUNT)


def can_fail(work: Path):
    """The same record with ONE published count moved off the data."""
    root = _tree(work, "subject_fail", _PROTOCOLS_SPEC_COUNT + 1)
    return root, ("RESULT_fixture_sweep.md publishes specification="
                  f"{_PROTOCOLS_SPEC_COUNT + 1} but the data says "
                  f"{_PROTOCOLS_SPEC_COUNT}")


#: Derived, never typed twice: the number of protocols the specimen tiers as
#: `specification`. The can-pass publishes it and the can-fail publishes one
#: more, so adding a protocol to `_PROTOCOLS` cannot leave the two arms
#: disagreeing about anything except the one integer the mutation moves.
_PROTOCOLS_SPEC_COUNT = sum(
    1 for _t, _d in _PROTOCOLS.values() if _t == "specification")
