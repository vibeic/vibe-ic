# Vibe-IC v0.95 — Encrypted IP Artifacts

**Status**: shipped 2026-04-26 (`plugin_crypto.py` + `vibe-ic plugin ip` +
`install --ip-key`).
**Scope**: how an IC vendor ships proprietary RTL / GDS / lib through
the v0.85 plugin format without exposing the artifact to the registry
or to anyone except authorized customers.
**Prereqs**: v0.85 plugin foundation, v0.90 registry protocol.

---

## 0. Goal in one paragraph

A vendor publishes a plugin whose `ip.artifacts.<name>` files are
**encrypted on disk** before pack. The bundle uploaded to vibeic.ai
contains opaque ciphertext. Customers fetch the bundle the normal way,
then pass `--ip-key KEYFILE` at install time; the install path detects
encrypted artifacts and decrypts them in place. Vendors distribute
keys to authorized customers out-of-band (or via a future
`/api/v1/ip-keys/...` endpoint, deferred from this release).

---

## 1. Crypto choice

- **Algorithm**: AES-256-GCM (AEAD; integrity + confidentiality in one).
- **Key size**: 32 bytes (256-bit).
- **Nonce**: 12 bytes (96-bit), random per file.
- **Library**: stdlib via `cryptography.hazmat.primitives.ciphers.aead`
  (already a dep of `plugin_sign.py`).

GCM tag verification is the integrity gate: a corrupt or wrong-key blob
fails decrypt with `CryptoError("AES-GCM verify failed")`. No silent
truncation, no partial output.

---

## 2. On-disk blob format

```
+--------+------+--------+----------------------+
| MAGIC  | ALG  | NONCE  | CIPHERTEXT || TAG    |
| 8 B    | 1 B  | 12 B   | variable + 16 B GCM  |
+--------+------+--------+----------------------+

MAGIC = b"VIBEIC95"
ALG   = 0x01  (AES-256-GCM)
```

`is_encrypted(path)` checks the first 8 bytes. AAD = `MAGIC` (binds the
header to the encrypted payload). Future algorithms reserve `ALG ∈ {0x02..}`.

---

## 3. Key fingerprint

`fingerprint(key) = sha256(key)[:16]` (16 hex chars).

Used as:
- Manifest field hint for which key decrypts which bundle (informational
  only — actual key never appears in manifest)
- Future: registry endpoint path `/api/v1/ip-keys/{fingerprint}`

Not a security primitive — just an identifier. Fingerprint collisions
have probability 2^-64; sufficient for human-readable lookups.

---

## 4. CLI surface (under `vibe-ic plugin ip`)

```bash
vibe-ic plugin ip keygen --out KEYFILE
    # writes 32 random bytes; chmod 600

vibe-ic plugin ip encrypt FILE --key KEYFILE [--out FILE.enc]
    # writes VIBEIC95 blob; default output adds .enc suffix

vibe-ic plugin ip decrypt FILE.enc --key KEYFILE [--out FILE]
    # verifies tag; refuses on mismatch

vibe-ic plugin ip fingerprint --key KEYFILE
    # prints 16-hex fingerprint
```

Install hook:
```bash
vibe-ic plugin install vendor/proprietary-ip --ip-key customer-key.bin
```
After extracting the bundle, install walks the install dir; any file
matching the `VIBEIC95` magic is auto-decrypted. Wrong key or tampered
ciphertext rolls back the install (cleanup).

Filename convention:
- `foo.v.enc` → `foo.v` after decrypt (`.enc` stripped)
- `foo.bin`   → `foo.bin.dec` after decrypt (no convention to strip)

---

## 5. Vendor publish workflow

```bash
# 1. Generate per-customer (or per-cohort) AES-256 key
vibe-ic plugin ip keygen --out keys/cust_acme.bin

# 2. Encrypt sensitive RTL
vibe-ic plugin ip encrypt rtl/secret.v \
    --key keys/cust_acme.bin \
    --out src/files/secret.v.enc

# 3. plugin.yaml lists the encrypted artifact
cat plugin.yaml
  # ip:
  #   deliverable_kind: soft-ip
  #   metadata: ./ip_metadata.yaml
  #   artifacts:
  #     rtl: ./files/secret.v.enc

# 4. Pack + sign + publish like any other plugin
vibe-ic plugin pack ./src --out my-ip-1.0.0.tgz --sign signing-key.pem
vibe-ic plugin publish my-ip-1.0.0.tgz

# 5. Email keys/cust_acme.bin to ACME's procurement (or use a real key
#    distribution channel — see § 7).
```

The bundle on the registry contains only ciphertext. Customers without
the key can install but cannot use the encrypted artifacts.

---

## 6. Customer install workflow

```bash
# 1. (Once) Install the plugin (downloads + extracts; encrypted files
#    stay encrypted until step 2)
vibe-ic plugin install vendor/proprietary-ip
    # prints: installed: vendor/proprietary-ip@1.0.0
    # files/secret.v.enc is on disk but cannot be used

# 2. Re-install with key (or run a separate decrypt step)
vibe-ic plugin install vendor/proprietary-ip --ip-key cust_acme.bin
    # prints: installed; decrypted 1 encrypted artifact(s) using --ip-key
    # files/secret.v is now usable
```

Wrong key:
```
$ vibe-ic plugin install vendor/proprietary-ip --ip-key wrong.bin
decrypt failed for .../files/secret.v.enc: AES-GCM verify failed
# → install rolls back the entire bundle dir
```

---

## 7. Key distribution (out-of-scope for v0.95)

For v0.95, vendors distribute `cust_acme.bin` via whatever channel they
already use today (GPG-encrypted email, secure portal, on-site key
exchange, etc.). The platform does not handle this.

For v0.97 (planned), the registry will optionally host:
```
GET /api/v1/ip-keys/{customer_id}/{fingerprint}
Authorization: Bearer <customer-token>
```
This returns the AES-256 key only after the registry verifies the
customer has an active entitlement for that plugin. Vendors enroll
customers via a sibling `/api/v1/ip-entitlements/...` endpoint.

The on-disk blob format and `--ip-key` CLI surface stay unchanged when
v0.97 ships — customer just runs `vibe-ic plugin ip key fetch` to
populate `~/.vibe-ic/ip_keys/<fingerprint>.bin` automatically.

---

## 8. Out-of-scope for v0.95 (explicit)

- HSM / TPM-backed keys. Today keys are 32 bytes on disk under
  customer's `chmod 600` discretion. v1.x can add hardware backing.
- Per-file keys with manifest fingerprint lookup. Today the same key
  decrypts every encrypted artifact in a bundle. v0.97 considers
  per-artifact rotation.
- Automatic key fetch from registry. § 7.
- Forward-secrecy / ephemeral keys. Vendors rotate per customer cohort
  by re-encrypting + re-publishing.

---

## 9. Test surface

`tests/test_plugin_crypto.py` (14 tests):
- `generate_key` / `fingerprint` shape
- round-trip encrypt → decrypt
- wrong-key, tampered, bad-magic, wrong-key-length all raise
- `is_encrypted` distinguishes plain from encrypted
- CLI `ip keygen` / `encrypt` / `decrypt` / `fingerprint` round-trip
- `install --ip-key` auto-decrypts a real soft-IP plugin
- `install --ip-key WRONG` rolls back the install dir

`acceptance_gate_full.py` step 7 + 10 exercises this end-to-end against
the live registry + ed25519-signed bundle path.
