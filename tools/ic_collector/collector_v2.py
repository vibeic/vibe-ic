#!/usr/bin/env python3
"""
Vibe-IC Document Collector v2 — Download real IC PDFs + extract design knowledge
================================================================================
Downloads actual PDF datasheets/appnotes from manufacturer websites,
deduplicates by SHA-256 content hash, saves to SSD2, extracts design knowledge,
and imports structured specs into PostgreSQL.

Storage: /mnt/2a6ff798-a964-4a91-b131-e34fd4ca66ed/ic_documents/
Database: PostgreSQL vibe_ic (only extracted specs, NO file paths)

Usage:
    python3 collector_v2.py download --part ADS1115 --url "https://www.ti.com/lit/ds/symlink/ads1115.pdf"
    python3 collector_v2.py download --batch sources.json
    python3 collector_v2.py scan                    # Scan existing PDFs on SSD2, register hashes
    python3 collector_v2.py status                  # Show stats
    python3 collector_v2.py list-new                # Show PDFs not yet in hash registry

Rules:
    1. Download REAL PDFs, not HTML
    2. Save to SSD2/ic_documents/datasheets/ (NOT AI_IC_design/)
    3. DB stores extracted specs ONLY — no file paths, no URLs to PDFs
    4. SHA-256 content hash for dedup — same content = same file, skip
    5. No cron jobs — run manually, verify quality
"""

import hashlib
import json
import os
import sys
import tempfile
import argparse
from pathlib import Path
from datetime import datetime

# `_progress_run` lives in the plugin's `programs/`, which is not a sibling of
# this file. Walk UP until the directory that actually holds it is found, so
# this works from `tools/`, from `tools/<sub>/`, and from inside the flattened
# plugin cache where the marketplace path does not exist.
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

# ============================================================================
# Configuration
# ============================================================================
SSD2_BASE = Path("/mnt/2a6ff798-a964-4a91-b131-e34fd4ca66ed/ic_documents")
DATASHEETS_DIR = SSD2_BASE / "datasheets"
APPNOTES_DIR = SSD2_BASE / "application_notes"
METADATA_DIR = SSD2_BASE / "datasheets_metadata"
HASH_REGISTRY = Path("~/AI_IC_design/tools/ic_collector/hash_registry.json")
LOG_FILE = Path("~/AI_IC_design/tools/ic_collector/collector_v2.log")


# ============================================================================
# Hash Registry — SHA-256 content-based dedup
# ============================================================================
def load_registry() -> dict:
    if HASH_REGISTRY.exists():
        with open(HASH_REGISTRY) as f:
            return json.load(f)
    return {}


def save_registry(registry: dict):
    HASH_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with open(HASH_REGISTRY, 'w') as f:
        json.dump(registry, f, indent=2, sort_keys=True)


def file_sha256(filepath: str) -> str:
    """Compute SHA-256 hash of file content."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def is_real_pdf(filepath: str) -> bool:
    """Check if file is a real PDF (not HTML or empty)."""
    try:
        size = os.path.getsize(filepath)
        if size < 5000:  # Less than 5KB = probably not a real datasheet
            return False
        with open(filepath, 'rb') as f:
            header = f.read(5)
        return header == b'%PDF-'
    except Exception:
        return False


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')


# ============================================================================
# Download
# ============================================================================
def download_pdf(part_number: str, url: str, doc_type: str = "datasheet") -> dict:
    """
    Download a PDF, verify it's real, check hash for dedup, save to SSD2.
    Returns: {status, hash, path, size} or {status: 'skip'/'fail', reason}
    """
    registry = load_registry()

    # Target directory
    target_dir = DATASHEETS_DIR if doc_type == "datasheet" else APPNOTES_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{part_number}.pdf"

    # Step 1: Download to temp file
    log(f"DOWNLOAD {part_number} from {url}")
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = _pr.run(
            ["curl", "-sL", "--max-time", "30", "-o", tmp_path, url],
            capture_output=True, text=True, 
        )
        if result.returncode != 0:
            os.unlink(tmp_path)
            log(f"  FAIL: curl error (rc={result.returncode})")
            return {"status": "fail", "reason": "download_error"}

        # Step 2: Verify it's a real PDF
        if not is_real_pdf(tmp_path):
            size = os.path.getsize(tmp_path)
            os.unlink(tmp_path)
            log(f"  FAIL: not a real PDF ({size} bytes)")
            return {"status": "fail", "reason": "not_pdf"}

        # Step 3: Compute SHA-256 hash
        content_hash = file_sha256(tmp_path)

        # Step 4: Check hash registry for duplicate
        if content_hash in registry:
            existing = registry[content_hash]
            os.unlink(tmp_path)
            log(f"  SKIP: duplicate content (same as {existing['part_number']}, registered {existing['registered']})")
            return {"status": "skip", "reason": "duplicate_hash", "existing": existing['part_number']}

        # Step 5: Check if same filename already exists on SSD2
        if target_path.exists():
            existing_hash = file_sha256(str(target_path))
            if existing_hash == content_hash:
                os.unlink(tmp_path)
                # Register the hash (it was on disk but not in registry)
                registry[content_hash] = {
                    "part_number": part_number,
                    "doc_type": doc_type,
                    "size": os.path.getsize(str(target_path)),
                    "registered": datetime.now().isoformat(),
                }
                save_registry(registry)
                log(f"  SKIP: already on SSD2 (hash registered)")
                return {"status": "skip", "reason": "already_exists"}
            else:
                # Different content, same filename — rename old one
                backup = target_dir / f"{part_number}_old_{existing_hash[:8]}.pdf"
                os.rename(str(target_path), str(backup))
                log(f"  NOTE: existing file differs, backed up as {backup.name}")

        # Step 6: Copy to SSD2 (can't rename across mount points)
        import shutil
        shutil.copy2(tmp_path, str(target_path))
        os.unlink(tmp_path)
        file_size = os.path.getsize(str(target_path))

        # Step 7: Register hash
        registry[content_hash] = {
            "part_number": part_number,
            "doc_type": doc_type,
            "size": file_size,
            "registered": datetime.now().isoformat(),
        }
        save_registry(registry)

        log(f"  OK: {target_path.name} ({file_size:,} bytes, hash={content_hash[:12]})")
        return {
            "status": "ok",
            "hash": content_hash,
            "path": str(target_path),
            "size": file_size,
        }

    except Exception as e:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        log(f"  FAIL: {e}")
        return {"status": "fail", "reason": str(e)}


# ============================================================================
# Scan — Register existing PDFs on SSD2
# ============================================================================
def scan_existing():
    """Scan all existing PDFs on SSD2 and register their hashes."""
    registry = load_registry()
    new_count = 0
    skip_count = 0

    log("SCAN: Registering existing PDFs on SSD2...")

    for pdf_dir, doc_type in [(DATASHEETS_DIR, "datasheet"), (APPNOTES_DIR, "appnote")]:
        if not pdf_dir.exists():
            continue
        for pdf_file in sorted(pdf_dir.glob("*.pdf")):
            if not is_real_pdf(str(pdf_file)):
                log(f"  SKIP: {pdf_file.name} (not a real PDF)")
                continue

            content_hash = file_sha256(str(pdf_file))

            if content_hash in registry:
                skip_count += 1
                continue

            part_name = pdf_file.stem  # filename without .pdf
            file_size = os.path.getsize(str(pdf_file))

            registry[content_hash] = {
                "part_number": part_name,
                "doc_type": doc_type,
                "size": file_size,
                "registered": datetime.now().isoformat(),
            }
            new_count += 1
            log(f"  NEW: {pdf_file.name} ({file_size:,} bytes, hash={content_hash[:12]})")

    save_registry(registry)
    log(f"SCAN COMPLETE: {new_count} new, {skip_count} already registered, {len(registry)} total")
    return {"new": new_count, "skip": skip_count, "total": len(registry)}


# ============================================================================
# Batch Download
# ============================================================================
def download_batch(sources_file: str):
    """Download multiple PDFs from a JSON source file.

    JSON format:
    [
        {"part": "ADS1115", "url": "https://www.ti.com/lit/ds/symlink/ads1115.pdf", "type": "datasheet"},
        ...
    ]
    """
    with open(sources_file) as f:
        sources = json.load(f)

    results = {"ok": 0, "skip": 0, "fail": 0}

    for entry in sources:
        part = entry["part"]
        url = entry["url"]
        doc_type = entry.get("type", "datasheet")

        result = download_pdf(part, url, doc_type)
        results[result["status"]] = results.get(result["status"], 0) + 1

    log(f"BATCH COMPLETE: {results}")
    return results


# ============================================================================
# List New — PDFs on SSD2 not in hash registry
# ============================================================================
def list_new():
    """List PDFs on SSD2 that aren't in the hash registry."""
    registry = load_registry()
    known_hashes = set(registry.keys())

    print("PDFs on SSD2 not yet in hash registry:\n")
    count = 0
    for pdf_file in sorted(DATASHEETS_DIR.glob("*.pdf")):
        if not is_real_pdf(str(pdf_file)):
            continue
        content_hash = file_sha256(str(pdf_file))
        if content_hash not in known_hashes:
            size = os.path.getsize(str(pdf_file))
            print(f"  {pdf_file.name:40s} {size:>10,} bytes  hash={content_hash[:12]}")
            count += 1

    print(f"\nTotal unregistered: {count}")
    return count


# ============================================================================
# Status
# ============================================================================
def show_status():
    registry = load_registry()

    # Count PDFs on SSD2
    pdf_count = len(list(DATASHEETS_DIR.glob("*.pdf"))) if DATASHEETS_DIR.exists() else 0
    real_pdf_count = sum(1 for f in DATASHEETS_DIR.glob("*.pdf") if is_real_pdf(str(f))) if DATASHEETS_DIR.exists() else 0
    total_size = sum(os.path.getsize(str(f)) for f in DATASHEETS_DIR.glob("*.pdf")) if DATASHEETS_DIR.exists() else 0

    print("=== Vibe-IC Document Collector v2 Status ===\n")
    print(f"  SSD2 PDFs:        {pdf_count} files ({real_pdf_count} real PDFs)")
    print(f"  Total size:       {total_size / (1024*1024):.1f} MB")
    print(f"  Hash registry:    {len(registry)} entries")
    print(f"  Unregistered:     {pdf_count - len([h for h in registry.values() if h['doc_type'] == 'datasheet'])} (run 'scan' to register)")
    print(f"\n  Registry file:    {HASH_REGISTRY}")
    print(f"  Datasheets dir:   {DATASHEETS_DIR}")
    print(f"  Log file:         {LOG_FILE}")


# ============================================================================
# Main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="Vibe-IC Document Collector v2")
    sub = parser.add_subparsers(dest="cmd")

    p_dl = sub.add_parser("download", help="Download a PDF")
    p_dl.add_argument("--part", help="Part number")
    p_dl.add_argument("--url", help="PDF URL")
    p_dl.add_argument("--type", default="datasheet", choices=["datasheet", "appnote"])
    p_dl.add_argument("--batch", help="JSON file with multiple sources")

    sub.add_parser("scan", help="Scan existing PDFs and register hashes")
    sub.add_parser("status", help="Show status")
    sub.add_parser("list-new", help="List unregistered PDFs")

    args = parser.parse_args()

    if args.cmd == "download":
        if args.batch:
            download_batch(args.batch)
        elif args.part and args.url:
            download_pdf(args.part, args.url, args.type)
        else:
            print("Need --part + --url, or --batch")
    elif args.cmd == "scan":
        scan_existing()
    elif args.cmd == "status":
        show_status()
    elif args.cmd == "list-new":
        list_new()
    else:
        parser.print_help()


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
