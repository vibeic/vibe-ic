"""vibe-ic#2105 — the SUPERVISED exec route must carry the image's quiet knob.

THE DEFECT, AT THE CONSUMER.  v1.18.43 (854d30295) moved
`phase3_one_shot_runner._docker_exec`'s supervised branch onto the shared
`_docker_watchdog.run_docker_supervised`, but the route seam `_exec_argv` did
not travel with it: the shared path builds its own argv and passes no `opts`.
So from that landing every LONG tool run — the `marker=` sites: PnR, route, CTS,
klayout DRC, magic ext2spice, netgen LVS — stopped carrying
`-e IIC_OSIC_TOOLS_QUIET=1`, and the vibeic-eda image's login profile printed

    [INFO] Final PATH variable: ...
    [INFO] Final PYTHONPATH variable: ...

to STDOUT ahead of the tool's own output.  MEASURED on the pinned image, one
container, same command, only the program blobs differing: base 3 stdout lines
of which 2 are banner, fix 1 line.  That is the defect #211 fixed for a single
consumer and the seam was built to close at source for all of them; the SHORT
probes (`_docker_exec_raw`) kept the knob the whole time, which is why no
existing test noticed — every banner test drives the raw entry point only.

WHY THIS TEST STARTS ITS OWN CONTAINER.  The property is about what a real
login shell prints, so a real container is the subject.  It is started HERE,
from the pinned digest, under a name this file owns, and removed by the id it
recorded — never a container this host happened to have, whose image is not
ours to assume and whose bytes are not ours to trust.  When the engine or the
pinned image is unreachable the test SKIPS WITH THE REASON NAMED; it never
assumes the host and never reports a green it did not measure.

THE MUTATION IT IS REQUIRED TO KILL: taking the supervised dispatch off the
seam (dropping `exec_argv=_exec_argv` in `_docker_exec`, or the `exec_argv`
branch in `run_docker_supervised`) must bring the two banner lines back.
"""
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _eda_pin as PIN            # noqa: E402 — the ONE pin resolver
import phase3_one_shot_runner as R  # noqa: E402
from _tool_probes import skip_not_verified  # noqa: E402

#: The tool's own output. The denominator: "no banner" means nothing at all
#: unless the tool actually ran and we can see that it did.
TOKEN = "CZ2105_TOOL_OUTPUT"
#: What the image's profile prints when the knob is not set.
BANNER = "[INFO] Final "


def _docker() -> str:
    import shutil
    return shutil.which("docker") or ""


@pytest.fixture
def pinned_container():
    """A container of OUR OWN, from the pinned digest. Skips, by name, rather
    than assuming anything about this host."""
    docker = _docker()
    if not docker:
        skip_not_verified(
            "no `docker` client on PATH, so no container route exists to "
            "measure here (this is the in-image case)",
            "run this from the HOST beside the image rather than inside it")
    image = PIN.image_reference()
    if subprocess.run([docker, "image", "inspect", image],
                      capture_output=True).returncode != 0:
        skip_not_verified(
            "the pinned image %s is not present on this host and this test "
            "will not pull one" % image,
            "docker pull %s" % image)
    name = "cz2105_probe_%s" % secrets.token_hex(6)
    started = subprocess.run(
        [docker, "run", "-d", "--rm", "--name", name,
         "--entrypoint", "/bin/sleep", image, "300"],
        capture_output=True, text=True)
    if started.returncode != 0:
        skip_not_verified(
            "could not start a container from the pinned image: %s"
            % (started.stderr or "").strip()[:200],
            "check the docker daemon is reachable and the pinned digest is "
            "runnable on this host")
    cid = started.stdout.strip()
    try:
        yield name
    finally:
        subprocess.run([docker, "rm", "-f", cid], capture_output=True)


def _supervised_stdout(container, tmp_path, monkeypatch):
    """Run an echo-shaped tool through the SUPERVISED entry point and return
    its stdout lines."""
    monkeypatch.setattr(R, "_PROV_SINK", str(tmp_path), raising=False)
    monkeypatch.setattr(R, "_LOCAL_EXEC_MODE", None, raising=False)
    monkeypatch.delenv("IIC_OSIC_TOOLS_QUIET", raising=False)
    rc, out, err = R._docker_exec(container, "echo %s" % TOKEN,
                                  timeout=120, marker=TOKEN)
    return rc, [l for l in out.splitlines() if l.strip()], err


def test_a_supervised_tool_run_yields_only_the_tools_own_stdout(
        pinned_container, tmp_path, monkeypatch):
    """THE CONSUMER PROOF. Zero banner lines, and the tool's own line present."""
    # THE ROUTE IS ASSERTED FIRST, and it is not a formality: on the LOCAL
    # route there is no login profile to print a banner, so "zero banner lines"
    # would be true for a reason that has nothing to do with the seam. A green
    # from the wrong route is the failure this check exists to refuse.
    assert R._local_exec_mode() is False, (
        "this host took the LOCAL exec route, so nothing was measured about "
        "the container login banner")

    rc, lines, err = _supervised_stdout(pinned_container, tmp_path, monkeypatch)

    # THE DENOMINATOR, before the property. An empty stdout has zero banner
    # lines too, and would read as a pass.
    assert any(TOKEN in l for l in lines), (
        "the supervised entry point produced no tool output at all "
        "(rc=%s, stdout=%r, stderr=%r) — nothing was measured about the banner"
        % (rc, lines, (err or "")[:300]))

    banner = [l for l in lines if l.startswith(BANNER)]
    assert banner == [], (
        "the image's login banner reached the tool's stdout through the "
        "SUPERVISED route: %r. The seam passes `-e IIC_OSIC_TOOLS_QUIET=1`; "
        "a dispatch that builds its own argv does not." % (banner,))
    assert lines == [l for l in lines if TOKEN in l], (
        "stdout carries lines the tool did not print: %r" % (lines,))


def test_the_short_probe_route_was_never_the_broken_one(
        pinned_container, tmp_path, monkeypatch):
    """The CONTROL that keeps the claim honest: `_docker_exec_raw` carried the
    knob the whole time, on both sides of #2105. If this ever goes red the
    defect is wider than the supervised path and the diagnosis above is wrong."""
    monkeypatch.setattr(R, "_LOCAL_EXEC_MODE", None, raising=False)
    monkeypatch.delenv("IIC_OSIC_TOOLS_QUIET", raising=False)
    rc, out, err = R._docker_exec_raw(pinned_container,
                                      "echo %s" % TOKEN, timeout=120)
    lines = [l for l in out.splitlines() if l.strip()]
    assert any(TOKEN in l for l in lines), (rc, lines, (err or "")[:300])
    assert [l for l in lines if l.startswith(BANNER)] == [], lines
