#!/usr/bin/env python3
"""`tools/ci/run_suite_in_eda_image.sh` — the harness that makes the container
engine reachable where the suite runs.

WHAT THIS FILE REFUSES
======================
1. **A remapped bind.** The harness hands the HOST daemon paths that were
   composed inside the container, so a path that is not identical on both sides
   is not an error — Docker creates an empty directory and mounts that. Measured
   on this harness with the socket already working: the CLI ran, the arm reached
   container creation, and the daemon answered `bind source path does not exist:
   /tmp/vibeic-hermetic-dsz78fvv/progress-plan.json`.
2. **The sandbox being handed the socket.** The harness is the OUTER
   environment; the hermetic arms it lets the suite launch are the sandbox, and
   an arm runs unreviewed candidate code. Giving one the host daemon is the
   removal of the gate, not a repair of it.
3. **A scratch root the external-storage gate cannot see** — the falsifying root
   that turns honest passes into failures naming their own fixtures. How many
   is not written here: it is stated, and re-measured every run, by
   `_VOLATILE_ADVISORY` in `programs/scratch_root_guard.py` (0 at 4b3843f22c,
   which is why the GUARD declares this condition instead of refusing on it;
   this harness pins its own `--scratch` for a different reason, stated there).
4. **An absent engine reported as anything other than a refusal.** "I could not
   look" is not a test verdict, and a `which("docker")` skip in the suite would
   delete the landing gate's only end-to-end proof.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

_CI = Path(__file__).resolve().parent
_REPO = _CI.parents[1]
_HARNESS = _CI / "run_suite_in_eda_image.sh"
_RUNNER = _CI / "hermetic_candidate_runner.py"
_GATE = (_REPO / "vibe-ic-marketplace/plugins/vibe-ic/programs"
         / "project_outputs_in_tree_check.py")
_BOUND = 60

#: A path that is nobody's directory. The volatile rule is a fact about a
#: string, and the harness asks it before it creates anything or starts
#: anything, so a notional path drives exactly that rule and nothing else.
_NOT_VOLATILE = "/vibeic-run-suite-not-a-volatile-root"


def _binds() -> list[tuple[str, str]]:
    """Every `-v HOST:CONTAINER[:opts]` the harness DECLARES, as pairs.

    Comment lines are excluded on purpose: this file's own prose shows a
    `docker run -v A:B` to explain the trap, and a scanner that read its own
    example would report the explanation as the defect.
    """
    pairs = []
    for line in _HARNESS.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        # Only a line whose first token is `-v` — `grep -v` takes the same
        # flag and its argument is a pattern, not a mount.
        for raw in re.findall(r'(?:^|\(\s*)-v\s+"?([^"\s]+)"?',
                              line.strip()):
            parts = raw.split(":")
            if len(parts) < 2:
                continue
            pairs.append((parts[0], parts[1]))
    assert pairs, "no bind mounts found — this test would prove nothing"
    return pairs


def _run(*args, env_extra=None, timeout=_BOUND):
    import os
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return _pr.run([str(_HARNESS), *args], capture_output=True,
                          text=True, env=env, cwd=str(_REPO))


def test_every_bind_is_at_its_own_path():
    """THE IDENTICAL-PATH RULE. A remap does not fail loudly; it silently mounts
    an empty directory the host daemon invents."""
    offenders = [(h, c) for h, c in _binds()
                 if h != c and c != "/etc/passwd"]
    assert not offenders, offenders


def test_the_only_remap_is_the_passwd_overlay_and_it_is_named():
    """The one exception is a FILE the container needs at a fixed path, and it
    is never a bind SOURCE handed back to the daemon."""
    remaps = [(h, c) for h, c in _binds() if h != c]
    assert [c for _h, c in remaps] == ["/etc/passwd"], remaps


def test_the_runners_hardcoded_transport_directory_is_shared():
    """`/tmp` is shared because the runner hardcodes it, not because it is
    conventional. If the runner ever moves that directory this test fails and
    the harness gets updated — rather than the arms silently NORECORDing."""
    runner = _RUNNER.read_text(encoding="utf-8")
    assert 'prefix="vibeic-hermetic-", dir="/tmp"' in runner, (
        "the runner no longer puts its private transport directory in /tmp; "
        "the harness shares /tmp for exactly that reason and must follow it")
    assert ("/tmp", "/tmp") in _binds()


def test_the_hermetic_arm_is_never_given_the_socket():
    """LOAD-BEARING, and the reason this repair is not a weakening. The arm runs
    UNREVIEWED candidate code under `--network none`, a read-only rootfs,
    `--cap-drop ALL` and uid 65534. A daemon socket there is root on the machine
    that is judging the candidate, including on the tree under test."""
    runner = _RUNNER.read_text(encoding="utf-8")
    # The runner does not merely omit the socket — it REFUSES a candidate that
    # has one, by inspecting the container Docker actually created. Asserting
    # the refusal rather than the absence is the difference between "nobody
    # added it" and "it cannot be added".
    assert 'raise Refusal("candidate inspection exposes docker.sock")' in runner
    assert 'raise ValueError("receipt exposes docker.sock")' in runner
    # And the harness never puts a socket anywhere but its own argument list.
    harness_socket_binds = [c for h, c in _binds() if "docker.sock" in h + c]
    assert all(h == c for h, c in _binds() if "docker.sock" in h + c), \
        harness_socket_binds


def test_a_scratch_root_the_gate_cannot_see_is_refused():
    r = _run("--no-engine", "--scratch", _NOT_VOLATILE, "--", "-q", "x.py")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not under a volatile root" in r.stderr, r.stderr


def test_the_refusal_names_the_prefixes_the_gate_actually_matches():
    """A harness that names its own list rather than the gate's would drift, and
    a drifted list refuses roots the gate is happy with."""
    spec = importlib.util.spec_from_file_location("_gate_for_prefixes", _GATE)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    r = _run("--no-engine", "--scratch", _NOT_VOLATILE, "--", "-q", "x.py")
    for prefix in gate._VOLATILE_PREFIXES:
        assert prefix.rstrip("/") in r.stderr, (prefix, r.stderr)


def test_the_refusal_states_no_cost_of_its_own_and_says_where_the_cost_lives():
    """This arm used to require the refusal to NAME TWO TEST FILES, and both of
    them cost 0 by the time anyone read it.

    That is the whole defect this file's own docstring warns about — "How many
    is not written here: it is stated, and re-measured every run, by
    `_VOLATILE_ADVISORY`" — asserted in the docstring and contradicted forty
    lines below it, where the `case` block carried
    `test_issue146_collect_external_outputs.py  4` (fixed in fc32402c8) and
    `test_project_outputs_in_tree_check.py  2` (fixed in the v1.16.85 landing).
    The arm PINNED the stale table in place: correcting the text would have
    turned this test red.

    So it is inverted. The refusal must carry NO count of its own, and must
    send the reader to the one place the count is re-measured every run.
    """
    r = _run("--no-engine", "--scratch", _NOT_VOLATILE, "--", "-q", "x.py")
    assert "scratch_root_guard.py" in r.stderr, r.stderr
    assert "_VOLATILE_ADVISORY" in r.stderr, r.stderr
    stale = re.findall(r"programs/tests/[A-Za-z0-9_.\-]+\.py\s+\d+", r.stderr)
    assert not stale, (
        "the harness states a cost table of its own; it will decay exactly as "
        f"the last one did, and nothing re-runs it: {stale}")


def test_a_volatile_scratch_root_is_not_refused_for_that_reason():
    """THE NEGATIVE CONTROL. A rule that refuses every root is a ban, not a
    rule. The engine is deliberately named as absent so the run stops right
    after the scratch question with no daemon involved."""
    r = _run("--scratch", "/var/tmp/vibeic-harness-selftest", "--", "-q", "x.py",
             env_extra={"VIBEIC_SUITE_DOCKER_BIN": "/no/such/docker"})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not under a volatile root" not in r.stderr, r.stderr
    assert "not an executable file" in r.stderr, r.stderr


def test_an_engine_that_is_named_and_absent_is_a_refusal_not_a_skip():
    r = _run("--scratch", "/var/tmp/vibeic-harness-selftest", "--", "-q", "x.py",
             env_extra={"VIBEIC_SUITE_DOCKER_BIN": "/no/such/docker"})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "REFUSED" in r.stderr


def test_no_engine_declares_itself_as_the_control_it_is():
    """`--no-engine` exists so the 23 can be brought back on demand — a repair
    that cannot be undone into the original failure was not measured. It must
    never read as an ordinary operating mode."""
    text = _HARNESS.read_text(encoding="utf-8")
    assert "--no-engine IS A CONTROL, NOT A MODE" in text
    assert "a green result would mean the control stopped checking" in text


def _pinned_parts() -> dict:
    """The two constants the harness reads: the pinned DIGEST and the DEFAULT
    repository.

    The pin is split on purpose. The digest is the identity -- the bytes -- and
    is asserted everywhere. The repository is deployment configuration, because
    the same bytes are served from the published registry and from a LAN one and
    which a host can reach is a fact about the network. This helper composes them
    exactly as the harness does, so the test moves with the harness and not with
    a copy of its answer.
    """
    import ast
    wanted = ("IMAGE_DIGEST", "IMAGE_REPO_DEFAULT")
    src = (_REPO / "tools/ci/hermetic_candidate_runner.py").read_text(
        encoding="utf-8")
    found = {}
    for node in ast.parse(src).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name = getattr(target, "id", "")
            if name in wanted and name not in found:
                found[name] = ast.literal_eval(node.value)
    missing = [name for name in wanted if name not in found]
    if missing:
        raise AssertionError(
            f"hermetic_candidate_runner.py pins no {', '.join(missing)}")
    return found


def _pinned_image() -> str:
    """The reference the harness will use with no env set."""
    parts = _pinned_parts()
    return f"{parts['IMAGE_REPO_DEFAULT']}@{parts['IMAGE_DIGEST']}"


def test_the_harness_keeps_no_literal_copy_of_the_pinned_digest():
    """The digest is READ from the one place the repo pins it, never copied.

    This file used to assert that `IMAGE_DEFAULT` WAS a digest literal, which is
    the property that let the two drift: measured 2026-09-06, the owner had
    ruled the runtime image forward to the 0.3.47-era build while this harness's
    own literal still named 0.3.6 — forty patch releases behind — so every
    operator who did not pass `--image` silently measured a toolchain nobody had
    pinned. A second copy of a pinned value is a second definition of it.
    """
    text = _HARNESS.read_text(encoding="utf-8")
    assert not re.search(r'IMAGE_DEFAULT="[^"]*@sha256:[0-9a-f]', text), (
        "the harness has grown a literal digest again; read the pin instead")
    assert "hermetic_candidate_runner.py" in text, (
        "the harness must name the pin it reads")


def test_the_pinned_image_is_a_digest_and_matches_the_landing_preflight():
    """A floating tag is how a host ends up with a runtime nobody pinned.

    THE PREFLIGHT READS THE PIN NOW; IT NO LONGER SPELLS IT. This used to look
    for the digest as TEXT in that file, which is the very shape the tests
    beside it assert against: a second literal copy of a pinned value is a
    second definition of it. The plugin's copy moved into
    `programs/_eda_pin.py`, so what is bound here is that the two REMAINING
    definitions -- the harness's and the plugin's -- name the same bytes, and
    that the preflight composes its reference from the plugin's rather than
    from a literal of its own.
    """
    image = _pinned_image()
    assert "@sha256:" in image, image
    digest = "sha256:" + image.split("@sha256:")[1]
    programs = _REPO / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    preflight = (programs / "landing_pytest_runtime_preflight.py").read_text(
        encoding="utf-8")
    assert "_pin.image_reference()" in preflight, (
        "the landing runtime preflight must READ the pin, not spell it")
    assert digest not in preflight, (
        "the landing runtime preflight has grown a literal digest again")

    import ast
    pin_src = (programs / "_eda_pin.py").read_text(encoding="utf-8")
    plugin_pin = None
    for node in ast.parse(pin_src).body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "IMAGE_DIGEST" for t in node.targets):
            plugin_pin = ast.literal_eval(node.value)
            break
    assert plugin_pin == digest, (
        "the pinned runtime and the plugin's pin name different images: "
        f"harness {digest} vs plugin {plugin_pin}")


def test_the_harness_composes_the_pin_from_digest_and_configured_repository():
    """The identity is the digest; the repository is configuration.

    The harness must read BOTH constants and honour the one env, so that a host
    which reaches the same bytes at a different registry is still pinned to those
    bytes. If it ever went back to reading a single composed constant, a
    deployment could only follow by editing the pin -- which is how a second
    definition of the runtime gets created.
    """
    text = _HARNESS.read_text(encoding="utf-8")
    assert "IMAGE_DIGEST" in text and "IMAGE_REPO_DEFAULT" in text, (
        "the harness must read the digest and the default repository")
    assert "VIBEIC_EDA_IMAGE_REPO" in text, (
        "the harness must honour the one repository config point")
    # and the digest it reads is a real digest, not a tag
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", _pinned_parts()["IMAGE_DIGEST"])


def test_the_harness_FORWARDS_the_one_config_point_into_the_container():
    """Resolving the repository on the HOST is half a config point.

    MEASURED 2026-09-07 on 8hd-3 (lane czto12, reproduced through this script):
    the harness resolved the pin with `${VIBEIC_EDA_IMAGE_REPO:-…}` on the host,
    started a container that could not see the variable, and a NESTED resolve
    inside it reported

        VIBEIC_EDA_IMAGE_REPO = None
        ghcr.io/vibeic/vibeic-eda@sha256:8da785a8… -> IMAGE_NOT_PRESENT

    while the identical resolve on the host names the fleet registry and finds
    the image. A deployment serving the pinned bytes from elsewhere could
    configure the host correctly and still have everything inside the harness
    fall back to a repository it cannot reach.

    The BARE `-e NAME` form is required, not `-e NAME=value`: docker copies the
    value when the variable is set and does NOT create it when unset, so an
    unset host env cannot inject an empty value that shadows the default. A
    literal address here would also be exactly the thing this repo forbids —
    the registry is CONFIGURATION and never belongs in the tree.
    """
    text = _HARNESS.read_text(encoding="utf-8")
    assert re.search(r"^\s*-e VIBEIC_EDA_IMAGE_REPO\s*$", text, re.M), (
        "the harness resolves VIBEIC_EDA_IMAGE_REPO on the host but does not "
        "forward it into the container; a nested resolve there falls back to "
        "the published repository and reports IMAGE_NOT_PRESENT")
    assert not re.search(r"-e VIBEIC_EDA_IMAGE_REPO=", text), (
        "forward the VARIABLE, never a value: `-e NAME=` would inject an empty "
        "string when the host env is unset and shadow the default")


def test_the_harness_writes_no_registry_address_into_the_tree():
    """The digest is the identity; the repository is deployment configuration.
    Configuration does not get committed."""
    text = _HARNESS.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text), (
        "a literal host address appears in the harness; the repository belongs "
        "in VIBEIC_EDA_IMAGE_REPO, not in the tree")


def test_the_harness_refuses_when_the_pin_cannot_be_read():
    """A read that fails must REFUSE, never fall back to a literal — a fallback
    is exactly how the second copy comes back."""
    text = _HARNESS.read_text(encoding="utf-8")
    assert "cannot read the pinned runtime image" in text
    assert "there is deliberately no fallback literal here" in text


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
