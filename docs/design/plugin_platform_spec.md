# Vibe-IC v0.85 — Plugin Platform Foundation Spec

**Status**: spec, drafted 2026-04-26 from roadmap § 6 expansion
**Scope**: turn the open-marketplace vision in roadmap § 6 into concrete v0.85
work items with acceptance criteria. v0.85 = single-namespace pilot —
foundations only, no public registry, no billing, no remote publish.
**Audience**: developers picking up v0.85 work items.

The intent is *not* to ship the marketplace at v0.85. The intent is to ship
the primitives so that v0.90 / v0.95 / v1.0 work can build on a stable base
without renegotiating the manifest format every release.

---

## 0. What v0.85 IS and IS NOT

**IS**:
- `plugin.yaml` schema v1 (frozen for the v0.x line)
- Local-only `vibe-ic plugin` CLI (`pack`, `validate`, `install`, `list`,
  `uninstall`, `info`)
- Detached-signature support (sign / verify) using cosign-style
  ed25519 keys
- Local plugin registry directory layout (`~/.vibe-ic/plugins/`)
- IC Expert Agent reads installed plugins' K3 contributions alongside
  core K3 (with `trust_tier: experimental` for everything until evidence
  exists)
- Reference plugin: vibe-ic-core itself can be packed as `core/vibe-ic-core`
  to validate the round-trip

**IS NOT**:
- A public registry (no network publish/install). v0.85 = local install
  from `.tgz` file only.
- Billing rail. Per-call accounting waits for v1.0.
- Trust-tier auto-recompute. Tier is hard-coded `experimental` for
  third-party until v0.90.
- Encrypted-RTL handling. Hard-IP encryption stays as plaintext on local
  disk in v0.85; encryption arrives in v0.95.
- A web UI. Everything is CLI in v0.85.

---

## 1. Deliverable list

| # | Deliverable | Owner | Acceptance criteria |
|---|-------------|-------|---------------------|
| D1 | `plugin.yaml` schema (vibe-ic-plugin/v1) | platform-core | Parse → validate → reject + diagnose for every field listed in § 2.1. JSON Schema published at `docs/design/schemas/plugin.v1.schema.json`. |
| D2 | `plugin_manifest.py` validator program | platform-core | All required fields enforced (§ 2.1). Layer-aware (exp/ip/eda each gates layer-specific block). Semver validated. CLI `--validate-only PATH` returns 0/1/2 like other v0.78 programs. |
| D3 | `vibe_ic_plugin.py` CLI | platform-core | Subcommands: `pack`, `validate`, `install`, `list`, `uninstall`, `info`. Local-only. Plugin tarball is gzipped tar containing `plugin.yaml` + payload. |
| D4 | Local registry layout | platform-core | `~/.vibe-ic/plugins/<namespace>/<plugin_id>/<version>/` is canonical install path. `~/.vibe-ic/plugins/index.json` is the registry catalogue (regenerated from disk on every CLI call — never the source of truth). |
| D5 | Detached signature (sign/verify) | platform-core | ed25519 keypair gen via `vibe-ic plugin keygen`; `pack --sign KEY` produces `.tgz` + `.tgz.sig`; `install --verify-sig PUBKEY` rejects on bad sig. |
| D6 | IC Expert Agent integration | agents-core | Agent's K3 lookup also walks `~/.vibe-ic/plugins/*/L_exp/k3/`. Conflicts: core wins on tie; community-tier entries surfaced as suggestions, not as default. |
| D7 | Reference plugin: pack vibe-ic-core | platform-core | `vibe-ic plugin pack` against the core directory itself produces a valid bundle that re-installs cleanly. Validates the round-trip. |
| D8 | Migration path for ip_metadata.yaml | platform-core | Existing § 4.1 `ip_metadata.yaml` is the L_ip layer-specific payload — same file, just bundled inside `plugin.yaml`. No format change to ip_metadata.yaml itself. |

---

## 2. Schemas

### 2.1 `plugin.yaml` (vibe-ic-plugin/v1)

Required at root for **every** plugin:

| Field | Type | Constraint |
|-------|------|------------|
| `plugin_id` | string | `^[a-z][a-z0-9._-]{1,63}$` |
| `namespace` | string | `^[a-z][a-z0-9-]{1,32}$` |
| `layer` | enum | `exp` \| `ip` \| `eda` |
| `version` | string | semver `MAJOR.MINOR.PATCH(-pre)?` |
| `schema_version` | string | exact value `vibe-ic-plugin/v1` |
| `publisher.org` | string | non-empty |
| `publisher.contact` | string | email-like or URL |
| `publisher.trust_tier` | enum | one of: `core`, `vendor-verified`, `community-trusted`, `community`, `experimental`, `quarantined` |
| `provenance.source_kind` | enum | `internal` \| `open-source` \| `licensed-binary` |
| `provenance.built_from` | string | non-empty (URL or `local:<path>`) |

Optional at root:

| Field | Type | Notes |
|-------|------|-------|
| `provenance.signature` | string | `sha256:<hex>` for detached `.tgz.sig` |
| `provenance.signing_key` | string | key id (matches keygen output) |
| `depends_on` | list | each entry `{plugin_id, version}` with version range `==1.2.3` / `>=1.0.0` / `~1.2` |
| `billing` | object | reserved for v1.0; if present in v0.85, validator warns |

### 2.2 Layer-specific payloads

**`layer: exp`** — required field `experience`:
```yaml
experience:
  k3_entries: ./k3/                  # dir of yaml files merged as K3 contributions
  practical_notes: ./notes/          # dir of *.md per-skill notes
  experience_units: ./units/         # dir of experience_unit.t5/t6.yaml files
  decision_logs: ./decision_logs/    # dir of *.jsonl files
```
At least one of the four sub-fields must be present.

**`layer: ip`** — required field `ip`:
```yaml
ip:
  deliverable_kind: hard-ip          # hard-ip | firm-ip | soft-ip
  metadata: ./ip_metadata.yaml       # § 4.1 schema
  artifacts:
    lib: ./files/block.lib
    lef: ./files/block.lef
    gds: ./files/block.gds            # required when deliverable_kind=hard-ip
    rtl_stub: ./files/block.v         # required when deliverable_kind=hard-ip
    rtl: ./files/block.v              # required when deliverable_kind=firm-ip|soft-ip
```

**`layer: eda`** — required field `eda`:
```yaml
eda:
  mcp_tool_name: "eda_synth_dc"      # the registered MCP tool
  capabilities: [synth]               # subset of the 33-step capability vocab
  supported_platforms: [linux-x86_64]
  vendor_endpoint: "https://api.example.com/vibe-ic/dc/v1"   # optional
  requires_license_server: false
```

### 2.3 Bundle layout (`.tgz` contents)

```
plugin.yaml                       # at root, mandatory
ip_metadata.yaml                  # if layer == ip
experience/
  k3/<class>.yaml                 # if layer == exp
  notes/<skill>.md
  units/experience_unit.t5.*.yaml
  decision_logs/*.jsonl
files/                            # if layer == ip
  block.lib
  block.lef
  block.gds
  block.v
LICENSE.md                        # optional
README.md                         # optional
CHANGELOG.md                      # optional
```

Tarball is **gzipped** — file extension `.tgz` enforced by CLI. Contents
must validate before install.

### 2.4 Local registry layout

```
~/.vibe-ic/
├── plugins/
│   ├── arm/
│   │   └── cortex-m0/
│   │       ├── 1.0.3/             # the install dir = unpacked bundle
│   │       │   ├── plugin.yaml
│   │       │   ├── ip_metadata.yaml
│   │       │   └── files/...
│   │       └── 1.0.4/             # multiple versions live side-by-side
│   └── nccu-icdesign-lab/
│       └── spi-experience/
│           └── 0.4.0/
│               ├── plugin.yaml
│               └── experience/...
├── index.json                     # regenerated from disk; never source of truth
└── keys/
    ├── trusted_publishers.txt     # one pubkey per line; for --verify-sig default
    └── publisher_2026.pem         # local signing keys (per-machine)
```

`index.json` shape:
```json
{
  "schema_version": "vibe-ic-registry/v1",
  "rebuilt_at": "2026-04-26T11:00:00Z",
  "plugins": [
    {
      "plugin_id": "cortex-m0",
      "namespace": "arm",
      "version": "1.0.3",
      "layer": "ip",
      "trust_tier": "vendor-verified",
      "install_path": "/home/u/.vibe-ic/plugins/arm/cortex-m0/1.0.3/"
    }
  ]
}
```

---

## 3. CLI surface (D3)

```
vibe-ic plugin pack DIR --out FILE.tgz [--sign KEY]
vibe-ic plugin validate FILE.tgz | DIR
vibe-ic plugin install FILE.tgz [--verify-sig PUBKEY]
vibe-ic plugin uninstall NAMESPACE/PLUGIN_ID[@VERSION]
vibe-ic plugin list [--namespace N] [--layer L] [--json]
vibe-ic plugin info NAMESPACE/PLUGIN_ID[@VERSION]
vibe-ic plugin keygen --out KEY
vibe-ic plugin index-rebuild
```

**Exit codes** (consistent with v0.78 programs):
- 0 = success
- 1 = validation / business-logic error (bad manifest, signature mismatch,
  conflict)
- 2 = IO / file-not-found / bad CLI args

**`pack` semantics:**
- Walk `DIR` (must contain `plugin.yaml`).
- Validate manifest against schema BEFORE building tarball; refuse to pack
  invalid manifests.
- Compute sha256 of payload; record as `provenance.signature` if `--sign`.
- Tarball is `<plugin_id>-<version>.tgz` by default unless `--out` overrides.

**`install` semantics:**
- Reject if tarball validation fails.
- Reject if a different version of `<namespace>/<plugin_id>` is currently
  *active* and the user has not passed `--allow-multiple` or `--upgrade`.
- Default behaviour: install side-by-side. Existing version stays.
- Rebuild `index.json` after install.

**`uninstall` semantics:**
- Without `@VERSION`: refuse if multiple versions exist.
- With `@VERSION`: removes only that version dir. Other versions stay.

**`list` semantics:**
- Walks the `~/.vibe-ic/plugins/` tree; outputs the table. Reuses
  `index.json` if fresh (mtime within 60 s); else rebuilds.

---

## 4. IC Expert Agent integration (D6)

Today the agent's K3 lookup reads only:
```
vibe-ic-marketplace/plugins/vibe-ic-core/agents/defaults/class_reference.yaml
```

v0.85 extension — also walk:
```
~/.vibe-ic/plugins/*/*/*/L_exp/k3/*.yaml
```
…and merge into the in-memory K3 view. Conflict policy:
- A *core* class entry wins over any community entry of the same key.
- Multiple community entries on the same key: agent surfaces them as a
  ranked list (by `trust_tier` weight from § 6.3) instead of merging.
- IC Expert Agent's "where did this default come from?" trace MUST cite
  the namespace + plugin_id + version of the source.

Required code change locations (estimated from v0.78.5 codebase):
- `vibe-ic-marketplace/plugins/vibe-ic-core/agents/ic-expert-agent.md`
  — add a new section "External plugin sources" referencing the lookup
  path.
- New file `vibe-ic-marketplace/plugins/vibe-ic-d/programs/k3_view_resolve.py`
  — programmatic equivalent: given a class name, return the merged view
  with full provenance. Used by `k3_patch_proposer.py` so it sees the
  same view.

---

## 5. Test plan

| Layer | Test | Lives in |
|-------|------|----------|
| schema | every required field rejected when missing | `tests/test_plugin_manifest.py` |
| schema | each layer's payload required when `layer == X` | same |
| schema | semver validation (good + bad cases) | same |
| CLI | pack DIR → install .tgz → list → uninstall round-trip | `tests/test_vibe_ic_plugin.py` |
| CLI | install rejects unsigned bundle when `--verify-sig` given without matching pubkey | same |
| CLI | install side-by-side + uninstall single version | same |
| CLI | `index.json` regenerated correctly from on-disk plugins | same |
| reference plugin | pack vibe-ic-core, install, verify K3 still resolves | `tests/test_reference_core_plugin.py` (D7) |

Min coverage gate: 90% on the validator + CLI; round-trip test must pass
for vibe-ic-core itself.

---

## 6. Out-of-scope explicitly

- No HTTP/API surface; no `vibe-ic plugin publish` over the network.
  v0.90 adds this (with auth + rate-limit).
- No encrypted artifact handling. v0.95 adds it (per-customer key fetch
  on install).
- No per-call billing. v1.0 adds it (separate `billing.py` module).
- No `pattern_effectiveness_eval` integration (auto-tier-recompute). v0.90
  adds this; v0.85 assumes everything third-party stays at `experimental`
  unless an operator manually edits the manifest.
- No web UI. CLI-only.
- No multi-machine plugin sync. Each machine has its own
  `~/.vibe-ic/plugins/`.

---

## 7. Dependency graph (build order)

```
D1 (schema) ─┬─► D2 (validator) ─┬─► D3 (CLI) ─┬─► D7 (reference plugin round-trip)
             │                    │             │
             │                    │             ├─► D4 (registry layout)
             │                    │             │
             │                    │             ├─► D5 (sign/verify)
             │                    │             │
             │                    │             └─► D8 (ip_metadata bundling)
             │                    │
             │                    └─► D6 (IC Expert Agent reads installed)
             │
             └─► (also feeds v0.90 publisher protocol design)
```

D1 → D2 → D3 is critical path. D5 / D6 / D7 can branch off in parallel
once D3 is functional.

---

## 8. Acceptance gate for v0.85 release

A single bench-test demonstrates v0.85 readiness:

1. `vibe-ic plugin keygen --out test_key.pem` → produces ed25519 keypair.
2. Hand-write a `plugin.yaml` for a fake `nccu-icdesign-lab/test-spi`
   experience plugin with one K3 entry.
3. `vibe-ic plugin pack ./test-spi --sign test_key.pem` → produces
   `test-spi-0.1.0.tgz` + `.sig`.
4. `vibe-ic plugin validate test-spi-0.1.0.tgz` → exits 0.
5. `vibe-ic plugin install test-spi-0.1.0.tgz --verify-sig test_key.pub` →
   installs to `~/.vibe-ic/plugins/nccu-icdesign-lab/test-spi/0.1.0/`.
6. `vibe-ic plugin list` → shows the new entry.
7. Run `k3_patch_proposer` against a benchmark IC; confirm the new K3
   entry appears in the proposer's source citations alongside core K3.
8. `vibe-ic plugin uninstall nccu-icdesign-lab/test-spi@0.1.0` → removes
   cleanly; `list` no longer shows it.

If all 8 steps pass on a clean machine, v0.85 ships.
