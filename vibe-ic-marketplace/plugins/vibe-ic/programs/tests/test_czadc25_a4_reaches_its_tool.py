"""A4 asks for the container the run was given, and says so when it cannot.

`analog_one_shot_runner` passes `--container` at seven sites. Six read
`getattr(args, "container", None) or os.environ.get(...)`. A4 alone omitted
the `getattr` and asked for the literal `vibeic-eda`, so an orchestrated run
invoked with `--container <name>` sent the corner sweep after a container that
was not running. The sweep then exits 2 having written nothing, and the
runner's fallthrough reported `artefact missing — invoke skill 'ams-sim'`:
a deterministic producer that could not reach its tool, recorded as a step
that needs the AI. A4 is the A-track's only real simulation step, so the
consequence is that it had never run under the orchestrator on any design.

The second half is the PDK. A4's default was the bare string `"sky130"`,
which is not an installed directory name on any host this repo runs on (the
installed family is `sky130A`), so a design that declares its own PDK was
swept under a name nothing resolves.

MEASURED CORRECTION to the report this file was written from: the misroute
was reported as exiting rc=0. It exits 2. The 0 was `tail`'s exit code, read
through a pipe (`prog ... | tail -12; echo rc=$?`). The runner's record was
still wrong, but for the reason pinned below — the fallthrough — and not
because the producer lied about its exit code.
"""
import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
ANALOG = PROGRAMS / "analog_one_shot_runner.py"
SWEEP = PROGRAMS / "analog_real_corner_sweep.py"

sys.path.insert(0, str(PROGRAMS))


def _a4_dispatch_src(n: int = 6000) -> str:
    """The A4 DISPATCH block. Anchored on the sub-producer it invokes, because
    `if step_name == "A4_corner_sweep":` appears earlier in the file inside
    `_emit_deterministic_stub` — and a test anchored there reads the stub
    emitter while reporting on the dispatch."""
    src = ANALOG.read_text()
    i = src.index('real_prog = PROGRAMS_DIR / "analog_real_corner_sweep.py"')
    return src[i:i + n]


# ── every container site, DERIVED from the tree, not counted from a report ──

def _container_arg_sites(src: str):
    """Every `"--container"` string literal in the module, with the source of
    the ~6 lines that follow it. Derived by parse position rather than by a
    hand-written list of line numbers, which is what let one site sit outside
    the convention for as long as it did."""
    lines = src.splitlines()
    sites = {}
    for i, line in enumerate(lines):
        if '"--container"' in line and "add_argument" not in line:
            sites[i + 1] = "\n".join(lines[i:i + 7])
    return sites


def test_every_container_site_consults_args_first():
    """RED BEFORE THE FIX at exactly one site: A4's."""
    sites = _container_arg_sites(ANALOG.read_text())
    assert len(sites) >= 6, f"expected the runner's container sites, got {sites.keys()}"
    # THE DEFECT SHAPE, stated exactly: reaching for the environment fallback
    # WITHOUT consulting the run's own --container first. A site that passes a
    # container it was handed as a parameter is not in scope — it never had
    # `args` to consult, and demanding `getattr(args, ...)` of it would be a
    # rule about this test rather than about the runner.
    offenders = []
    for lineno, blob in sites.items():
        reaches_env = 'os.environ.get(' in blob and "VIBEIC_ANALOG_CONTAINER" in blob
        reads_args = 'getattr(args, "container"' in blob or "_a4_container" in blob
        if reaches_env and not reads_args:
            offenders.append(lineno)
    assert not offenders, (
        f"container site(s) at line(s) {offenders} fall back to the "
        f"environment without consulting the run's own --container; an "
        f"orchestrated run will address a container it was never told about")


def test_no_literal_pdk_default_at_the_a4_site():
    """The `"sky130"` literal is gone and nothing replaced it with another
    literal. A default here is a claim about a design the runner has not
    read."""
    a4 = _a4_dispatch_src(8000)
    # the environment lookup must not carry a fallback value any more
    assert not re.search(r'VIBEIC_ANALOG_PDK"\s*,\s*\n?\s*"[^"]+"', a4), (
        "VIBEIC_ANALOG_PDK still has a literal default at the A4 site")
    assert '"sky130"' not in a4, "the sky130 literal is still at the A4 site"


# ── the PDK precedence, exercised as a function ────────────────────────────

def _l19(tmp_path: Path, target):
    import json
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"doc_id": "L19", "fields": {"pdk_target": target}}))
    return tmp_path


def test_effective_pdk_prefers_the_flag(tmp_path, monkeypatch):
    import analog_one_shot_runner as r
    monkeypatch.delenv("VIBEIC_ANALOG_PDK", raising=False)
    proj = _l19(tmp_path, "sg13g2")
    assert r._effective_analog_pdk(SimpleNamespace(pdk="gf180mcuD"), proj) \
        == "gf180mcuD"


def test_effective_pdk_falls_back_to_the_environment(tmp_path, monkeypatch):
    import analog_one_shot_runner as r
    monkeypatch.setenv("VIBEIC_ANALOG_PDK", "gf180mcuD")
    proj = _l19(tmp_path, "sg13g2")
    assert r._effective_analog_pdk(SimpleNamespace(pdk=""), proj) == "gf180mcuD"


def test_effective_pdk_falls_back_to_the_design(tmp_path, monkeypatch):
    """The design's own declaration, which is what the removed literal was
    standing in front of."""
    import analog_one_shot_runner as r
    monkeypatch.delenv("VIBEIC_ANALOG_PDK", raising=False)
    proj = _l19(tmp_path, "sg13g2")
    assert r._effective_analog_pdk(SimpleNamespace(pdk=""), proj) == "sg13g2"


def test_effective_pdk_invents_nothing(tmp_path, monkeypatch):
    """Nothing told, nothing declared → EMPTY, and the caller then forwards no
    `--pdk` at all. The one outcome that must never happen here is a value:
    a selector the runner made up is a claim about a design it has not read."""
    import analog_one_shot_runner as r
    monkeypatch.delenv("VIBEIC_ANALOG_PDK", raising=False)
    proj = _l19(tmp_path, None)
    assert r._effective_analog_pdk(SimpleNamespace(pdk=""), proj) == ""


def test_effective_pdk_ignores_auto(tmp_path, monkeypatch):
    """`auto` is the orchestrator's argparse default and means "the design
    decides" — treating it as a selector would sweep every default run under
    a PDK named `auto`."""
    import analog_one_shot_runner as r
    monkeypatch.delenv("VIBEIC_ANALOG_PDK", raising=False)
    proj = _l19(tmp_path, "sg13g2")
    assert r._effective_analog_pdk(SimpleNamespace(pdk="auto"), proj) == "sg13g2"


# ── the environment gap is NAMED, not flattened into "invoke a skill" ──────

class _CP:
    def __init__(self, out="", err="", rc=2):
        self.stdout, self.stderr, self.returncode = out, err, rc


def test_env_gap_detects_the_producers_own_sentence():
    import analog_one_shot_runner as r
    cp = _CP(err="[real_sim] ngspice not in container czadc25_eda\n")
    gap = r._producer_env_gap(cp)
    assert gap and "czadc25_eda" in gap, (
        "the gap must carry the container NAME — that name is the whole value "
        "of the message to whoever reads the run record")


def test_env_gap_detects_an_unresolvable_mount_root():
    import analog_one_shot_runner as r
    cp = _CP(err="[real_sim] block=b0 BLOCKED on host mount root: nothing\n")
    assert r._producer_env_gap(cp)


@pytest.mark.parametrize("msg", [
    "[real_sim] block=b0 BLOCKED on A3_netlist_gen: x.sp absent",
    "[real_sim] block=b0 type=ldo: no successful sim",
    "[real_sim] block=b0: the delivered deck reported no measurement",
])
def test_design_side_refusals_are_not_env_gaps(msg):
    """THE CONTROL, and the direction written down first. These three also
    exit 2, and a skill CAN act on them — they are statements about the
    DESIGN. If the detector claimed them too it would relabel every honest
    design-side refusal as a broken environment, which is the same
    mis-attribution in the other direction."""
    import analog_one_shot_runner as r
    assert r._producer_env_gap(_CP(err=msg + "\n")) is None


def test_env_gap_is_none_when_the_producer_said_nothing():
    import analog_one_shot_runner as r
    assert r._producer_env_gap(_CP()) is None


# ── the refusal statuses cannot round up to green ──────────────────────────

def test_a4_env_refusal_status_is_in_the_fail_tier():
    """A status not enumerated in `_aggregate_verdict` falls through its
    catch-all and produces a GREEN run — the defect class that function's own
    comments were written about. Both A4 refusals use `step_preflight`'s
    BLOCKED, which IS enumerated."""
    import analog_one_shot_runner as r
    import step_preflight as spf
    assert spf.REFUSAL_STATUS in r._FAIL_STATUSES
    a4 = _a4_dispatch_src()
    assert a4.count("_spf.REFUSAL_STATUS") == 1, (
        "expected exactly one A4 refusal — the unreachable container. A "
        "no-PDK refusal was measured to be wrong here: the sweep resolves the "
        "effective PDK itself and a refusal blocks runs it can complete")


def test_a4_refusals_do_not_defer_to_a_skill():
    """The fallthrough this replaces said `invoke skill 'ams-sim'`. No skill
    can supply a container or an ngspice binary, so that advice could not be
    acted on and the environment gap was never named."""
    import analog_one_shot_runner as r
    a4 = _a4_dispatch_src()
    chunks = a4.split("_spf.REFUSAL_STATUS")[1:]
    # A LOOP OVER AN EMPTY POPULATION IS A PASS THAT MEASURED NOTHING. On the
    # pre-fix tree there are no refusals at this site at all, so without this
    # guard the body below never executes and the test reports green about a
    # runner that has none of the behaviour it describes.
    assert chunks, "no A4 refusal to inspect — this test measured nothing"
    for chunk in chunks:
        head = chunk[:900]
        assert "suggested_skill" not in head
        assert "ENV_UNAVAILABLE" in head, (
            "an A4 refusal must carry the ENV_UNAVAILABLE tier so a reader "
            "can tell an environment gap from a design gap")


# ── the sweep's own exit code, pinned so the correction cannot be re-lost ──

def test_sweep_exits_non_zero_when_it_cannot_reach_ngspice():
    """Read out of the source, because reproducing it needs a host with no
    such container. The claim being pinned is the CORRECTED one: the producer
    exits 2, it does not exit 0."""
    src = SWEEP.read_text()
    i = src.index("ngspice not in container")
    tail = src[i:i + 400]
    assert "return 2" in tail, (
        "the sweep must exit non-zero when ngspice is unreachable; a rc-0 "
        "'nothing happened' is indistinguishable from a clean run")


def test_a4_forwards_no_pdk_when_it_knows_none():
    """The other half of "no literal default": when nothing declares a PDK the
    argv carries no `--pdk` at all, rather than a name the runner made up.

    The sweep's own contract then resolves the EFFECTIVE PDK from the project
    and stamps it as `pdk_used_for_sim`, which is the component entitled to
    answer. RED BEFORE THE FIX: the argv always carried `--pdk`, defaulted to
    the literal "sky130"."""
    a4 = _a4_dispatch_src()
    cmd = a4[a4.index("rs_cmd = ["):]
    cmd = cmd[:cmd.index("rs_cp = ")]
    assert "if _a4_pdk:" in cmd, (
        "the `--pdk` argument is not conditional on actually having one")
    head = cmd[:cmd.index("if _a4_pdk:")]
    assert "--pdk" not in head, (
        "`--pdk` is still unconditionally in the argv list")
