"""The FICTIONAL NDA token set the plugin test suite runs against — DERIVED,
never written down.

WHY IT EXISTS. Until v1.12.49 these tests reached the real NDA tokens by
decoding `_commercial_pdk._ENCODED_NDA`, which worked only because the secret
shipped inside the plugin. That is the exposure the token move removes, so the
suite can no longer be built on it — and should never have been: a test of the
NDA MACHINERY has no business depending on the machinery's secret.

WHY IT IS DERIVED AND NOT A LITERAL TABLE. The first version of this file WAS a
literal table of eight invented strings, and `source_chip_agnostic_check`'s NDA
panel promptly failed the tree on it — correctly. That panel's contract is that
a literal NDA token appears NOWHERE under the plugin tree, with "NO allowlist of
any kind (no file-level, no line-level)", and a fixture is not entitled to an
exemption the contract says does not exist. So the values are computed from a
fixed seed at import: what is tracked here is a generator, and the panel finds
nothing to flag because there is nothing to find.

The eight values are deterministic, stable across processes (which is what lets
`conftest` publish them through `VIBEIC_NDA_TOKENS` and the gate subprocesses
read the same set), and matched in SHAPE to the real roles so every branch the
guards have is genuinely exercised — a one-word product, a long SKU, a short
SKU prefix that is a STRICT PREFIX of it, three brands of which one is TWO WORDS
(the `[\\s_\\-]+` separator-insensitive path), a vendor, and a long part number.
Hash-derived letters resemble no real foundry, IP vendor, process or part.
"""
from __future__ import annotations

import hashlib

_SEED = "vibe-ic/fictional-nda-fixture/v1"
_ALPHA = "bcdfghjklmnpqrstvwxz"   # consonant-ish: never spells a real word
_DIGIT = "0123456789"


def _stream(tag: str) -> "list[int]":
    """A long deterministic byte stream for `tag`."""
    out: list[int] = []
    block = 0
    while len(out) < 64:
        out.extend(hashlib.sha256(
            f"{_SEED}|{tag}|{block}".encode()).digest())
        block += 1
    return out


def _shape(tag: str, spec: str) -> str:
    """Build a string from `spec`: 'a' -> letter, 'd' -> digit, ' ' -> space."""
    src = _stream(tag)
    out: list[str] = []
    i = 0
    for slot in spec:
        if slot == " ":
            out.append(" ")
            continue
        pool = _ALPHA if slot == "a" else _DIGIT
        out.append(pool[src[i] % len(pool)])
        i += 1
    return "".join(out)


_SKU_PREFIX = _shape("sku", "aaddaa")                       # 6
_SKU_FULL = _SKU_PREFIX + _shape("sku_tail", "aaadddd")     # 13, prefix-of

FICTIONAL_NDA_TOKENS: dict[str, str] = {
    "foundry_product": _shape("product", "aaaaaaa"),        # 7
    "sku_full": _SKU_FULL,                                  # 13
    "sku_prefix": _SKU_PREFIX,                              # 6
    "foundry_brand1": _shape("brand1", "aaaaaaaaaa"),       # 10
    "foundry_brand2": _shape("brand2", "aaaaa aaaaaa"),     # 12, TWO WORDS
    "foundry_brand3": _shape("brand3", "aaaaaaaa"),         # 8
    "ip_vendor": _shape("vendor", "aaaaaaa"),               # 7
    "ip_part": _shape("part", "aadddd") + _shape("part2", "aaaaaaaaaaa"),  # 17
}

assert FICTIONAL_NDA_TOKENS["sku_full"].startswith(
    FICTIONAL_NDA_TOKENS["sku_prefix"]), "the prefix role must prefix the full SKU"
assert len(set(FICTIONAL_NDA_TOKENS.values())) == 8, "the eight roles must differ"
