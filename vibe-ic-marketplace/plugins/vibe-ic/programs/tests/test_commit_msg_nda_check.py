"""test_commit_msg_nda_check.py — §4.05 proofs for the commit-MESSAGE NDA guard.

The guard closes the last unguarded NDA leak surface: `source_chip_agnostic_
check.py` scans SOURCE only, so a commit whose MESSAGE names the commercial
foundry passed every gate — and one really did land on origin/main.

§4.05 requires BOTH directions to be proven, or the gate is decorative:

  POSITIVE — ordinary messages, INCLUDING ones that legitimately say
             "commercial PDK" / "commercial foundry" / "a foundry deck",
             must be ACCEPTED (rc 0). A guard that fails these is unusable and
             would be disabled within a day.
  NEGATIVE — a message carrying the SKU / brand / process codename must be
             REJECTED (rc != 0), in any case variant, embedded mid-sentence the
             way the real leak was, in BOTH --message-file and --rev-range mode.

Every leak string here is RECONSTRUCTED AT RUNTIME from `_commercial_pdk`'s
encoded store. No literal NDA token appears in this file — a test that spelled
one out would itself be the leak it is testing for, and would trip the source
guard.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_PLUGIN_ROOT = _HERE.parents[2]
_PROGRAMS = _PLUGIN_ROOT / "programs"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _commercial_pdk as cpdk  # noqa: E402
import commit_msg_nda_check as guard  # noqa: E402

_CHECKER = _PROGRAMS / "commit_msg_nda_check.py"


# ---------------------------------------------------------------------------
# Leak strings, reconstructed at runtime — never literals.
# ---------------------------------------------------------------------------
def _tok(role: str) -> str:
    return cpdk._dec(role)


def _run(args, cwd=None, input_text=None):
    proc = subprocess.run([sys.executable, str(_CHECKER), *args],
                          capture_output=True, text=True, cwd=cwd,
                          input=input_text)
    return proc.returncode, proc.stdout, proc.stderr


def _git(repo: Path, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True, env=env)


@pytest.fixture()
def tiny_repo(tmp_path):
    """A throwaway git repo with a deterministic identity, so --rev-range mode
    can be exercised on real commit objects rather than a mock."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"],
                   check=True)
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "f.txt").write_text("seed\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "seed: initial commit")
    return repo


def _commit(repo: Path, message: str, n: int) -> None:
    """Commit `message` bypassing any hook (we are testing the CHECKER here)."""
    (repo / f"f{n}.txt").write_text(f"{n}\n")
    _git(repo, "add", f"f{n}.txt")
    _git(repo, "commit", "-q", "--no-verify", "-m", message)


# ===========================================================================
# POSITIVE — clean messages are ACCEPTED.
# ===========================================================================
_CLEAN_MESSAGES = [
    "phase3 gds: substitute std-cell artwork for a FLAT MULTI-TOP library GDS",
    "dynamic-ir: wire the commercial PDK liberty into the runner's -transient call",
    "drc: run the commercial foundry deck natively via the in-KLayout interpreter",
    "lvs: bulk-normalize before compare; a foundry deck rule-id is not quoted here",
    "benchmark(spm): clean_run A/B re-verify against the commercial PDK\n\n"
    "The commercial foundry's rule deck is NDA, so results only.\n"
    "Co-Authored-By: Claude <noreply@anthropic.com>",
    "fix: key lookup in the foundry-agnostic cell mapper",  # 'key' + 'foundry' apart
    "docs: describe the process node and the product SKU generically",
]


@pytest.mark.parametrize("msg", _CLEAN_MESSAGES)
def test_positive_clean_message_file_accepted(tmp_path, msg):
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text(msg, encoding="utf-8")
    rc, out, err = _run(["--message-file", str(f)])
    assert rc == 0, f"clean message wrongly REJECTED: {msg!r}\n{err}"
    assert "PASS" in out


@pytest.mark.parametrize("msg", _CLEAN_MESSAGES)
def test_positive_clean_message_stdin_accepted(msg):
    rc, out, _err = _run(["--stdin"], input_text=msg)
    assert rc == 0
    assert "PASS" in out


def test_positive_clean_rev_range_accepted(tiny_repo):
    for i, msg in enumerate(_CLEAN_MESSAGES):
        _commit(tiny_repo, msg, i)
    rc, out, err = _run(["--repo", str(tiny_repo), "--rev-range", "main"])
    assert rc == 0, f"clean history wrongly REJECTED\n{err}"
    assert "PASS" in out


def test_positive_commented_lines_ignored(tmp_path):
    """git strips `#` lines before creating the commit, so a token quoted in the
    template/verbose diff section cannot leak and must not FAIL the author."""
    msg = ("fix: generic subject line\n\n"
           "# Please enter the commit message for your changes.\n"
           f"# On branch feature/{_tok('foundry_product')}-port\n")
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text(msg, encoding="utf-8")
    rc, _out, _err = _run(["--message-file", str(f)])
    assert rc == 0


# ===========================================================================
# NEGATIVE — leaked messages are REJECTED.
# ===========================================================================
def _leak_messages():
    """Every NDA role, in several shapes: mid-sentence (the real leak's shape),
    upper/mixed case, glued to punctuation, and in the body rather than the
    subject."""
    out = []
    for role in cpdk._ENCODED_NDA:
        t = _tok(role)
        out.append((role, f"phase3 gds: substitute artwork for the {t} "
                          f"macro-box artefact, on the opposite library shape."))
        out.append((role, f"fix: port the flow to {t.upper()}"))
        out.append((role, f"fix: generic subject\n\nDetails: built on ({t}).\n"))
        out.append((role, f"chore: bump deps [{t.title()}]"))
    return out


@pytest.mark.parametrize("role,msg", _leak_messages())
def test_negative_message_file_rejected(tmp_path, role, msg):
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text(msg, encoding="utf-8")
    rc, _out, err = _run(["--message-file", str(f)])
    assert rc == 1, f"LEAK NOT CAUGHT (role={role})"
    assert "FAIL" in err


@pytest.mark.parametrize("role,msg", _leak_messages())
def test_negative_stdin_rejected(role, msg):
    rc, _out, err = _run(["--stdin"], input_text=msg)
    assert rc == 1, f"LEAK NOT CAUGHT on stdin (role={role})"
    assert "FAIL" in err


def test_negative_rev_range_rejected(tiny_repo):
    """The real-leak shape, committed for every role, must FAIL --rev-range."""
    leaks = _leak_messages()
    for i, (_role, msg) in enumerate(leaks):
        _commit(tiny_repo, msg, i)
    rc, _out, err = _run(["--repo", str(tiny_repo), "--rev-range", "main"])
    assert rc == 1, "LEAK NOT CAUGHT in --rev-range mode"
    assert "FAIL" in err


def test_negative_rev_range_isolates_the_offending_commit(tiny_repo):
    """A clean range around a leaked commit must PASS, and the range containing
    it must FAIL — i.e. the gate is range-accurate, not blanket-red."""
    _commit(tiny_repo, "chore: clean commit one", 1)
    base = _git(tiny_repo, "rev-parse", "HEAD").stdout.strip()
    _commit(tiny_repo, f"feat: integrate the {_tok('sku_full')} cell views", 2)
    leaked = _git(tiny_repo, "rev-parse", "HEAD").stdout.strip()
    _commit(tiny_repo, "chore: clean commit two", 3)

    rc_bad, _o, _e = _run(["--repo", str(tiny_repo),
                           "--rev-range", f"{base}..{leaked}"])
    assert rc_bad == 1

    rc_good, _o, _e = _run(["--repo", str(tiny_repo),
                            "--rev-range", f"{leaked}..HEAD"])
    assert rc_good == 0


# ===========================================================================
# The guard's OWN output must not leak the token it caught.
# ===========================================================================
def test_output_masks_the_literal_token(tmp_path):
    tok = _tok("sku_full")
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text(f"feat: bring up the {tok} corner set\n", encoding="utf-8")
    report = tmp_path / "report.json"
    rc, out, err = _run(["--message-file", str(f), "--json", str(report)])
    assert rc == 1
    blob = out + err + report.read_text(encoding="utf-8")
    assert tok.lower() not in blob.lower(), \
        "the guard printed the literal NDA token — its own output is a leak"
    assert "<NDA-TOKEN:sku_full>" in blob, "masked role marker missing"
    assert "corner set" in blob, "context stripped — finding is not actionable"


def test_report_json_names_the_role_not_the_token(tmp_path):
    import json
    tok = _tok("foundry_brand1")
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text(f"docs: credit {tok} for the deck\n", encoding="utf-8")
    report = tmp_path / "r.json"
    _run(["--message-file", str(f), "--json", str(report)])
    d = json.loads(report.read_text(encoding="utf-8"))
    assert d["verdict"] == "FAIL"
    assert d["findings_count"] == 1
    assert d["findings"][0]["role"] == "foundry_brand1"
    assert tok.lower() not in json.dumps(d).lower()


# ===========================================================================
# Wiring / robustness.
# ===========================================================================
def test_token_table_covers_every_encoded_role():
    """The guard must derive its tokens from the encoded store, so a token added
    to `_commercial_pdk` is covered with no edit here (no drift)."""
    assert set(guard.token_roles()) == set(cpdk._ENCODED_NDA)
    for role, tok in guard.token_roles().items():
        assert tok, f"empty token for role {role}"


def test_message_regex_is_a_superset_of_the_source_regex_family():
    """A token the SOURCE guard forbids must also be forbidden in a message —
    otherwise the two surfaces disagree and the weaker one is the leak path."""
    rx = guard.message_regex()
    for tok in cpdk.nda_regex_family():
        assert rx.search(f"prefix {tok} suffix"), \
            "message guard is weaker than the source guard"


def test_bad_rev_range_errors_loudly_not_silently_clean(tiny_repo):
    """An unwalkable range must exit 2 (ERROR), never 0 — a silently empty scan
    is exactly how a guard becomes decorative."""
    rc, _out, err = _run(["--repo", str(tiny_repo),
                          "--rev-range", "no-such-ref-xyz..HEAD"])
    assert rc == 2
    assert "error" in err.lower()


def test_missing_message_file_errors(tmp_path):
    rc, _out, err = _run(["--message-file", str(tmp_path / "nope")])
    assert rc == 2
    assert "no such message file" in err.lower()


def test_hooks_and_installer_are_present_and_executable():
    """The checker is inert unless the hooks exist and the installer can install
    them — assert the wiring ships, not just the program."""
    repo_root = _PLUGIN_ROOT.parents[2]
    hooks = repo_root / "tools" / "git-hooks"
    for name in ("commit-msg", "pre-push"):
        h = hooks / name
        assert h.is_file(), f"missing tracked hook: {h}"
        assert "commit_msg_nda_check.py" in h.read_text(encoding="utf-8"), \
            f"hook {name} does not invoke the checker"
    installer = repo_root / "tools" / "install-git-hooks.sh"
    assert installer.is_file(), "missing tools/install-git-hooks.sh"


def test_this_guard_contains_no_literal_nda_token():
    """§4.05 self-check: the checker, the tests and the hooks must themselves be
    SKU-literal-free, or the guard is the leak."""
    repo_root = _PLUGIN_ROOT.parents[2]
    targets = [
        _CHECKER,
        _HERE,
        repo_root / "tools" / "git-hooks" / "commit-msg",
        repo_root / "tools" / "git-hooks" / "pre-push",
        repo_root / "tools" / "git-hooks" / "README.md",
        repo_root / "tools" / "install-git-hooks.sh",
    ]
    rx = guard.message_regex()
    for t in targets:
        if not t.is_file():
            continue
        text = t.read_text(encoding="utf-8", errors="replace")
        m = rx.search(text)
        assert m is None, (f"{t.name} contains a literal NDA token "
                           f"(role={guard._role_of(m.group(1))}) at offset "
                           f"{m.start()}")
