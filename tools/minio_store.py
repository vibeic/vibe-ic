#!/usr/bin/env python3
"""
Vibe-IC MinIO Object Storage Client
====================================
S3-compatible storage for IC design artifacts.

Buckets:
    vibeic-gds        — GDSII layout files
    vibeic-designs    — RTL, netlist, DEF intermediates
    vibeic-documents  — AI-generated datasheets/appnotes
    vibeic-fpga       — SOF/bitstream files
    vibeic-collected  — IC documents from manufacturer websites

Usage:
    python3 minio_store.py upload --file design.gds --bucket vibeic-gds --key ic_001/design.gds
    python3 minio_store.py download --bucket vibeic-gds --key ic_001/design.gds --output ./
    python3 minio_store.py list --bucket vibeic-gds
    python3 minio_store.py status
    python3 minio_store.py sync-project --project ic_projects_v2/ic_001_CD4013B/
"""

import os
import sys
import json
import hashlib
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

MINIO_ENDPOINT  = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MC_BIN          = os.environ.get("MC_BIN", os.path.expanduser("~/bin/mc"))

BUCKETS = {
    "gds": "vibeic-gds",
    "designs": "vibeic-designs",
    "documents": "vibeic-documents",
    "fpga": "vibeic-fpga",
    "collected": "vibeic-collected",
}


def mc_cmd(args: list) -> tuple:
    """Run mc command, return (stdout, returncode)."""
    cmd = [MC_BIN] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip(), result.returncode


def file_hash(filepath: str) -> str:
    """SHA-256 hash of file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def upload(filepath: str, bucket: str, key: str = None):
    """Upload file to MinIO."""
    if not os.path.exists(filepath):
        print(f"  ❌ File not found: {filepath}")
        return False

    if key is None:
        key = os.path.basename(filepath)

    fhash = file_hash(filepath)
    size = os.path.getsize(filepath)

    out, rc = mc_cmd(["cp", filepath, f"vibeic/{bucket}/{key}"])
    if rc == 0:
        print(f"  ✅ Uploaded: {bucket}/{key} ({size:,} bytes, hash={fhash})")
        return True
    else:
        print(f"  ❌ Upload failed: {out}")
        return False


def download(bucket: str, key: str, output_dir: str = "."):
    """Download file from MinIO."""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, os.path.basename(key))
    out, rc = mc_cmd(["cp", f"vibeic/{bucket}/{key}", out_path])
    if rc == 0:
        print(f"  ✅ Downloaded: {out_path}")
        return True
    else:
        print(f"  ❌ Download failed: {out}")
        return False


def list_objects(bucket: str, prefix: str = ""):
    """List objects in bucket."""
    path = f"vibeic/{bucket}/{prefix}" if prefix else f"vibeic/{bucket}/"
    out, rc = mc_cmd(["ls", "--recursive", path])
    if rc == 0:
        print(out)
    return out


def status():
    """Show MinIO status."""
    print("=== MinIO Object Storage Status ===\n")
    for name, bucket in BUCKETS.items():
        out, _ = mc_cmd(["du", f"vibeic/{bucket}/"])
        count_out, _ = mc_cmd(["ls", "--recursive", f"vibeic/{bucket}/"])
        count = len(count_out.splitlines()) if count_out else 0
        size = out.split('\t')[0] if out else "0B"
        print(f"  {bucket:25s} {count:5d} files  {size}")
    print()


def sync_project(project_dir: str):
    """Upload all design artifacts from a project directory to MinIO."""
    project_dir = Path(project_dir)
    if not project_dir.exists():
        print(f"  ❌ Directory not found: {project_dir}")
        return

    ic_name = project_dir.name
    print(f"\n  Syncing project: {ic_name}")

    # Upload GDS
    for gds in project_dir.rglob("*.gds"):
        upload(str(gds), "vibeic-gds", f"{ic_name}/{gds.name}")

    # Upload RTL
    for sv in project_dir.rglob("*.sv"):
        upload(str(sv), "vibeic-designs", f"{ic_name}/rtl/{sv.name}")

    # Upload DEF
    for def_f in project_dir.rglob("*.def"):
        upload(str(def_f), "vibeic-designs", f"{ic_name}/pnr/{def_f.name}")

    # Upload datasheets/appnotes
    for md in project_dir.rglob("*datasheet*.md"):
        upload(str(md), "vibeic-documents", f"{ic_name}/{md.name}")
    for md in project_dir.rglob("*appnote*.md"):
        upload(str(md), "vibeic-documents", f"{ic_name}/{md.name}")

    # Upload SOF
    for sof in project_dir.rglob("*.sof"):
        upload(str(sof), "vibeic-fpga", f"{ic_name}/{sof.name}")

    print(f"  ✅ Project {ic_name} synced to MinIO")


def main():
    parser = argparse.ArgumentParser(description="Vibe-IC MinIO Storage")
    sub = parser.add_subparsers(dest="cmd")

    p_upload = sub.add_parser("upload")
    p_upload.add_argument("--file", required=True)
    p_upload.add_argument("--bucket", required=True)
    p_upload.add_argument("--key", default=None)

    p_download = sub.add_parser("download")
    p_download.add_argument("--bucket", required=True)
    p_download.add_argument("--key", required=True)
    p_download.add_argument("--output", default=".")

    p_list = sub.add_parser("list")
    p_list.add_argument("--bucket", required=True)
    p_list.add_argument("--prefix", default="")

    sub.add_parser("status")

    p_sync = sub.add_parser("sync-project")
    p_sync.add_argument("--project", required=True)

    args = parser.parse_args()

    if args.cmd == "upload":
        upload(args.file, args.bucket, args.key)
    elif args.cmd == "download":
        download(args.bucket, args.key, args.output)
    elif args.cmd == "list":
        list_objects(args.bucket, args.prefix)
    elif args.cmd == "status":
        status()
    elif args.cmd == "sync-project":
        sync_project(args.project)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
