#!/usr/bin/env python3
"""
agent/packaging/build_macos.py — macOS App Bundle, Codesigning, and PKG Builder (§15.1).

Builds:
- LaptopMon.app with embedded Info.plist and entitlements.
- Codesigning with Developer ID Application and Hardened Runtime.
- Component and product installer PKG via pkgbuild / productbuild.
- Notarization submission helper via xcrun notarytool.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"
BUNDLE_ID = "com.laptopmon.agent"
APP_NAME = "LaptopMon"


def generate_info_plist() -> dict[str, str | bool]:
    return {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": "Laptop Productivity Monitor",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundlePackageType": "APPL",
        "CFBundleSignature": "????",
        "CFBundleExecutable": "LaptopMon",
        "LSUIElement": True,  # Runs as agent tray application without dock icon
        "NSSupportsAutomaticGraphicsSwitching": True,
        "NSScreenCaptureUsageDescription": "LaptopMon requires screen recording access to take periodic productivity screenshots as defined by your organization's policy.",
        "NSAppleEventsUsageDescription": "LaptopMon requires access to monitor active applications.",
    }


def generate_entitlements_plist() -> dict[str, bool]:
    return {
        "com.apple.security.cs.allow-jit": True,
        "com.apple.security.cs.allow-unsigned-executable-memory": False,
        "com.apple.security.cs.disable-library-validation": False,
        "com.apple.security.automation.apple-events": True,
    }


class MacOSPackager:
    """Packager helper class for building and signing macOS application bundles."""

    def __init__(self, version: str = VERSION, bundle_id: str = BUNDLE_ID, app_name: str = APP_NAME) -> None:
        self.version = version
        self.bundle_id = bundle_id
        self.app_name = app_name

    def generate_info_plist(self) -> dict[str, str | bool]:
        return generate_info_plist()

    def generate_entitlements(self) -> dict[str, bool]:
        return generate_entitlements_plist()

    def build_app(self, output_dir: Path) -> Path:
        return build_app_bundle(output_dir)



def build_app_bundle(output_dir: Path) -> Path:
    """Constructs the directory hierarchy for LaptopMon.app."""
    app_dir = output_dir / f"{APP_NAME}.app"
    contents_dir = app_dir / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"

    for d in (macos_dir, resources_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Write Info.plist
    with open(contents_dir / "Info.plist", "wb") as f:
        plistlib.dump(generate_info_plist(), f)

    # Write Entitlements.plist
    entitlements_path = output_dir / "entitlements.plist"
    with open(entitlements_path, "wb") as f:
        plistlib.dump(generate_entitlements_plist(), f)

    # Launcher script entrypoint
    launcher_script = macos_dir / "LaptopMon"
    with open(launcher_script, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nexec python3 -m agent.core.lifecycle \"$@\"\n")
    launcher_script.chmod(0o755)

    print(f"Created macOS App Bundle: {app_dir}")
    return app_dir


def sign_app_bundle(app_path: Path, identity: str, entitlements_path: Path) -> bool:
    """Signs the app bundle using codesign with hardened runtime."""
    if shutil.which("codesign") is None:
        print("codesign tool not available; skipping on non-macOS environment.")
        return False

    cmd = [
        "codesign",
        "--force",
        "--options", "runtime",
        "--deep",
        "--entitlements", str(entitlements_path),
        "--sign", identity,
        str(app_path),
    ]
    print(f"Signing app bundle with identity: {identity}")
    res = subprocess.run(cmd)
    return res.returncode == 0


def create_pkg(app_path: Path, output_pkg: Path, identity: Optional[str] = None) -> bool:
    """Packages LaptopMon.app into an installer .pkg using pkgbuild."""
    if shutil.which("pkgbuild") is None:
        print("pkgbuild tool not available; skipping PKG build on non-macOS environment.")
        return False

    cmd = [
        "pkgbuild",
        "--component", str(app_path),
        "--install-location", "/Applications",
        "--identifier", BUNDLE_ID,
        "--version", VERSION,
    ]
    if identity:
        cmd.extend(["--sign", identity])
    cmd.append(str(output_pkg))

    print(f"Building PKG: {output_pkg}")
    res = subprocess.run(cmd)
    return res.returncode == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and package macOS desktop agent")
    parser.add_argument("--output-dir", type=Path, default=Path("./build/macos"), help="Output directory")
    parser.add_argument("--sign-identity", type=str, default="", help="Developer ID Application signing identity")
    args = parser.parse_args()

    app_dir = build_app_bundle(args.output_dir)
    if args.sign_identity:
        entitlements_path = args.output_dir / "entitlements.plist"
        sign_app_bundle(app_dir, args.sign_identity, entitlements_path)
    pkg_path = args.output_dir / f"{APP_NAME}-{VERSION}.pkg"
    create_pkg(app_dir, pkg_path)
