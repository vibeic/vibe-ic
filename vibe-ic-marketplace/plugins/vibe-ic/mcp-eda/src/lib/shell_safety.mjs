// ─── Shell-safety helpers (command-injection hardening) ───
//
// Before v0.114.6 every EDA tool built its shell command by string-
// interpolating caller-supplied params (module names, file paths, project
// dirs) and ran it via `execSync("docker exec C bash -c \"" +
// cmd.replace(/"/g,'\\"') + "\"")` — escaping ONLY double quotes. A value
// containing `;` `$` `` ` `` `'` or a newline could break out of the intended
// command context and execute arbitrary shell — on the HOST for the FPGA /
// doc-extract / DB tools. These validators are applied at each tool's entry
// (and the runners switched to argv-based spawnSync) to close that surface.
//
// They are pure (no I/O / no deps) so they can be unit-tested in isolation.

// POSIX single-quote escape — wrap a value so it survives as exactly ONE shell
// token regardless of content. Use for path / filename values that appear as
// standalone arguments inside a shell command string.
export function shq(s) {
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

// Strict identifier guard — for names interpolated INSIDE an already
// single-quoted tool script (e.g. `yosys -p '... synth -top NAME ...'`,
// `magic -c '... load NAME ...'`) where shq() cannot wrap. Verilog-style
// identifiers only; throws on anything that could break the quoting.
export const _IDENT_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
export function assertSafeIdent(value, label = "identifier") {
  if (typeof value !== "string" || !_IDENT_RE.test(value)) {
    throw new Error(`unsafe ${label}: ${JSON.stringify(value)} (expected a plain identifier ${_IDENT_RE})`);
  }
  return value;
}

// Part / cell / layer token — like an identifier but also allows '-' and '.'
// (e.g. Vivado part "xc7a35tcpg236-1", metal layer "met1"). Still rejects every
// shell metacharacter.
export const _TOKEN_RE = /^[A-Za-z0-9_.\-]+$/;
export function assertSafeToken(value, label = "token") {
  if (typeof value !== "string" || value.length === 0 || !_TOKEN_RE.test(value)) {
    throw new Error(`unsafe ${label}: ${JSON.stringify(value)} (expected [A-Za-z0-9_.-])`);
  }
  return value;
}

// Docker container-name guard. A container name is NOT a Verilog identifier:
// docker's own grammar is [a-zA-Z0-9][a-zA-Z0-9_.-]*, and the names this server
// ships with ("vibeic-eda") carry a hyphen. Guarding such a param with
// assertSafeIdent — whose class has no '-' — makes a tool's own default fail the
// tool's own guard, refusing every invocation unconditionally; that is exactly
// what happened to eda_sta's `container` and eda_extraction's
// `field_solve_container` from 9d7e5e1a5 (2026-07-13) until this fix.
//
// The class below adds ONLY '-' and '.' to the identifier class and additionally
// requires an alphanumeric first character, so it is strictly tighter than
// assertSafeToken: it rejects every shell metacharacter (none of `;&|<>$`(){}[]!*?~"'\\`,
// whitespace or newline is in the class) AND rejects a leading '-', which docker
// would otherwise parse as a command-line flag rather than a container name.
export const _CONTAINER_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;
export function assertSafeContainer(value, label = "container") {
  if (typeof value !== "string" || !_CONTAINER_RE.test(value)) {
    throw new Error(`unsafe ${label}: ${JSON.stringify(value)} (expected a docker container name ${_CONTAINER_RE})`);
  }
  return value;
}

// Path guard — reject shell metacharacters, whitespace and newlines. The
// container/project paths this server handles never legitimately contain them,
// so rejecting closes the injection surface for path-typed params while
// turning a previously-silent quoting break into a clear, actionable error.
export const _PATH_BAD_RE = /[;&|<>$`(){}\[\]!*?~"'\\\s]/;
export function assertSafePath(value, label = "path") {
  if (typeof value !== "string" || value.length === 0 || _PATH_BAD_RE.test(value)) {
    throw new Error(`unsafe ${label}: ${JSON.stringify(value)} (contains a shell metacharacter or whitespace)`);
  }
  return value;
}
// Validate every element of a path-array param.
export function assertSafePaths(values, label = "path") {
  if (!Array.isArray(values)) throw new Error(`unsafe ${label}: expected an array`);
  values.forEach((v) => assertSafePath(v, label));
  return values;
}

// Soft guard for free-form list / args params (comma- or space-separated cell
// names, extra CLI args): allow spaces / commas / slashes but reject the
// characters that can break out of a shell command.
export const _META_RE = /[;&|<>$`(){}\[\]!*?~"'\\\n\r]/;
export function assertNoShellMeta(value, label = "value") {
  if (typeof value === "string" && _META_RE.test(value)) {
    throw new Error(`unsafe ${label}: ${JSON.stringify(value)} (contains a shell metacharacter)`);
  }
  return value;
}

// Optional variants — skip undefined / null / empty, validate otherwise.
export function optPath(v, label = "path") { if (v !== undefined && v !== null && v !== "") assertSafePath(v, label); return v; }
export function optIdent(v, label = "identifier") { if (v !== undefined && v !== null && v !== "") assertSafeIdent(v, label); return v; }
export function optToken(v, label = "token") { if (v !== undefined && v !== null && v !== "") assertSafeToken(v, label); return v; }
export function optContainer(v, label = "container") { if (v !== undefined && v !== null && v !== "") assertSafeContainer(v, label); return v; }
export function optNoShellMeta(v, label = "value") { if (v !== undefined && v !== null && v !== "") assertNoShellMeta(v, label); return v; }

// Build a standard MCP error envelope so a guard throw returns a clean
// {success:false,error} payload instead of crashing the tool call.
export function guardError(e) {
  return { content: [{ type: "text", text: JSON.stringify({ success: false, error: `input rejected: ${e.message}` }) }] };
}
