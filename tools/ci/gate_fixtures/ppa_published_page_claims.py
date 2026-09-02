"""`PPA published page claims` — a claim promoted past the evidence it cites.

THE MUTATION IS THE GATE'S OWN DOCUMENTED DEFECT. `ppa_page_claim_check.py`
checks two directions, and the second one is stated in its docstring as
"a claim's status may never be STRONGER than the weakest evidence record it
cites". This fixture applies exactly that: one claim in the published
`claims.json` is promoted to `MEASURED` while the evidence it cites stays
`DERIVED`. Nothing else in either tree differs.

WHY NOT THE OTHER DIRECTION. The page->claims half (a banned form left
unqualified, a citation that resolves to nothing) would require EDITING A
PUBLISHED SENTENCE, and a fixture that rewrites prose proves the gate reacts to
a sentence somebody typed rather than to a fact. Promoting a status changes an
ANSWER inside the corpus and leaves every sentence, every citation and both
counts alone.

THE DENOMINATOR IS IDENTICAL IN BOTH ARMS, and this is checkable rather than
asserted: the gate prints it, and both arms print `35 sentence(s), 139
claim(s), 9 banned form(s) enforced`. The refusal is a verdict about one of
those 139 claims, not the corpus going to zero — which is the vacuous-refusal
path this protocol refuses to accept as evidence.

THE SUBJECT IS THE REPOSITORY'S OWN PUBLISHED PAIR, copied in. It is the only
page/claims pair in this tree where every row is cited by construction, which
is what the declaration's `--cite-numbers` requires; a synthesised pair would
prove the gate accepts something this repository never publishes. Copying is
safe here because the fixture may choose the INPUT — the gate's own code stays
at `$PG`.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process; the
claim it touches is selected by its status fields, never by its metric name.
"""
from pathlib import Path
import json
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "PPA published page claims"

#: Byte-for-byte the two paths the declaration passes. The gate names FILES, so
#: the subject has to carry exactly these; anywhere else and it reads nothing
#: and answers about that instead.
#: ASKED OF THE ROW, NEVER RE-TYPED (vibe-ic#2019 fallout). The campaign trees
#: moved to `docs/campaigns/` and this literal did not follow, so the subject
#: was built where the gate no longer looks. `declared_subject_path` reads the
#: page path this row actually passes, so the two cannot disagree.
_TAIL = "ppa-e2e/report/winner/report.md"


def _rel() -> Path:
    """The winner directory, from this row's own argument.

    Resolved lazily: a missing row must fail THIS fixture, not the census that
    imports every fixture module.
    """
    return Path(F.declared_subject_path(GATE, _TAIL)).parent

#: `ppa_page_claim_check.STATUS_STRENGTH`, which is what the comparison the
#: mutation has to invert is made of. Kept as a literal rather than imported so
#: a fixture cannot silently inherit a weakening of the table it is testing.
_STRENGTH = {"MEASURED": 4, "DERIVED": 3, "ESTIMATED": 2,
             "NOT_APPLICABLE": 1, "INVALID": 0, "NOT_MEASURED": 0}
_TOP = "MEASURED"


def _source() -> Path:
    src = F.REPO_ROOT / _rel()
    if not (src / "report.md").is_file() or not (src / "claims.json").is_file():
        raise AssertionError(
            f"the published page/claims pair is not at {src}. This fixture "
            f"cannot build a subject for a gate whose corpus has moved; fix "
            f"the declaration rather than letting the fixture answer over an "
            f"empty tree.")
    return src


def _tree(work: Path) -> Path:
    root = work / "subject"
    rel = _rel()
    (root / rel).mkdir(parents=True, exist_ok=True)
    src = _source()
    shutil.copy2(src / "report.md", root / rel / "report.md")
    shutil.copy2(src / "claims.json", root / rel / "claims.json")
    return root


def can_pass(work: Path) -> Path:
    """The published pair, unmodified: every claim within its evidence, rc 0."""
    return _tree(work)


def can_fail(work: Path):
    """One claim promoted to MEASURED over evidence that is not."""
    root = _tree(work)
    doc = json.loads((root / _rel() / "claims.json").read_text(encoding="utf-8"))
    promoted = None
    for claim in doc.get("claims", []):
        evidence = claim.get("evidence") or []
        if not all(isinstance(e, dict) for e in evidence) or not evidence:
            continue
        weakest = min(_STRENGTH.get(e.get("status"), -1) for e in evidence)
        if weakest < 0 or weakest >= _STRENGTH[_TOP]:
            continue
        if _STRENGTH.get(claim.get("status"), -1) >= _STRENGTH[_TOP]:
            continue
        claim["status"] = _TOP
        promoted = claim.get("id")
        break
    if promoted is None:
        raise AssertionError(
            "no claim in the published document cites evidence weaker than "
            f"{_TOP}, so this mutation has nothing to invert. The fixture "
            "would otherwise hand the gate a CLEAN subject and call its rc 0 "
            "a discrimination.")
    (root / _rel() / "claims.json").write_text(
        json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    # The token the refusal must carry, so the pair test knows the gate refused
    # for THIS mutation and not by coincidence.
    return root, "CLAIM_OUTRUNS_EVIDENCE"
