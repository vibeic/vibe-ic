import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const helper = fileURLToPath(new URL("../../programs/vibeic_temp.py", import.meta.url));
const owned = new Set();
let session;

function query(args, env = process.env) {
  return execFileSync("python3", [helper, ...args], {
    encoding: "utf-8", env: { ...process.env, ...env },
  }).trim();
}

export function beginTemp(who, what, env = process.env) {
  const record = JSON.parse(query(["begin", who, what, "--owner-pid", String(process.pid)], env));
  owned.add(record);
  return {
    ...record,
    close() {
      if (!owned.has(record)) return;
      query(["finish", "--context", JSON.stringify(record)], record.env);
      owned.delete(record);
    },
  };
}

export function configureTemp(env = process.env) {
  if (!session || session.env.VIBEIC_TMP !== (env.VIBEIC_TMP || session.env.VIBEIC_TMP)) {
    session = beginTemp("mcp", "server", env);
  }
  Object.assign(env, session.env);
  return session.env;
}

export function scratchPath(...parts) {
  return join(configureTemp().TMPDIR, ...parts);
}

export function dockerTempMount(env = process.env) {
  configureTemp(env);
  return JSON.parse(query(["docker-mounts"], env));
}

function cleanupOwned() {
  for (const record of owned) {
    try { query(["finish", "--context", JSON.stringify(record)], record.env); }
    catch (error) { process.stderr.write(`Temporary cleanup failed: ${error.message}\n`); }
    owned.delete(record);
  }
}
process.once("exit", cleanupOwned);
process.once("SIGINT", () => { cleanupOwned(); process.exit(130); });
process.once("SIGTERM", () => { cleanupOwned(); process.exit(143); });
