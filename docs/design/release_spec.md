# Vibe-IC v1.0 — Release Spec (MCP hand-off + Billing rail + API freeze)

**Status**: shipped 2026-04-26 (mcp_tool_registry + billing_log + 15-step
acceptance gate).
**Scope**: the final piece of the open marketplace — third-party EDA
tools register into mcp-eda-server automatically on plugin install, and
every billable invocation flows through a stdlib JSONL accounting rail.
At v1.0 the schemas (`vibe-ic-plugin/v1`, `vibe-ic-mcp-tools/v1`,
`vibe-ic-registry/v1`) are frozen for the v1.x line.
**Prereqs**: v0.85 (plugin format) + v0.90 (registry HTTP) + v0.95
(encrypted IP).

---

## 0. The two new files on disk

After v1.0 ships, every machine running vibe-ic CLI gains two files
that downstream consumers (mcp-eda-server, billing audit, ops dashboards)
can read:

| File | Owner | Schema | Purpose |
|------|-------|--------|---------|
| `~/.vibe-ic/mcp_tools.json` | `mcp_tool_registry.py` (auto-rebuild on install/uninstall) | `vibe-ic-mcp-tools/v1` | catalogue of every L_eda plugin's tool name + capabilities + endpoint + trust + billing. mcp-eda-server reads this at startup and registers each tool alongside its 20 built-ins. |
| `~/.vibe-ic/billing.jsonl` | `billing_log.py` (append-only) | `vibe-ic-billing/v1` (one row per call) | per-call accounting; mcp-eda-server appends one row per billed invocation. `vibe-ic plugin billing report` aggregates. |

Both files are local-only. The registry never sees billing rows; the
mcp catalogue is local because it's per-machine (different machines
install different plugins).

---

## 1. mcp_tools.json schema

```json
{
  "schema_version": "vibe-ic-mcp-tools/v1",
  "rebuilt_at": "2026-04-26T11:00:00Z",
  "tools": [
    {
      "namespace": "synopsys",
      "plugin_id": "dc-shell-2025.06",
      "version": "1.0.0",
      "mcp_tool_name": "eda_synth_dc",
      "capabilities": ["synth"],
      "supported_platforms": ["linux-x86_64"],
      "vendor_endpoint": "https://api.synopsys.com/vibe-ic/dc/v1",
      "requires_license_server": true,
      "trust_tier": "vendor-verified",
      "install_path": "/home/u/.vibe-ic/plugins/synopsys/.../1.0.0",
      "billing": {"model": "per-call", "per_call_cents": 1500}
    }
  ]
}
```

Capability vocabulary (substitutable via the 33-step flow): `synth`,
`pnr`, `sta`, `gds`, `drc`, `lvs`, `dft`, `equiv`, `formal`,
`simulate`, `fpga_compile`, `fpga_program`, `scope`, `jtag`,
`ir_drop`, `extraction`, `spice`, `lint`, `rtl_audit`, `doc_extract`.

When more than one tool advertises the same capability, both are
registered; the workflow chooses by user default config or per-run
flag, and provenance records which one ran.

`mcp_tool_registry.detect_capability_conflicts()` lists
multi-provider capabilities so the operator knows where they need a
default.

---

## 2. mcp-eda-server integration (separate codebase)

mcp-eda-server is a separate process under `mcp-eda-server/` (not in
this repo). At startup it does:

```python
from pathlib import Path
import json
mcp_tools_path = Path.home() / ".vibe-ic" / "mcp_tools.json"
if mcp_tools_path.exists():
    catalogue = json.loads(mcp_tools_path.read_text())
    for entry in catalogue["tools"]:
        register_tool(entry)   # mcp-eda-server's own register fn
```

`register_tool(entry)` is a one-liner in mcp-eda-server that wires the
new MCP tool into its dispatch table. The contract:

- Tool name MUST be unique across the union of built-ins + plugins.
  Server SHOULD warn if a plugin tries to shadow a built-in (e.g.
  `eda_synth` already exists; plugin should use `eda_synth_<vendor>`).
- For tools with `vendor_endpoint`: server forwards each call to the
  endpoint as a JSON POST with the call args; response replays the
  MCP tool result schema.
- For tools without `vendor_endpoint`: server expects an executable
  on `$PATH` named `<mcp_tool_name>` and shells out to it.

This is an mcp-eda-server work item; this repo only ships the catalogue.

---

## 3. billing.jsonl schema (one line per call)

```json
{
  "ts": "2026-04-26T11:00:00Z",
  "namespace": "synopsys",
  "plugin_id": "dc-shell-2025.06",
  "version": "1.0.0",
  "mcp_tool_name": "eda_synth_dc",
  "ic_id": "example_chip",
  "step": 8,
  "duration_ms": 34521,
  "cost_cents": 1500,
  "currency": "USD",
  "billing_model": "per-call",
  "platform_fee_pct": 20,
  "session_id": "uuid"
}
```

Fields with `null` allowed: `ic_id`, `step`, `duration_ms`. Other
fields required.

`mcp-eda-server` is intended to call:

```python
from billing_log import record_call
record_call(namespace="synopsys", plugin_id="dc-shell-2025.06",
            version="1.0.0", mcp_tool_name="eda_synth_dc",
            cost_cents=1500, ic_id="example_chip", step=8,
            duration_ms=34521)
```

after every successful billed tool invocation. Failure modes (tool
crashed, license-server down, etc.) do NOT record — billing only on
provable success.

---

## 4. CLI surface (final v1.0 set)

Plugin lifecycle:
```
vibe-ic plugin pack DIR --out FILE.tgz [--sign KEY]
vibe-ic plugin validate PATH
vibe-ic plugin install PATH | NS/PID[@VER] [--ip-key KEY] [--verify-sig PUB]
vibe-ic plugin uninstall NS/PID[@VER]
vibe-ic plugin list / info / index-rebuild / keygen
```

Registry:
```
vibe-ic plugin login    --namespace NS --secret SECRET
vibe-ic plugin search   [QUERY] [--namespace] [--layer] [--min-trust-tier]
vibe-ic plugin publish  FILE.tgz
vibe-ic plugin yank     NS/PID@VER --reason TXT
```

Encrypted IP (v0.95):
```
vibe-ic plugin ip keygen / encrypt / decrypt / fingerprint
```

MCP catalogue (v1.0):
```
vibe-ic plugin mcp-tools list
vibe-ic plugin mcp-tools show
```

Billing (v1.0):
```
vibe-ic plugin billing record  ...
vibe-ic plugin billing report  [--since 30d|ISO]
```

---

## 5. Frozen schemas at v1.0

These three schemas are frozen for the v1.x line. Future changes need
a new `schema_version` value in their respective documents.

| Schema | Used by | Where defined |
|--------|---------|---------------|
| `vibe-ic-plugin/v1` | every `plugin.yaml` | `docs/design/plugin_platform_spec.md` § 2 |
| `vibe-ic-registry/v1` | HTTP API + reference server + `index.json` | `docs/design/registry_api.md` |
| `vibe-ic-mcp-tools/v1` | `~/.vibe-ic/mcp_tools.json` | this doc § 1 |

Per-call billing JSONL doesn't have a `schema_version` field today
because it's append-only and consumers can detect schema by field
presence. v0.98 will add it.

---

## 6. Acceptance gate (acceptance_gate_full.py — 15 steps)

The runnable gate exercises every surface in this stack. Live run on
the build machine: ALL 15 STEPS PASSED. CI re-runs it via
`tests/test_acceptance_gate_full.py`.

If the gate exits 0 on a clean machine, v1.0 ships.

---

## 7. What v1.0 does NOT yet have (cleared in v0.98 — 2026-04-26)

Every bullet below was a v1.0 deferral. All have shipped in v0.98.

- **Federation between registries** — ✅ shipped in v0.98 U (commit
  `1da0b006`). `/federation/upstreams` endpoint + client fall-through
  via `vibe-ic plugin install --use-upstreams`.
- **Web UI** — ✅ shipped in v0.98 Z (commit `43db31f7`). Self-contained
  vanilla HTML+JS served by the reference server at `/`,
  `/browse/p/{ns}/{pid}`, `/api/v1/auth/device`.
- **OAuth device-code flow** — ✅ shipped in v0.98 V (commit `6836a20c`).
  RFC 8628 implementation; `vibe-ic plugin login --device`.
- **Sigstore-style transparency log** — ✅ shipped in v0.98 T (commit
  `7ad9515c`). Append-only sha256 hash chain + client-side
  `verify_transparency_chain`.
- **HSM-backed signing keys** — ✅ shipped in v0.98 W (commit
  `a6d8e8b8`). External signer hook: `vibe-ic plugin pack --sign-cmd CMD
  --sign-pubkey PUB`. (HSM-backed *encryption* keys still post-v0.98; same
  hook pattern can extend.)
- **Automatic IP-key fetch endpoint** — ✅ shipped in v0.97 (commit
  `076c344d`). Customer auth + entitlement table + `vibe-ic plugin ip
  key fetch`.
- **mcp-eda-server-side adapter** — ✅ shipped in v0.98 X (commit
  `6872a55e`). `vibeic_mcp_adapter.py` is the importable bridge.
- **Vendor-verified onboarding tooling** — ✅ shipped in v0.98 Y (commit
  `9230ce64`). `vibeic-registry vendor-verified add/remove/list` plus
  `register-namespace --vendor-verified`.

The v0.98 line therefore delivers the full open-platform stack with no
remaining "out-of-scope" deferrals from the original v1.0 design.

See `CHANGELOG.md` § "v0.98 — 2026-04-26" for the per-commit changelog
and the post-v0.98 backlog (Merkle-tree transparency head, pull-mirroring,
FIDO2 device approval, full-text index).
