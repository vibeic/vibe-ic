"""Nothing under tools/ may resolve only on one person's machine.

MEASURED 2026-08-30, fresh clones of both public repos: 1017 tracked files
carry the literal `/home/reyerchu`. Almost all of it is recorded evidence --
tool argv, cwd, transcripts -- and rewriting a record to clean a grep
falsifies the record. Four were functional defects. These tests hold the two
that live in this repo, and they hold the ONE place the literal is load-bearing
and must NOT be rewritten.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / "tools" / "ci"

# A home directory belonging to a named account. `/home/user`, `/home/testuser`
# and friends are the sanitized placeholders fixtures are supposed to use, so
# the pattern deliberately does not care which name it is -- any account name
# baked into an executable path is the defect.
_HOME = re.compile(r"/home/(?!runner/)[A-Za-z0-9._-]*[A-Za-z0-9_]")


def _units():
    return sorted(list(CI.glob("*.service")) + list(CI.glob("*.timer")))


# ----------------------------------------------------- the two real defects --
def test_the_d9_scratch_default_is_not_a_home_directory():
    """`--scratch` defaulted to one machine's scratch tree.

    Every other host then wrote throwaway run copies into a path that did not
    exist. The copies are made with shutil.copytree, not `cp -l`, so a
    different filesystem costs nothing -- there are no hardlinks to break
    across devices.
    """
    src = (ROOT / "tools" / "d9_corpus_baseline.py").read_text(encoding="utf-8")
    block = re.search(r'"--scratch".*?\)\n', src, re.S)
    assert block, "the --scratch argument is gone; this test needs rewriting"
    hit = _HOME.search(block.group(0))
    assert hit is None, (
        f"--scratch defaults into a home directory ({hit.group(0)!r}); it must "
        f"default under $TMPDIR so every host can run the baseline"
    )


def test_no_shipped_ci_unit_names_an_account_or_a_home_directory():
    """A unit naming one developer can be installed on exactly one machine."""
    offenders = []
    for unit in _units():
        text = unit.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue                      # prose may discuss the defect
            hit = _HOME.search(line)
            if hit:
                offenders.append(f"{unit.name}:{n}: {hit.group(0)}")
            if re.match(r"\s*User\s*=\s*(?!root\b)\S", line):
                offenders.append(f"{unit.name}:{n}: baked User=")
    assert not offenders, (
        "machine-pinned lines in shipped systemd units:\n  "
        + "\n  ".join(offenders)
        + "\nWrite them at install time instead (install_gatekeeper_poller.sh)."
    )


def test_the_poller_unit_takes_its_checkout_from_the_environment_file():
    """And the file is NOT optional: a poller that gates nothing is the bug."""
    text = (CI / "gatekeeper-poller.service").read_text(encoding="utf-8")
    assert "EnvironmentFile=/etc/default/gatekeeper-poller" in text, \
        "the unit must read its machine-specific values from an env file"
    assert "EnvironmentFile=-" not in text, \
        "the env file must not be optional -- a silent start gates nothing"
    exec_lines = [l for l in text.splitlines() if l.startswith("ExecStart=")]
    assert len(exec_lines) == 1, exec_lines
    assert "${GATEKEEPER_REPO_ROOT}" in exec_lines[0], exec_lines[0]


def test_the_installer_renders_for_any_user_and_any_checkout(tmp_path):
    """Two-arm proof of portability: a foreign user and a foreign checkout."""
    installer = CI / "install_gatekeeper_poller.sh"
    assert installer.is_file(), "the installer that writes the machine-specific half is missing"
    fake = tmp_path / "srv" / "vibe-ic"
    (fake / "tools" / "ci").mkdir(parents=True)
    (fake / "tools" / "ci" / "gatekeeper_status_poller.py").write_text("", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(fake)], check=True)

    who = "nobody" if _has_user("nobody") else os.environ.get("USER", "")
    if not who or who == "root":
        pytest.skip("no non-root account available to render for")
    r = subprocess.run(
        ["bash", str(installer), "--print"],
        env={**os.environ, "GATEKEEPER_RUN_USER": who,
             "GATEKEEPER_REPO_ROOT": str(fake)},
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"GATEKEEPER_REPO_ROOT={fake}" in r.stdout, r.stdout
    assert f"User={who}" in r.stdout, r.stdout
    # Nothing it emits may point back at whoever authored the unit.
    for line in r.stdout.splitlines():
        if line.startswith("GATEKEEPER_REPO_ROOT="):
            assert _HOME.search(line) is None, line


def _has_user(name: str) -> bool:
    return subprocess.run(["getent", "passwd", name],
                          capture_output=True).returncode == 0


# ------------------------------------------------------------- the CONTROLS --
def test_the_timer_unit_is_machine_neutral():
    """CONTROL. Green before this change and after it; if it ever goes red the
    guard above has started matching something it should not."""
    text = (CI / "gatekeeper-poller.timer").read_text(encoding="utf-8")
    assert _HOME.search(text) is None
    assert not re.search(r"^\s*User\s*=", text, re.M)


def test_the_harvest_join_key_is_left_alone():
    """CONTROL, and a tripwire.

    `/home/reyerchu/_agentjob_i1015/wt` is NOT a path anything opens -- it is a
    JOIN KEY across six files in tools/harvest/, and the key of the row
    verify_consolidation.py's negative control flips to LANDED to prove
    validate() rejects a falsified verdict.

    MEASURED both ways: rewriting only the code, or only the data, makes the
    control raise `negative-control target is missing`; rewriting BOTH
    consistently makes it raise `source/verdict path multisets differ`, because
    the key also lives in _harv_shard_a.tsv. It cannot silently stop
    controlling -- but a blanket path rewrite still disarms it, so this test
    exists to stop one.
    """
    key = "/home/reyerchu/_agentjob_i1015/wt"
    harvest = ROOT / "tools" / "harvest"
    carriers = {
        "verify_consolidation.py": 2,
        "verdicts_shard_a.tsv": 2,
        "verdicts_joined.tsv": 2,
        "_harv_shard_a.tsv": 2,
        "CORRECTION_shard_a_false_landed.tsv": 1,
        "rescue/README.md": 1,
    }
    missing = []
    for name, expected in carriers.items():
        p = harvest / name
        if not p.is_file():
            missing.append(f"{name}: file is gone")
            continue
        n = p.read_text(encoding="utf-8", errors="ignore").count(key)
        if n != expected:
            missing.append(f"{name}: {n} occurrence(s), expected {expected}")
    assert not missing, (
        "the harvest join key was rewritten or dropped:\n  " + "\n  ".join(missing)
        + "\nThis key is data, not a path. Rewriting it disarms the "
          "verify_consolidation.py negative control."
    )


# ----------------------------------------- the LIVE SURFACE the guards missed --
#
# The two cases above hold the shipped systemd units and one argparse default.
# Neither reaches the OPERATOR DOCUMENTATION beside them, and neither reaches
# tools/tests/. MEASURED on ebccf100a0 (v1.13.77), with both cases above GREEN:
#
#   tools/ci/GATEKEEPER_ENFORCEMENT.md:114   ## Deploying on 8HD-4 (<a LAN address>)
#   tools/tests/test_gen_flow_gate_d9_premise.py:98
#                                            live = Path("/home/<operator>/vibeic.ai/...")
#
# The heading is LIVE SURFACE, not a record: it is the instruction a reader
# follows, and it names an address on someone's internal network. The pinned
# page is worse than unportable -- it is a test that could run on exactly one
# machine on earth and skipped, identically and silently, everywhere else. The
# path does not exist even on the machine it names.

#: An IPv4 dotted quad. Deliberately not narrowed to RFC1918: a routable
#: address in a deploy instruction is the same defect wearing a different hat,
#: and `docs/research/` keeps its host lines because a record is not an
#: instruction. MEASURED: with the heading repaired, tools/ci carries ZERO
#: matches, so this case has no false positives to tolerate.
_IPV4 = re.compile(r"(?<![\w.])((?:\d{1,3}\.){3}\d{1,3})(?![\w.])")


def _operator_surface():
    """Everything under tools/ci/ a reader is meant to READ or RUN."""
    out = []
    for pat in ("*.md", "*.sh", "*.service", "*.timer"):
        out.extend(CI.glob(pat))
    return sorted(out)


def test_no_operator_facing_file_names_a_host_address():
    """A deploy instruction may not name one network's address.

    `test_no_shipped_ci_unit_names_an_account_or_a_home_directory` above scans
    ONLY `*.service` / `*.timer`, so the deploy doc that tells you how to
    install them was held to nothing.
    """
    offenders = []
    for p in _operator_surface():
        for n, line in enumerate(p.read_text(encoding="utf-8",
                                             errors="ignore").splitlines(), 1):
            for m in _IPV4.finditer(line):
                if all(int(o) < 256 for o in m.group(1).split(".")):
                    offenders.append(f"{p.relative_to(ROOT)}:{n}: {m.group(1)}")
    assert not offenders, (
        "host address(es) in operator-facing files under tools/ci:\n  "
        + "\n  ".join(offenders)
        + "\nName the ROLE, not the address -- the reader's host is not yours."
    )


def test_the_d9_premise_page_is_resolved_from_the_environment():
    """The published page is a fact about the publishing host, not the repo.

    Pinned to one home directory this test skipped on every machine including
    the one it named, where the path does not exist either. Reading it from
    `VIBEIC_PUBLISHED_FLOW_GATE_PAGE` is what lets any publisher run it at all.
    """
    src = (ROOT / "tools" / "tests"
           / "test_gen_flow_gate_d9_premise.py").read_text(encoding="utf-8")
    assert "VIBEIC_PUBLISHED_FLOW_GATE_PAGE" in src, (
        "the published-page location must be named by env var, so a host other "
        "than the author's can supply it"
    )
    hit = _HOME.search(src)
    assert hit is None, (
        f"the d9 premise test pins a home directory ({hit.group(0)!r}); it can "
        f"then run on one machine and skip, silently, on every other"
    )
