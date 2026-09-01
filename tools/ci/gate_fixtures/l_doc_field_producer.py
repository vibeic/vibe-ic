"""`L-doc field producer` — a field a checker reads that no document fills.

THE GATE'S OWN CLAIM is that "a field a checker READS must have a PRODUCER":
it collects the field names the real `*_check.py` programs pull out of an
L-doc `fields` object, counts how many published L-docs carry a NON-EMPTY
value for each, and FAILS on a field that has at least one reader, is present
in at least one document, and is populated in none. That is the #312 family:
the consumer sees an empty value, and an empty value is indistinguishable
from a clean one.

HOW THE SUBJECT IS AIMED AT A SYNTHETIC TREE
============================================
The declaration passes neither a corpus nor `--programs`, so both halves are
resolved by the checker itself and only one of them is the fixture's to move:

  * THE READERS stay REAL. `--programs` is not passed, so the gate reads the
    field names out of the actual programs directory — the same `$PG` the
    engine refuses to redirect. The fixture supplies the corpus, never the
    gate's own code.
  * THE CORPUS is the SUBJECT's. `_corpus_location.default_named` is BOUNDED
    at the repository root and this repository has carried no
    `benchmark-data/ic` since v1.10.56, so the checker falls back to the
    LITERAL RELATIVE path `benchmark-data/ic` — and the dispatcher declares
    this gate with cwd `$ROOT`, which the engine sets to the subject. A
    subject that carries `benchmark-data/ic/` therefore IS the corpus, with no
    argv invented and no environment steered.

WHAT THE PASSING SPECIMEN PRESENTS  (it is NOT accepted for finding nothing)
===========================================================================
A gate that accepts because it had nothing to judge is the "detector that
never says no", and this checker has TWO such holes wired shut as rc 2:
`fields_read == 0` and `docs_scanned == 0`. The passing specimen clears both
with a real, populated instance rather than by evading them:

    DENOMINATOR PRESENTED:  1 published L-doc carrying a `fields` object
                            (`docs_scanned == 1`, not 0)
                            against the field names the real checkers read
                            (`fields_read != 0`)
    INSIDE THAT DOCUMENT:   `signal_crossings` — read by the real
                            `power_domain_signal_crossing_check` — is
                            POPULATED, so the gate has an actual producer to
                            find and correctly does not report it. Every field
                            the register already records is present and EMPTY,
                            which is the state the register records; that is
                            what makes the run rc 0 rather than a `paid`/`new`
                            disagreement with it.

THE RECORDED FIELDS ARE READ OUT OF THE REGISTER, NOT TYPED HERE. The
declaration passes no `--baseline`, so the gate adjudicates against the real
`l_doc_field_producer_baseline.json`, whose register MAY ONLY SHRINK. A
hand-copied list of its names would be a frozen copy of a value the repository
computes live, and it would go quietly wrong the day somebody pays one of them
off — this fixture would then fail while nothing was broken. It
reads the register, so the specimen stays the known-good subject FOR WHATEVER
THE REGISTER CURRENTLY SAYS.

THE MUTATION BREAKS EXACTLY ONE THING
=====================================
One value: `fields.signal_crossings` goes from one synthetic crossing record to
`[]`. Nothing else differs between the two trees.

    BROKEN:        exactly one field acquires a reader-without-producer —
                   `signal_crossings`, present in 1 doc and populated in 0.
    LEFT INTACT:   the corpus still resolves (not an absent-corpus refusal);
                   the document still parses as JSON and still carries a
                   `fields` object, so `docs_scanned` is still 1 and the
                   reader denominator is unchanged; every recorded field is
                   untouched, so no entry reads as
                   `(resolved)` and the run cannot refuse for a shrinking
                   register; the file name still matches `L*_*.json`.

So the refusal is rc 1 for one attributable reason and the fixture pins it:
the expected fragment is the finding line for that field, which no other
outcome of this gate prints.

WHY `signal_crossings` AND NOT ONE OF THE RECORDED FIELDS. A recorded field
cannot be the mutation — it is already a finding in the register, so emptying
it changes nothing. `signal_crossings` is read by a real checker and is NOT in
the register, which is exactly the shape the gate blocks on: a NEW
reader-without-producer. The preceding field, `power_domains`, stopped being a
valid fixture input when the published-corpus register recorded it.

ONE ENVIRONMENT THIS SUBJECT DOES NOT REACH, MEASURED
=====================================================
`_corpus_location.resolve` gives $GATEKEEPER_BENCHMARK_DATA_SHA + $VIBE_IC_BENCHMARK_DATA absolute precedence and "refus[es] any candidate-local
benchmark-data/ic shadow" — by design, so a bound landing cannot be shown a
corpus it did not attest. The fixture engine passes its own environment
through to the gate (`invoke` copies `os.environ` and pops only
`GATEKEEPER_HYGIENE_JOBS`), so under a BOUND pointer this gate reads the bound
corpus and not the subject, and BOTH directions then answer rc 2 UNDETERMINED.

MEASURED with a bound pointer at a corpus carrying no L-doc, on this tree:
this pair, `PPA measurement contract` and `tracked-symlink target present` —
the two corpus fixtures already in the repo — failed IDENTICALLY, 3 of 3. It
is a property of the ENGINE's environment handling shared by every
corpus-reading fixture, not of this subject, and the fixture does not paper
over it by writing $VIBE_IC_BENCHMARK_DATA itself: this module runs in the
runner's own process, so a pointer set here would outlive the pair and aim the
LATER fixtures at a deleted temporary directory. The repair belongs in
`invoke`, once, for all three.

NOT A GIT REPOSITORY, DELIBERATELY. This gate counts VALUES inside documents
with an `rglob` and never reads git's index — its own docstring says so, and
contrasts itself with the two gates that do. A `git init` here would add a
second thing the subject asserts about itself for no reason.

chip-AGNOSTIC / PDK-AGNOSTIC: the document names no foundry, process node,
SKU, vendor or chip codename. `L21` is this repository's own layer number and
the two domain names are placeholders. The tree is SYNTHETIC and says so in
the document: no design stands behind it and it must never be read as
evidence of one.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "L-doc field producer"

#: The literal relative path `_corpus_location.default_named` falls back to
#: when the repository carries no corpus of its own, resolved against the cwd
#: the dispatcher gives this gate — the subject.
_CORPUS_REL = Path("benchmark-data") / "ic"

#: One published L-doc. `_document_files` globs `L*_*.json`.
_DOC_REL = _CORPUS_REL / "specimen_cell" / "signoff" / "L21_power_intent.json"

#: The register the gate adjudicates against, in the REAL programs tree — the
#: same one `$PG` names. Read, never re-spelled.
_REGISTER = F.PROGRAMS / "l_doc_field_producer_baseline.json"

#: The field whose producer the mutation removes: read by the real
#: `power_domain_signal_crossing_check`, recorded by no register entry.
_PRODUCED = "signal_crossings"
_A_PRODUCER = [{
    "signal": "signal_one",
    "driver_domain": "domain_one",
    "receiver_domain": "domain_two",
}]


def _recorded() -> list:
    """The fields the register already records as having no producer."""
    doc = json.loads(_REGISTER.read_text(encoding="utf-8"))
    known = sorted({str(x) for x in doc.get("known", [])})
    if _PRODUCED in known:
        raise RuntimeError(
            f"{_REGISTER.name} now records {_PRODUCED!r}. This fixture uses it "
            f"as the field whose producer the mutation REMOVES, which only "
            f"discriminates while the register does not already excuse it. "
            f"Choose another field a checker reads and the register omits.")
    return known


def _tree(work: Path, name: str, produced) -> Path:
    root = work / name
    doc = root / _DOC_REL
    doc.parent.mkdir(parents=True, exist_ok=True)
    fields = {f: [] for f in _recorded()}
    fields[_PRODUCED] = produced
    doc.write_text(json.dumps({
        "layer": "L21",
        "synthetic": True,
        "note": ("a gate fixture, not evidence: no design stands behind this "
                 "document"),
        "fields": fields,
    }, indent=2) + "\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """One L-doc with `signal_crossings` populated: rc 0 against the register."""
    return _tree(work, "subject_pass", _A_PRODUCER)


def can_fail(work: Path):
    """The same document with `signal_crossings` emptied: one NEW finding."""
    root = _tree(work, "subject_fail", [])
    return root, f"{_PRODUCED}: "
