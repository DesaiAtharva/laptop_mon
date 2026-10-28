"""Desktop Agent Installer.

Implements REQ-15-1: Silent admin installer supporting:
/TOKEN=<enrollment_token>
/SERVER=<server_url>
/QUIET
/TARGET_DIR=<target_dir>
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("installer")


def parse_arguments(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse installer arguments supporting Windows slash-style and POSIX flags."""
    raw_args = argv if argv is not None else sys.argv[1:]
    normalized_args: list[str] = []

    for arg in raw_args:
        upper_arg = arg.upper()
        if upper_arg.startswith("/TOKEN="):
            normalized_args.append(f"--token={arg.split('=', 1)[1]}")
        elif upper_arg.startswith("/SERVER="):
            normalized_args.append(f"--server={arg.split('=', 1)[1]}")
        elif upper_arg.startswith("/TARGET_DIR="):
            normalized_args.append(f"--target-dir={arg.split('=', 1)[1]}")
        elif upper_arg == "/QUIET":
            normalized_args.append("--quiet")
        elif upper_arg == "/NO_STARTUP":
            normalized_args.append("--no-startup")
        else:
            normalized_args.append(arg)

    parser = argparse.ArgumentParser(description="Laptop Productivity Monitoring SaaS Agent Installer")
    parser.add_argument("--token", required=False, help="Agent enrollment token")
    parser.add_argument("--server", required=False, default="http://localhost:8000", help="Backend API server URL")
    parser.add_argument("--target-dir", required=False, help="Target installation directory")
    parser.add_argument("--quiet", action="store_true", help="Silent installation with no interactive UI")
    parser.add_argument("--no-startup", action="store_true", help="Do not register in Windows startup/Run registry")

    return parser.parse_args(normalized_args)


def register_windows_startup(app_name: str, executable_path: str) -> bool:
    """Register executable in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""
    if sys.platform != "win32":
        return False
    try:
        import winreg  # type: ignore[import-not-found]

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{executable_path}"')
        return True
    except Exception as exc:
        logger.warning("Failed to register Windows startup: %s", exc)
        return False


def install(
    target_dir: Optional[str | Path] = None,
    token: Optional[str] = None,
    server: str = "http://localhost:8000",
    quiet: bool = False,
    register_startup: bool = True,
) -> Dict[str, Any]:
    """Execute installation creating directory tree, config, and startup registration."""
    if target_dir is None:
        local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        install_path = Path(local_app_data) / "LaptopMon"
    else:
        install_path = Path(target_dir)

    # 1. Create directory layout
    bin_dir = install_path / "bin"
    data_dir = install_path / "data"
    logs_dir = install_path / "logs"

    bin_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 2. Write configuration
    config_path = install_path / "config.json"
    config_data = {
        "version": "1.0.0",
        "server_url": server.rstrip("/"),
        "enrollment_token": token or "",
        "data_dir": str(data_dir),
        "logs_dir": str(logs_dir),
        "installed_at": "now",
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    # 3. Startup registration
    startup_registered = False
    agent_exe = bin_dir / ("agent.exe" if sys.platform == "win32" else "agent")
    if register_startup and sys.platform == "win32":
        startup_registered = register_windows_startup("LaptopMonAgent", str(agent_exe))

    if not quiet:
        print(f"Successfully installed LaptopMon Agent to: {install_path}")
        print("Transparency Notice: Transparent, policy-driven productivity monitoring is active.")

    return {
        "success": True,
        "install_dir": str(install_path),
        "bin_dir": str(bin_dir),
        "data_dir": str(data_dir),
        "logs_dir": str(logs_dir),
        "config_file": str(config_path),
        "startup_registered": startup_registered,
    }


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point for installer."""
    args = parse_arguments(argv)
    res = install(
        target_dir=args.target_dir,
        token=args.token,
        server=args.server,
        quiet=args.quiet,
        register_startup=not args.no_startup,
    )
    return 0 if res.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
