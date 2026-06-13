"""url_oracle_guard — RTL-as-oracle prohibition for cited-URL handling.

Ships in v1.6.95 as scaffolding for the Capability 2 / 3 "cited-standards
resolver" work tracked in GitHub issue #27. The fetcher itself is deferred
(needs network access + per-standard PDF extractors), but these helpers
ship now so the deeper README parser (Capability 1) can already drop any
URL that resolves to the project's own RTL repo BEFORE adding it to
``L1.references``.

The benchmark protocol forbids the spec-to-RTL flow from ever using the
IP's own RTL / testbench as a data source — that would be the oracle the
benchmark is set up to detect. Public standards (NIST / IETF / JEDEC /
IEEE / SD-A / PCI-SIG / SATA-IO / USB-IF / ISO / OpenCores) are
allow-listed; everything else is treated as neutral (caller decides).
"""
from __future__ import annotations

import re
from typing import Optional, Tuple
from urllib.parse import urlparse


# Public-standard hosts whose URLs are always safe to reference / fetch.
# Adding a host here is a deliberate policy decision; do not expand
# casually. (Mirror domains / CDN aliases are intentionally NOT folded
# in — keep the allow-list literal so an audit grep is a one-shot.)
PUBLIC_STANDARD_HOSTS: Tuple[str, ...] = (
    "csrc.nist.gov", "www.nist.gov", "nvlpubs.nist.gov",
    "www.rfc-editor.org", "datatracker.ietf.org",
    "www.jedec.org",
    "standards.ieee.org", "ieeexplore.ieee.org",
    "www.sdcard.org",
    "pcisig.com",
    "sata-io.org",
    "usb.org", "www.usb.org",
    "www.iso.org",
    "opencores.org",
)


# Markdown badge / link forms that commonly identify the project's own
# GitHub repo. Captures group(1) = "org", group(2) = "repo".
#
# Examples (each must match one of these patterns):
#   [![Build](badge)](https://github.com/myorg/myrepo/actions)
#   [![License](badge)](https://github.com/myorg/myrepo)
#   <https://github.com/myorg/myrepo>
#   [Source](https://github.com/myorg/myrepo)
#   https://github.com/myorg/myrepo.git
_GITHUB_REPO_URL_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9][A-Za-z0-9._-]*)/"
    r"([A-Za-z0-9][A-Za-z0-9._-]*?)(?:\.git)?(?=[/)>\s]|$)",
    re.IGNORECASE,
)

# Repo-path tokens that are NOT a real <repo> name (they're sub-pages
# under github.com/<org>/<sub>). Filters out e.g. github.com/sponsors/<x>
# or github.com/orgs/<x> from being treated as repos.
_GITHUB_RESERVED_OWNERS = frozenset({
    "orgs", "sponsors", "marketplace", "topics", "collections",
    "trending", "events", "settings", "notifications", "pulls",
    "issues", "search", "explore", "new", "join", "login", "logout",
    "site", "about", "features", "pricing", "enterprise",
})


def parse_project_self_repo(readme_text: str) -> Optional[str]:
    """Return ``"org/repo"`` if README badges or links identify the
    project's own GitHub repo, else None.

    Heuristic: walk all github.com URLs in the README, drop reserved
    owners, and pick the most-frequently-mentioned ``org/repo`` pair.
    Ties broken by first-occurrence order (badges typically appear at
    the top of the README and identify the project itself).

    The return value feeds :func:`url_allowed` so any later URL that
    points back into the project's own repo can be dropped before being
    added to ``L1.references``.
    """
    if not readme_text:
        return None
    counts: dict[str, int] = {}
    order: list[str] = []
    for m in _GITHUB_REPO_URL_RE.finditer(readme_text):
        org = m.group(1)
        repo = m.group(2)
        if not org or not repo:
            continue
        if org.lower() in _GITHUB_RESERVED_OWNERS:
            continue
        # Drop common per-action suffixes like "actions" / "issues" /
        # "blob" — those are paths under the repo, not repo names. The
        # capture stops at "/" so they should not appear here, but
        # belt-and-braces.
        if repo.lower() in {"actions", "blob", "tree", "wiki",
                            "releases", "pulls", "issues"}:
            continue
        key = f"{org}/{repo}"
        if key not in counts:
            counts[key] = 0
            order.append(key)
        counts[key] += 1
    if not counts:
        return None
    # Prefer the most-mentioned; break ties by first occurrence.
    best = max(order, key=lambda k: (counts[k], -order.index(k)))
    return best


def is_self_repo_url(url: str, self_repo: Optional[str]) -> bool:
    """True iff ``url`` points into ``github.com/<self_repo>/`` (or the
    bare repo URL itself). Sub-paths (blob / tree / actions / raw) all
    count.

    Returns False when ``self_repo`` is None — the caller doesn't know
    what the project's own repo is, so the deny rule cannot fire.
    """
    if not url or not self_repo:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.netloc.lower() not in {"github.com", "www.github.com",
                                     "raw.githubusercontent.com"}:
        return False
    org_repo = self_repo.lower()
    path = parsed.path.lower().lstrip("/")
    # raw.githubusercontent.com/<org>/<repo>/<branch>/<path>
    # github.com/<org>/<repo>(/...)
    if path == org_repo or path.startswith(org_repo + "/") \
            or path.startswith(org_repo + ".git"):
        return True
    return False


def is_public_standard_url(url: str) -> bool:
    """True iff the URL's host is in :data:`PUBLIC_STANDARD_HOSTS`."""
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return host in PUBLIC_STANDARD_HOSTS


def url_allowed(url: str, self_repo: Optional[str]) -> Tuple[bool, str]:
    """Return ``(allowed, reason)`` for whether ``url`` may be added to
    L1.references / fetched by the cited-standards resolver.

    Reasons:
      * ``"self_repo_denied"`` — URL points into the project's own repo;
        denied per the RTL-as-oracle prohibition.
      * ``"public_standard_allowed"`` — URL is a known public standard
        host (NIST / IETF / JEDEC / IEEE / SD-A / PCI-SIG / SATA-IO /
        USB-IF / ISO / OpenCores).
      * ``"unknown_host_neutral"`` — URL is neither self-repo nor a
        known public-standard host. Returned as ``(True, ...)``: caller
        decides whether to keep or drop. Policy choice: do NOT block
        unknown hosts globally, only the RTL-oracle (self-repo) class.
        This lets the Capability 1 README parser still emit vendor /
        consultancy / blog links (the AES README cites
        "Assured Security Consultants") for human review without
        treating every third-party URL as suspicious. Capability 2
        (the actual fetcher) will tighten this when it lands by
        whitelisting only PUBLIC_STANDARD_HOSTS for fetch.
    """
    if is_self_repo_url(url, self_repo):
        return (False, "self_repo_denied")
    if is_public_standard_url(url):
        return (True, "public_standard_allowed")
    return (True, "unknown_host_neutral")
