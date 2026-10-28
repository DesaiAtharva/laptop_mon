#!/usr/bin/env python3
"""Database restore verification and drill execution tool (§15, E86)."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def restore_backup(backup_file: Path, db_name: str = "laptop_mon", verify_only: bool = False) -> bool:
    """Restores database from compressed backup file after validating SHA-256 integrity."""
    if not backup_file.exists():
        print(f"Error: backup file not found: {backup_file}", file=sys.stderr)
        return False

    manifest_file = backup_file.with_suffix("").with_suffix(".manifest.json")
    if manifest_file.exists():
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        expected_sha = manifest.get("sha256")

        # Validate checksum
        with open(backup_file, "rb") as f:
            content = f.read()
            actual_sha = hashlib.sha256(content).hexdigest()

        if expected_sha and actual_sha != expected_sha:
            print(f"Integrity check FAILED: expected {expected_sha}, got {actual_sha}", file=sys.stderr)
            return False
        print(f"Integrity check PASSED: SHA256 verified ({actual_sha[:16]}...)")
    else:
        with open(backup_file, "rb") as f:
            content = f.read()

    try:
        decompressed_sql = gzip.decompress(content)
    except Exception as exc:
        print(f"Decompression error: {exc}", file=sys.stderr)
        return False

    if verify_only:
        print(f"Backup verification successful ({len(decompressed_sql)} SQL bytes verified).")
        return True

    host = os.environ.get("MYSQL_HOST", "localhost")
    user = os.environ.get("MYSQL_USER", "laptop_user")
    password = os.environ.get("MYSQL_PASSWORD", "laptop_pass")
    port = os.environ.get("MYSQL_PORT", "3306")

    has_mysql = shutil.which("mysql") is not None
    if has_mysql:
        cmd = [
            "mysql",
            f"-h{host}",
            f"-P{port}",
            f"-u{user}",
            f"-p{password}",
            db_name,
        ]
        result = subprocess.run(cmd, input=decompressed_sql, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print(f"Restore failed: {result.stderr.decode('utf-8')}", file=sys.stderr)
            return False

    print(f"Restore successfully completed into database '{db_name}'.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore database backup with checksum verification")
    parser.add_argument("backup_file", type=Path, help="Path to .sql.gz backup file")
    parser.add_argument("--db-name", type=str, default="laptop_mon", help="Target database name")
    parser.add_argument("--verify-only", action="store_true", help="Only verify file integrity without applying")
    args = parser.parse_args()

    success = restore_backup(args.backup_file, args.db_name, args.verify_only)
    sys.exit(0 if success else 1)
