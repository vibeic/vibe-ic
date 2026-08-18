# Security Policy

## Supported versions

Vibe-IC is in initial public release. Until 1.0.0, only the **latest
minor version** is supported with security fixes. Patch fixes are
backported to the current minor only.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, email **reyer.chu@vibeic.ai** with:

- A description of the issue
- Steps to reproduce (a minimal test case is ideal)
- The affected component (`mcp-eda`, plugin skill name, …)
- Your assessment of impact (RCE, data exposure, supply chain, etc.)
- Whether you'd like public credit when the fix ships

We will:

- Acknowledge receipt within **3 working days**
- Provide an initial assessment within **7 working days**
- Coordinate a fix and disclosure timeline, typically **30-90 days**
  depending on severity and complexity
- Credit you in the changelog and the release notes (unless you opt
  out)

## Scope

In scope:

- Code execution / privilege escalation via MCP tool invocation
- Path traversal in artefact handling (`mcp-eda`)
- Unsafe deserialization / template injection in any skill or
  program
- Secrets leak through logs, error messages, or generated artefacts
- Bypass of the chip-AGNOSTIC source guard that would let private
  data leak into a public commit
- Dependency vulnerabilities with a working exploit path

Out of scope:

- Bugs in `hpretl/iic-osic-tools` (upstream — report there)
- Bugs in PDKs (upstream — report to SkyWater, GF, IHP)
- Theoretical issues without a reproducible attack scenario
- Issues that require local-host access the attacker already has
  (we assume the host is trusted)

## Severity guidance

| Severity | Example                                                           | Target fix window |
|----------|-------------------------------------------------------------------|-------------------|
| Critical | Remote code execution, secrets leak in CI artefacts               | 7 days            |
| High     | Privilege escalation, sandbox escape from a skill                 | 14 days           |
| Medium   | Local DoS, log injection, unsafe defaults                         | 30 days           |
| Low      | Hardening suggestions, defense-in-depth gaps                      | next minor        |

## PGP

If you require encrypted communication, a public key is available at:
<https://github.com/vibeic/.well-known/security.asc> (forthcoming —
email plaintext is currently the only channel).

## Acknowledgements

Past security reporters credited in [SECURITY_HALL_OF_FAME.md](.github/SECURITY_HALL_OF_FAME.md)
(created on first report).
