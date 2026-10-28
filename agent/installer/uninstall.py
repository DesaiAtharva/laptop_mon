"""Desktop Agent Uninstaller.

Implements REQ-15-2 & E13:
- Inspects pending queue depth in local journal.
- Pending data safety policy: never silently discard unsynced events.
- Supports /EXPORT_PATH=<path> or --export-path=<path> to save unsynced data.
- Supports /FORCE_DELETE or --force-delete to intentionally discard unsynced data.
- Removes startup keys and agent binaries.
- Never silently restarts monitoring after an explicit uninstall.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("uninstaller")


def parse_arguments(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse uninstaller arguments supporting Windows slash-style and POSIX flags."""
    raw_args = argv if argv is not None else sys.argv[1:]
    normalized_args: list[str] = []

    for arg in raw_args:
        upper_arg = arg.upper()
        if upper_arg.startswith("/EXPORT_PATH="):
            normalized_args.append(f"--export-path={arg.split('=', 1)[1]}")
        elif upper_arg.startswith("/INSTALL_DIR="):
            normalized_args.append(f"--install-dir={arg.split('=', 1)[1]}")
        elif upper_arg == "/FORCE_DELETE":
            normalized_args.append("--force-delete")
        elif upper_arg == "/QUIET":
            normalized_args.append("--quiet")
        else:
            normalized_args.append(arg)

    parser = argparse.ArgumentParser(description="Laptop Productivity Monitoring SaaS Agent Uninstaller")
    parser.add_argument("--install-dir", required=False, help="Agent installation directory to remove")
    parser.add_argument("--export-path", required=False, help="Path to export unacknowledged events before cleanup")
    parser.add_argument("--force-delete", action="store_true", help="Force deletion of pending data without export")
    parser.add_argument("--quiet", action="store_true", help="Quiet uninstallation")

    return parser.parse_args(normalized_args)


def unregister_windows_startup(app_name: str = "LaptopMonAgent") -> bool:
    """Remove executable from HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""
    if sys.platform != "win32":
        return False
    try:
        import winreg  # type: ignore[import-not-found]

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, app_name)
        return True
    except FileNotFoundError:
        return True  # Already not present
    except Exception as exc:
        logger.warning("Failed to unregister Windows startup: %s", exc)
        return False


def check_pending_events(data_dir: Path) -> int:
    """Inspect local journal SQLite database to count pending unacknowledged events."""
    journal_path = data_dir / "journal.db"
    if not journal_path.exists():
        return 0

    try:
        import sqlite3

        conn = sqlite3.connect(str(journal_path))
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM journal WHERE status = 'pending'")
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Could not read journal: %s", exc)
        return 0


def export_pending_events(data_dir: Path, export_target: Path) -> int:
    """Export pending unacknowledged events to a target JSON archive."""
    journal_path = data_dir / "journal.db"
    if not journal_path.exists():
        return 0

    import sqlite3

    conn = sqlite3.connect(str(journal_path))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, event_type, timestamp, payload FROM journal WHERE status = 'pending'")
        rows = cursor.fetchall()

        events = []
        for r in rows:
            events.append({
                "id": r[0],
                "event_type": r[1],
                "timestamp": r[2],
                "payload": json.loads(r[3]) if r[3] else {},
            })

        export_target.parent.mkdir(parents=True, exist_ok=True)
        with open(export_target, "w", encoding="utf-8") as f:
            json.dump({"exported_pending_count": len(events), "events": events}, f, indent=2)

        return len(events)
    finally:
        conn.close()


def uninstall(
    install_dir: Optional[str | Path] = None,
    export_path: Optional[str | Path] = None,
    force_delete: bool = False,
    quiet: bool = False,
    unregister_startup: bool = True,
) -> Dict[str, Any]:
    """Execute uninstallation following pending data safety rules (REQ-15-2, E13)."""
    if install_dir is None:
        local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        install_path = Path(local_app_data) / "LaptopMon"
    else:
        install_path = Path(install_dir)

    if not install_path.exists():
        return {"success": True, "message": "Installation directory does not exist"}

    data_dir = install_path / "data"
    pending_count = check_pending_events(data_dir)

    # REQ-15-2 & E13 Safety Policy:
    # If unacknowledged events exist, require --export-path or --force-delete.
    if pending_count > 0 and not export_path and not force_delete:
        err_msg = (
            f"Uninstallation blocked: {pending_count} unacknowledged monitoring events remain in local journal. "
            f"Specify --export-path=<file> to save them or --force-delete to discard them deliberately."
        )
        if not quiet:
            print(f"ERROR: {err_msg}", file=sys.stderr)
        return {
            "success": False,
            "error": "PENDING_DATA_BLOCKED",
            "message": err_msg,
            "pending_count": pending_count,
        }

    exported_count = 0
    if pending_count > 0 and export_path:
        exported_count = export_pending_events(data_dir, Path(export_path))
        if not quiet:
            print(f"Exported {exported_count} unacknowledged events to {export_path}")

    # Remove startup registration
    if unregister_startup and sys.platform == "win32":
        unregister_windows_startup("LaptopMonAgent")

    # Remove files and directories
    try:
        shutil.rmtree(install_path)
    except Exception as exc:
        logger.error("Failed to remove directory %s: %s", install_path, exc)
        return {"success": False, "error": str(exc)}

    if not quiet:
        print(f"Successfully uninstalled LaptopMon Agent from: {install_path}")

    return {
        "success": True,
        "pending_count": pending_count,
        "exported_count": exported_count,
        "removed_dir": str(install_path),
    }


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point for uninstaller."""
    args = parse_arguments(argv)
    res = uninstall(
        install_dir=args.install_dir,
        export_path=args.export_path,
        force_delete=args.force_delete,
        quiet=args.quiet,
    )
    return 0 if res.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
