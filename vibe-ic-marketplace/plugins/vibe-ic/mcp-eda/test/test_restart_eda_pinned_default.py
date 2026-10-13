#!/usr/bin/env python3
"""Regression: `restart-eda.sh` must default to an IMMUTABLE image reference,
never a floating `latest` — a stale local `latest` would silently recreate the
MCP-EDA container on an outdated toolchain (the same drift class fixed for
`fault_atpg_run.py` in v1.3.80). Measured on 8HD-9 2026-08-21, that risk is not
hypothetical: the local `latest` tag carried RepoDigest `sha256:549357686ed1…`
while the registry's `latest` was `sha256:f34af8763eb0…` — the same name, two
different images, in the same minute.

WHAT CHANGED. The default used to be `$(cat tools/vibeic-eda/VERSION)` —
vibeic-eda's version number stored in the vibe-ic repo, which meant a PR here for
every image release. That file is gone. The default is now a DIGEST, and the
script SHELLS OUT to `programs/_eda_image.py --judged` for it rather than growing
a second copy of "which image" in bash: two implementations of one rule is the
drift these tests exist to catch, one level up.

`RESTART_EDA_PRINT_IMAGE=1` prints the resolved ref and exits before any docker
interaction, so the argument-handling tests need no docker daemon. The default
path DOES need one — it asks this host what it has — and it says so rather than
passing when it could not look.
"""
import os
import re
import shutil
from pathlib import Path

import pytest

import sys
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


def _find(rel):
    for up in Path(__file__).resolve().parents:
        c = up / rel
        if c.is_file():
            return c
    return None


SCRIPT = _find(Path("tools") / "vibeic-eda" / "restart-eda.sh")
RESOLVER = _find(Path("vibe-ic-marketplace") / "plugins" / "vibe-ic" /
                 "programs" / "_eda_image.py")
_skip = pytest.mark.skipif(SCRIPT is None,
                           reason="tools/vibeic-eda/restart-eda.sh not present")

#: The script needs `python3` on PATH to reach the resolver, so the environment
#: is not the bare `/usr/bin:/bin` this file used to hand it.
_ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "RESTART_EDA_PRINT_IMAGE": "1"}
_DIGEST_REF = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = next((
    up for up in Path(__file__).resolve().parents
    if (up / ".claude-plugin" / "marketplace.json").is_file()
    and (up / "vibe-ic-marketplace" / "plugins" / "vibe-ic").is_dir()
), None)
PACKAGED_SCRIPT = PLUGIN_ROOT / "tools" / "vibeic-eda" / "restart-eda.sh"
CANONICAL_SCRIPT = (
    REPO_ROOT / "tools" / "vibeic-eda" / "restart-eda.sh"
    if REPO_ROOT is not None else None
)
INSTALL_GUIDE = PLUGIN_ROOT / "mcp-eda" / "INSTALL_GUIDE.md"
MCP_README = PLUGIN_ROOT / "mcp-eda" / "README.md"


def _resolve(*args, expect_ok=True):
    r = _pr.run(["bash", str(SCRIPT), *args],
                       capture_output=True, text=True, env=_ENV)
    if expect_ok:
        assert r.returncode == 0, r.stderr
    return r


@_skip
def test_the_script_reads_no_version_out_of_this_repo():
    """The rule, asserted on the SOURCE. A default that re-learns a version from
    a file here brings back the PR-per-release coupling, and it would look like a
    one-line convenience in review."""
    src = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "VERSION" not in code, (
        "restart-eda.sh reads a version out of the source tree again")
    assert "_eda_image.py" in code and "--judged" in code, (
        "restart-eda.sh should ask the one resolver rather than deciding itself")


@_skip
@pytest.mark.skipif(
    RESOLVER is None or shutil.which("docker") is None,
    reason="NOT_VERIFIED: the default asks this host which image it holds and "
           "needs docker — remedy: install docker, or "
           "docker pull ghcr.io/vibeic/vibeic-eda:latest")
def test_the_default_is_a_digest_or_an_honest_refusal():
    """Two acceptable answers and one forbidden one.

    A host holding a vibeic-eda image gets that image BY DIGEST. A host holding
    none gets a non-zero exit naming the problem. What it must never do is fall
    back to a floating tag, which is the whole point of the file."""
    r = _resolve(expect_ok=False)
    got = r.stdout.strip()
    if r.returncode == 0:
        assert _DIGEST_REF.match(got), got
    else:
        assert "pass a tag explicitly" in (r.stderr or ""), r.stderr
        assert not got, got
    assert ":latest" not in got


@_skip
def test_bare_tag_prepends_repo():
    assert _resolve("0.1.99").stdout.strip() == "ghcr.io/vibeic/vibeic-eda:0.1.99"


@_skip
def test_full_ref_honored_as_is():
    ref = "example.com/some/image:1.2.3"
    assert _resolve(ref).stdout.strip() == ref


@_skip
def test_explicit_latest_still_honored_as_opt_in():
    assert _resolve("latest").stdout.strip() == "ghcr.io/vibeic/vibeic-eda:latest"


@_skip
def test_no_floating_default_in_source():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "${1:-latest}" not in src, (
        "restart-eda.sh must not default to a floating :latest tag")


def test_issue1933_restart_helper_is_in_the_marketplace_package():
    """The remediation path is relative to the installed plugin root, so the
    file must live inside that root rather than only in the source repository."""
    assert PACKAGED_SCRIPT.is_file(), (
        "marketplace package is missing tools/vibeic-eda/restart-eda.sh")
    assert os.access(PACKAGED_SCRIPT, os.X_OK), (
        "packaged tools/vibeic-eda/restart-eda.sh is not executable")
    if CANONICAL_SCRIPT is not None:
        assert PACKAGED_SCRIPT.read_bytes() == CANONICAL_SCRIPT.read_bytes(), (
            "source and packaged restart helpers drifted; both remediation "
            "paths must execute the same policy")


def test_issue1933_packaged_layout_finds_the_shipped_image_resolver(tmp_path):
    """Exercise the installed layout without Docker. The old lookup understood
    only <repo>/vibe-ic-marketplace/plugins/vibe-ic/programs and a copied script
    still failed after packaging because <plugin>/programs was never searched."""
    installed_root = tmp_path / "installed-plugin"
    installed_script = installed_root / "tools" / "vibeic-eda" / "restart-eda.sh"
    installed_script.parent.mkdir(parents=True)
    shutil.copy2(PACKAGED_SCRIPT, installed_script)
    installed_programs = installed_root / "programs"
    installed_programs.mkdir()
    (installed_programs / "_eda_image.py").write_text("# fixture\n", encoding="utf-8")
    (installed_programs / "_docker_memory.py").write_text("# fixture\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "python-argv.txt"
    digest = "ghcr.io/vibeic/vibeic-eda@sha256:" + "a" * 64
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" > \"$RESTART_EDA_CALL_LOG\"\n"
        f"printf '%s\\n' '{digest}'\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "RESTART_EDA_CALL_LOG": str(log),
        "RESTART_EDA_PRINT_IMAGE": "1",
    }

    result = _pr.run(
        ["bash", str(installed_script)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == digest
    assert log.read_text(encoding="utf-8").splitlines() == [
        str(installed_programs / "_eda_image.py"),
        "--judged",
    ]
    assert "find_plugin_program _docker_memory.py" in PACKAGED_SCRIPT.read_text(
        encoding="utf-8")


def test_issue1933_install_docs_use_marketplace_autowire_only():
    guide = INSTALL_GUIDE.read_text(encoding="utf-8")
    readme = MCP_README.read_text(encoding="utf-8")

    for required in (
        "claude plugin marketplace add",
        "claude plugin install vibe-ic",
        '${CLAUDE_PLUGIN_ROOT}/mcp-eda/src/bootstrap.mjs',
        "eda_doctor(skip_versions=false)",
        "--memory",
        "--memory-swap",
        "tools/vibeic-eda/restart-eda.sh",
    ):
        assert required in guide, f"INSTALL_GUIDE.md omits {required!r}"

    for stale in (
        "claude mcp add",
        "git clone <your-repo-url>/mcp-eda.git",
        "plugins/vibe-ic-d",
        "-p 8888:80",
        "-p 5901:5901",
    ):
        assert stale not in guide, f"INSTALL_GUIDE.md retains stale route {stale!r}"

    assert "claude plugin install vibe-ic" in readme
    assert "bootstrap.mjs" in readme
    assert "eda_doctor(skip_versions=false)" in readme
    assert "claude mcp add" not in readme
    assert "github.com/anthropics/mcp-eda" not in readme


# ---------------------------------------------------------------------------
# vibe-ic#2349 — PULL=1 is the install route, and it fetches the PINNED bytes.
#
# The published manual told a user to `docker pull ghcr.io/vibeic/vibeic-eda:latest`
# and `docker run --name vibeic-eda … :latest`. Measured 2026-09-17: `latest` was
# sha256:7e528297… while `_eda_pin.IMAGE_DIGEST` is sha256:89a8fd72…, so every
# container the manual produced was CONTAINER_IMAGE_MISMATCH by construction. The
# manual now runs this script with PULL=1 and names no image at all; these tests
# hold the script to the half of that route that lives here.
# ---------------------------------------------------------------------------

#: A mocked `docker`: records argv; `image inspect` succeeds only once the image is
#: "present" (MOCK_PRESENT=1, or after a successful `pull`); `container inspect`
#: says no container exists, so a run that got PAST the image stage stops at the
#: fresh-container DESIGNS_DIR refusal without creating anything.
_PULL_FAKE_DOCKER = r'''#!/bin/sh
printf '%s\n' "$*" >> "$MOCK_LOG"
case "$1 $2" in
  "image inspect")
    if [ "$MOCK_PRESENT" = "1" ] || [ -f "$MOCK_PULLED" ]; then
      echo "sha256:0000000000000000000000000000000000000000000000000000000000000000"; exit 0
    fi
    exit 1 ;;
  "container inspect") exit 1 ;;
esac
case "$1" in
  pull) [ "$MOCK_PULL_FAILS" = "1" ] && exit 1; : > "$MOCK_PULLED"; exit 0 ;;
  images) exit 0 ;;
esac
exit 0
'''

_PINNED = "ghcr.io/vibeic/vibeic-eda@sha256:" + "b" * 64


def _pull_harness(tmp_path, **extra):
    """An installed-layout copy of the real script, a fake resolver that logs its
    argv and prints a pinned reference, and a fake docker."""
    root = tmp_path / "installed-plugin"
    script = root / "tools" / "vibeic-eda" / "restart-eda.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(PACKAGED_SCRIPT, script)
    (root / "programs").mkdir()
    (root / "programs" / "_eda_image.py").write_text("# fixture\n", encoding="utf-8")
    (root / "programs" / "_docker_memory.py").write_text("# fixture\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$RESOLVER_LOG\"\n"
        f"printf '%s\\n' '{_PINNED}'\n", encoding="utf-8")
    (bin_dir / "docker").write_text(_PULL_FAKE_DOCKER, encoding="utf-8")
    for exe in ("python3", "docker"):
        (bin_dir / exe).chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "RESOLVER_LOG": str(tmp_path / "resolver.log"),
        "MOCK_LOG": str(tmp_path / "docker.log"),
        "MOCK_PULLED": str(tmp_path / "pulled.flag"),
    }
    env.update(extra)
    r = _pr.run(["bash", str(script)], capture_output=True, text=True, env=env)

    def _lines(name):
        p = tmp_path / name
        return p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    return r, _lines("resolver.log"), _lines("docker.log")


def test_issue2349_pull_asks_the_resolver_about_the_pinned_digest_only(tmp_path):
    """PULL=1 explicitly refreshes through the SAME resolver; it does not name
    an image of its own, and without PULL=1 the call is unchanged."""
    _r, resolver, _d = _pull_harness(tmp_path, PULL="1", RESTART_EDA_PRINT_IMAGE="1")
    assert _r.returncode == 0, _r.stderr
    assert _r.stdout.strip() == _PINNED
    assert [l.split()[1:] for l in resolver] == [["--judged", "--allow-pull", "--refresh"]]

    plain = tmp_path / "plain"
    plain.mkdir()
    _r2, resolver2, _d2 = _pull_harness(plain, RESTART_EDA_PRINT_IMAGE="1")
    assert [l.split()[1:] for l in resolver2] == [["--judged"]]


def test_issue2349_pull_fetches_exactly_the_resolved_reference(tmp_path):
    r, _res, docker = _pull_harness(tmp_path, PULL="1")
    assert f"pull {_PINNED}" in docker, docker
    assert not any("latest" in l for l in docker), docker
    # got PAST the image stage: the next refusal is the fresh-container one
    assert "DESIGNS_DIR" in r.stderr, r.stderr
    assert not any(l.startswith("run ") for l in docker), docker


def test_issue2349_without_pull_the_script_still_never_fetches(tmp_path):
    r, _res, docker = _pull_harness(tmp_path)
    assert r.returncode != 0
    assert not any(l.startswith("pull") for l in docker), docker
    assert "not found locally" in r.stderr and "PULL=1" in r.stderr, r.stderr


def test_issue2349_pull_skips_the_fetch_when_the_pinned_image_is_present(tmp_path):
    _r, _res, docker = _pull_harness(tmp_path, PULL="1", MOCK_PRESENT="1")
    assert not any(l.startswith("pull") for l in docker), docker


def test_issue2349_a_failed_pull_touches_no_container(tmp_path):
    r, _res, docker = _pull_harness(tmp_path, PULL="1", MOCK_PULL_FAILS="1")
    assert r.returncode != 0
    assert "docker pull" in r.stderr and "nothing was stopped or removed" in r.stderr
    assert not any(l.split()[:1] in (["container"], ["rm"], ["run"], ["stop"],
                                     ["rename"]) for l in docker), docker


def test_issue2349_install_docs_name_no_image_and_take_the_pull_route():
    """The shipped install docs take the same route as the published manual: the
    helper with PULL=1 and no image argument. A tag typed into a doc is a second
    statement of the image identity, and `:latest` is the one that produced
    CONTAINER_IMAGE_MISMATCH for every container built by following it.

    INSTALL_GUIDE.md only: mcp-eda/README.md carries the same route, but the
    landing delta excludes every `*README.md` (they are regenerated at landing),
    so a pin on it here would be measured against a README the landing does
    not take."""
    for doc in (INSTALL_GUIDE,):
        text = doc.read_text(encoding="utf-8")
        assert "PULL=1" in text and "tools/vibeic-eda/restart-eda.sh" in text, doc
        assert not re.search(r"vibeic/vibeic-eda[:@]", text), (
            f"{doc.name} names an image reference; the plugin's pin is the only one")
        assert not re.search(r"docker (pull|run)\b", text), (
            f"{doc.name} builds the container by hand instead of through the helper")
