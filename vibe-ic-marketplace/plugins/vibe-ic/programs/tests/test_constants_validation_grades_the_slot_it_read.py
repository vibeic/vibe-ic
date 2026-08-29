"""`constants_validation` graded every document against ONE schema, whichever
key it had actually read — and reported the finding under the name of a key the
document did not contain.

THE SUBJECT, MEASURED 2026-08-29 over 2614 real-design `L8_RTL_CONSTANTS.json`
files on one host (1453 of them under `phase1/generated_docs`, which is the tree
the flow clause actually points the gate at):

    non-empty `constants` key ................................  0 of 2614
    entry carrying both `value` and `width`/`bits` ...........  0 of 2614
    matching the five hard-coded RECOGNIZED_SECTIONS names ...  0 of 2614
    non-empty `parameters` key ............................... 139 of 2614

Every file on that host that satisfied the pre-fix schema was a pytest temporary
fixture written to satisfy this program. Not one was a design. The pre-fix gate
therefore failed EVERY design, with a message naming `constants[0]` about
documents that have no `constants` key — and `advisory_program_exit_zero` wiring
is why it survived: loud, permanent, and free until an audit reader believes it.

WHICH SIDE WAS WRONG, from the code and not from the message. The emitter is
right. `phase1_doc_one_shot_runner._l8_parameters` builds
`{name, default, source, extraction_strategy}` and there is no width anywhere in
that extraction, because a parameter default lifted out of a README table has no
bit width to report. The gate was written for an L8 shape that no design emits.

WHAT THIS FILE DRIVES. The three classes the fix separates — graded, abstained,
refused — and then, at length, the one that decides whether the fix is worth
landing: the gate MUST STILL SAY NO. A gate relaxed until the corpus is green is
not a fix, it is a deletion with a changelog entry, so every accepting rule below
is paired with a rejecting one over the same slot.

chip-AGNOSTIC / tool-AGNOSTIC / PDK-AGNOSTIC: JSON schema bookkeeping only. The
synthetic fixtures name no design, and `test_no_design_specific_literals`
asserts the five that used to be compiled into the program are gone.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
_GATE = _PROGRAMS / "constants_validation.py"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import constants_validation as cv  # noqa: E402
from _hostpaths import corpus_root  # noqa: E402


def _tree(tmp_path: Path, doc, name: str = "L8_RTL_CONSTANTS.json") -> Path:
    """A project directory holding one constants document."""
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(doc), encoding="utf-8")
    return d


def _run_cli(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(_GATE), str(project_dir)],
                          capture_output=True, text=True)


#: The shape Phase 1 actually emits. Field-for-field what
#: `phase1_doc_one_shot_runner._l8_parameters` appends: no `value`, no `width`.
EMITTED = {
    "ic_name": "synthetic_block",
    "doc_class": "rtl_constants",
    "schema_version": "1",
    "parameters": [
        {"name": "DATA_WIDTH", "default": "32",
         "source": "README.md", "extraction_strategy": "bullet_kv",
         "description": "datapath width"},
        {"name": "FIFO_DEPTH", "default": "16",
         "source": "README.md", "extraction_strategy": "grid_table",
         "description": "buffer depth"},
    ],
    "timing_constants": [],
    "clock_domains": [],
}


# ===========================================================================
# 1. THE DEFECT — the emitted shape is graded, and graded as `parameters`
# ===========================================================================
def test_the_emitted_parameters_shape_is_accepted(tmp_path):
    """The exact shape Phase 1 writes must pass. Pre-fix it failed, on every
    design, with `constants[0]: missing 'width' or 'bits' field`."""
    result = cv.audit(str(_tree(tmp_path, EMITTED)))
    assert result.passed is True, [f"{f.rule}: {f.message}" for f in result.findings
                                   if f.severity == "ERROR"]
    assert result.summary["graded"] == 2
    assert cv.status_word(result) == "PASS"


def test_a_finding_names_the_slot_it_actually_read(tmp_path):
    """The message may not name a key the document does not contain.

    This is the half that made the defect survive: an audit reader chasing
    `constants[0]` in a file with no `constants` key finds nothing and concludes
    the tooling is broken rather than the document."""
    doc = json.loads(json.dumps(EMITTED))
    doc["parameters"][0].pop("default")          # now genuinely defective
    result = cv.audit(str(_tree(tmp_path, doc)))
    errs = [f for f in result.findings if f.severity == "ERROR"]
    assert errs, "a parameter with no value and no default must be an ERROR"
    assert all("parameters[" in f.message for f in errs), \
        [f.message for f in errs]
    assert not any("constants[" in f.message for f in errs), \
        [f.message for f in errs]


def test_the_first_list_fallback_is_gone(tmp_path):
    """A list under an unrelated key is NOT a constants list.

    Pre-fix, `extract_constants` fell back to the first list value in the dict
    and graded it. MEASURED across the corpus, that fallback picked
    `source_documents`, `evidence`, `clock_domains`, `max_throughput_table` and
    `tap_state_names_in_canonical_order` on 339 files — grading prose provenance
    against a constants schema."""
    doc = {
        "ic_name": "synthetic_block",
        "source_documents": ["a.md", "b.md"],
        "evidence": [{"quote": "the bus is 32 bits wide", "file": "a.md"}],
    }
    result = cv.audit(str(_tree(tmp_path, doc)))
    assert result.summary["graded"] == 0, \
        "an unrelated list was graded as constants"
    assert any(f.rule == "SLOT_UNRECOGNIZED" for f in result.findings)
    assert cv.status_word(result) == "NOT_GRADED"


# ===========================================================================
# 2. ABSTENTION IS NAMED, AND IS NOT A PASS
# ===========================================================================
def test_an_empty_slot_abstains_by_name_and_never_prints_pass(tmp_path):
    """87.3% of the real corpus (1269 of 1453 generated_docs trees) declares no
    constants. That is a legitimate state, so it is not an ERROR — and nothing
    was verified, so it is not a PASS either."""
    doc = dict(EMITTED, parameters=[])
    result = cv.audit(str(_tree(tmp_path, doc)))
    assert result.passed is True
    assert result.summary["graded"] == 0
    assert result.summary["abstained_files"] == 1
    assert any(f.rule == "NO_CONSTANTS_DECLARED" and f.severity == "INFO"
               for f in result.findings)
    assert cv.status_word(result) == "NOT_GRADED"


def test_the_cli_prints_not_graded_and_says_it_is_not_a_pass(tmp_path):
    """The status WORD carries the distinction, because the exit code cannot:
    this gate is wired `advisory_program_exit_zero` and its rc is not read as a
    verdict at all."""
    proc = _run_cli(_tree(tmp_path, dict(EMITTED, parameters=[])))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "NOT_GRADED" in proc.stdout
    assert "This is not a PASS." in proc.stdout
    assert "\nPASS " not in proc.stdout


def test_an_ungraded_document_is_disclosed_not_swallowed(tmp_path):
    """A document whose constants live under design-descriptive section names is
    out of the declared scope. It must say so by name — guessing which section
    holds constants is the defect this fix removes, one refactor tidier."""
    doc = {"ic_name": "x", "clock_constants": {"F": 1}, "width_parameters": {"W": 8}}
    result = cv.audit(str(_tree(tmp_path, doc)))
    warn = [f for f in result.findings if f.rule == "SLOT_UNRECOGNIZED"]
    assert warn, [f.rule for f in result.findings]
    assert "NOT GRADED" in warn[0].message
    assert cv.status_word(result) == "NOT_GRADED"


# ===========================================================================
# 3. CAN THIS GATE STILL SAY NO — the half that decides whether it lands
# ===========================================================================
#: (label, document) pairs that MUST produce at least one ERROR. Every relaxed
#: rule above has a rejecting twin here over the SAME slot.
REFUSALS = [
    ("parameter with neither value nor default",
     dict(EMITTED, parameters=[{"name": "W", "source": "r.md"}])),
    ("parameter with an empty name",
     dict(EMITTED, parameters=[{"name": "   ", "default": "32"}])),
    ("parameter whose default is null",
     dict(EMITTED, parameters=[{"name": "W", "default": None, "value": None}])),
    ("slot present but a string — schema regression",
     dict(EMITTED, parameters="DATA_WIDTH=32")),
    ("slot present but a number — schema regression",
     dict(EMITTED, parameters=32)),
    ("list entry that is not a dict",
     dict(EMITTED, parameters=["DATA_WIDTH"])),
    ("strict `constants` list entry missing width",
     {"constants": [{"name": "W", "value": 32, "comment": "c"}]}),
    ("strict `constants` list entry missing value",
     {"constants": [{"name": "W", "width": 8, "comment": "c"}]}),
    ("width present but zero",
     {"constants": [{"name": "W", "value": 1, "width": 0, "comment": "c"}]}),
    ("width present but not an integer",
     {"constants": [{"name": "W", "value": 1, "width": "wide", "comment": "c"}]}),
    ("parameter carrying a malformed width is still refused",
     dict(EMITTED, parameters=[{"name": "W", "default": "1", "width": -4}])),
    ("mapping entry whose value is null",
     {"constants": {"W": None}}),
    ("mapping entry with an empty key",
     {"constants": {"": 32}}),
]


@pytest.mark.parametrize("label,doc", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_the_gate_still_refuses(label, doc, tmp_path):
    result = cv.audit(str(_tree(tmp_path, doc)))
    errs = [f"{f.rule}: {f.message}" for f in result.findings
            if f.severity == "ERROR"]
    assert errs, f"{label}: accepted with no ERROR — this gate cannot say no"
    assert result.passed is False
    assert cv.status_word(result) == "FAIL"


def test_duplicate_names_across_two_files_are_still_caught(tmp_path):
    d = _tree(tmp_path, EMITTED)
    (d / "extra_constants.json").write_text(
        json.dumps({"constants": [{"name": "DATA_WIDTH", "value": 8,
                                   "width": 4, "comment": "clash"}]}),
        encoding="utf-8")
    result = cv.audit(str(d))
    assert any(f.rule == "DUPLICATE_NAME" for f in result.findings)
    assert result.passed is False


def test_a_refusal_exits_one_and_a_pass_exits_zero(tmp_path):
    """EXACT exit codes, both directions — never `rc != 0`."""
    bad = _run_cli(_tree(tmp_path / "bad",
                         dict(EMITTED, parameters=[{"name": "W"}])))
    assert bad.returncode == 1, bad.stdout + bad.stderr
    good = _run_cli(_tree(tmp_path / "good", EMITTED))
    assert good.returncode == 0, good.stdout + good.stderr


# ===========================================================================
# 4. THE GATE MAY NOT CARRY A DESIGN'S PRIVATE VOCABULARY
# ===========================================================================
def test_no_design_specific_literals(tmp_path):
    """`RECOGNIZED_SECTIONS` was five section names from ONE design
    (`tx_phy_constants`, `rx_phy_constants`, `crc8_constants`,
    `mac_key_signals`, `port_naming_convention`) and matched 0 of 2614 real L8
    files. A flow-level program that hardcodes one design's vocabulary has
    stopped being flow."""
    src = _GATE.read_text(encoding="utf-8")
    for literal in ("tx_phy_constants", "rx_phy_constants", "crc8_constants",
                    "mac_key_signals", "port_naming_convention"):
        assert literal not in src, (
            f"{literal!r} is back in {_GATE.name} — this gate is shared by every "
            "design and may not carry one design's section names")


def test_the_enforcement_declaration_is_present_and_says_advisory():
    """Criterion 5 of flow-change-acceptance: BLOCKING or ADVISORY, stated in
    the gate. This one is wired `advisory_program_exit_zero`, so it must not
    claim to block."""
    src = _GATE.read_text(encoding="utf-8")
    assert "ENFORCEMENT: advisory" in src


# ===========================================================================
# 5. REAL ARTEFACTS — a suite of fixtures authored alongside the fix cannot
#    distinguish the fix from its own absence.
# ===========================================================================
def _real_l8_dirs(root: Path, limit: int = 400):
    out = []
    for p in root.rglob("L8_RTL_CONSTANTS.json"):
        if "generated_docs" in p.parts and "pytest-of-" not in str(p):
            out.append(p.parent)
            if len(out) >= limit:
                break
    return sorted(set(out))


def test_no_real_design_is_falsely_reddened():
    """Corpus sweep: over real emitted L8 documents the gate raises ZERO
    ERRORs, and grades at least one of them.

    The second half is what stops this being vacuous — a gate that abstained on
    everything would also raise zero errors."""
    root = corpus_root()
    if root is None or not root.is_dir():
        pytest.skip("external corpus not available: set $VIBEIC_CORPUS_ROOT to "
                    "a tree containing phase1/generated_docs/L8_RTL_CONSTANTS.json")
    dirs = _real_l8_dirs(root)
    if not dirs:
        pytest.skip(f"no generated_docs L8 documents under {root}")
    reddened, graded_total = [], 0
    for d in dirs:
        r = cv.audit(str(d))
        graded_total += r.summary.get("graded", 0)
        if not r.passed:
            reddened.append((str(d), [f"{f.rule}: {f.message}"
                                      for f in r.findings if f.severity == "ERROR"][:3]))
    assert not reddened, (
        f"{len(reddened)} of {len(dirs)} real design(s) reddened by this gate — "
        f"a gate that fires on a legitimately-complete design is a bug in the "
        f"gate:\n" + "\n".join(f"  {p}\n    {e}" for p, e in reddened[:5]))
    assert graded_total > 0, (
        f"swept {len(dirs)} real design(s) and graded ZERO entries — the sweep "
        "proves nothing, because a gate that never looks also never fires")
