# Vibe-IC v0.90 — Registry HTTP API Spec

**Status**: spec, drafted 2026-04-26
**Scope**: HTTP protocol that lets any vibe-ic CLI install / publish /
search plugins against a remote registry. Reference deployment target is
`https://vibeic.ai/api/v1/`. Any organisation can host their own private
registry by setting `VIBE_IC_REGISTRY_URL`.
**Audience**: registry server implementers + CLI client implementers.

The protocol is REST + multipart-bundle uploads, JSON everywhere except the
bundle download (octet-stream tarball). Auth is API-token. Trust tiers are
server-computed from pattern-effectiveness telemetry (see § 5).

---

## 0. Compatibility & versioning

- API version is in the URL path: `/api/v1/...`. Breaking changes bump
  to `/api/v2/`.
- Server returns `X-Vibe-Ic-Api-Version: 1` on every response.
- Plugin manifest schema is independent: the API version may evolve while
  `plugin.yaml: schema_version: vibe-ic-plugin/v1` stays frozen.

---

## 1. Endpoints

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| `GET`  | `/api/v1/` | none | — | service banner JSON |
| `GET`  | `/api/v1/health` | none | — | `{"status":"ok","time":"..."}` |
| `POST` | `/api/v1/auth/token` | publisher creds | login JSON | `{"token":"...","expires":"..."}` |
| `GET`  | `/api/v1/plugins` | none | query string | search results |
| `GET`  | `/api/v1/plugins/{ns}/{pid}` | none | — | latest version metadata |
| `GET`  | `/api/v1/plugins/{ns}/{pid}/{ver}` | none | — | full version manifest + signature info |
| `GET`  | `/api/v1/plugins/{ns}/{pid}/{ver}/bundle` | none | — | `application/octet-stream` (`.tgz` bytes) |
| `GET`  | `/api/v1/plugins/{ns}/{pid}/{ver}/bundle.sig` | none | — | `text/plain` (`.tgz.sig` contents) |
| `POST` | `/api/v1/plugins/{ns}/{pid}` | token | multipart (.tgz + .sig) | created version |
| `DELETE` | `/api/v1/plugins/{ns}/{pid}/{ver}` | token + owner | — | yank record (bundle stays installed for existing users) |

### 1.1 GET `/api/v1/`

Service banner. Used for liveness + version probing by clients before
making real calls.

```json
{
  "service": "vibe-ic-registry",
  "api_version": "v1",
  "schema_version": "vibe-ic-plugin/v1",
  "registry_id": "vibeic.ai",
  "trust_tiers_supported": [
    "core", "vendor-verified", "community-trusted",
    "community", "experimental", "quarantined"
  ],
  "max_bundle_bytes": 134217728
}
```

### 1.2 POST `/api/v1/auth/token`

Body: `{"namespace": "test-org", "secret": "<api-secret>"}`
Response: `{"token": "<bearer>", "expires": "2026-05-26T00:00:00Z"}`

The secret is provisioned out-of-band when an org registers a namespace.
Token TTL ≥ 30 days. Token revocation: `DELETE /api/v1/auth/token` with
the `Authorization: Bearer <token>` header.

For v0.90, secret-based; v0.95 adds OAuth device-code flow.

### 1.3 GET `/api/v1/plugins`

Query parameters (all optional):

| Param | Type | Notes |
|-------|------|-------|
| `q` | string | free-text search across plugin_id + description |
| `namespace` | string | filter by exact namespace |
| `layer` | enum | `exp` / `ip` / `eda` |
| `min_trust_tier` | enum | exclude tiers below this floor |
| `limit` | int | default 20, max 100 |
| `cursor` | string | pagination cursor |

Response:
```json
{
  "next_cursor": null,
  "results": [
    {
      "namespace": "example-org",
      "plugin_id": "spi-peripheral-experience",
      "latest_version": "0.1.0",
      "layer": "exp",
      "trust_tier": "community",
      "description": "Open community SPI experience pack",
      "publisher_org": "Example IC Design Lab",
      "downloads_30d": 142
    }
  ]
}
```

### 1.4 GET `/api/v1/plugins/{ns}/{pid}/{ver}`

Returns:
```json
{
  "namespace": "example-org",
  "plugin_id": "spi-peripheral-experience",
  "version": "0.1.0",
  "manifest": { /* the full plugin.yaml as JSON */ },
  "trust_tier": "community",
  "trust_tier_history": [
    {"tier": "experimental", "at": "2026-04-26T11:00:00Z"},
    {"tier": "community",     "at": "2026-05-10T11:00:00Z"}
  ],
  "signature": {
    "key_id": "ab12cd34...",
    "publisher_pubkey_url": "https://vibeic.ai/api/v1/keys/ab12cd34..."
  },
  "bundle": {
    "url":  "/api/v1/plugins/example-org/spi-peripheral-experience/0.1.0/bundle",
    "size_bytes": 4096,
    "sha256": "deadbeef..."
  },
  "uploaded_at": "2026-04-26T11:00:00Z",
  "yanked": false,
  "yank_reason": null
}
```

### 1.5 POST `/api/v1/plugins/{ns}/{pid}`

`Authorization: Bearer <token>` (token must own the namespace).
`Content-Type: multipart/form-data` with two parts:
- `bundle`: the `.tgz` (filename irrelevant; server reads + validates manifest)
- `signature`: the detached `.tgz.sig` (text content)

Server actions on POST:
1. Parse manifest from bundle. Reject if invalid (HTTP 400 + errors list).
2. Verify token owns `manifest.namespace`. Reject if not (HTTP 403).
3. Verify `manifest.plugin_id == pid` from URL. Reject if mismatch (HTTP 400).
4. Verify version is unique within `(ns, pid)`. Reject if duplicate (HTTP 409).
5. Verify signature key_id matches publisher's registered pubkey. Reject
   if no match (HTTP 400 — clients must `vibe-ic plugin register-key` first).
6. Store bundle + sig + extracted manifest. Initial `trust_tier =
   experimental`. Returns 201 with the same shape as GET single-version.

### 1.6 DELETE `/api/v1/plugins/{ns}/{pid}/{ver}` — yank

Same auth as POST. Sets `yanked=true` + `yank_reason` (from request body).
Yanked versions are still downloadable (existing installs continue to
work) but excluded from search and refused by `install` unless
`--allow-yanked` flag.

---

## 2. Auth model (v0.90 first-cut)

| Identity | How obtained | Stored where |
|----------|--------------|--------------|
| Namespace secret | Issued by registry admin when org registers a namespace | publisher's CI secret store |
| Bearer token | `POST /auth/token` with namespace + secret | client `~/.vibe-ic/auth.json` (chmod 600) |
| Publisher pubkey | Registered via `POST /api/v1/keys` (separate flow) | server-side pubkey table |

`~/.vibe-ic/auth.json`:
```json
{
  "registry_url": "https://vibeic.ai/api/v1",
  "namespace_tokens": {
    "test-org": {
      "token": "<bearer>",
      "expires": "2026-05-26T00:00:00Z"
    }
  }
}
```

---

## 3. Error responses

All errors return JSON:
```json
{"error": "<code>", "message": "<human-readable>"}
```

| HTTP | Code | When |
|------|------|------|
| 400  | `bad_manifest`     | manifest fails validation |
| 400  | `bad_signature`    | signature key_id doesn't match registered pubkey, or bad blob |
| 401  | `unauth`           | missing/expired token |
| 403  | `forbidden`        | token does not own namespace |
| 404  | `not_found`        | plugin/version doesn't exist |
| 409  | `version_exists`   | (ns, pid, ver) already published — never overwrite |
| 413  | `bundle_too_large` | bundle exceeds `max_bundle_bytes` |
| 429  | `rate_limited`     | per-IP or per-token quota hit; `Retry-After` header set |
| 503  | `unavailable`      | server in maintenance |

---

## 4. Rate limits (v0.90 starter)

Per IP (anonymous): 60 req/min, 1000 req/hour.
Per token (publisher): 600 req/min, no hourly cap.
Per namespace (publish only): 10 publishes/min.

Rate-limit headers on every 200/4xx response:
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 23
X-RateLimit-Reset: 1714137600
```

---

## 5. Trust-tier auto-recompute

Trust tier is **never set by the publisher**. The registry recomputes it
nightly from telemetry:

Inputs:
- `pattern_effectiveness_eval` verdicts from clients that opted in to
  telemetry (default: anonymized aggregates only)
- Install/uninstall counts (last 30 days)
- Publisher-account age + signed-bundle-history continuity

Decision table (see roadmap § 6.3 for tier ladder):

| Condition | Resulting tier |
|-----------|----------------|
| `pattern_effectiveness` HARMFUL ≥ 3 ICs | `quarantined` |
| < 3 ICs of evidence (new plugin) | `experimental` |
| ≥ 3 ICs evidence + verdict NEUTRAL/HELPFUL + < 10 successful uses | `community` |
| ≥ 10 successful uses + verdict HELPFUL + zero HARMFUL ever | `community-trusted` |
| Identity-verified org + signing-key audit pass | `vendor-verified` |
| Shipped with vibe-ic-core | `core` |

Tier transitions are reflected in `trust_tier_history` on the version
record. Publishers can dispute a HARMFUL verdict via support email; one
re-evaluation round is granted with new sample data.

`trust_tier_recompute.py` (this commit's sibling tool) implements the
above table. The reference server runs it from cron (or systemd timer).

---

## 6. Privacy & telemetry

The CLI sends **anonymous aggregate telemetry** by default:
- Plugin install events (no IP, no user, no IC content)
- `pattern_effectiveness` verdicts at the class level (no IC names)

Opt out with `vibe-ic plugin telemetry off` or
`VIBE_IC_TELEMETRY=0`. The registry server logs only what was sent;
no traffic-analysis or fingerprinting.

---

## 7. Out-of-scope for v0.90

- Per-call billing rail (v1.0 — separate `/billing/...` namespace)
- Encrypted-RTL artifact key fetch (v0.95 — separate `/ip-keys/...` namespace)
- Web UI for browsing (separate front-end project; not API)
- Mirror federation between registries (v1.x)
- Plugin signing transparency log (sigstore-style, v1.x)

---

## 8. Sequencing

| Item | Location | Owner |
|------|----------|-------|
| OpenAPI YAML | `docs/design/vibeic_registry_openapi.yaml` | this commit |
| Reference server | `vibe-ic-marketplace/plugins/vibe-ic-d/programs/vibeic_registry_server.py` | follow-up commit (K) |
| HTTP client | `vibe-ic-marketplace/plugins/vibe-ic-d/programs/plugin_registry_client.py` | follow-up commit (J) |
| CLI integration | extends `vibe_ic_plugin.py` with `login` / `search` / `publish` + `install ns/pid[@ver]` | commit J |
| Trust-tier recompute | `vibe-ic-marketplace/plugins/vibe-ic-d/programs/trust_tier_recompute.py` | commit L |
| End-to-end gate | `acceptance_gate_registry.py` extending v0.85's 8 steps with publish→search→install via registry | commit M |
| `vibeic.ai` deployment | Reference-server-as-systemd-unit under `/var/www/vibeic-api/` | out-of-repo (deployment) |
