import { homedir } from "node:os";
import { spawnSync } from "node:child_process";

const DEFAULT_IMAGE = "ghcr.io/vibeic/vibeic-eda:latest";
const MANAGED_LABEL = "org.vibeic.mcp-managed=true";

function runDocker(args, run = spawnSync) {
  const result = run("docker", args, {
    encoding: "utf-8",
    timeout: 600_000,
    env: process.env,
  });
  if (result.error || result.status !== 0) {
    const detail = result.error?.message || result.stderr || result.stdout || `exit ${result.status}`;
    throw new Error(`docker ${args[0]} failed: ${String(detail).trim()}`);
  }
  return String(result.stdout || "").trim();
}

function inspectJson(kind, ref, run) {
  const noun = kind === "container" ? ["inspect", ref] : ["image", "inspect", ref];
  return JSON.parse(runDocker(noun, run))[0];
}

function immutableRef(image, inspected) {
  if (image.includes("@sha256:")) return image;
  const repo = image.replace(/:[^/:]+$/, "");
  const digest = (inspected.RepoDigests || []).find(ref => ref.startsWith(`${repo}@sha256:`))
    || (inspected.RepoDigests || [])[0];
  if (!digest) throw new Error(`pulled image ${image} exposes no immutable RepoDigest`);
  return digest;
}

const COMPAT_SCRIPT = String.raw`set -euo pipefail
if [ -x /foss/tools/yosys/bin/yosys ] && [ -d /foss/pdks ]; then exit 0; fi
env_bin=$(dirname "$(command -v yosys)")
: "\${PDK_ROOT:?Nix vibeic-eda image must export PDK_ROOT}"
mkdir -p /foss/tools /foss
ln -sfn "$env_bin" /foss/tools/bin
for tool in yosys openroad iverilog verilator netgen ngspice; do
  mkdir -p "/foss/tools/$tool"
  ln -sfn "$env_bin" "/foss/tools/$tool/bin"
done
mkdir -p /foss/tools/klayout
ln -sfn "$(command -v klayout)" /foss/tools/klayout/klayout
iv_real=$(readlink -f "$(command -v iverilog)")
iv_lib=$(dirname "$(dirname "$iv_real")")/lib
if [ -d "$iv_lib" ]; then ln -sfn "$iv_lib" /foss/tools/iverilog/lib; else mkdir -p /foss/tools/iverilog/lib; fi
ln -sfn "$PDK_ROOT" /foss/pdks`;

export function ensureContainerRuntime({ env = process.env, run = spawnSync } = {}) {
  if (env.VIBEIC_EDA_AUTO_BOOTSTRAP !== "1") return null;

  const image = (env.VIBEIC_EDA_IMAGE || DEFAULT_IMAGE).trim();
  const container = (env.EDA_CONTAINER || env.VIBEIC_EDA_CONTAINER || "vibeic-eda").trim();
  runDocker(["pull", image], run);
  const target = inspectJson("image", image, run);
  const immutable = immutableRef(image, target);

  let current = null;
  try { current = inspectJson("container", container, run); }
  catch (error) {
    const message = error.message.toLowerCase();
    if (!message.includes("no such") && !message.includes("not found")) throw error;
  }

  if (current && current.Image !== target.Id) {
    if (current.Config?.Labels?.["org.vibeic.mcp-managed"] !== "true") {
      throw new Error(
        `container ${container} uses ${current.Image}, not newest ${target.Id}; ` +
        `refusing to replace an unmanaged container`
      );
    }
    runDocker(["rm", "-f", container], run);
    current = null;
  }

  if (!current) {
    runDocker([
      "run", "-d", "--name", container, "--restart", "unless-stopped",
      "--label", MANAGED_LABEL, "-v", `${homedir()}:${homedir()}`,
      immutable, "sleep", "infinity",
    ], run);
  } else if (!current.State?.Running) {
    runDocker(["start", container], run);
  }

  runDocker(["exec", container, "bash", "-lc", COMPAT_SCRIPT], run);
  env.EDA_CONTAINER = container;
  env.VIBEIC_EDA_CONTAINER = container;
  env.VIBEIC_EDA_IMAGE = immutable;
  return { container, image: immutable, imageId: target.Id };
}
