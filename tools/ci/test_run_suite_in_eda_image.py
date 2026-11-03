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
5. **A session that collected nothing, read as a clean one** (vibe-ic#2123). The
   harness runs pytest with the PLUGIN directory as the working directory, so a
   repo-root-relative selector after `--` resolves under the plugin directory,
   where it does not exist. MEASURED 2026-09-07 on 8hd-3 in the pinned image:
   `-- -q tools/ci/test_gatekeeper_status_poller.py` ended
   `[PASS] suite_write_guard: ...` / `no tests ran in 0.07s` /
   `ERROR: file or directory not found: ...`, rc 4. Nothing ran, no line said
   so, and the last verdict-shaped line was a PASS. A selector that names
   nothing here is now refused BY NAME before any container starts, and pytest
   exit 4 and exit 5 are refusals with a line of the harness's own.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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
    r = _run("--scratch", "/tmp/vibeic-harness-selftest", "--", "-q", "x.py",
             env_extra={"VIBEIC_SUITE_DOCKER_BIN": "/no/such/docker"})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not under a volatile root" not in r.stderr, r.stderr
    assert "not an executable file" in r.stderr, r.stderr


def test_an_engine_that_is_named_and_absent_is_a_refusal_not_a_skip():
    r = _run("--scratch", "/tmp/vibeic-harness-selftest", "--", "-q", "x.py",
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
    """The identity the runner will use, ASKED not parsed.

    This used to `ast.parse` `hermetic_candidate_runner.py` for an
    `IMAGE_DIGEST` assignment — right while the digest was a literal, and the
    reason it was read here rather than copied. There is no literal now: the
    identity is resolved from whatever EDA image this host holds, so a source
    parse finds nothing and this raised on every id in the file. Ask the module,
    which is still the OTHER module and still refuses rather than falling back.
    """
    import importlib.util as _u
    import sys as _sys
    p = _CI / "hermetic_candidate_runner.py"
    spec = _u.spec_from_file_location("_hcr_suite_probe", p)
    mod = _u.module_from_spec(spec)
    # Register before exec: the runner defines dataclasses, and @dataclass
    # resolves `sys.modules.get(cls.__module__).__dict__` while processing them.
    _sys.modules["_hcr_suite_probe"] = mod
    spec.loader.exec_module(mod)
    digest = mod._resolve_digest()
    if not digest:
        raise AssertionError(
            "hermetic_candidate_runner resolved no image identity on this host")
    return {"IMAGE_DIGEST": digest,
            "IMAGE_REPO_DEFAULT": mod.IMAGE_REPO_DEFAULT}


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

    # THE TWO HALVES STILL HAVE TO AGREE, and now they agree by construction:
    # both ASK `_eda_pin.resolved_image_digest()` rather than each holding a
    # literal that could drift from the other. This used to `ast.parse` the
    # plugin module for an `IMAGE_DIGEST` assignment; there is no assignment to
    # find, so it read None. Asking the module keeps the question — "do the
    # harness and the plugin name the same image" — answerable, and it is still
    # a real question: the harness reaches the identity through the runner and
    # the plugin through its own module, so a seam between them would show.
    import importlib.util as _u
    import sys as _sys
    _spec = _u.spec_from_file_location("_pin_agree_probe", programs / "_eda_pin.py")
    _pin = _u.module_from_spec(_spec)
    _sys.modules["_pin_agree_probe"] = _pin
    _spec.loader.exec_module(_pin)
    plugin_pin = _pin.resolved_image_digest()
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
    assert "cannot resolve the EDA runtime image" in text
    assert "there is deliberately no fallback literal here" in text


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))


# ── vibe-ic#2123: a session that collected nothing is not a clean session ──
#
# Everything below drives the harness itself. The two arms that need a
# container are given a STUB `docker` through `VIBEIC_SUITE_DOCKER_BIN`, which
# is the only way to fix pytest's exit code from outside: the question here is
# what the HARNESS does with an exit code, not what pytest does with a
# selection, and a 31 GB image is not needed to ask it. The end-to-end
# measurements against the real pinned image are recorded in the lane evidence
# named in the landing note; these are the arms that run anywhere.

#: WITHHELD ON PURPOSE, in every arm that drives the harness PAST the selector
#: check. An arm that reaches the container starts the real suite the moment the
#: check it is testing is mutated away — MEASURED in this lane: dropping the
#: selector check turned the `--deselect` arm into a full `programs/tests` run
#: inside the pinned image, which had to be killed by container id. A test whose
#: negative arm is a 20-minute suite run is not a test.
_NO_ENGINE_AT_ALL = {"VIBEIC_SUITE_DOCKER_BIN": "/no/such/docker"}

_STUB = """#!/bin/sh
# A stand-in for the Docker CLI on the native image: /etc/passwd is served, and
# /headless and --skip fail as they do there. Exits with $VIBEIC_STUB_RC for the
# run that would be the suite.
for a in "$@"; do
  case "$a" in
    /etc/passwd) echo "root:x:0:0:root:/root:/bin/sh"; exit 0 ;;
    /headless/*) exit 1 ;;
    --skip) exit 127 ;;
  esac
done
exit ${VIBEIC_STUB_RC:-0}
"""


def _stub_docker() -> tuple[str, str]:
    """`(scratch, stub_path)` — both under /tmp, both this call's own.

    `tempfile.mkdtemp(dir="/tmp")` rather than pytest's `tmp_path`: the scratch
    root has to be under a volatile prefix whoever runs this and wherever their
    TMPDIR points, and in this image `tmp_path` has been measured carrying a
    newline.
    """
    import os
    import stat
    import tempfile
    root = tempfile.mkdtemp(dir="/tmp", prefix="vibeic-2123-")
    stub = os.path.join(root, "docker")
    with open(stub, "w", encoding="utf-8") as fh:
        fh.write(_STUB)
    os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)
    return os.path.join(root, "scratch"), stub


def _stub_run(*args, rc: int):
    scratch, stub = _stub_docker()
    return _run("--no-engine", "--scratch", scratch, "--", *args,
                env_extra={"VIBEIC_SUITE_DOCKER_BIN": stub,
                           "VIBEIC_STUB_RC": str(rc)})


def test_a_relative_selector_that_names_nothing_here_is_refused_by_name():
    """THE DEFECT. `tools/ci/...` is a real path from the repository root and
    nothing at all from the plugin directory the harness runs in."""
    sel = "tools/ci/test_gatekeeper_status_poller.py"
    r = _run("--no-engine", "--scratch", "/tmp/vibeic-harness-selftest",
             "--", "-q", sel, env_extra=_NO_ENGINE_AT_ALL)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "REFUSED" in r.stderr, r.stderr
    # BY NAME: the selector, and the directory it was resolved against.
    assert sel in r.stderr, r.stderr
    assert "vibe-ic-marketplace/plugins/vibe-ic" in r.stderr, r.stderr
    assert "NOTHING WAS RUN" in r.stderr, r.stderr
    # and, because this one does exist at the repository root, the form to type
    assert str(_REPO / sel) in r.stderr, r.stderr


def test_the_selector_is_refused_and_never_silently_remapped():
    """A relative path re-resolved against a second directory is one string with
    two meanings; the caller never learns which one ran. The harness refuses for
    the same reason it refuses a remapped bind."""
    sel = "tools/ci/test_gatekeeper_status_poller.py"
    r = _run("--no-engine", "--scratch", "/tmp/vibeic-harness-selftest",
             "--", "-q", sel, env_extra=_NO_ENGINE_AT_ALL)
    assert "REMAPS NOTHING" in r.stderr, r.stderr
    # It stopped. A remap would have gone on to start a container.
    assert r.returncode == 2, r.stdout + r.stderr


def test_a_relative_selector_that_does_exist_here_is_not_refused():
    """THE NEGATIVE CONTROL for the selector check. A rule that refuses every
    relative selector is a ban, not a rule — `programs/tests/...` is how this
    suite is normally selected and it must still pass straight through.

    The engine is deliberately named as absent, so the run stops at the first
    thing AFTER the selector question — reading /etc/passwd out of the image —
    and that refusal is the evidence the selector check let it by.
    """
    sel = "programs/tests"
    assert (_REPO / "vibe-ic-marketplace/plugins/vibe-ic" / sel).is_dir(), (
        "this control needs a selector that really does exist under the plugin "
        "directory; it proves nothing otherwise")
    r = _run("--no-engine", "--scratch", "/tmp/vibeic-harness-selftest",
             "--", "-q", sel,
             env_extra={"VIBEIC_SUITE_DOCKER_BIN": "/no/such/docker"})
    assert "names nothing this run could collect" not in r.stderr, r.stderr
    assert "cannot read /etc/passwd" in r.stderr, r.stderr


# ── the OUTPUT paths: #2123's rule, asked of what the run WRITES ──────────
# The selector tests above cover a path the run READS. These cover a path it
# WRITES, which fails later and louder: pytest creates a `--junitxml` in
# `pytest_sessionfinish`, AFTER every test has run and BEFORE the terminal
# reporter writes its summary, so an unwritable one destroys the whole report
# and still exits 1 -- the same rc as a real failure, with no failure anywhere
# in the output for a scrape to find.

_UNMOUNTED = "/var/empty/vibeic-harness-selftest-unwritable/out.xml"


@pytest.mark.parametrize("opt,val", [
    ("--junitxml", _UNMOUNTED),
    ("--junit-xml", _UNMOUNTED),
    ("--log-file", "/var/empty/vibeic-harness-selftest-unwritable/run.log"),
    ("--basetemp", "/var/empty/vibeic-harness-selftest-unwritable/bt"),
])
def test_an_output_path_the_container_cannot_write_is_refused_by_name(opt, val):
    """MEASURED before this guard existed, pinned image, the SAME one-file
    selection with and without the option: without it, `1 failed, 7 passed`
    and a `FAILED` line; with it, rc still 1 but ZERO `N failed, M passed`
    lines, ZERO `short test summary info`, ZERO `FAILED` lines and no XML --

        PermissionError: [Errno 13] Permission denied: '<the host dir>'
          in pytest_sessionfinish -> os.makedirs

    The run's entire report is destroyed. This refuses before the tests run."""
    r = _run("--no-engine", "--scratch", "/tmp/vibeic-harness-selftest",
             "--", "-q", opt, val, "programs/tests",
             env_extra=_NO_ENGINE_AT_ALL)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "REFUSED" in r.stderr, r.stderr
    # BY NAME: the option and the path, as #2123 names the selector.
    assert opt in r.stderr, r.stderr
    assert val in r.stderr, r.stderr
    # and what it costs, so the refusal is not a bare rule
    assert "pytest_sessionfinish" in r.stderr, r.stderr


def test_the_attached_form_of_an_output_option_is_refused_too():
    """`--junitxml=PATH` never reaches the separate-value branch. A guard that
    only sees `--junitxml PATH` is one spelling away from being switched off."""
    r = _run("--no-engine", "--scratch", "/tmp/vibeic-harness-selftest",
             "--", "-q", f"--junitxml={_UNMOUNTED}", "programs/tests",
             env_extra=_NO_ENGINE_AT_ALL)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "REFUSED" in r.stderr, r.stderr
    assert _UNMOUNTED in r.stderr, r.stderr


@pytest.mark.parametrize("where", ["scratch", "repo", "tmp"])
def test_an_output_path_under_a_mount_is_not_refused(where, tmp_path):
    """THE NEGATIVE CONTROL, and the half that keeps this a rule rather than a
    ban: a guard that refuses EVERY output path would pass the tests above and
    make the option unusable. All three writable roots this harness mounts
    must still go through.

    As with the selector control, the engine is named absent so the run stops
    at the first thing AFTER the output-path question -- reading /etc/passwd
    out of the image -- and that refusal is the evidence it let this by."""
    target = {
        "scratch": "/tmp/vibeic-harness-selftest/out.xml",
        "repo": str(_REPO / "out-selftest.xml"),
        "tmp": "/tmp/vibeic-harness-selftest-out.xml",
    }[where]
    r = _run("--no-engine", "--scratch", "/tmp/vibeic-harness-selftest",
             "--", "-q", f"--junitxml={target}", "programs/tests",
             env_extra=_NO_ENGINE_AT_ALL)
    assert "is not writable from inside the container" not in r.stderr, r.stderr
    assert "cannot read /etc/passwd" in r.stderr, r.stderr


def test_a_non_output_attached_option_is_not_read_as_an_output_path():
    """THE FALSE-REFUSAL CONTROL for the attached-form branch. `--tb=line` and
    friends take the same `--name=value` shape and must pass straight through;
    the branch asks the OPTION first and only then the path."""
    r = _run("--no-engine", "--scratch", "/tmp/vibeic-harness-selftest",
             "--", "-q", "--tb=line", "--maxfail=1", "programs/tests",
             env_extra=_NO_ENGINE_AT_ALL)
    assert "is not writable from inside the container" not in r.stderr, r.stderr
    assert "cannot read /etc/passwd" in r.stderr, r.stderr
# ── the TIME BOUND precondition, declared rather than assumed ─────────────

def _shipped_timeout_probe() -> str:
    """The `python3 -c "..."` precondition block, lifted from the shipped
    harness and unescaped back into plain Python.

    Lifted rather than restated, for the reason the selector tests are driven
    rather than read: a copy of this logic in the test would keep passing after
    the shipped one changed."""
    text = _HARNESS.read_text(encoding="utf-8")
    marker = 'python3 -c "\nimport ast, importlib.util as _u'
    assert marker in text, (
        f"{_HARNESS} no longer carries the time-bound precondition block. "
        "Every @pytest.mark.timeout(...) in the suite is INERT in the pinned "
        "image and this block is the only thing that says so. If it moved, "
        "point this test at whatever replaced it -- do not delete it.")
    start = text.index(marker)
    start = text.index('"', start) + 1
    end = text.index('\n" || true', start)
    # Undo exactly what the inner bash undoes for a double-quoted word: a
    # backslash is literal EXCEPT before " \ $ or a backtick. Collapsing only
    # \" would leave \\n as a literal backslash-n and the arms would compare
    # against text the harness never prints.
    return re.sub(r'\\(["\\$`])', r'\1', text[start:end])


def _run_probe(tmp_path, *, plugin_present: bool, markers: str = ""):
    tests = tmp_path / "programs" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_probe_subject.py").write_text(markers, encoding="utf-8")
    env = dict(os.environ)
    shim = tmp_path / "shim"
    shim.mkdir()
    if plugin_present:
        (shim / "pytest_timeout.py").write_text("", encoding="utf-8")
    env["PYTHONPATH"] = str(shim)
    # `-S` -- site-packages OFF. THE HOST RUNNING THIS TEST MAY HAVE
    # pytest-timeout INSTALLED, and this one does, so an absent arm that merely
    # cleared PYTHONPATH would quietly become a second copy of the present arm
    # and prove nothing. With `-S` the only importable third-party module is
    # whatever `shim` holds, which is exactly the pinned image condition this
    # arm is about. The probe itself imports nothing but the standard library,
    # so `-S` costs it nothing.
    r = subprocess.run([sys.executable, "-S", "-c", _shipped_timeout_probe()],
                       capture_output=True, text=True, timeout=60,
                       cwd=str(tmp_path), env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    return r.stderr


def test_an_absent_timeout_plugin_is_declared_and_the_inert_markers_counted(tmp_path):
    """THE DEFECT. `pytest_timeout` is ABSENT from the pinned image, so pytest
    treats every `@pytest.mark.timeout(...)` as an unknown mark and runs the
    test with NO bound -- a wedged test hangs the whole session instead of
    failing one case, and the author who asked for the bound is never told.
    vibe-ic#1128: a precondition the tests assume must be DECLARED."""
    out = _run_probe(tmp_path, plugin_present=False, markers=(
        "import pytest\n"
        "pytestmark = pytest.mark.timeout(0)\n"
        "@pytest.mark.timeout(600)\n"
        "def test_a(): pass\n"
        "@pytest.mark.timeout(BUDGET)\n"
        "def test_b(): pass\n"))
    assert "pytest-timeout is ABSENT" in out, out
    assert "INERT" in out, out
    # The census is BROKEN DOWN and it ADDS UP, so a marker whose argument the
    # counter cannot read is reported rather than dropped: 3 markers = 1 real
    # bound + 1 zero + 1 non-literal.
    assert "3 marker(s) in 1 file(s)" in out, out
    assert "1 name a real bound" in out, out
    assert "1 name 0 (no bound asked for)" in out, out
    assert "1 have a non-literal argument" in out, out


def test_a_present_timeout_plugin_is_declared_as_active(tmp_path):
    """THE OTHER DIRECTION, and the one that keeps the line above a
    MEASUREMENT rather than a constant: with the plugin importable the same
    shipped block must say the bounds are active, not print the census."""
    out = _run_probe(tmp_path, plugin_present=True, markers=(
        "import pytest\n@pytest.mark.timeout(600)\ndef test_a(): pass\n"))
    assert "pytest-timeout is present" in out, out
    assert "ACTIVE" in out, out
    assert "ABSENT" not in out, out
    assert "INERT" not in out, out


def test_the_declaration_never_stops_the_run(tmp_path):
    """It DECLARES, it does not refuse. Refusing on an absent plugin would stop
    every run on the image the fleet currently uses, for a precondition no
    caller asked for -- the markers are the TESTS own requests. The shipped
    block is therefore `|| true` and writes only to stderr; if it ever grows a
    non-zero exit, that is a fleet-wide decision and this test says so."""
    text = _HARNESS.read_text(encoding="utf-8")
    probe_end = text.index('\n" || true',
                           text.index('import ast, importlib.util as _u'))
    assert probe_end > 0
    # ...and it writes to stderr only: nothing it prints can be mistaken for a
    # pytest verdict by a reader scraping stdout.
    assert "sys.stderr.write" in _shipped_timeout_probe()
    assert "sys.stdout" not in _shipped_timeout_probe()


def test_the_precondition_probe_carries_no_bash_active_characters():
    """A REGRESSION OF MY OWN, landed in #2445 and caught here.

    The probe is a python program written inside a bash DOUBLE-QUOTED word, so
    bash expands it before python ever sees it. A backtick opens a command
    substitution and `$` opens a parameter expansion -- in TEXT THAT LOOKS LIKE
    AN INERT COMMENT. #2445 added the explanatory line

        # every `mark.timeout(` in a COMMENT or a DOCSTRING too, ...

    and every harness run on the fleet then printed, to stderr, before a single
    test:

        bash: command substitution: line 53: syntax error near unexpected token `newline'
        bash: command substitution: line 53: `mark.timeout('

    The disclosure itself still printed and the census was right, so nothing
    went red and nothing said so -- which is exactly why this is pinned by a
    test rather than by care. A backtick inside that word is not a style
    question: bash RUNS what is between them, and the next one may sit in code
    rather than in a comment.
    """
    probe = _shipped_timeout_probe()
    # `_shipped_timeout_probe` has already undone bash's escaping, so anything
    # left here is what bash would have acted on.
    assert "`" not in probe, (
        "backtick(s) in the precondition probe: bash opens a command "
        "substitution inside the double-quoted word this program is written "
        "in. Offending line(s): "
        + repr([l for l in probe.splitlines() if "`" in l]))
    assert "$" not in probe, (
        "`$` in the precondition probe: bash expands it inside the "
        "double-quoted word. Offending line(s): "
        + repr([l for l in probe.splitlines() if "$" in l]))


def test_a_pattern_valued_option_is_not_read_as_a_selector():
    """THE FALSE-REFUSAL CONTROL. `--ignore-glob` takes a PATTERN, and a pattern
    that looks like a path must not be adjudicated as one — a check that refuses
    a legal invocation is a worse harness than the one it replaced."""
    r = _run("--no-engine", "--scratch", "/tmp/vibeic-harness-selftest",
             "--", "-q", "--ignore-glob", "tools/ci/*.py", "programs/tests",
             env_extra={"VIBEIC_SUITE_DOCKER_BIN": "/no/such/docker"})
    assert "names nothing this run could collect" not in r.stderr, r.stderr
    assert "cannot read /etc/passwd" in r.stderr, r.stderr


def test_a_deselect_that_names_nothing_here_is_refused_like_any_selector():
    """`--ignore` and `--deselect` take SELECTORS, and one that names nothing
    removes nothing — silently. They are checked, not skipped, and the refusal
    says so when the path is nowhere at all rather than pointing at a root."""
    r = _run("--no-engine", "--scratch", "/tmp/vibeic-harness-selftest",
             "--", "-q", "--deselect", "tools/ci/test_no_such_file.py::test_x",
             "programs/tests/test_covered_by.py", env_extra=_NO_ENGINE_AT_ALL)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "tools/ci/test_no_such_file.py::test_x" in r.stderr, r.stderr
    assert "does not exist under the repository root either" in r.stderr, r.stderr


def test_an_absolute_selector_is_the_callers_own_and_is_passed_through():
    """The escape hatch the refusal points at has to work. An absolute path is
    unambiguous, so the harness does not adjudicate it — including one that does
    not exist, which is pytest's rc 4 and is refused by the arm below."""
    r = _stub_run("-q", "/nonexistent-cz2123/test_x.py", rc=0)
    assert "names nothing this run could collect" not in r.stderr, r.stderr
    assert r.returncode == 0, r.stdout + r.stderr


def test_pytest_exit_4_is_a_refusal_and_names_that_nothing_ran():
    """rc 4 is pytest's usage error — what a selector naming no file produces.
    It is non-zero, and being non-zero was never the problem: its OUTPUT reads
    as a clean run to everything that scrapes it by text."""
    r = _stub_run("-q", "/nonexistent-cz2123/test_x.py", rc=4)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "REFUSED" in r.stderr, r.stderr
    assert "pytest exited 4" in r.stderr, r.stderr
    assert "0 collected" in r.stderr, r.stderr
    assert "NOTHING WAS RUN" in r.stderr, r.stderr


def test_pytest_exit_5_zero_collected_is_a_refusal_not_a_green():
    """rc 5 is `EXIT_NO_TESTS_COLLECTED` — an empty collection, including one
    emptied by `-k`, `-m` or `--deselect` AFTER collection. MEASURED against
    the real pinned image: `-k zzz_matches_nothing` printed
    `17 deselected in 0.05s` and no failure at all."""
    r = _stub_run("-q", "/nonexistent-cz2123/test_x.py", rc=5)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "REFUSED" in r.stderr, r.stderr
    assert "pytest exited 5" in r.stderr, r.stderr
    assert "0 collected" in r.stderr, r.stderr


def test_an_ordinary_run_is_not_turned_into_a_refusal():
    """THE OTHER DIRECTION. A refusal that fires on a real result would delete
    the harness. rc 0 and rc 1 must both come back unchanged."""
    green = _stub_run("-q", "/nonexistent-cz2123/test_x.py", rc=0)
    assert green.returncode == 0, (green.returncode, green.stdout, green.stderr)
    assert "REFUSED" not in green.stderr, green.stderr
    red = _stub_run("-q", "/nonexistent-cz2123/test_x.py", rc=1)
    assert red.returncode == 1, (red.returncode, red.stdout, red.stderr)
    assert "REFUSED" not in red.stderr, red.stderr


def test_every_run_ends_with_a_line_of_the_harness_own():
    """WHY THE DEFECT WAS READABLE AS CLEAN: the last verdict-shaped line in the
    stream belonged to the in-suite write guard (`[PASS] suite_write_guard`),
    and the harness said nothing at all about whether it had produced a verdict.
    Now it always does — on the green run too, or the line's presence would
    itself be the signal."""
    for rc, phrase in ((0, "pytest exited 0"), (1, "pytest exited 1"),
                       (3, "pytest exited 3")):
        r = _stub_run("-q", "/nonexistent-cz2123/test_x.py", rc=rc)
        assert phrase in r.stderr, (rc, r.stderr)


def test_the_zero_collect_readers_the_harness_names_all_refuse_it():
    """The harness is not the only thing that reads this stream, and it must not
    be the one reader that disagrees with the rest. Every reader named in its
    exit-code block is called here, so the naming cannot go stale.
    """
    text = _HARNESS.read_text(encoding="utf-8")
    for named in ("tools/core_agent/covered_by.py",
                  "tools/ci/gatekeeper_status_poller.py",
                  "programs/pytest_per_file_junit.py"):
        assert named in text, (
            f"the harness no longer names {named} as a reader of this stream")

    def _load(rel, name):
        spec = importlib.util.spec_from_file_location(name, _REPO / rel)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    covered_by = _load("tools/core_agent/covered_by.py", "_cz2123_covered_by")
    assert covered_by.classify_run("no tests ran in 0.01s\n", 5) == \
        covered_by.FAILED

    poller = _load("tools/ci/gatekeeper_status_poller.py", "_cz2123_poller")
    state, _why = poller.classify(
        4, "ERROR: file or directory not found: tools/ci/x.py\n"
           "\nno tests ran in 0.07s\n")
    assert state == "error", state

    # The JUnit driver is read rather than imported: it is a several-thousand
    # line program with a CLI, and the property wanted here is one predicate.
    junit = (_REPO / "vibe-ic-marketplace/plugins/vibe-ic/programs"
             / "pytest_per_file_junit.py").read_text(encoding="utf-8")
    assert "def _zero_collect(" in junit, (
        "the per-file JUnit driver no longer separates a zero-collect file from "
        "a green one; the harness names it as a reader that refuses this shape")


def test_the_harness_states_the_defect_it_closes():
    """A refusal whose reason is not written down is deleted by the next person
    who finds it inconvenient."""
    text = _HARNESS.read_text(encoding="utf-8")
    assert "vibe-ic#2123" in text
    assert "no tests ran in 0.07s" in text, (
        "the harness must keep the measurement that produced this rule")


# ══════════════════════════════════════════════════════════════════════════
# THE PIN IS RESOLVED BY DIGEST HERE TOO (vibe-ic#2170)
#
# This harness composed `<configured repo>@<pinned digest>` and handed that
# STRING to `docker run`. That is the same composition defect #2170 repaired in
# `hermetic_candidate_runner`, one call site over, and it was not in the
# measured red set only because nothing had exercised it on a host that would
# fail. It has no red to reproduce, so it is DRIVEN: a stub Docker states what
# the host holds, and the harness's own behaviour is read off its output.
#
# Worse here than a refusal, which is why the arms below assert it: there is no
# `--pull=never` on the `docker run` calls, so an unresolvable reference starts
# fetching a ~22 GB image inside a landing gate rather than failing fast.
# ══════════════════════════════════════════════════════════════════════════

_RESOLVE_STUB = """#!/bin/sh
# A stand-in for the Docker CLI that STATES what this host holds.
#   VIBEIC_STUB_HELD   — newline-separated `repo@sha256:…` rows for `image ls`
#   VIBEIC_STUB_HAVE   — the one reference `image inspect` resolves ("" = none)
# Every argv is appended to $VIBEIC_STUB_LOG so an arm can assert what was
# ASKED: "it refused" and "it refused without starting a fetch" are different
# claims and only the argv separates them.
printf '%s\\n' "$*" >> "$VIBEIC_STUB_LOG"
case "$1 $2" in
  "image inspect")
    [ -n "$VIBEIC_STUB_HAVE" ] || { echo "Error: No such image: $3" >&2; exit 1; }
    [ "$3" = "$VIBEIC_STUB_HAVE" ] || { echo "Error: No such image: $3" >&2; exit 1; }
    echo '[]'; exit 0 ;;
  "image ls")
    # TAGGED vs UNTAGGED, because `docker image ls` lists tagged images ONLY and
    # an image pulled by digest carries no tag (#2170). A stub that ignores the
    # flag is more capable than the command and cannot fail.
    case " $* " in
      *" -a "*|*" --all "*) printf '%s\\n' "$VIBEIC_STUB_HELD_ALL" ;;
      *)                    printf '%s\\n' "$VIBEIC_STUB_HELD_TAGGED" ;;
    esac
    exit 0 ;;
esac
for a in "$@"; do
  case "$a" in
    /etc/passwd) echo "root:x:0:0:root:/root:/bin/sh"; exit 0 ;;
    /headless/*) exit 1 ;;
    --skip) exit 127 ;;
  esac
done
exit ${VIBEIC_STUB_RC:-0}
"""


_ABS_SELECTOR = str(_HARNESS.parent / "test_run_suite_in_eda_image.py")


def _resolve_case(held, have, repo_env="registry.published.invalid/vibeic-eda",
                  tagged=None):
    """Drive the harness with the engine ON and a stated host.

    The engine arm needs a UNIX socket to exist, and this makes its OWN rather
    than borrowing `/var/run/docker.sock`: an arm whose premise is "this host
    runs Docker" asserts something different on a host that does not.
    """
    import os
    import socket
    import stat
    import tempfile
    root = tempfile.mkdtemp(dir="/tmp", prefix="vibeic-pinresolve-")
    stub = os.path.join(root, "docker")
    with open(stub, "w", encoding="utf-8") as fh:
        fh.write(_RESOLVE_STUB)
    os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)
    sock_path = os.path.join(root, "docker.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    log = os.path.join(root, "argv.log")
    open(log, "w", encoding="utf-8").close()
    env = {"VIBEIC_SUITE_DOCKER_BIN": stub,
           "DOCKER_HOST": "unix://" + sock_path,
           "VIBEIC_STUB_LOG": log,
           "VIBEIC_STUB_HELD_ALL": "\n".join(held),
           "VIBEIC_STUB_HELD_TAGGED": "\n".join(tagged if tagged is not None
                                                 else held),
           "VIBEIC_STUB_HAVE": have or "",
           "VIBEIC_STUB_RC": "0"}
    env["VIBEIC_EDA_IMAGE_REPO"] = repo_env
    try:
        # AN ABSOLUTE SELECTOR, which this harness passes through untouched.
        # A repo-root-relative one is refused before any container is
        # considered, and that refusal would end every arm below at the
        # selector check instead of at the thing being measured.
        proc = _run("--scratch", os.path.join(root, "scratch"), "--", "-q",
                    "--collect-only", _ABS_SELECTOR, env_extra=env)
    finally:
        srv.close()
    with open(log, encoding="utf-8") as fh:
        argv = fh.read()
    return proc, argv


def _pin_digest():
    return _pinned_parts()["IMAGE_DIGEST"]


def test_the_harness_runs_the_pinned_digest_held_under_another_repository():
    """The measured fleet state: 8HD-9 holds the pin under the mirror only.

    The configured reference does not resolve, an image carrying the pinned
    digest does, and the harness runs THAT one -- naming both, so the operator
    learns the repository they configured is absent here.
    """
    mirror = f"registry.invalid:5000/vibeic-eda@{_pin_digest()}"
    proc, argv = _resolve_case(held=[mirror], have=None)
    assert "[DISCLOSURE]" in proc.stderr, (
        f"the substitution was silent; VIBEIC_EDA_IMAGE_REPO is decorative if a "
        f"fallback is not announced. stderr:\n{proc.stderr[-2000:]}")
    assert mirror in proc.stderr and _pin_digest() in proc.stderr
    assert f"run " in argv and mirror in argv, (
        f"the resolved reference is not the one that was run: {argv[-2000:]}")


def test_the_harness_refuses_when_no_local_image_carries_the_pinned_digest():
    """And refuses WITHOUT starting a fetch, which is the point.

    A different digest is present, under exactly the published name, so this
    arm fails on identity and not on the lookup — and nothing may be widened to
    let it through.
    """
    other = "sha256:" + "b" * 64
    proc, argv = _resolve_case(held=[f"ghcr.io/vibeic/vibeic-eda@{other}"],
                               have=None)
    assert proc.returncode != 0
    assert _pin_digest() in proc.stderr, (
        f"the refusal does not name the digest it wanted: {proc.stderr[-2000:]}")
    assert "pull" not in argv.split("image ls")[-1], (
        f"a fetch was started by the refusal path: {argv}")
    assert "\nrun " not in "\n" + argv, (
        f"the container was started anyway: {argv}")


def test_the_harness_says_nothing_when_the_configured_reference_resolves():
    """The disclosure is CONDITIONAL, and this is the control that proves it.

    Without this arm, a harness that printed `[DISCLOSURE]` unconditionally
    would pass the test above while telling every operator their configuration
    had been overridden.
    """
    repo = "registry.invalid:5000/vibeic-eda"
    configured = f"{repo}@{_pin_digest()}"
    proc, _argv = _resolve_case(held=[configured], have=configured,
                                repo_env=repo)
    assert "[DISCLOSURE]" not in proc.stderr, proc.stderr[-2000:]


def test_an_explicit_image_is_the_operators_own_and_is_never_resolved_away():
    """`--image` is the operator naming a runtime themselves.

    Resolving that to something else would be this harness overruling a person,
    which is a different act from resolving its own pin.
    """
    import os
    import socket
    import stat
    import tempfile
    root = tempfile.mkdtemp(dir="/tmp", prefix="vibeic-pinresolve-")
    stub = os.path.join(root, "docker")
    with open(stub, "w", encoding="utf-8") as fh:
        fh.write(_RESOLVE_STUB)
    os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)
    sock_path = os.path.join(root, "docker.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    log = os.path.join(root, "argv.log")
    open(log, "w", encoding="utf-8").close()
    mine = "my.registry.invalid/thing:1.2.3"
    try:
        proc = _run("--image", mine, "--scratch", os.path.join(root, "scratch"),
                    "--", "-q", "--collect-only", _ABS_SELECTOR,
                    env_extra={"VIBEIC_SUITE_DOCKER_BIN": stub,
                               "DOCKER_HOST": "unix://" + sock_path,
                               "VIBEIC_STUB_LOG": log,
                               "VIBEIC_STUB_HELD_ALL": "",
                               "VIBEIC_STUB_HELD_TAGGED": "",
                               "VIBEIC_STUB_HAVE": "",
                               "VIBEIC_STUB_RC": "0"})
    finally:
        srv.close()
    with open(log, encoding="utf-8") as fh:
        argv = fh.read()
    assert "[DISCLOSURE]" not in proc.stderr
    assert mine in argv, f"the operator's own image was not the one run: {argv}"


def test_the_harness_finds_the_pin_when_it_is_held_UNTAGGED():
    """THE FLEET'S REAL STATE (#2170, isolated on 8HD-9).

    Pulled by digest, so no tag, so `docker image ls` does not list it. This
    arm holds the pin ONLY in the `-a` listing, which is what a digest-pinned
    host actually looks like — and it is the arm that fails if the flag is
    dropped.
    """
    mirror = f"registry.invalid:5000/vibeic-eda@{_pin_digest()}"
    proc, argv = _resolve_case(held=[mirror], tagged=[], have=None)
    assert "[DISCLOSURE]" in proc.stderr, (
        f"the pin is held untagged and was not found: {proc.stderr[-2000:]}")
    assert mirror in argv


def test_the_harness_lists_ALL_images_when_it_resolves_the_pin():
    """The argv, asserted, so a future edit that drops `-a` reddens."""
    mirror = f"registry.invalid:5000/vibeic-eda@{_pin_digest()}"
    _proc, argv = _resolve_case(held=[mirror], tagged=[], have=None)
    listings = [ln for ln in argv.splitlines() if ln.startswith("image ls")]
    assert listings, f"the harness never listed images: {argv}"
    for ln in listings:
        assert " -a " in f" {ln} " or " --all " in f" {ln} ", (
            f"`docker image ls` without `-a` cannot see an image pulled by "
            f"digest: {ln}")
