"""`a declared output has a live producer` — the writer is gone, the file is not.

THE MUTATION IS THE MEASURED DEFECT. On the 68x9 matrix (plugin v1.12.33),
dimension D3 answers "are declared `required_outputs` genuinely written?" for
122 of its 166 entries by asking whether a run tree committed into
`benchmark-data` still carries a matching file. Deleting the WRITER of step
A8's declared `.gds` left D3 green in every configuration: the artefact was
still in the corpus, and nothing asked whether anything still made it.

BOTH TREES DECLARE THE SAME TWO OUTPUTS. The flow is byte-identical in both
directions and both producers exist in both — what changes is that one of them
stops writing its declared path and writes an unrelated one instead. So the
declaration count, the venue count and the file count are all constant, and
only the producer's DESTINATION moves.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402,F401

GATE = "a declared output has a live producer"

_FLOW_REL = "vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"
_PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"
_BASELINE_REL = _PROGRAMS_REL + "/declared_output_write_site_baseline.json"

#: THE SUBJECT CARRIES ITS OWN BASELINE, and it has to. The gate blocks on a
#: DEMOTION -- a path this tree had resolved to a write site no longer having
#: one -- which is a comparison against that file. A subject without one is a
#: subject the gate cannot put its question to (rc 2), so leaving it out would
#: make the fixture measure the absence of an input rather than the mutation.
#:
#: Both directions ship the SAME baseline, naming both declared outputs. That
#: is what keeps the pair a controlled comparison: the flow, the producer file,
#: the venue and the baseline are byte-identical across the two trees, and the
#: single thing that moves is the producer's second destination.
_BASELINE = """{
  "write_site": [
    "reports/synthetic_alpha_report.json",
    "reports/synthetic_beta_report.json"
  ]
}
"""

_FLOW = '''steps:
  - id: '1'
    name: synthetic step one
    required_outputs:
      - reports/synthetic_alpha_report.json
  - id: '2'
    name: synthetic step two
    required_outputs:
      - reports/synthetic_beta_report.json
'''

_WRITES_BOTH = '''"""A synthetic producer for the two declared outputs."""
from pathlib import Path


def emit(project):
    (Path(project) / "reports" / "synthetic_alpha_report.json").write_text("{}")
    (Path(project) / "reports" / "synthetic_beta_report.json").write_text("{}")
'''

#: The SAME producer, still writing two files — the second one is no longer
#: the path the flow declares. Nothing was deleted; a destination moved.
_WRITES_ELSEWHERE = '''"""A synthetic producer for the two declared outputs."""
from pathlib import Path


def emit(project):
    (Path(project) / "reports" / "synthetic_alpha_report.json").write_text("{}")
    (Path(project) / "reports" / "scratch_note.json").write_text("{}")
'''


def _tree(work: Path, producer: str) -> Path:
    root = work / "subject"
    flow = root / _FLOW_REL
    flow.parent.mkdir(parents=True, exist_ok=True)
    flow.write_text(_FLOW, encoding="utf-8")
    programs = root / _PROGRAMS_REL
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "synthetic_report_emit.py").write_text(producer, encoding="utf-8")
    (root / _BASELINE_REL).write_text(_BASELINE, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Both declared outputs are written by a producer in the tree."""
    return _tree(work, _WRITES_BOTH)


def can_fail(work: Path):
    """The same producer, no longer writing — or naming — the second output.

    The expected refusal names the DEMOTION and not the `[NO-TRACE]` line the
    same run also prints, because demotion is what this gate blocks on.
    `test_no_trace_is_unreachable_so_it_cannot_be_the_only_blocker` measured
    that on the real tree: deleting the sole producer of all 34
    single-producer declared paths moved not one of them to NO-TRACE, because
    the path's name survives in the source its READERS wrote. A fixture that
    took the NO-TRACE line as the refusal would be green on a blocker a real
    tree can never reach.
    """
    return (_tree(work, _WRITES_ELSEWHERE),
            "[LOST WRITE SITE] reports/synthetic_beta_report.json")
