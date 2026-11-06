import json
import subprocess
from pathlib import Path


MODULE = Path(__file__).parents[1] / "src" / "container_runtime.mjs"


def test_bootstrap_pulls_latest_and_pins_the_digest_without_host_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBEIC_TMP", str(tmp_path))
    script = r'''
const { ensureContainerRuntime } = await import(process.argv[1]);
const calls = [];
const digest = "sha256:" + "8".repeat(64);
const repoDigest = "ghcr.io/vibeic/vibeic-eda@" + digest;
function result(status, stdout = "", stderr = "") { return { status, stdout, stderr }; }
function run(_cmd, args) {
  calls.push(args);
  if (args[0] === "pull") return result(0);
  if (args[0] === "image" && args[1] === "inspect") return result(0, JSON.stringify([{
    Id: digest, RepoDigests: [repoDigest]
  }]));
  if (args[0] === "inspect") return result(1, "", "error: no such object: vibeic-eda");
  if (args[0] === "run") return result(0, "container-id");
  if (args[0] === "exec") return result(0);
  throw new Error("unexpected docker call " + JSON.stringify(args));
}
const env = {
  VIBEIC_EDA_AUTO_BOOTSTRAP: "1",
  VIBEIC_EDA_IMAGE: "ghcr.io/vibeic/vibeic-eda:latest",
  EDA_CONTAINER: "vibeic-eda"
};
const out = ensureContainerRuntime({ env, run });
console.log(JSON.stringify({ out, env, calls }));
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, MODULE.as_uri()],
        text=True, capture_output=True, check=True,
    )
    record = json.loads(result.stdout)
    assert record["env"]["VIBEIC_EDA_IMAGE"].startswith(
        "ghcr.io/vibeic/vibeic-eda@sha256:"
    )
    flat = json.dumps(record["calls"])
    assert '"pull", "ghcr.io/vibeic/vibeic-eda:latest"' in flat
    assert "--label" in flat and "org.vibeic.mcp-managed=true" in flat
    created = next(call for call in record["calls"] if call[0] == "run")
    mounts = {created[index + 1] for index, flag in enumerate(created[:-1]) if flag == "-v"}
    assert mounts == {f"{Path.home()}:{Path.home()}", f"{tmp_path.resolve()}:{tmp_path}"}
    assert "docker.sock" not in flat
    assert not Path(record["env"]["TMPDIR"]).exists()
    assert not Path(record["env"]["VIBEIC_RUN_DIR"]).exists()


def test_bootstrap_refuses_to_replace_an_unmanaged_container():
    script = r'''
const { ensureContainerRuntime } = await import(process.argv[1]);
const newest = "sha256:" + "8".repeat(64), old = "sha256:" + "7".repeat(64);
function result(status, stdout = "", stderr = "") { return { status, stdout, stderr }; }
function run(_cmd, args) {
  if (args[0] === "pull") return result(0);
  if (args[0] === "image") return result(0, JSON.stringify([{
    Id: newest, RepoDigests: ["ghcr.io/vibeic/vibeic-eda@" + newest]
  }]));
  if (args[0] === "inspect") return result(0, JSON.stringify([{
    Image: old, Config: {Labels: {}}, State: {Running: true}
  }]));
  throw new Error("mutation reached: " + JSON.stringify(args));
}
try {
  ensureContainerRuntime({env: {VIBEIC_EDA_AUTO_BOOTSTRAP: "1"}, run});
  process.exit(2);
} catch (error) {
  console.log(error.message);
}
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, MODULE.as_uri()],
        text=True, capture_output=True,
    )
    assert result.returncode == 0
    assert "refusing to replace an unmanaged container" in result.stdout


def test_existing_nonroot_runtime_initializes_paths_without_recreation():
    script = r'''
const { ensureContainerRuntime } = await import(process.argv[1]);
const digest = 'sha256:' + '8'.repeat(64), calls = [];
function run(_cmd, args) {
  calls.push(args);
  const ok = stdout => ({status: 0, stdout: stdout || ''});
  if (args[0] === 'pull') return ok();
  if (args[0] === 'image') return ok(JSON.stringify([{
    Id: digest, RepoDigests: ['neutral.invalid/eda@' + digest]
  }]));
  if (args[0] === 'inspect') return ok(JSON.stringify([{
    Image: digest, Config: {User: '1000', Labels: {}}, State: {Running: true}
  }]));
  if (args[0] === 'exec') {
    if (args.slice(1, 3).join(' ') === '--user 0') return ok();
    return {status: 1, stderr: 'mkdir: cannot create directory /foss/tools: Permission denied'};
  }
  throw Error('unexpected container mutation ' + JSON.stringify(args));
}
const env = {VIBEIC_EDA_AUTO_BOOTSTRAP: '1', VIBEIC_EDA_IMAGE: 'neutral.invalid/eda:latest'};
ensureContainerRuntime({env, run});
console.log(JSON.stringify(calls));
'''
    result = subprocess.run(
        ['node', '--input-type=module', '-e', script, MODULE.as_uri()],
        text=True, capture_output=True, check=True,
    )
    calls = json.loads(result.stdout)
    assert [call[0] for call in calls] == ['pull', 'image', 'inspect', 'exec']


def test_managed_runtime_gets_the_new_temporary_mount_even_when_image_is_current(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBEIC_TMP", str(tmp_path))
    script = r'''
const { ensureContainerRuntime } = await import(process.argv[1]);
const digest = 'sha256:' + '8'.repeat(64), calls = [];
function run(_cmd, args) {
  calls.push(args);
  const ok = stdout => ({status: 0, stdout: stdout || ''});
  if (args[0] === 'pull') return ok();
  if (args[0] === 'image') return ok(JSON.stringify([{
    Id: digest, RepoDigests: ['neutral.invalid/eda@' + digest]
  }]));
  if (args[0] === 'inspect') return ok(JSON.stringify([{
    Image: digest, Config: {Labels: {'org.vibeic.mcp-managed': 'true'}},
    State: {Running: true}, Mounts: []
  }]));
  if (['rm', 'run', 'exec'].includes(args[0])) return ok();
  throw Error('unexpected call ' + JSON.stringify(args));
}
ensureContainerRuntime({env: {VIBEIC_EDA_AUTO_BOOTSTRAP: '1'}, run});
console.log(JSON.stringify(calls));
'''
    result = subprocess.run(['node', '--input-type=module', '-e', script, MODULE.as_uri()],
                            text=True, capture_output=True, check=True)
    calls = json.loads(result.stdout)
    assert [call[0] for call in calls] == ['pull', 'image', 'inspect', 'rm', 'run', 'exec']
    created = next(call for call in calls if call[0] == 'run')
    assert f'{tmp_path.resolve()}:{tmp_path}' in created
