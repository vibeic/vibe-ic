"""`signoff report states its stage` — the sibling the same emitter did not stamp.

THE MUTATION IS THE GATE'S OWN MOTIVATING INCIDENT, and the gate's docstring is
explicit that only ONE of its two arms can reach it. Arm A is keyed on the
flow's `required_outputs` and is "BLIND TO THE INCIDENT THAT MOTIVATED THIS
RULE" in its own words; arm B is keyed on the module's demonstrated convention,
taken from the capture verbatim: "One report in a family carries the stage
statement because its own emitter writes it, and the sibling reports that
actually decide the slow and fast corners are written by different emitters that
do not." So the mutation is exactly that — one module, two timing reports it
writes itself, and the stamp dropped from the second.

THE DIRECTION. The gate does not flag "a module that stamps nothing"; such a
module is not in arm B's population at all. It flags a module that PROVES it
knows how to stamp and then leaves a sibling bare. Removing both stamps would
therefore make the subject GREENER, not redder, which is the direction a fixture
for this rule is easiest to get backwards.

BOTH ARMS SHIP THE SAME DENOMINATOR: the same flow declaring the same one
timing report, and the same one module writing the same two reports. `population`
is 1 and `found` is 1 in both directions, so neither arm can reach the rc=2
NOT-CHECKED tier — the tier that exists precisely so an empty corpus cannot read
as a pass. What moves is one string constant inside one function.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "signoff report states its stage"

_FLOW_REL = "vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"
_PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"

#: One step, declaring ONE of the two reports the emitter module writes. The
#: other is emitted-but-undeclared, which is what puts the finding out of arm
#: A's reach and into arm B's — the same asymmetry the capture recorded.
_FLOW = """version: "fixture"
flow_name: "fixture"
steps:
  - id: 33
    name: "Sign-off timing"
    stage: stage3
    required_outputs:
      - "reports/phase3/sta.rpt"
"""

#: The emitter, with BOTH reports stamped. `body` is a literal rather than
#: something read from another path: a scope whose written bytes come from a
#: read is classified as a COPIER and leaves the population, which would empty
#: the denominator instead of changing the answer.
_STAMPED_SIBLING = '''"""A synthetic sign-off report emitter."""


def emit_sta_report(project, body):
    rpt = project / "sta.rpt"
    rpt.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)


def emit_power_report(project, body):
    rpt = project / "power.rpt"
    rpt.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)
'''

#: The same module, the same two reports, the same two writes — and the second
#: emitter's stage statement replaced by prose that names the basis without
#: making the claim any reader can parse. This is the shape the finding took on
#: the real tree: a header that said `basis:` beside a value it had already
#: computed, and no `STA_BASIS`.
_BARE_SIBLING = '''"""A synthetic sign-off report emitter."""


def emit_sta_report(project, body):
    rpt = project / "sta.rpt"
    rpt.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)


def emit_power_report(project, body):
    rpt = project / "power.rpt"
    rpt.write_text("# basis: the routed, post-PnR netlist\\n" + body)
'''


def _tree(work: Path, emitter: str) -> Path:
    root = F.git_init(work / "subject")
    flow = root / _FLOW_REL
    flow.parent.mkdir(parents=True, exist_ok=True)
    flow.write_text(_FLOW, encoding="utf-8")
    programs = root / _PROGRAMS_REL
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "_signoff_emit.py").write_text(emitter, encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """Every timing/power report the module writes carries the stamp."""
    return _tree(work, _STAMPED_SIBLING)


def can_fail(work: Path):
    """The same module, one sibling left without a stage statement."""
    return _tree(work, _BARE_SIBLING), \
        "while the same module stamps another timing/power report it emits"
