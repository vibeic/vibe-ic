#!/usr/bin/env python3
"""eda_doctor must name the IMAGE the container actually runs.

A container's image is fixed when it is CREATED. `docker pull` moves a TAG and
leaves an existing container on the old bytes, so an operator who pulls and then
runs executes every tool, PDK and sign-off number from the OLDER image.

`container_image_provenance.py` names this exact failure — "Stale-container
substitution (silent)" — and RECORDS the identity on every run, but it only
ENFORCES under `--require-image`, which nothing in the flow passes. A fact that
nobody compares does not make the substitution visible.

And `eda_doctor`, which `skills/loop2converge/SKILL.md` §1.0 tells operators to
read the toolchain back from — in the same table that catches the MCP-binding
version of this mistake — answered "container reachable" and named no image.

MEASURED 2026-08-30 on 8hd-3 after following §1.0 literally:

    container `vibeic-eda`  sha256:ddbf1e71… 2026-08-28  openroad 26Q3-1867-gfbdee51542
    :latest, same host      sha256:de6b0e0f… 2026-08-29  openroad 26Q3-1884-g80f878d28a

`eda_doctor` reported "12/12 checks passed". The gap was load-bearing: on 1867
`repair_timing -setup` died of SIGSEGV in `postroute_drv_repair` and the run
halted; on 1884 the same design cleared that stage in four repair+reroute
iterations. A tool bug was filed against a build already superseded on the very
machine that filed it.

The helper is EXECUTED here, not grepped for: these tests stub the docker calls
and run `_containerImageIdentity` under node, so they assert what it DOES. The
registration test is the only static one, because the wiring is a shape.
"""
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
INDEX_JS = HERE.parent / "src" / "index.js"

sys.path.insert(0, str(HERE.parents[1] / "programs"))
import _watchdog                                              # noqa: E402

_STALL_GRACE_S = 60

RUNNING_ID = "sha256:" + "a" * 64
NEWER_ID = "b" * 12
RUNNING_REF = "ghcr.io/vibeic/vibeic-eda@sha256:" + "a" * 64


def _helper_source() -> str:
    """The shipped helper itself. A copy in this file would pass while the
    server did something else, which is the failure this test exists to catch."""
    src = INDEX_JS.read_text(encoding="utf-8")
    start = src.index("const _EDA_IMAGE_REPO =")
    end = src.index("// ─── Tool: eda_doctor", start)
    body = src[start:end]
    assert "_containerImageIdentity" in body, body[:200]
    return body


def _run(responses: dict) -> dict:
    """`responses` maps a marker present in the argv to {status, stdout}.

    Dispatching on argv rather than call order is deliberate: an order-indexed
    stub silently keeps passing if the helper is refactored to ask in a
    different sequence, which is the kind of test that measures nothing.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available; the helper under test is JavaScript")
    script = textwrap.dedent(f"""
        const CONTAINER = "vibeic-eda";
        const RESPONSES = {json.dumps(responses)};
        const _spawnSync = (cmd, args) => {{
          const key = Object.keys(RESPONSES).find(k => args.join(" ").includes(k));
          return key ? RESPONSES[key] : {{ status: 1, stdout: "" }};
        }};
        {_helper_source()}
        console.log(JSON.stringify(_containerImageIdentity()));
    """)
    argv = [node, "-e", script]
    res = _watchdog.run_host_supervised(argv, stall_grace_s=_STALL_GRACE_S)
    assert res.outcome not in ("stalled", "ceiling"), (
        f"the node child made NO forward progress for {_STALL_GRACE_S}s\n"
        f"{res.out}{res.err}")
    run = _watchdog.completed_process(argv, res)
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def _responses(*, running_created, newest_created, label="0.3.36",
               newest_tag="ghcr.io/vibeic/vibeic-eda:latest"):
    rows = []
    if newest_created is not None:
        rows.append(f"{NEWER_ID}\t{newest_created}\t{newest_tag}")
    return {
        "inspect vibeic-eda --format": {
            "status": 0, "stdout": f"{RUNNING_ID}\t{RUNNING_REF}\n"},
        "image inspect": {
            "status": 0, "stdout": f"{running_created}\t{label}\n"},
        "image ls": {"status": 0, "stdout": "\n".join(rows) + "\n"},
    }


# ── the case this exists for ───────────────────────────────────────────────

def test_a_container_older_than_a_local_image_is_reported_stale():
    out = _run(_responses(running_created="2026-08-28T09:22:50.0Z",
                          newest_created="2026-08-29 19:42:34 +0800 CST"))
    assert out["ok"] is False
    assert "STALE CONTAINER" in out["detail"]


def test_the_message_carries_both_identities_and_the_fix():
    """An operator who cannot see WHICH two images differ cannot act, and one
    who is not told a recreate drops the mounts and the ceiling loses both."""
    d = _run(_responses(running_created="2026-08-28T09:22:50.0Z",
                        newest_created="2026-08-29 19:42:34 +0800 CST"))["detail"]
    assert "a" * 12 in d and NEWER_ID in d
    assert "docker rm -f" in d and "--memory-swap" in d and "mounts" in d
    assert "fixed when it is CREATED" in d, (
        "the message must say WHY a pull did not move the container")


def test_the_version_label_is_read_back():
    """§1.0 asks for the digest AND the label; the label is what a human says."""
    d = _run(_responses(running_created="2026-08-28T09:22:50.0Z",
                        newest_created="2026-08-29 19:42:34 +0800 CST",
                        label="0.3.36"))["detail"]
    assert "0.3.36" in d


# ── the controls: green in both directions ─────────────────────────────────

def test_control_a_container_on_the_newest_local_image_passes():
    """THE CONTROL. Without it the check is satisfied by code that calls every
    container stale."""
    out = _run(_responses(running_created="2026-08-29T11:42:34.0Z",
                          newest_created="2026-08-28 17:22:50 +0800 CST"))
    assert out["ok"] is True
    assert "STALE" not in out["detail"]
    assert "newest local image" in out["detail"]


def test_control_the_running_image_is_not_compared_against_itself():
    """The running image is usually still tagged. Counting it as 'newer than
    itself' would report every container stale — the same everything-matches
    defect `_commercial_pdk` refuses an empty alternation for."""
    r = _responses(running_created="2026-08-29T11:42:34.0Z", newest_created=None)
    r["image ls"] = {"status": 0,
                     "stdout": f"{'a' * 12}\t2026-08-29 19:42:34 +0800 CST\t"
                               f"ghcr.io/vibeic/vibeic-eda:latest\n"}
    out = _run(r)
    assert out["ok"] is True, out["detail"]


def test_control_no_other_local_image_still_passes():
    out = _run(_responses(running_created="2026-08-29T11:42:34.0Z",
                          newest_created=None))
    assert out["ok"] is True


# ── cannot-look is never a clean bill ──────────────────────────────────────

def test_an_unreadable_container_is_not_reported_as_current():
    out = _run({})
    assert out["ok"] is False
    assert "UNIDENTIFIED" in out["detail"]


def test_an_undateable_image_says_it_was_not_compared():
    """NOT-KNOWN IS NOT CURRENT. An unparseable creation time must not silently
    sort as newest and print a clean bill."""
    out = _run(_responses(running_created="not-a-date",
                          newest_created="2026-08-29 19:42:34 +0800 CST"))
    assert "NOT compared" in out["detail"]


def test_an_unlistable_image_set_says_so_rather_than_claiming_current():
    r = _responses(running_created="2026-08-29T11:42:34.0Z", newest_created=None)
    r["image ls"] = {"status": 1, "stdout": ""}
    assert "could not list" in _run(r)["detail"]


# ── registration shape ─────────────────────────────────────────────────────

def test_the_check_is_soft_and_wired_after_the_docker_probe():
    """SOFT deliberately, like the memory ceiling beside it: an older image runs
    every flow correctly and may be pinned on purpose. `if (!ok && !soft) allOk
    = false;` is what makes `soft` mean that."""
    src = INDEX_JS.read_text(encoding="utf-8")
    i = src.index('check: "eda_image_identity"')
    block = src[i - 400:i + 400]
    assert "_containerImageIdentity()" in block
    assert "soft: img.ok ? undefined : true" in block
    assert src.index('check: "docker_reachable"') < i, (
        "the identity check must run after docker is known reachable")


def _doctor_source():
    """Run the shipped doctor registration and execution helpers unchanged.

    The stdio server is not started. Only its schema/registration transport and
    machine providers are fixtures; neither the doctor nor Python pairing
    verdict is replaced by a test implementation.
    """
    src = INDEX_JS.read_text(encoding="utf-8")

    def function(name):
        start = src.index(f"function {name}(")
        return src[start:src.index("\n}", start) + 2]

    def between(first, last):
        start = src.index(first)
        return src[start:src.index(last, start)]

    return "\n".join([
        between("const CONTAINER =", "// ─── Parallel-by-default"),
        function("_run"),
        between("let _dockerProbeAt =", "// v0.1.11: container-visibility"),
        function("dockerExec"),
        between("const SERVER_VERSION =", "// Helper: run an arbitrary command"),
        between("const _versionCache =", "// ─── Tool identity for the provenance log"),
        between("const _BYTES_PER_GIB =", "// ─── Tool: eda_run_tcl"),
    ])


def _doctor_call(case):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available; the doctor under test is JavaScript")
    programs = HERE.parents[1] / "programs"
    # Only image presence/digest providers are authored. In particular,
    # default_container_name, container_pin_state and preflight run unchanged.
    python_setup = (
        "import json,os,sys;import _runtime_pair_preflight as R;"
        "fixture=json.loads(os.environ['PAIR_FIXTURE']);"
        "R._pin.pinned_image_present=lambda env: "
        "(os.environ['VIBEIC_EDA_IMAGE'],'') if fixture.get('image_present',True) "
        "else (None,R._pin.IMAGE_NOT_PRESENT+': neutral image absent');"
        "R._pin.container_image_digest=lambda name: "
        "(sys.stderr.write('PAIR_SUBJECT='+name+'\\n') and "
        "tuple(fixture['containers'].get(name,[None,R._pin.CONTAINER_ABSENT+': '+name])));"
    )
    script = textwrap.dedent(f"""
        const cp = require('child_process');
        const fixture = {json.dumps(case)};
        delete process.env.EDA_CONTAINER;
        delete process.env.VIBEIC_EDA_CONTAINER;
        delete process.env.IIC_EDA_IMAGE;
        Object.assign(process.env, fixture.env);
        process.env.VIBEIC_EDA_IMAGE = 'neutral.invalid/eda@' + fixture.required;
        process.env.PAIR_FIXTURE = JSON.stringify(fixture);
        const VIBE_IC_PROGRAMS_DIR = {json.dumps(str(programs))};
        const calls = [], pairSubjects = [];
        const _spawnSync = (cmd, args, opts = {{}}) => {{
          calls.push({{cmd, args}});
          if (cmd === 'python3') {{
            if (fixture.python === 'exit') return {{status: 1, stderr: 'neutral provider unavailable'}};
            if (fixture.python === 'malformed') return {{status: 0, stdout: 'not JSON'}};
            const child = cp.spawnSync(cmd,
              [args[0], {json.dumps(python_setup)} + args[1]],
              {{...opts, env: {{...process.env, ...(opts.env || {{}})}}}});
            pairSubjects.push(...String(child.stderr || '').split('\\n')
              .filter(s => s.startsWith('PAIR_SUBJECT=')).map(s => s.slice(13)));
            return child;
          }}
          if (cmd !== 'docker') throw Error('unexpected machine provider: ' + cmd);
          if (args[0] === 'ps') {{
            const name = args.find(a => a.startsWith('name=')).slice(5);
            return {{status: 0, stdout: fixture.absent === name ? '' : name + '\\n'}};
          }}
          if (args[0] === 'exec') {{
            if (args.join(' ').includes('command -v timeout'))
              return {{status: 0, stdout: '/usr/bin/timeout\\n'}};
            return {{status: 0, stdout: fixture.tool_missing
              ? 'command not found' : 'neutral 1.2 container=' + args[1] + '\\n'}};
          }}
          if (args[0] === 'inspect') {{
            const name = args[1], format = args[args.length - 1];
            const digest = (fixture.containers[name] || [null])[0];
            if (fixture.absent === name) return {{status: 1, stdout: ''}};
            if (format.includes('HostConfig')) return {{status: 0, stdout: '2147483648 2147483648'}};
            const id = 'sha256:' + 'c'.repeat(64);
            return {{status: 0, stdout: format.includes('Config.Image')
              ? id + '\\tneutral.invalid/eda@' + (digest || 'unknown') : id}};
          }}
          if (args[0] === 'image' && args[1] === 'inspect')
            return {{status: 0, stdout: '2026-01-01T00:00:00Z\\tneutral-version'}};
          if (args[0] === 'image' && args[1] === 'ls') return {{status: 0, stdout: ''}};
          throw Error('unexpected docker argv: ' + JSON.stringify(args));
        }};
        const existsSync = () => true;
        const optPath = () => {{}};
        const execSync = () => 'neutral host tool 1.2';
        const schema = new Proxy(() => schema, {{get: () => schema}});
        const z = schema;
        const handlers = {{}};
        const server = {{tool: (name, description, fields, handler) => {{handlers[name] = handler;}}}};
        {_doctor_source()}
        const request = {{method: 'tools/call', params: {{name: 'eda_doctor', arguments: {{skip_versions: false}}}}}};
        handlers[request.params.name](request.params.arguments).then(envelope => {{
          console.log(JSON.stringify({{result: JSON.parse(envelope.content[0].text), calls, pairSubjects}}));
        }}).catch(error => {{console.error(error); process.exitCode = 1;}});
    """)
    argv = [node, "-e", script]
    res = _watchdog.run_host_supervised(argv, stall_grace_s=_STALL_GRACE_S)
    assert res.outcome not in ("stalled", "ceiling"), res.out + res.err
    run = _watchdog.completed_process(argv, res)
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


_PAIR_A = "sha256:" + "a" * 64
_PAIR_B = "sha256:" + "b" * 64
_ISOLATED = "eda-isolated-fixture"


@pytest.mark.parametrize("selectors,selected,default_digest,selected_digest,ok", [
    ({}, "vibeic-eda", _PAIR_A, _PAIR_B, True),
    ({"EDA_CONTAINER": _ISOLATED}, _ISOLATED, _PAIR_A, _PAIR_B, False),
    ({"VIBEIC_EDA_CONTAINER": _ISOLATED}, _ISOLATED, _PAIR_A, _PAIR_B, False),
    ({"EDA_CONTAINER": _ISOLATED, "VIBEIC_EDA_CONTAINER": _ISOLATED}, _ISOLATED, _PAIR_A, _PAIR_B, False),
    ({"EDA_CONTAINER": _ISOLATED, "VIBEIC_EDA_CONTAINER": "vibeic-eda"}, _ISOLATED, _PAIR_A, _PAIR_B, False),
    ({"EDA_CONTAINER": _ISOLATED, "VIBEIC_EDA_CONTAINER": "vibeic-eda"}, _ISOLATED, _PAIR_B, _PAIR_A, True),
    ({"EDA_CONTAINER": _ISOLATED}, _ISOLATED, _PAIR_B, _PAIR_A, True),
    ({"VIBEIC_EDA_CONTAINER": _ISOLATED}, _ISOLATED, _PAIR_B, _PAIR_A, True),
    ({"EDA_CONTAINER": _ISOLATED, "VIBEIC_EDA_CONTAINER": _ISOLATED}, _ISOLATED, _PAIR_B, _PAIR_A, True),
], ids=["default", "eda-only-mismatch", "python-only-mismatch", "equal-mismatch",
        "conflict-mismatch", "conflict-match", "selected-match-default-mismatch",
        "python-only-match", "equal-match"])
def test_issue3023_doctor_judges_its_execution_target(
        selectors, selected, default_digest, selected_digest, ok):
    out = _doctor_call({"env": selectors, "required": _PAIR_A, "containers": {
        "vibeic-eda": [default_digest, ""], _ISOLATED: [selected_digest, ""]}})
    result = out["result"]
    pair = next(row for row in result["checks"] if row["check"] == "runtime_pair_match")
    assert result["success"] is ok, result
    assert pair["ok"] is ok, pair
    assert out["pairSubjects"] == [selected], out
    assert f"container={selected} " in pair["detail"], pair
    # Check actual native probe argv, including binary execution, against the
    # same declared target. A good pair for another target is insufficient.
    subjects = [call["args"][1] for call in out["calls"]
                if call["cmd"] == "docker" and call["args"][0] in ("exec", "inspect")]
    assert subjects and set(subjects) == {selected}, out
    image = next(row for row in result["checks"] if row["check"] == "eda_image_identity")
    assert image["detail"].startswith(selected + " runs "), image
    assert all(f"container={selected}" in row["detail"]
               for row in result["checks"] if row["check"].startswith("tool_")), result


@pytest.mark.parametrize("failure", ["absent", "unreadable", "image-absent", "exit", "malformed", "tool-missing"])
def test_issue3023_doctor_cannot_borrow_an_unmeasured_target(failure):
    case = {"env": {"EDA_CONTAINER": _ISOLATED}, "required": _PAIR_A,
            "containers": {"vibeic-eda": [_PAIR_A, ""], _ISOLATED: [_PAIR_A, ""]}}
    if failure == "absent":
        case["absent"] = _ISOLATED
        case["containers"].pop(_ISOLATED)
    elif failure == "unreadable":
        case["containers"][_ISOLATED] = [None, "neutral image has no registry digest"]
    elif failure == "image-absent":
        case["image_present"] = False
    elif failure in ("exit", "malformed"):
        case["python"] = failure
    else:
        case["tool_missing"] = True
    out = _doctor_call(case)
    assert out["result"]["success"] is False, out
    rows = {row["check"]: row for row in out["result"]["checks"]}
    if failure == "absent":
        assert rows["docker_reachable"]["ok"] is False
        assert "runtime_pair_match" not in rows
        assert _ISOLATED in rows["docker_reachable"]["detail"]
    elif failure == "tool-missing":
        assert rows["runtime_pair_match"]["ok"] is True
        assert rows["tool_yosys"]["ok"] is False
    else:
        assert rows["runtime_pair_match"]["ok"] is False, rows
        if failure in ("exit", "malformed"):
            assert "RUNTIME_PAIR_NOT_MEASURED" in rows["runtime_pair_match"]["detail"]
        else:
            assert out["pairSubjects"] == [_ISOLATED], out


def test_issue3023_explicit_matching_image_preserves_admission():
    out = _doctor_call({"env": {"EDA_CONTAINER": _ISOLATED}, "required": _PAIR_B,
                        "containers": {"vibeic-eda": [_PAIR_A, ""], _ISOLATED: [_PAIR_B, ""]}})
    assert out["result"]["success"] is True, out
    pair = next(row for row in out["result"]["checks"] if row["check"] == "runtime_pair_match")
    assert f"required={_PAIR_B} found={_PAIR_B}" in pair["detail"], pair
    assert out["pairSubjects"] == [_ISOLATED], out
