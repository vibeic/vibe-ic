"""A minimal flow YAML for the two gates that read the canonical flow.

WHY A SHARED HELPER. `closed-loop edges resolve` and `closed-loop executable
census` read the SAME file and, by their own comment, are "deliberately the
same shape so the two cannot disagree about what a declaration is". Two
hand-written copies of a subject flow would be free to drift apart, and a
drifting subject is how a fixture stops testing the thing it names.

WHY A MINIMAL FLOW AND NOT A COPY OF THE REAL ONE. A copy would carry 69 steps
of unrelated declarations, any of which could be the reason a gate refuses —
and `gate_fixture_runner` requires the CAN-FAIL refusal to name the mutation's
own token, so a subject that can refuse for a second reason is a subject that
can pass its pair test while proving nothing. Three steps is the smallest tree
in which an edge can resolve, close a loop, and be gated.

chip-AGNOSTIC: no process, foundry, vendor, PDK or product is named here, and
the step names describe the SHAPE of the graph rather than any flow stage.
"""
from pathlib import Path

#: Where both declarations look, resolved from `$ROOT` by the dispatcher.
FLOW_REL = Path("vibe-ic-marketplace/plugins/vibe-ic/flow/"
                "phase1_phase2_phase3.yaml")

_GATE = '      program_exit_zero: "true"\n'


def flow_yaml(*, fallback_to="1", trigger="the downstream check refused",
              gate_on_2=True, declare_closed_loop=True) -> str:
    """A three-step flow. Step 2 carries the closed_loop under examination.

    `declare_closed_loop=False` drops the block entirely, which is the ONLY
    input that moves `closed_loop_executable_coverage_check` off rc 0 through
    this declaration — see that fixture's docstring for the measurement.

    Defaults are the HEALTHY shape: `2 -> 1` resolves to a declared step, and
    1 is a transitive `blocks_on` ancestor of 2, so the edge closes a loop;
    the trigger is a non-empty string; step 2 has a gate that can produce a
    verdict. Each keyword mutates exactly one of those four conditions.
    """
    fb = "" if fallback_to is None else f"      fallback_to: {fallback_to}\n"
    tg = "" if trigger is None else f"      trigger: {trigger!r}\n"
    return (
        "version: 2\n"
        "flow_name: fixture\n"
        "total_steps: 3\n"
        "steps:\n"
        "  - id: 1\n"
        "    name: the step the edge returns to\n"
        "    stage: stage1\n"
        "    blocks_on: []\n"
        "    gate:\n" + _GATE +
        "  - id: 2\n"
        "    name: the step that declares the closed loop\n"
        "    stage: stage1\n"
        "    blocks_on: [1]\n"
        + ("    gate:\n" + _GATE if gate_on_2 else "")
        + ("    closed_loop:\n" + fb + tg if declare_closed_loop else "") +
        "  - id: 3\n"
        "    name: a step with no closed_loop at all\n"
        "    stage: stage1\n"
        "    blocks_on: [2]\n"
        "    gate:\n" + _GATE
    )


def write(root: Path, **kw) -> Path:
    p = root / FLOW_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(flow_yaml(**kw), encoding="utf-8")
    return p
