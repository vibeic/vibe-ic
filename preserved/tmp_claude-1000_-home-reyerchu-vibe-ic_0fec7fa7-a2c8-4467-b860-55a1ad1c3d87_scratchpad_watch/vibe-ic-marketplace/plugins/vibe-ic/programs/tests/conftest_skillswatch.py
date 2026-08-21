"""Attribute the shipped-`skills/` write to the module that makes it.

`test_tools_and_integration.py` captures a digest of `skills/` at MODULE IMPORT
— which pytest does during collection, before any test runs — and asserts it at
the end of its own tests. So any module running before it finishes can trip the
assertion, while the message says "a test in this module". Session-scoped
mechanism, module-scoped prose.

Bisecting by re-running halves is the obvious approach and the wrong one here:
this suite takes over 90 minutes on a host that HAS the EDA tools, so a binary
search is a day's work. Instead, hash `skills/` after every module in ONE pass
and print the first module whose digest differs from the previous one. That is
the writer, by name, in a single traversal.

Deliberately does not fail anything — it observes. The point is to identify the
writer so the WRITER can be fixed, per the brief; relaxing or reinterpreting the
digest assertion is explicitly not the remedy.
"""
import hashlib
from pathlib import Path

_PLUGIN = Path(__file__).resolve().parent.parent.parent  # programs/tests -> programs -> PLUGIN
_SKILLS = _PLUGIN / "skills"
_state = {"digest": None, "last_module": None}


def _digest():
    h = hashlib.md5()
    for p in sorted(_SKILLS.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(_SKILLS)).encode())
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


#: pytest CAPTURES stdout during tests, which silently swallowed every finding
#: of the previous run — only the `pytest_configure` line survived, because that
#: hook runs before capture starts. A detector that cannot report is the same
#: defect as one that cannot see, so findings go to a FILE, flushed per write.
_LOG = Path("/tmp/skillswatch_findings.txt")


def _say(msg):
    with _LOG.open("a") as fh:
        fh.write(msg + "\n")
        fh.flush()


def pytest_configure(config):
    _state["digest"] = _digest()
    _LOG.write_text("")
    _say(f"[skillswatch] baseline digest {_state['digest'][:12]}")


def pytest_runtest_logfinish(nodeid, location):
    mod = nodeid.split("::")[0]
    if _state["last_module"] is None:
        # First module of the session: nothing has run before it, so there is
        # no previous module to attribute a change to. Record it and move on —
        # reporting "None" as the writer, as the first draft did, names a
        # module that does not exist.
        _state["last_module"] = mod
        return
    if mod == _state["last_module"]:
        return
    # module boundary — check what the PREVIOUS module left behind
    now = _digest()
    if now != _state["digest"]:
        _say(f"[skillswatch] WRITER: {_state['last_module']}  "
             f"{_state['digest'][:12]} -> {now[:12]}")
        _state["digest"] = now
    _state["last_module"] = mod
