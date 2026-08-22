"""Two contracts that solved ONE problem — the shared subject builder.

UNDERSCORE-PREFIXED ON PURPOSE: `load_fixtures` skips `_*.py`, so this is a
helper and never itself a gate fixture. The two campaign rows that need it are
thin modules beside this one.

`ppa_problem_integrity_check` groups contracts BY PROBLEM IDENTITY and compares
every pair inside a group. One arm is not a comparison — a single contract
yields "problem identity <hash> has ONE arm ... rc=2" — so the subject has to
carry two, and they have to land in the SAME group.

That constrains the mutation. Changing the PROBLEM would split the group in two
and give each half one arm, which is rc 2 CANNOT CHECK and proves only that the
gate could not compare. The mutation therefore moves the TOOLCHAIN identity: the
two arms stay one problem, stay comparable, and now disagree about the tools
that produced them — PPA-C-012, rc 1, which is a finding about the comparison.
"""
from pathlib import Path
import copy
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ppa_measurement_contract as _contract_fixture  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                       / "programs"))
from _ppa import contract as C  # noqa: E402

#: The one fact the CAN-FAIL moves, and the value it moves to. Both arms
#: declare the first; the mutated arm declares the second.
_TOOLCHAIN_SAME = "synthetic_fixture_no_tools"
_TOOLCHAIN_OTHER = "synthetic_fixture_other_toolchain"


def _arm(root: Path, impl_text: str, toolchain_value: str) -> dict:
    """Build one arm in place. The implementation bytes differ between arms —
    that is what makes them two arms of one problem rather than one arm twice —
    and every other declared input is shared."""
    for rel, text in _contract_fixture._FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (root / "impl" / "netlist.txt").write_text(impl_text, encoding="utf-8")
    decl = copy.deepcopy(_contract_fixture._DECLARATION)
    decl["toolchain"]["facts"][0]["value"] = toolchain_value
    return C.build(decl, root)


def _tree(work: Path, corpus: str, toolchain_b: str) -> Path:
    root = F.git_init(work / "subject")
    out = root / corpus / "records"
    out.mkdir(parents=True, exist_ok=True)
    for name, impl, tool in (("arm_a_contract.json", "arm A netlist\n",
                              _TOOLCHAIN_SAME),
                             ("arm_b_contract.json", "arm B netlist\n",
                              toolchain_b)):
        doc = _arm(root, impl, tool)
        (out / name).write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return root


def build_can_pass(work: Path, corpus: str) -> Path:
    """Two arms, one problem, one pair compared, no identity conflict."""
    root = _tree(work, corpus, _TOOLCHAIN_SAME)
    F.git_commit(root)
    return root


def build_can_fail(work: Path, corpus: str):
    """The same two arms, disagreeing about the toolchain that built them."""
    root = _tree(work, corpus, _TOOLCHAIN_OTHER)
    F.git_commit(root)
    # The token has to APPEAR IN THE REFUSAL — the pair test refuses a can-fail
    # rejected for a reason it cannot match, because a gate that refuses for the
    # wrong reason is a coincidence and not a check.
    return root, "PPA-C-012"
