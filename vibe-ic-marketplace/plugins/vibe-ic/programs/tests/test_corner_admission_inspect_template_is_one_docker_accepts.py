"""test_corner_admission_inspect_template_is_one_docker_accepts.py — the
admission probe's `docker inspect` format must be a template Docker PARSES
(lane icadc, 2026-09-15).

THE DEFECT, MEASURED against the live daemon while an A4 corner was running:

    docker inspect -f '{{.Id}}\\t{{.HostConfig.Memory}}\\t{{index .Config.Labels \\"vibeic.corner.token\\"}}' <id>
    rc=64   template parsing error: template: :1: unexpected "\\\\" in operand

The format was built in Python as `"...\\\\t...\\\\\\"vibeic.corner.token\\\\\\""`, so LITERAL
backslashes reached Docker — `\\t` as two characters, `\\"` around the label
key. The argv goes to execve, not to a shell, so nothing ever unescapes them.

WHY IT SURVIVED, AND WHY IT IS WORSE THAN IT LOOKS. `docker_active_reservations`
returns `{}` EARLY when `docker ps` lists no ids, so the broken template is
never reached when nothing is running: it is healthy at the start of every
sweep and refuses from the moment the first corner is alive. In
`_run_pvt_corners` that `AdmissionRefused` is charged to EVERY pooled corner as
`RAM_ADMISSION_REFUSED` — which is exactly the `corners_executed 1/9` /
`A4_PVT_SWEEP_NOT_MEASURED` three tests have been red on main with, and it
breaks REAL sweeps on real hosts, not only fixtures.

AND THE OLD TEST PINNED THE BUG. `test_issue2236_aggregate_ram_admission`
asserted the exact broken string — the MECHANISM — rather than the property
"a template Docker accepts". It was written from the source instead of from
what Docker does with it, which is why nothing caught this.

BOTH DIRECTIONS. The template must parse; and every refusal the probe is
supposed to make on a malformed answer must still fire.

No chip / SKU / foundry literal.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analog_corner_admission as aca            # noqa: E402
# vibe-ic#1128 — "docker is not on this host" means A VERIFICATION DID NOT
# HAPPEN, not that one passed. Declared through `not_verified_tier` so the
# run's roll-up cannot count this site under `passed`, and so the reader is
# told which command would make it answerable.
from _tool_probes import skip_not_verified  # noqa: E402

DOCKER_REMEDY = "install docker, or run this suite on a host that has the daemon"


def _template_used():
    """The format argv the probe actually passes, captured from the call."""
    seen = {}

    def runner(argv, **kw):
        if argv[:3] == ["docker", "ps", "-q"]:
            return types.SimpleNamespace(returncode=0, stdout="cid0\n", stderr="")
        seen["argv"] = list(argv)
        return types.SimpleNamespace(
            returncode=0, stdout="cid0\t1073741824\ttok0\n", stderr="")

    aca.docker_active_reservations(runner=runner)
    argv = seen["argv"]
    return argv[argv.index("-f") + 1]


# ── the defect arm ─────────────────────────────────────────────────────────
def test_the_inspect_template_carries_no_literal_backslash():
    """THE DEFECT ARM. A backslash in the operand is what Go refused."""
    fmt = _template_used()
    assert "\\" not in fmt, repr(fmt)


def test_the_template_separates_its_three_fields_with_a_REAL_tab():
    """`docker_active_reservations` splits the answer on `"\\t"` — a real tab.
    A template emitting the two characters backslash-t would render one field,
    and the probe would call a healthy answer malformed."""
    fmt = _template_used()
    assert fmt.count("\t") == 2, repr(fmt)
    assert fmt.split("\t") == ["{{.Id}}", "{{.HostConfig.Memory}}",
                               '{{index .Config.Labels "vibeic.corner.token"}}']


def test_the_label_key_is_quoted_the_way_a_go_template_quotes_it():
    fmt = _template_used()
    assert '.Config.Labels "vibeic.corner.token"' in fmt, repr(fmt)


def test_docker_itself_parses_the_template():
    """THE ARM THAT WOULD HAVE CAUGHT IT: hand the template to Docker instead
    of asserting what it looks like. Run against the daemon's own `docker`
    binary with no container — a parse error is reported before any lookup, so
    this needs no running container and no image.

    Where there is no `docker` binary this does not quietly pass: it reports
    NOT_VERIFIED by name through `not_verified_tier`, because the whole point
    of this test is that the string is checked by the parser that rejected it
    rather than by another assertion about its characters.
    """
    if shutil.which("docker") is None:
        skip_not_verified(
            "docker is not on this host, so the template cannot be handed to "
            "the Go template parser that rejected it", DOCKER_REMEDY)
    fmt = _template_used()
    cp = subprocess.run(["docker", "inspect", "-f", fmt, "__vibeic_absent__"],
                        capture_output=True, text=True, timeout=30)
    assert "template parsing error" not in (cp.stderr or ""), cp.stderr
    assert "unexpected" not in (cp.stderr or ""), cp.stderr


# ── the refusals that must still fire ──────────────────────────────────────
def _probe(ps_out, inspect_rc=0, inspect_out=""):
    def runner(argv, **kw):
        if argv[:3] == ["docker", "ps", "-q"]:
            return types.SimpleNamespace(returncode=0, stdout=ps_out, stderr="")
        return types.SimpleNamespace(returncode=inspect_rc, stdout=inspect_out,
                                     stderr="")
    return runner


def test_no_running_corner_is_an_empty_map_not_a_refusal():
    assert aca.docker_active_reservations(runner=_probe("")) == {}


def test_a_failing_inspect_is_still_refused():
    with pytest.raises(aca.AdmissionRefused):
        aca.docker_active_reservations(runner=_probe("cid0\n", inspect_rc=1))


def test_a_malformed_line_is_still_refused():
    for bad in ("cid0\t1073741824\n", "cid0\tnot-a-number\ttok\n",
                "\t1073741824\ttok\n", "cid0\t0\ttok\n"):
        with pytest.raises(aca.AdmissionRefused):
            aca.docker_active_reservations(runner=_probe("cid0\n",
                                                         inspect_out=bad))


def test_a_missing_token_is_charged_as_legacy_not_collapsed():
    """Docker renders an absent map entry as `<no value>`; two such containers
    must not collapse onto one pseudo-token and be under-counted."""
    out = "cidA\t100\t<no value>\ncidB\t200\t<no value>\n"
    got = aca.docker_active_reservations(runner=_probe("cidA cidB\n",
                                                       inspect_out=out))
    assert got == {"legacy:cidA": 100, "legacy:cidB": 200}


def test_a_duplicate_token_is_charged_twice():
    out = "cidA\t100\ttok\ncidB\t200\ttok\n"
    got = aca.docker_active_reservations(runner=_probe("cidA cidB\n",
                                                       inspect_out=out))
    assert got == {"tok": 300}
