#!/usr/bin/env python3
"""Host-only NDA guards for the exact squash that hermetic landing will judge.

No private detector input, path, matched text, or digest enters this receipt.
The child receives only public source/range identities and measured return
codes. The trusted runner binds both PASS units to the stopped B2 completion.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from landing_record_primitives import _git, _git_env, _object_format, _commit_and_tree

PROGRAMS = "vibe-ic-marketplace/plugins/vibe-ic/programs"
GUARDS = ("commit_msg_nda_check.py", "nda_diff_scan_check.py")
SOURCE = GUARDS + ("_commercial_pdk.py",)
OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
KIND = "vibeic.trusted-host-nda/v1"
ROLES = frozenset({"foundry_product", "sku_full", "sku_prefix",
                   "foundry_brand1", "foundry_brand2", "foundry_brand3",
                   "ip_vendor", "ip_part"})


class Refusal(Exception):
    pass


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode()


def _private_source_is_well_formed(authority: Path, forbidden_roots: tuple[Path, ...]) -> dict[str, str]:
    # The BASE resolver accepts partial sources and silently ignores malformed
    # ones for public installs. Landing must validate the *effective* set that
    # the BASE guard will actually use, including its default HOME config.
    def pairs(rows: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("duplicate private JSON key")
            result[key] = value
        return result

    def valid_tokens(value: object) -> bool:
        return (isinstance(value, dict) and bool(value)
                and set(value) <= ROLES
                and all(isinstance(v, str) and bool(v.strip())
                        for v in value.values())
                and len({v.strip() for v in value.values()}) == len(value))

    raw = os.environ.get("VIBEIC_NDA_TOKENS")
    if raw is not None:
        try:
            doc = json.loads(raw, object_pairs_hook=pairs)
        except (ValueError, TypeError) as exc:
            raise Refusal("detector input is malformed") from exc
        if not valid_tokens(doc):
            raise Refusal("detector input is malformed")
    configured = os.environ.get("VIBEIC_PRIVATE_CONFIG")
    config_path = (Path(configured) if configured is not None else
                   Path.home() / ".config/vibeic/commercial_pdk.json")
    if configured is not None or config_path.exists() or config_path.is_symlink():
        try:
            if any(config_path.resolve().is_relative_to(root.resolve()) for root in forbidden_roots):
                raise Refusal("detector configuration must remain outside mounted inputs")
            st = config_path.lstat()
            if not stat.S_ISREG(st.st_mode) or config_path.is_symlink():
                raise Refusal("detector configuration is unavailable")
            doc = json.loads(config_path.read_text(encoding="utf-8"),
                             object_pairs_hook=pairs)
        except (OSError, ValueError, UnicodeError) as exc:
            raise Refusal("detector configuration is unavailable") from exc
        if not isinstance(doc, dict):
            raise Refusal("detector configuration is malformed")
        if "nda_tokens" in doc and not valid_tokens(doc["nda_tokens"]):
            raise Refusal("detector configuration is malformed")
    spec = importlib.util.spec_from_file_location(
        "_trusted_base_nda_resolver", authority / "_commercial_pdk.py")
    if spec is None or spec.loader is None:
        raise Refusal("BASE NDA resolver is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if set(module.NDA_ROLES) != ROLES:
        raise Refusal("BASE NDA role population differs")
    effective = module._nda_token_map()
    if (set(effective) != ROLES
            or len({v.strip() for v in effective.values()}) != len(ROLES)):
        raise Refusal("effective detector set is incomplete or ambiguous")
    values = list(effective.values())
    def normalized(value: str) -> str:
        return re.sub(r"[\s_\-]+", " ", value).strip().casefold()

    for index, left in enumerate(values):
        for right in values[index + 1:]:
            left_matches_right = re.fullmatch(
                module._token_alt(left), right, flags=re.IGNORECASE)
            right_matches_left = re.fullmatch(
                module._token_alt(right), left, flags=re.IGNORECASE)
            if (normalized(left) == normalized(right)
                    or (left_matches_right and right_matches_left)):
                raise Refusal("effective detector roles are regex-equivalent")
    scanner = module.nda_source_regex()
    for role in module.NDA_ROLES:
        value = effective[role]
        match = scanner.search(value)
        if (match is None or match.span() != (0, len(value))
                or module.nda_role_of(match.group(0)) != role):
            raise Refusal("BASE scanner cannot identify one detector role")
    return effective


def _identity(repo: Path, base: str, head: str) -> tuple[str, str, str]:
    _, n = _object_format(repo)
    b, _ = _commit_and_tree(repo, base, n, "base")
    h, tree = _commit_and_tree(repo, head, n, "verified")
    ancestry = _git(repo, ["merge-base", "--is-ancestor", b, h], binary=True)
    # _git raises on nonzero. A zero exit has empty bytes.
    if b == h or ancestry != b"":
        raise Refusal("verified range is empty or not anchored")
    return b, h, tree


def run(repo: Path, base: str, head: str, *, forbidden_roots: tuple[Path, ...] = ()) -> dict:
    base, head, tree = _identity(repo, base, head)
    source_hashes = {}
    results = []
    with tempfile.TemporaryDirectory(prefix="vibeic-host-nda-") as name:
        authority = Path(name)
        for source in SOURCE:
            raw = _git(repo, ["show", f"{base}:{PROGRAMS}/{source}"], binary=True)
            assert isinstance(raw, bytes)
            source_hashes[source] = hashlib.sha256(raw).hexdigest()
            (authority / source).write_bytes(raw)
        effective = _private_source_is_well_formed(authority, (repo, *forbidden_roots))
        # Freeze the one validated BASE-resolved map for both trusted host
        # guards. An operator config rotation cannot change the question
        # between validation and either scan. Nothing below enters Docker.
        empty_config = authority / "empty-private-config.json"
        empty_config.write_text("{}\n", encoding="utf-8")
        empty_config.chmod(0o600)
        env = _git_env()
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(authority),
                    "VIBEIC_NDA_TOKENS": json.dumps(effective, sort_keys=True),
                    "VIBEIC_PRIVATE_CONFIG": str(empty_config)})
        for source in GUARDS:
            proc = subprocess.run(
                [sys.executable, "-B", str(authority / source),
                 "--repo", str(repo), "--rev-range", f"{base}..{head}"],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=120)
            # Discard streams at the OS boundary. Even a broken guard cannot
            # copy private text into a parent log or public receipt.
            results.append({"guard": source, "rc": proc.returncode})
    payload = {"base": base, "head": head, "tree": tree,
               "range": f"{base}..{head}", "source_sha256": source_hashes,
               "guards": results}
    return {"kind": KIND, "payload": payload}


def _load_record(path: Path) -> dict:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or path.is_symlink() or st.st_nlink != 1:
        raise Refusal("host receipt is not a regular file")
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise Refusal("host receipt lacks its canonical final newline")
    return public_result(raw.decode().removesuffix("\n"))


def public_result(raw: str) -> dict:
    if not isinstance(raw, str) or len(raw) > 16384:
        raise Refusal("host result is not bounded")
    doc = json.loads(raw)
    raw = (raw + "\n").encode()
    if raw != _canonical(doc) or not isinstance(doc, dict) or set(doc) != {"kind", "payload"}:
        raise Refusal("host receipt is not canonical")
    if doc["kind"] != KIND:
        raise Refusal("host receipt kind differs")
    p = doc["payload"]
    if not isinstance(p, dict) or set(p) != {"base", "head", "tree", "range", "source_sha256", "guards"}:
        raise Refusal("host receipt schema differs")
    if any(not isinstance(p[k], str) or OID.fullmatch(p[k]) is None
           for k in ("base", "head", "tree")):
        raise Refusal("host receipt identity is malformed")
    if p["range"] != f'{p["base"]}..{p["head"]}':
        raise Refusal("host receipt range differs")
    hashes = p["source_sha256"]
    if (not isinstance(hashes, dict) or set(hashes) != set(SOURCE)
            or any(not isinstance(v, str) or HEX.fullmatch(v) is None
                   for v in hashes.values())):
        raise Refusal("host source identity is malformed")
    if (p["guards"] != [{"guard": g, "rc": 0} for g in GUARDS]
            or any(type(row["rc"]) is not int for row in p["guards"])):
        raise Refusal("host NDA guards did not both pass")
    return p


def verify_unit(raw: str, repo: Path, base: str, guard: str) -> None:
    p = public_result(raw)
    # The subject is a rootless, read-only mount owned by the parent UID.
    # Parent-only primitives deliberately scrub GIT_* (including the runner's
    # safe.directory environment). Bind only this explicit subject for reads;
    # do not inherit ambient Git configuration or broaden to '*'.
    def git_read(args: list[str]) -> bytes:
        env = _git_env()
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        proc = subprocess.run(
            ["git", "-c", f"safe.directory={repo.resolve()}", "-C", str(repo), *args],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=False)
        if proc.returncode:
            raise Refusal("committed subject cannot be read")
        return proc.stdout
    actual = tuple(git_read(["rev-parse", value]).decode("ascii").strip()
                   for value in (base + "^{commit}", "HEAD^{commit}", "HEAD^{tree}"))
    if guard not in GUARDS or actual != (p["base"], p["head"], p["tree"]):
        raise Refusal("host NDA result is not for this committed subject")
    for source in SOURCE:
        data = git_read(["show", f"{base}:{PROGRAMS}/{source}"])
        if hashlib.sha256(data).hexdigest() != p["source_sha256"][source]:
            raise Refusal("host NDA source differs from BASE")


def verify_completion(p: dict, repo: Path, path: Path, arm: str) -> None:
    spec = importlib.util.spec_from_file_location(
        "_trusted_nda_completion", Path(__file__).with_name("landing_completion_record.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    completion = module.strict_load_record(path)["payload"]
    expected_head = p["base"] if arm == "A2" else p["head"]
    if (completion["arm"] != arm or completion["base"] != p["base"]
            or completion["head"] != expected_head
            or completion["tree"] != _commit_and_tree(repo, expected_head, len(p["base"]), arm)[1]):
        raise Refusal("host NDA result and completion identity differ")
    for label in ("cheap:nda-messages", "cheap:nda-content"):
        rows = [row for row in completion["gates"] if row["label"] == label]
        expected_state = "SKIP" if arm == "A2" else "PASS"
        if len(rows) != 1 or rows[0]["state"] != expected_state or rows[0]["returncode"] != 0:
            raise Refusal("NDA completion does not contain the measured host result")


def verify(path: Path, repo: Path, base: str, head: str, tree: str,
           a2: Path, b2: Path) -> None:
    p = _load_record(path)
    actual = _identity(repo, base, head)
    if actual != (p["base"], p["head"], p["tree"]) or actual != (base, head, tree):
        raise Refusal("host NDA receipt is not for the verified squash")
    for source in SOURCE:
        raw = _git(repo, ["show", f"{base}:{PROGRAMS}/{source}"], binary=True)
        assert isinstance(raw, bytes)
        if p["source_sha256"][source] != hashlib.sha256(raw).hexdigest():
            raise Refusal("host NDA guard source differs from BASE")
    spec = importlib.util.spec_from_file_location(
        "_trusted_landing_completion", Path(__file__).with_name("landing_completion_record.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for arm, path, expected in (("A2", a2, base), ("B2", b2, head)):
        try:
            completion = module.strict_load_record(path)["payload"]
        except module.Refusal as exc:
            raise Refusal("landing completion is malformed") from exc
        if (completion["arm"] != arm or completion["base"] != base
                or completion["head"] != expected
                or completion["tree"] != _commit_and_tree(repo, expected, len(base), arm)[1]):
            raise Refusal("host NDA receipt and landing completion differ")
        for label in ("cheap:nda-messages", "cheap:nda-content"):
            rows = [r for r in completion["gates"] if r["label"] == label]
            if len(rows) != 1 or rows[0]["state"] != ("SKIP" if arm == "A2" else "PASS") or rows[0]["returncode"] != 0:
                raise Refusal("child NDA unit disagrees with host measurement")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    unit = sub.add_parser("check-unit")
    unit.add_argument("--repo", type=Path, required=True)
    unit.add_argument("--base", required=True)
    unit.add_argument("--guard", choices=GUARDS, required=True)
    for mode in ("run", "verify"):
        command = sub.add_parser(mode)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--base", required=True)
        command.add_argument("--head", required=True)
        command.add_argument("--record", type=Path, required=True)
        if mode == "verify":
            command.add_argument("--tree", required=True)
            command.add_argument("--a2", type=Path, required=True)
            command.add_argument("--b2", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "check-unit":
            if (os.environ.get("VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY") != "1"
                    or os.environ.get("GATEKEEPER_NO_STAMP") != "1"
                    or os.environ.get("GATEKEEPER_RUNTIME_ROOT") != "/runtime"):
                raise Refusal("host result is restricted to an unstamped hermetic arm")
            verify_unit(os.environ.get("VIBEIC_NDA_HOST_RESULT", ""),
                        args.repo, args.base, args.guard)
            print("PASS: trusted host NDA guard, exact committed range")
        elif args.mode == "run":
            doc = run(args.repo, args.base, args.head)
            fd = os.open(args.record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                data = memoryview(_canonical(doc))
                while data:
                    n = os.write(fd, data)
                    if n <= 0:
                        raise OSError("short NDA receipt write")
                    data = data[n:]
                os.fsync(fd)
            finally:
                os.close(fd)
            states = [row["rc"] for row in doc["payload"]["guards"]]
            if any(rc not in {0, 1} for rc in states):
                raise Refusal("trusted NDA guard was not measured")
            if any(rc == 1 for rc in states):
                print("[REFUSE] trusted host NDA guard found forbidden content",
                      file=sys.stderr)
                return 1
        else:
            verify(args.record, args.repo, args.base, args.head, args.tree,
                   args.a2, args.b2)
    except (OSError, ValueError, Refusal, subprocess.SubprocessError) as exc:
        # Never include an exception message: git/scanner failures can contain
        # detector text or a private pathname.
        print("[NORECORD] trusted host NDA boundary refused", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
