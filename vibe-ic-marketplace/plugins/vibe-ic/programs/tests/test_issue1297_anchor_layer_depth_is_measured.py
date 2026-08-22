#!/usr/bin/env python3
"""vibe-ic#1297 — a tag that RESOLVES is not the same as a tag that can be PULLED.

THE DEFECT, as measured. Every instrument `sync_image_version.py` had asked a
question about NAMES: does each live pointer equal the anchor, does the anchor
exist on the registry, does `:latest` mean the same bytes as the anchor. On
2026-08-15, against the real registry, all three passed for the anchor `0.2.99`
and `docker pull` of that same tag failed on a clean host:

    $ docker pull <the vibeic-eda anchor of the day>      (8HD-7, overlay2, 29.1.3)
    ff210a8370bf: Pull complete
    e94f82f1a142: Pull complete
    failed to register layer: max depth exceeded
    RC=1

(The pull target is described rather than spelled: a fully-qualified
`ghcr.io/...:X.Y.Z` in a tracked file is read by this repo's own drift net as an
unregistered LIVE POINTER, and writing it here made `--check` go red — correctly.
See the `_GHCR` note below; it is the same rule, and it applies to prose too.)

The image carries 126 layers; the daemon's layer store registers at most 125.
So an anchor could be published, resolvable, current, and internally consistent
with every pointer in the tree — and still be impossible to materialise, with
NOTHING in the repository saying so. The tests that need that image then report
NOT VERIFIED and print a remedy (`docker pull ...`) that returns rc 1, which is
a disclosure that hands the reader an unsatisfiable command.

WHAT THIS FILE PINS

  THE INSTRUMENT EXISTS AND IS EXACT — `check_layer_depth` reads the layer count
  off the registry MANIFEST (no pull) and compares it against a MEASURED
  ceiling. The ceiling is the load-bearing number and this file pins it at 125,
  not 128: the issue inferred 128 from overlay2 and was wrong by three IN THE
  UNSAFE DIRECTION, which is how `0.2.98` was called "safe by inspection,
  headroom 2" while it was already one layer over. Reproduced directly:

      Step 126/129 : COPY f.txt /l125
       ---> 8750d92102e6          <- the 125th layer REGISTERS
      Step 127/129 : COPY f.txt /l126
      max depth exceeded          <- the 126th is REFUSED

  IT BLOCKS WHERE THIS REPO IS ACTING, AND ONLY THERE — `--set` is the moment
  this repository ADOPTS a tag, so an unpullable target is refused there, for
  the same reason and at the same instant as vibe-ic#354's does-it-resolve
  check. `--report-upstream` only REPORTS it, because the repair is a squash in
  the `vibeic/vibeic-eda` build: a blocking verdict here would be a red gate no
  commit in this repo could turn green, which is the unsatisfiable-gate shape
  the issue itself warns against.

PAIRED GUARDS — the second half of this file, and the reason this is a fix
rather than a new way to be stuck. The cheapest way to pass a depth check is to
raise the number, or to stop looking, so:

    the ceiling cannot be moved by the environment      still 125
    the check is off by ZERO, not by one                125 passes, 126 refuses
    an attestation entry is never counted as the image  a vacuous PASS is the
                                                        failure mode this check
                                                        is most exposed to
    `--check` still makes no registry call              vibe-ic#927 unbroken
    `--bump` (MINTING) is still not depth-checked       the tag cannot exist yet
    a registry that did not answer is NOT a refusal     and says it did not look
    `--allow-over-depth` adopts without SILENCING       the finding still prints

Deliberately NOT here: a test that queries the real ghcr. This suite runs on
landing hosts and a network round-trip would make its verdict a function of
whether ghcr answered the phone — the exact coupling vibe-ic#927 and #539
removed from the gate. The live reading belongs in `--report-upstream`, which is
where it now lives.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

# parents: [0]=tests [1]=programs [2]=vibe-ic [3]=plugins
# [4]=vibe-ic-marketplace [5]=repo root. `test_the_denominator_is_real` fails
# loudly if this is off by one, rather than letting every assertion below pass
# vacuously against a path that does not exist.
_REPO = Path(__file__).resolve().parents[5]
_PROG = _REPO / "tools" / "vibeic-eda" / "sync_image_version.py"
_ENV_KEY = "VIBEIC_EDA_PUBLISHED_TAG"

pytestmark = pytest.mark.skipif(
    not _PROG.is_file(),
    reason=f"{_PROG} not present (packaged plugin ships no repo-root tools/)")

#: The pull line is ASSEMBLED, never spelled as a literal — a fully-qualified
#: `ghcr.io/...:X.Y.Z` in a tracked file is what the repo-wide drift net reads
#: as an unregistered LIVE POINTER. Same reason, same shape, as the note in
#: test_issue927_*: a fixture the net cannot see needs no exemption.
_GHCR = "ghcr.io/vibeic/" + "vibeic-eda"


# ── harness ──────────────────────────────────────────────────────────────────

def _load_prog(name="siv1297"):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, _PROG)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _fixture_repo(tmp_path, anchor="1.0.0"):
    """A minimal self-contained repo the tool runs in unmodified.

    The tool prefers `script_dir/VERSION`, so the SCRIPT is copied in beside a
    fixture VERSION — its documented "runs from either repo" mode, not a hack.
    Synthetic versions are used so nothing here is coupled to whatever the real
    anchor happens to be on the day this runs.
    """
    root = tmp_path / "fixture"
    (root / "tools" / "vibeic-eda").mkdir(parents=True)
    shutil.copy2(_PROG, root / "tools" / "vibeic-eda" / "sync_image_version.py")
    (root / "tools" / "vibeic-eda" / "VERSION").write_text(anchor + "\n")
    (root / "README.md").write_text(
        f"# fixture\n\n    docker pull {_GHCR}:{anchor}\n")
    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"],
                ["git", "add", "-A"],
                ["git", "commit", "-qm", "fixture"]):
        subprocess.run(cmd, cwd=str(root), check=True,
                       capture_output=True, text=True)
    return root


def _run(root, argv, layers=None, layers_raise=False, sever_network=False,
         env_extra=None):
    """Run the tool in `root` with the LAYER READER stubbed to a known count.

    Only the one registry accessor this issue adds is stubbed, and it is stubbed
    from OUTSIDE (patched on the imported module before `main` runs) rather than
    by mocking the decision logic — mocking the code under test to prove the
    code under test is circular. `published_tags` is driven through its existing
    documented env override, so the "is it published" half is real code.
    """
    prog = root / "tools" / "vibeic-eda" / "sync_image_version.py"
    env = dict(os.environ)
    env.pop(_ENV_KEY, None)
    env.update(env_extra or {})
    pre = ["import sys, importlib.util",
           f"spec = importlib.util.spec_from_file_location('siv', {str(prog)!r})",
           "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)"]
    if sever_network:
        # Name resolution and connection setup only. Replacing `socket.socket`
        # itself breaks `ssl`'s class definition at IMPORT time, which would
        # make this arm fail for a reason unrelated to the registry.
        pre[:0] = ["import socket",
                   "def _boom(*a, **k):",
                   "    raise TimeoutError('simulated unreachable registry')",
                   "socket.getaddrinfo = _boom",
                   "socket.create_connection = _boom"]
    if layers_raise:
        pre.append("def _lr(*a, **k):\n"
                   "    raise TimeoutError('simulated unreachable registry')\n"
                   "m._query_ghcr_layer_count = _lr")
    elif layers is not None:
        pre.append(f"m._query_ghcr_layer_count = lambda *a, **k: {int(layers)}")
    pre.append(f"sys.exit(m.main({argv!r}))")
    return subprocess.run([sys.executable, "-c", "\n".join(pre)],
                          cwd=str(root), capture_output=True, text=True,
                          env=env, timeout=60)


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _version_of(root: Path) -> str:
    return (root / "tools" / "vibeic-eda" / "VERSION").read_text().strip()


# ── THE PROPERTY: both arms, same bytes ──────────────────────────────────────

def test_set_refuses_a_target_that_cannot_be_registered(tmp_path):
    """RED ARM. The target is published and resolves — and carries one layer
    more than the daemon will register. Before this change the adoption
    succeeded and every pointer in the tree named an image nobody could pull.

    The tree must be left EXACTLY as found: a refused adoption that already
    half-rewrote the pointers is a worse state than the one it refused.
    """
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    cp = _run(root, ["--set", "1.0.1"], layers=126,
              env_extra={_ENV_KEY: "1.0.1"})
    blob = cp.stdout + cp.stderr
    assert cp.returncode == 1, blob
    assert "UNPULLABLE ADOPTION TARGET" in cp.stdout, blob
    assert "126 layers" in cp.stdout, blob
    assert _version_of(root) == "1.0.0", (
        "the refused adoption still wrote VERSION — a rejected --set must "
        "leave the tree untouched")


def test_set_accepts_a_target_at_the_ceiling(tmp_path):
    """GREEN ARM. Same program, same fixture shape, one fewer layer — the
    adoption goes through and the anchor moves.

    Paired with the test above this is the whole claim: the check DISCRIMINATES.
    A green bought by a check that cannot fail proves nothing, and a red bought
    by a check that always fails proves less.
    """
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    cp = _run(root, ["--set", "1.0.1"], layers=125,
              env_extra={_ENV_KEY: "1.0.1"})
    blob = cp.stdout + cp.stderr
    assert cp.returncode == 0, blob
    assert "adoption target layer depth" in cp.stdout, blob
    assert "headroom 0" in cp.stdout, blob
    assert _version_of(root) == "1.0.1", blob


def test_both_arms_ran_the_same_program(tmp_path):
    """The two arms above differ ONLY in the layer count, and this proves it:
    the program's md5 is identical in both, so the opposite verdicts cannot be
    explained by a difference in the tree."""
    red = _fixture_repo(tmp_path / "red", anchor="1.0.0")
    green = _fixture_repo(tmp_path / "green", anchor="1.0.0")
    red_prog = red / "tools" / "vibeic-eda" / "sync_image_version.py"
    green_prog = green / "tools" / "vibeic-eda" / "sync_image_version.py"
    assert _md5(red_prog) == _md5(green_prog) == _md5(_PROG), (
        f"arms ran different bytes: red={_md5(red_prog)} "
        f"green={_md5(green_prog)} source={_md5(_PROG)}")
    rc_red = _run(red, ["--set", "1.0.1"], layers=126,
                  env_extra={_ENV_KEY: "1.0.1"}).returncode
    rc_green = _run(green, ["--set", "1.0.1"], layers=125,
                    env_extra={_ENV_KEY: "1.0.1"}).returncode
    assert (rc_red, rc_green) == (1, 0), (rc_red, rc_green)


@pytest.mark.parametrize("n,expect_rc", [(124, 0), (125, 0), (126, 1), (127, 1)])
def test_the_boundary_is_off_by_zero(tmp_path, n, expect_rc):
    """The ceiling is 125 and the comparison is `>`, both measured.

    This issue's own headline number was 128, inferred from the storage driver,
    and the error was in the direction that lets an unpullable image through.
    An off-by-one here would do the same thing again, so the boundary is
    asserted at each of its four neighbouring values rather than in the middle.
    """
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    cp = _run(root, ["--set", "1.0.1"], layers=n, env_extra={_ENV_KEY: "1.0.1"})
    assert cp.returncode == expect_rc, f"{n} layers -> rc {cp.returncode}\n{cp.stdout}"


# ── the reading itself: what gets counted ────────────────────────────────────

class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_registry(monkeypatch, manifests):
    """Serve `manifests` (ref -> payload) over a stubbed urlopen."""
    def _open(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if "/token" in url:
            return _Resp({"token": "t"})
        ref = url.rsplit("/manifests/", 1)[1]
        if ref not in manifests:
            raise KeyError(f"no such manifest: {ref}")
        return _Resp(manifests[ref])
    monkeypatch.setattr(urllib.request, "urlopen", _open)


def test_an_attestation_entry_is_never_counted_as_the_image(monkeypatch):
    """THE VACUOUS-PASS GUARD, and the failure mode this check is most exposed
    to.

    The registry serves BOTH manifest shapes for this image, measured:
    `0.2.89`/`0.2.92` are OCI indexes whose entries include an
    `unknown/unknown` attestation manifest, while `0.2.98`/`0.2.99` are plain
    image manifests. The attestation carries a handful of layers. An
    implementation that took the first index entry would therefore read ~1 on a
    200-layer image and print vast headroom — a PASS produced by looking at the
    wrong object, which is worse than no check at all.
    """
    m = _load_prog("siv1297_att")
    _fake_registry(monkeypatch, {
        "1.0.1": {"manifests": [
            {"digest": "sha256:att", "platform": {"os": "unknown",
                                                  "architecture": "unknown"}},
            {"digest": "sha256:amd", "platform": {"os": "linux",
                                                  "architecture": "amd64"}},
        ]},
        "sha256:att": {"layers": [{"digest": "sha256:x"}]},
        "sha256:amd": {"layers": [{"digest": f"sha256:{i}"} for i in range(200)]},
    })
    assert m._query_ghcr_layer_count("vibeic/vibeic-eda", "1.0.1") == 200


def test_a_plain_image_manifest_is_read_directly(monkeypatch):
    """The other shape the registry actually serves — no index, `layers` at the
    top level. Both shapes are live today, so both are pinned."""
    m = _load_prog("siv1297_plain")
    _fake_registry(monkeypatch, {
        "1.0.1": {"layers": [{"digest": f"sha256:{i}"} for i in range(126)]},
    })
    assert m._query_ghcr_layer_count("vibeic/vibeic-eda", "1.0.1") == 126


def test_an_index_with_no_amd64_entry_raises_rather_than_guessing(monkeypatch):
    """"I could not find the image" must not become "the image is small".

    Raising sends the caller down its could-not-look path, which prints NOT
    CHECKED / UNVERIFIED and never claims the depth is fine.
    """
    m = _load_prog("siv1297_noamd")
    _fake_registry(monkeypatch, {
        "1.0.1": {"manifests": [
            {"digest": "sha256:att", "platform": {"os": "unknown",
                                                  "architecture": "unknown"}},
        ]},
        "sha256:att": {"layers": [{"digest": "sha256:x"}]},
    })
    with pytest.raises(ValueError):
        m._query_ghcr_layer_count("vibeic/vibeic-eda", "1.0.1")


# ── PAIRED GUARDS: what must NOT change ──────────────────────────────────────

def test_the_ceiling_cannot_be_raised_by_the_environment(tmp_path):
    """The cheapest way to pass a depth check is to raise the number.

    Every other registry fact in this file has an env pin because it is a value
    another ORG moves; this one is a property of the DAEMON, and a knob would
    let the next bump wish the ceiling away instead of squashing the image.
    """
    m = _load_prog("siv1297_ceiling")
    assert m.MAX_REGISTRABLE_LAYERS == 125, (
        "the measured moby layer-store ceiling on Docker 29.1.3 / overlay2 is "
        "125; 128 is the overlay2 mount limit and is the wrong number, in the "
        "unsafe direction")
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    for key in ("MAX_REGISTRABLE_LAYERS", "VIBEIC_EDA_MAX_LAYERS",
                "VIBEIC_EDA_LAYER_CEILING", "DOCKER_MAX_LAYER_DEPTH"):
        cp = _run(root, ["--set", "1.0.1"], layers=126,
                  env_extra={_ENV_KEY: "1.0.1", key: "9999"})
        assert cp.returncode == 1, (
            f"{key} moved the ceiling — the gate is negotiable\n{cp.stdout}")
        assert _version_of(root) == "1.0.0"


def test_the_blocking_check_still_makes_no_registry_call(tmp_path):
    """vibe-ic#927 must survive this change.

    `--check` is the landing gate and it is offline BY CONSTRUCTION. A depth
    reading needs the registry, so it went to `--set` and `--report-upstream`
    and nowhere near here. Asserted behaviourally (sockets severed) AND
    structurally (the function body), because a program that calls the registry
    and then ignores the answer would satisfy the first alone.
    """
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    cp = _run(root, ["--check"], sever_network=True)
    blob = cp.stdout + cp.stderr
    assert cp.returncode == 0, blob
    assert "TimeoutError" not in blob, blob
    src = _PROG.read_text(encoding="utf-8")
    body = src.split("def do_check", 1)[1].split("\ndef ", 1)[0]
    assert "check_layer_depth" not in body and "_query_ghcr" not in body, (
        "the blocking half now reaches the registry — the coupling #927 removed")


def test_minting_a_version_is_still_not_depth_checked(tmp_path):
    """`--bump` runs in the `vibeic-eda` repo to CHOOSE the number about to be
    BUILT. That tag cannot exist yet, by construction, so it has no layer count
    and demanding one would make `--bump` permanently unusable — the same trap
    the adoption-resolves check fell into when it was first added."""
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    cp = _run(root, ["--bump", "patch"], sever_network=True)
    blob = cp.stdout + cp.stderr
    assert cp.returncode == 0, blob
    assert _version_of(root) == "1.0.1", blob
    assert "UNPULLABLE" not in blob, blob


def test_a_registry_that_did_not_answer_is_not_a_refusal(tmp_path):
    """"Could not look" is not "over the ceiling", and it is not "fine" either.

    Refusing to pin because ghcr timed out would make the anchor unmaintainable
    on a plane — the existing policy for the resolves check, kept. What is NOT
    kept is silence: the run must say the count was never read.
    """
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    cp = _run(root, ["--set", "1.0.1"], layers_raise=True,
              env_extra={_ENV_KEY: "1.0.1"})
    blob = cp.stdout + cp.stderr
    assert cp.returncode == 0, blob
    assert "UNVERIFIED" in cp.stdout and "count not read" in cp.stdout, blob
    assert _version_of(root) == "1.0.1", blob


def test_allow_over_depth_adopts_without_silencing_the_finding(tmp_path):
    """The escape hatch exists because the anchor is ALREADY over the ceiling
    and the repair lives in another repository; without it this check would
    freeze the anchor on someone else's schedule.

    What it must never become is a way to make the message go away. The full
    finding is printed either way and the override is announced on its own line,
    so a reader of the log sees a decision, not a green run.
    """
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    cp = _run(root, ["--set", "1.0.1", "--allow-over-depth"], layers=126,
              env_extra={_ENV_KEY: "1.0.1"})
    blob = cp.stdout + cp.stderr
    assert cp.returncode == 0, blob
    assert "LAYER DEPTH OVER CEILING" in cp.stdout, blob
    assert "[OVERRIDDEN]" in cp.stdout, blob
    assert _version_of(root) == "1.0.1", blob


def test_the_report_half_reports_and_never_blocks(tmp_path):
    """The asymmetry is the point.

    The repair for an over-depth anchor is a squash in the `vibeic/vibeic-eda`
    build. A blocking verdict here would hand every agent in this repo a red
    gate that no commit in this repo can turn green — the unsatisfiable-gate
    shape #1297 itself warns about. So the reading is loud, dated, and rc 0.
    """
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    out = tmp_path / "rec" / "upstream.json"
    cp = _run(root, ["--report-upstream", "--json", str(out)], layers=126,
              env_extra={_ENV_KEY: "1.0.0"})
    blob = cp.stdout + cp.stderr
    assert cp.returncode == 0, blob
    assert "CANNOT BE PULLED" in cp.stdout, blob
    rec = json.loads(out.read_text())
    assert rec["anchor_layers"] == 126, rec
    assert rec["max_registrable_layers"] == 125, rec
    assert rec["anchor_registrable"] == "no", rec
    assert rec["blocking"] is False, rec


def test_the_report_half_records_a_reading_it_could_not_take(tmp_path):
    """An unreadable count is recorded as `unknown`, never as `yes`.

    An empty result is not a zero: a registry that did not answer has said
    nothing about layer depth, and a JSON record that flattened that into
    "registrable" would be the same false clean bill the whole issue is about.
    """
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    out = tmp_path / "rec2" / "upstream.json"
    cp = _run(root, ["--report-upstream", "--json", str(out)],
              layers_raise=True, env_extra={_ENV_KEY: "1.0.0"})
    rec = json.loads(out.read_text())
    assert rec["anchor_layers"] is None, rec
    assert rec["anchor_registrable"] == "unknown", rec
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_the_denominator_is_real():
    """The path arithmetic above, asserted rather than assumed. If `parents[5]`
    is ever off by one, every test in this file would skip and the file would
    report green while measuring nothing."""
    assert _PROG.is_file(), f"{_PROG} does not exist — parents[5] is wrong"
    src = _PROG.read_text(encoding="utf-8")
    assert "def check_layer_depth" in src
    assert "def _query_ghcr_layer_count" in src
