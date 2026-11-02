import { shq } from "./shell_safety.mjs";

// Resolve a built-in legacy default INSIDE the selected container. Older EDA
// images expose /foss/tools; native images expose their immutable tools on PATH.
// An executable legacy default remains authoritative, even when it fails.
// Explicit operator paths must be executed directly, never passed here as a
// fallback candidate. This helper does not inspect the host or alter the image.
export function containerToolCommand(name, legacyPath) {
  if (!/^[A-Za-z0-9_-]+$/.test(name) || !String(legacyPath).startsWith("/")) {
    throw new Error("expected a tool name and an absolute built-in legacy path");
  }
  const missing = shq(`Error: tool unavailable in container: ${name}`);
  return `"$(if [ -x ${shq(legacyPath)} ]; then printf '%s' ${shq(legacyPath)}; else command -v ${shq(name)} || { printf '%s\\n' ${missing} >&2; exit 127; }; fi)"`;
}
