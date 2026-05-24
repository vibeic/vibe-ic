# Registry HTTP API

This document defines the HTTP protocol that lets a Vibe-IC client
publish, install, and search plugins against a remote registry. Any
organisation can host a private registry by setting
`VIBE_IC_REGISTRY_URL`; the same protocol is served by the bundled
reference server.

The protocol is REST + multipart-bundle uploads, JSON everywhere
except the bundle download (`application/octet-stream`). Auth is
API-token. Trust tiers are server-computed from telemetry (§ 5).

---

## 1. Versioning

The API version is in the URL path: `/api/v1/...`. Breaking changes
bump to `/api/v2/`. Servers return `X-Vibe-Ic-Api-Version: 1` on
every response.

The plugin manifest schema (`schema_version: vibe-ic-plugin/v1`) is
independent of the API version.

---

## 2. Endpoints

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| `GET`    | `/api/v1/` | none | — | service banner |
| `GET`    | `/api/v1/health` | none | — | `{"status":"ok","time":"..."}` |
| `POST`   | `/api/v1/auth/token` | publisher creds | login JSON | `{"token","expires"}` |
| `GET`    | `/api/v1/plugins` | none | query string | search results |
| `GET`    | `/api/v1/plugins/{ns}/{pid}` | none | — | latest version metadata |
| `GET`    | `/api/v1/plugins/{ns}/{pid}/{ver}` | none | — | full version manifest + signature |
| `GET`    | `/api/v1/plugins/{ns}/{pid}/{ver}/bundle` | none | — | bundle bytes |
| `GET`    | `/api/v1/plugins/{ns}/{pid}/{ver}/bundle.sig` | none | — | detached signature |
| `GET`    | `/api/v1/plugins/{ns}/{pid}/stats` | none | — | downloads / used-by / last-updated |
| `POST`   | `/api/v1/plugins/{ns}/{pid}` | token | multipart `(.tgz, .sig)` | created version |
| `DELETE` | `/api/v1/plugins/{ns}/{pid}/{ver}` | token + owner | yank reason | yank record |

### 2.1 Service banner

```json
{
  "service": "vibe-ic-registry",
  "api_version": "v1",
  "schema_version": "vibe-ic-plugin/v1",
  "registry_id": "<registry hostname>",
  "trust_tiers_supported": [
    "core", "vendor-verified", "community-trusted",
    "community", "experimental", "quarantined"
  ],
  "max_bundle_bytes": 134217728
}
```

### 2.2 Search

Query parameters (all optional):

| Param | Type | Notes |
|-------|------|-------|
| `q` | string | free-text search across `plugin_id` + description |
| `namespace` | string | exact namespace filter |
| `layer` | enum | `exp` / `ip` / `eda` |
| `min_trust_tier` | enum | exclude tiers below this floor |
| `sort` | enum | `downloads` (default) / `updated` / `name` / `trust` |
| `limit` | int | default 20, max 100 |
| `cursor` | string | pagination cursor |

Response shape:

```json
{
  "next_cursor": null,
  "sort": "downloads",
  "results": [
    {
      "namespace": "<ns>",
      "plugin_id": "<pid>",
      "latest_version": "<semver>",
      "layer": "exp | ip | eda",
      "trust_tier": "<tier>",
      "downloads_30d": 142,
      "used_by_ic_count": 7,
      "last_updated": "<ISO 8601>",
      "publisher_org": "<org>",
      "description": "<one-line>"
    }
  ]
}
```

### 2.3 Single-version metadata

```json
{
  "namespace": "<ns>",
  "plugin_id": "<pid>",
  "version": "<semver>",
  "manifest": { /* full plugin.yaml as JSON */ },
  "trust_tier": "<tier>",
  "trust_tier_history": [
    {"tier": "experimental", "at": "<ISO 8601>"},
    {"tier": "community",     "at": "<ISO 8601>"}
  ],
  "signature": {
    "key_id": "<hex>",
    "publisher_pubkey_url": "/api/v1/keys/<key_id>"
  },
  "bundle": {
    "url":  "/api/v1/plugins/<ns>/<pid>/<ver>/bundle",
    "size_bytes": 4096,
    "sha256": "<hex>"
  },
  "uploaded_at": "<ISO 8601>",
  "yanked": false,
  "yank_reason": null
}
```

### 2.4 Publish

`POST /api/v1/plugins/{ns}/{pid}` requires
`Authorization: Bearer <token>` (token must own the namespace) and
`multipart/form-data` with two parts:

- `bundle`: the `.tgz` (server reads the manifest from inside)
- `signature`: the detached `.tgz.sig` text

Server actions on POST:

1. Parse manifest from bundle. Reject if invalid (HTTP 400).
2. Verify token owns `manifest.namespace` (HTTP 403 if not).
3. Verify `manifest.plugin_id` matches the URL `pid` (HTTP 400).
4. Verify `(ns, pid, version)` is unique (HTTP 409).
5. Verify signature `key_id` matches a registered publisher pubkey
   (HTTP 400).
6. Store bundle + sig + manifest. Initial `trust_tier =
   experimental`. Returns 201 with the same shape as § 2.3.

Versions are immutable. The registry never overwrites an existing
`(ns, pid, ver)` tuple.

### 2.5 Yank

`DELETE /api/v1/plugins/{ns}/{pid}/{ver}` sets `yanked=true` and
records `yank_reason` from the request body. Yanked versions are
still downloadable so existing installs continue to work, but they
are excluded from search and refused by `install` unless the client
passes `--allow-yanked`.

---

## 3. Auth

Three identities are involved:

| Identity | How obtained | Stored where |
|----------|--------------|--------------|
| Namespace secret | Issued by the registry when an org registers a namespace | publisher's secret store |
| Bearer token | `POST /auth/token` with namespace + secret (or device-code flow) | client `~/.vibe-ic/auth.json` (chmod 600) |
| Publisher pubkey | Registered via `POST /api/v1/keys` | server-side pubkey table |

`~/.vibe-ic/auth.json` shape:

```json
{
  "registry_url": "<registry url>",
  "namespace_tokens": {
    "<ns>": {
      "token": "<bearer>",
      "expires": "<ISO 8601>"
    }
  }
}
```

Token TTL is at least 30 days. `DELETE /api/v1/auth/token` with the
bearer header revokes the current token.

---

## 4. Errors

All errors return JSON: `{"error": "<code>", "message": "<text>"}`.

| HTTP | Code | When |
|------|------|------|
| 400  | `bad_manifest`     | manifest fails validation |
| 400  | `bad_signature`    | signature key_id mismatch or bad blob |
| 401  | `unauth`           | missing or expired token |
| 403  | `forbidden`        | token does not own namespace |
| 404  | `not_found`        | plugin or version does not exist |
| 409  | `version_exists`   | `(ns, pid, ver)` already published |
| 413  | `bundle_too_large` | bundle exceeds `max_bundle_bytes` |
| 429  | `rate_limited`     | quota hit; `Retry-After` header set |
| 503  | `unavailable`      | server in maintenance |

---

## 5. Rate limits

Defaults the reference server applies (registries are free to choose
their own):

| Caller | Limit |
|--------|-------|
| Per IP (anonymous) | 60 req/min, 1000 req/hour |
| Per token (publisher) | 600 req/min, no hourly cap |
| Per namespace (publish) | 10 publishes/min |

Headers on every 200 / 4xx response:

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 23
X-RateLimit-Reset: 1714137600
```

---

## 6. Trust-tier recompute

Trust tier is **never set by the publisher**. The registry recomputes
it from server-side evidence:

| Condition | Resulting tier |
|-----------|----------------|
| Pattern-effectiveness verdict HARMFUL on ≥ 3 ICs | `quarantined` |
| Less than 3 ICs of evidence (new plugin) | `experimental` |
| ≥ 3 ICs evidence + verdict NEUTRAL/HELPFUL + < 10 successful uses | `community` |
| ≥ 10 successful uses + verdict HELPFUL + zero HARMFUL ever | `community-trusted` |
| Identity-verified org + signing-key audit pass | `vendor-verified` |
| Ships with the platform's core | `core` |

Tier transitions are appended to `trust_tier_history` on the version
record. Publishers can dispute a HARMFUL verdict; one re-evaluation
round is granted with new sample data.

The reference server runs the recompute on a timer (cron or systemd).

---

## 7. Telemetry

The CLI sends anonymous aggregate telemetry by default:

- Plugin install events (no IP, no user, no IC content)
- Pattern-effectiveness verdicts at the class level (no IC names)

Opt out with `vibe-ic plugin telemetry off` or
`VIBE_IC_TELEMETRY=0`.

The registry server logs only what was sent — no traffic analysis,
no fingerprinting.

---

## 8. Out of scope

- Per-call billing rail
- Encrypted-IP artifact key fetch (separate `/ip-keys/...` namespace
  defined in `encrypted_ip_spec.md`)
- Web UI (a separate front-end project, not part of this API)
- Mirror federation between registries
- Sigstore-style transparency log

The OpenAPI definition for this protocol is at
`docs/design/vibeic_registry_openapi.yaml`.
