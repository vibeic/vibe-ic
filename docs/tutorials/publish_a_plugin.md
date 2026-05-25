# Publish a Plugin to vibeic.ai — 10-Minute Quickstart

This walks an external publisher (an IC design lab, an EDA vendor, or
an individual contributor) from "I have a useful K3 contribution / IP
block / EDA tool" to "it's installable by anyone via
`vibe-ic plugin install <my-org>/<my-plugin>`" — entirely through the
v1.0 CLI.

Prerequisites:
- Python 3.10+
- Clone of `vibe-ic-marketplace` (or the released vibe-ic CLI)
- A namespace registered with vibeic.ai (request via support — one-time)
- The namespace's API secret (stored as env var `VIBE_IC_SECRET`)

For local development, you can point at a self-hosted reference server
instead — see § 6.

---

## 1. Pick your layer

| You have... | Use layer | Bundle root contains |
|-------------|-----------|----------------------|
| K3 entries, PRACTICAL_NOTES, or T5/T6 captures distilled from your team's IC work | `exp` | `experience/` (k3/, notes/, units/, decision_logs/) |
| RTL, .lib/.lef/.gds, or `ip_metadata.yaml` for an IP block | `ip`  | `ip_metadata.yaml` + `files/` |
| A new EDA tool you'd like the 33-step flow to be able to call | `eda` | `plugin.yaml` only (the tool itself runs separately) |

Three reference plugins ship under `vibe-ic-marketplace/reference-plugins/` —
copy the closest match as a template.

---

## 2. Write `plugin.yaml`

Minimum for an `exp` plugin:

```yaml
plugin_id: my-spi-experience       # ^[a-z][a-z0-9._-]{1,63}$
namespace: my-org                   # ^[a-z][a-z0-9-]{1,32}$
layer: exp                          # exp | ip | eda
version: 0.1.0                      # semver
schema_version: vibe-ic-plugin/v1   # frozen at v1.0

publisher:
  org: My Org
  contact: ic-team@my-org.example
  trust_tier: experimental         # set by you to experimental;
                                    # registry recomputes nightly

provenance:
  source_kind: open-source         # internal | open-source | licensed-binary
  built_from: 'local:./my-spi-experience'

experience:
  k3_entries: ./k3/
  practical_notes: ./notes/
```

Validate before continuing:

```bash
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/vibe_ic_plugin.py \
    validate ./my-spi-experience --json
# → {"valid": true, "errors": [], ...}
```

---

## 3. Generate signing key + IP key (if needed)

```bash
# ed25519 signing key — used to authenticate every bundle you publish
vibe-ic plugin keygen --out ~/.vibe-ic/keys/my-org-signing.pem

# Cat the .pub once and share with vibeic.ai support so they can verify
# your future uploads. Keep the .pem secret (chmod 600).
cat ~/.vibe-ic/keys/my-org-signing.pem.pub

# Only if you're publishing encrypted IP (layer=ip with .enc artifacts):
vibe-ic plugin ip keygen --out ~/.vibe-ic/keys/customer-acme.bin

# Encrypt your sensitive RTL with the customer key
vibe-ic plugin ip encrypt rtl/secret.v \
    --key ~/.vibe-ic/keys/customer-acme.bin \
    --out src/files/secret.v.enc

# Then list `./files/secret.v.enc` in plugin.yaml's ip.artifacts.rtl
# and distribute customer-acme.bin to ACME out-of-band.
```

---

## 4. Pack + sign

```bash
vibe-ic plugin pack ./my-spi-experience \
    --out my-spi-experience-0.1.0.tgz \
    --sign ~/.vibe-ic/keys/my-org-signing.pem

# This produces:
#   my-spi-experience-0.1.0.tgz       gzipped tarball with your bundle
#   my-spi-experience-0.1.0.tgz.sig   detached ed25519 signature
```

Pack refuses to build if `plugin.yaml` fails validation — the manifest
is the contract.

---

## 5. Login + publish to vibeic.ai

```bash
# One-time: authenticate (token persisted to ~/.vibe-ic/auth.json,
# chmod 600). Token TTL = 30 days.
export VIBE_IC_SECRET="…the secret vibeic.ai issued you…"
vibe-ic plugin login --namespace my-org

# Publish the bundle. Server validates manifest, signature key_id,
# (namespace, plugin_id, version) uniqueness, then stores it.
vibe-ic plugin publish my-spi-experience-0.1.0.tgz --json
```

Successful response:
```json
{
  "namespace": "my-org",
  "plugin_id": "my-spi-experience",
  "version": "0.1.0",
  "trust_tier": "experimental",        ← every new plugin starts here
  "trust_tier_history": [{"tier":"experimental", "at":"...", "reason":"initial publish"}],
  "uploaded_at": "..."
}
```

Your plugin is live. Anyone running:
```bash
vibe-ic plugin install my-org/my-spi-experience
```
…will fetch + extract it under their `~/.vibe-ic/plugins/`.

---

## 6. Trust-tier evolution (no action required)

Every new plugin starts at `experimental` (weight 0.3 in IC Expert
Agent's default-fill). The registry runs `trust_tier_recompute.py`
nightly against telemetry; transitions happen automatically:

| Condition observed in telemetry | Auto-promotes to |
|---------------------------------|------------------|
| ≥ 3 ICs of evidence, no HARMFUL verdicts | `community` (weight 0.5) |
| ≥ 10 helpful, zero HARMFUL | `community-trusted` (weight 0.8) |
| ≥ 3 ICs HARMFUL | `quarantined` (weight 0; not consumed) |

Vendor allow-list (separate org-onboarding flow) → `vendor-verified`
(weight 1.0).

**You cannot self-assign a tier.** Even if `plugin.yaml` says
`trust_tier: vendor-verified`, the registry overrides it on publish to
`experimental`. Honest defaults force the trust-tier system to be the
source of truth.

---

## 7. Self-hosting / local dev

If you don't want to publish to vibeic.ai while developing:

```bash
# Terminal 1 — start a local registry on port 8090
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/vibeic_registry_server.py \
    serve --port 8090 --state-dir ./local-registry-state

# Terminal 2 — provision your namespace there
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/vibeic_registry_server.py \
    register-namespace --namespace my-org --secret dev-secret \
    --state-dir ./local-registry-state

# Terminal 3 — publish + install against the local server
export VIBE_IC_REGISTRY_URL=http://127.0.0.1:8090/api/v1
export VIBE_IC_SECRET=dev-secret
vibe-ic plugin login --namespace my-org
vibe-ic plugin publish my-spi-experience-0.1.0.tgz
vibe-ic plugin install my-org/my-spi-experience
```

The reference server is stdlib-only (sqlite3 + http.server); no
external deps. Run behind nginx for HTTPS in production.

---

## 8. Versioning and yanking

```bash
# Bump version in plugin.yaml (e.g. 0.1.0 → 0.2.0), re-pack, re-publish:
vibe-ic plugin publish my-spi-experience-0.2.0.tgz

# Yank a bad version (existing installs continue to work; new
# installs refuse it unless --allow-yanked):
vibe-ic plugin yank my-org/my-spi-experience@0.1.0 \
    --reason "regression in K3 spi-peripheral; fixed in 0.2.0"
```

Yanked versions disappear from `vibe-ic plugin search` results but the
bundle stays available at the same URL (so existing installs don't
break overnight).

---

## 9. Reference plugins

Three real, end-to-end-tested examples ship with the repo:

```
vibe-ic-marketplace/reference-plugins/
├── example-exp/    # exp layer: K3 + notes + T5 + decision_log
├── example-ip/     # ip layer:  soft-IP (single Verilog file) + ip_metadata
└── example-eda/    # eda layer: third-party MCP synth tool stub
```

Use them as starting points. The CI test
`tests/test_reference_plugins.py` exercises the full pack → install →
list → uninstall round-trip on each one — if your bundle looks like
those, it'll work.
