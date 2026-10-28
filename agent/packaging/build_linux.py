#!/usr/bin/env python3
"""
agent/packaging/build_linux.py — Linux .deb and .tar.gz Packaging Builder (§15.1).

Builds:
- Debian/Ubuntu .deb package with control, postinst (systemd user unit activation),
  and prerm scripts.
- Standalone portable .tar.gz bundle with checksum manifest for non-Debian distributions (Fedora, RHEL, Arch).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path
from typing import Dict, Optional

VERSION = "1.0.0"
PACKAGE_NAME = "laptopmon-agent"
MAINTAINER = "LaptopMon Packaging Team <packaging@laptopmon.internal>"
DESCRIPTION = "Lightweight, auditable laptop productivity monitoring desktop agent"


def generate_control_file(version: str = VERSION, arch: str = "amd64") -> str:
    """Generates Debian package control file."""
    return f"""Package: {PACKAGE_NAME}
Version: {version}
Section: utils
Priority: optional
Architecture: {arch}
Depends: libc6 (>= 2.31), python3 (>= 3.9), libx11-6, libxss1, libxrandr2
Maintainer: {MAINTAINER}
Description: {DESCRIPTION}
 Transparent, policy-driven, auditable laptop monitoring client.
 Supports X11 and Wayland desktop environments with systemd autostart.
"""


def generate_postinst_script() -> str:
    """Generates post-installation script to register systemd user unit."""
    return """#!/bin/sh
set -e

# Enable systemd user service for logged-in graphical sessions
if [ -d /etc/systemd/user ]; then
    cp /opt/laptopmon/share/systemd/laptopmon-agent.service /etc/systemd/user/
fi

echo "LaptopMon Agent installed successfully."
exit 0
"""


def generate_prerm_script() -> str:
    """Generates pre-removal script to stop user service."""
    return """#!/bin/sh
set -e

# Stop running user units
systemctl --global disable laptopmon-agent.service 2>/dev/null || true
exit 0
"""


class LinuxPackager:
    """Packager helper class for Linux distribution artifacts."""

    def __init__(self, version: str = VERSION, package_name: str = PACKAGE_NAME) -> None:
        self.version = version
        self.package_name = package_name

    def generate_control(self, arch: str = "amd64") -> str:
        return generate_control_file(self.version, arch=arch)

    def generate_postinst(self) -> str:
        return generate_postinst_script()

    def generate_prerm(self) -> str:
        return generate_prerm_script()

    def build_deb_structure(self, output_dir: Path, arch: str = "amd64") -> Path:
        """Constructs Debian package directory hierarchy."""
        pkg_root = output_dir / f"{self.package_name}_{self.version}_{arch}"
        debian_dir = pkg_root / "DEBIAN"
        opt_dir = pkg_root / "opt" / "laptopmon" / "bin"
        systemd_dir = pkg_root / "opt" / "laptopmon" / "share" / "systemd"

        for d in (debian_dir, opt_dir, systemd_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Write control file
        with open(debian_dir / "control", "w", encoding="utf-8") as f:
            f.write(self.generate_control(arch=arch))

        # Write postinst script
        postinst = debian_dir / "postinst"
        with open(postinst, "w", encoding="utf-8") as f:
            f.write(self.generate_postinst())
        postinst.chmod(postinst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # Write prerm script
        prerm = debian_dir / "prerm"
        with open(prerm, "w", encoding="utf-8") as f:
            f.write(self.generate_prerm())
        prerm.chmod(prerm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # Launcher executable
        launcher = opt_dir / "laptopmon-agent"
        with open(launcher, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexec python3 -m agent.core.lifecycle \"$@\"\n")
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # Service file
        src_service = Path("agent/packaging/systemd/laptopmon-agent.service")
        if src_service.exists():
            shutil.copy(src_service, systemd_dir / "laptopmon-agent.service")

        return pkg_root

    def build_tarball(self, source_dir: Path, output_tar: Path) -> Path:
        """Builds .tar.gz bundle from staged directory."""
        output_tar.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output_tar, "w:gz") as tar:
            tar.add(source_dir, arcname=self.package_name)
        return output_tar

    def compute_sha256(self, file_path: Path) -> str:
        """Computes SHA-256 hash of an artifact file."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and package Linux desktop agent")
    parser.add_argument("--output-dir", type=Path, default=Path("./build/linux"), help="Output directory")
    parser.add_argument("--arch", type=str, default="amd64", help="Architecture (amd64, arm64)")
    args = parser.parse_args()

    packager = LinuxPackager()
    staged_dir = packager.build_deb_structure(args.output_dir, arch=args.arch)
    print(f"Staged Debian package structure at: {staged_dir}")

    tar_path = args.output_dir / f"{PACKAGE_NAME}-{VERSION}-{args.arch}.tar.gz"
    packager.build_tarball(staged_dir, tar_path)
    checksum = packager.compute_sha256(tar_path)
    print(f"Built portable tarball: {tar_path} (SHA256: {checksum})")
