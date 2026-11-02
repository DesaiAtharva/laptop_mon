"""Device management and enrollment API views."""
from __future__ import annotations

import uuid
from typing import Any
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.audit.services import log_audit_event
from apps.devices.models import Device, EnrollmentToken
from apps.devices.serializers import (
    AgentEnrollSerializer,
    CreateEnrollmentTokenSerializer,
    DeviceReassignSerializer,
    DeviceSerializer,
)
from apps.devices.services import enroll_device
from apps.policies.serializers import MonitoringPolicySerializer
from apps.rbac.permissions import IsOrgAdmin
from apps.tenancy.models import Membership


class DeviceListView(generics.ListAPIView):
    """List devices scoped to the organization (§8.4)."""

    serializer_class = DeviceSerializer
    permission_classes = [IsOrgAdmin]

    def get_queryset(self) -> Any:
        return Device.objects.filter(tenant=self.request.tenant).select_related(
            "membership__user"
        )


class CreateEnrollmentTokenView(APIView):
    """Admin endpoint to create a single-use expiring enrollment token (§8.4, E39)."""

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = CreateEnrollmentTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant = getattr(request, "tenant", None)
        if not tenant:
            from apps.tenancy.models import Tenant
            tenant = Tenant.objects.first()
            if not tenant:
                tenant = Tenant.objects.create(name="Saptasurya Solar", status="active")

        membership = None
        if data.get("membership_id"):
            try:
                membership = Membership.objects.get(
                    id=data["membership_id"], tenant=tenant
                )
            except Membership.DoesNotExist:
                raise ValidationError({"membership_id": ["Membership not found in this organization."]})

        token_obj, raw_token = EnrollmentToken.create_token(
            tenant=tenant,
            created_by=request.user,
            membership=membership,
            expires_hours=data.get("expires_hours", 24),
            max_uses=data.get("max_uses", 1),
        )

        log_audit_event(
            tenant=request.tenant,
            actor=request.user,
            action="device.enrollment_token_created",
            resource_type="enrollment_token",
            resource_id=str(token_obj.id),
            metadata={"expires_at": token_obj.expires_at.isoformat(), "max_uses": token_obj.max_uses},
            request=request,
        )

        return Response(
            {
                "token": raw_token,
                "enrollment_token": raw_token,
                "expires_at": token_obj.expires_at,
                "max_uses": token_obj.max_uses,
            },
            status=status.HTTP_201_CREATED,
        )


class AgentEnrollView(APIView):
    """Agent onboarding endpoint (§8.3, E23, E39, E40, E85).

    Token exchange issuing per-device credential. Universal secrets are forbidden.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AgentEnrollSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device, raw_secret, policy = enroll_device(
            token_str=data["token"],
            hostname=data["hostname"],
            os_name=data["os"],
            agent_version=data["agent_version"],
            hardware_id=data.get("hardware_id", ""),
            employee_id=data.get("employee_id", ""),
            employee_name=data.get("employee_name", ""),
        )

        return Response(
            {
                "device_id": str(device.id),
                "device_secret": raw_secret,
                "policy": MonitoringPolicySerializer(policy).data,
            },
            status=status.HTTP_201_CREATED,
        )


class RevokeDeviceView(APIView):
    """Admin endpoint to immediately revoke a device (E24, E38)."""

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request, pk: uuid.UUID, *args: Any, **kwargs: Any) -> Response:
        try:
            device = Device.objects.get(id=pk, tenant=request.tenant)
        except Device.DoesNotExist:
            raise NotFound("Device not found.")

        device.revoke(actor=request.user)
        return Response(
            {"message": f"Device {device.hostname} revoked successfully.", "status": device.status},
            status=status.HTTP_200_OK,
        )


class ReassignDeviceView(APIView):
    """Admin endpoint to reassign device ownership or OS user (E98)."""

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request, pk: uuid.UUID, *args: Any, **kwargs: Any) -> Response:
        try:
            device = Device.objects.get(id=pk, tenant=request.tenant)
        except Device.DoesNotExist:
            raise NotFound("Device not found.")

        serializer = DeviceReassignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership_id = serializer.validated_data["membership_id"]

        try:
            membership = Membership.objects.get(id=membership_id, tenant=request.tenant)
        except Membership.DoesNotExist:
            raise ValidationError({"membership_id": ["Target membership not found in this organization."]})

        device.reassign(new_membership=membership, actor=request.user)
        return Response(DeviceSerializer(device).data, status=status.HTTP_200_OK)


class DownloadInstallerScriptView(APIView):
    """Admin/Agent endpoint to download a pre-configured one-click installer script."""

    permission_classes = [permissions.AllowAny]

    def perform_content_negotiation(self, request: Any, force: bool = False) -> tuple[Any, str]:
        return (None, "")

    def get(self, request: Request) -> Any:
        from django.http import HttpResponse

        token = request.query_params.get("token", "").strip()
        target_os = request.query_params.get("os", "windows").lower()
        server_url = request.build_absolute_uri("/").rstrip("/")

        if target_os == "windows" and request.query_params.get("format") == "exe":
            from django.http import FileResponse, Http404
            from pathlib import Path
            from django.conf import settings

            candidates = [
                Path(settings.BASE_DIR) / "static" / "binaries" / "LaptopMon-Setup.exe",
                Path(settings.BASE_DIR).parent / "dist" / "LaptopMon-Setup.exe",
                Path(settings.BASE_DIR) / "dist" / "LaptopMon-Setup.exe",
            ]
            for p in candidates:
                if p.is_file():
                    return FileResponse(
                        open(p, "rb"),
                        content_type="application/vnd.microsoft.portable-executable",
                        as_attachment=True,
                        filename="LaptopMon-Setup.exe",
                    )
            raise Http404("Standalone Windows binary is currently building or unavailable.")

        if target_os == "windows":
            script = f"""@echo off
setlocal enabledelayedexpansion
title Laptop Productivity Monitoring - Setup Wizard

echo ==========================================================
echo   Laptop Productivity Monitoring - Setup Wizard (Windows)
echo ==========================================================
echo.
echo Connecting to server: {server_url}
echo.

set INSTALL_DIR=%LOCALAPPDATA%\\LaptopMon
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

:: 1. Attempt to download pre-compiled standalone EXE (Tamper-proof, no Python required)
echo [1/3] Checking for pre-compiled native executable...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try {{ (New-Object Net.WebClient).DownloadFile('{server_url}/api/devices/installer/download?format=exe', '%INSTALL_DIR%\\LaptopMon-Setup.exe'); exit 0 }} catch {{ exit 1 }}" 2>nul
if exist "%INSTALL_DIR%\\LaptopMon-Setup.exe" (
    echo [OK] Standalone native executable acquired.
    echo [2/3] Launching Setup Wizard...
    start "" "%INSTALL_DIR%\\LaptopMon-Setup.exe" --server "{server_url}" --token "{token}"
    exit /b 0
)

:: 2. Fallback: Download agent source bundle and check for Python
echo [2/3] Downloading agent bundle from cloud...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('{server_url}/api/devices/installer/agent-bundle.zip', '%INSTALL_DIR%\\agent.zip'); Expand-Archive -Path '%INSTALL_DIR%\\agent.zip' -DestinationPath '%INSTALL_DIR%' -Force; Remove-Item '%INSTALL_DIR%\\agent.zip' -Force" 2>nul

set PY_CMD=
python --version >nul 2>&1
if !errorlevel! equ 0 set PY_CMD=python
if "!PY_CMD!"=="" (
    python3 --version >nul 2>&1
    if !errorlevel! equ 0 set PY_CMD=python3
)
if "!PY_CMD!"=="" (
    echo [INFO] Installing lightweight Python runtime via Windows Package Manager...
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    set PY_CMD=python
)

if not exist "%INSTALL_DIR%\\agent\\installer\\gui_installer.py" (
    echo [ERROR] Could not unpack setup bundle. Please check your internet connection.
    pause
    exit /b 1
)

echo [3/3] Launching Setup Wizard...
!PY_CMD! "%INSTALL_DIR%\\agent\\installer\\gui_installer.py" --server="{server_url}" --token="{token}"
pause
"""
            resp = HttpResponse(script, content_type="application/x-bat")
            resp["Content-Disposition"] = 'attachment; filename="Install-LaptopMon.bat"'
            return resp
        elif target_os == "macos":
            script = f"""#!/bin/bash
set -e
echo "=========================================================="
echo "  Laptop Productivity Monitoring - Apple macOS Setup"
echo "=========================================================="
INSTALL_DIR="$HOME/.laptopmon"
mkdir -p "$INSTALL_DIR"

echo "[1/3] Downloading agent runtime bundle from {server_url}..."
curl -s -L -o "$INSTALL_DIR/agent.zip" "{server_url}/api/devices/installer/agent-bundle.zip"
unzip -q -o "$INSTALL_DIR/agent.zip" -d "$INSTALL_DIR"
rm -f "$INSTALL_DIR/agent.zip"

echo "[2/3] Configuring macOS LaunchAgent for autostart across reboots..."
PLIST_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$PLIST_DIR"
cat << 'EOF' > "$PLIST_DIR/com.laptopmon.agent.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.laptopmon.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>__INSTALL_DIR__/agent/runner.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>__INSTALL_DIR__/agent.log</string>
    <key>StandardErrorPath</key>
    <string>__INSTALL_DIR__/agent.err</string>
</dict>
</plist>
EOF
sed -i '' "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$PLIST_DIR/com.laptopmon.agent.plist"

echo "[3/3] Launching Native Setup Wizard..."
python3 "$INSTALL_DIR/agent/installer/gui_installer.py" --server="{server_url}" --token="{token}"

launchctl unload "$PLIST_DIR/com.laptopmon.agent.plist" 2>/dev/null || true
launchctl load "$PLIST_DIR/com.laptopmon.agent.plist" 2>/dev/null || true
echo "Setup complete. LaptopMon is running in the background."
"""
            resp = HttpResponse(script, content_type="text/x-shellscript")
            resp["Content-Disposition"] = 'attachment; filename="install-laptopmon-mac.sh"'
            return resp
        else:
            # Linux Workstation / Laptop
            script = f"""#!/bin/bash
set -e
echo "=========================================================="
echo "  Laptop Productivity Monitoring - Linux Workstation Setup"
echo "=========================================================="
INSTALL_DIR="$HOME/.laptopmon"
mkdir -p "$INSTALL_DIR"

echo "[1/3] Downloading agent runtime bundle from {server_url}..."
curl -s -L -o "$INSTALL_DIR/agent.zip" "{server_url}/api/devices/installer/agent-bundle.zip"
unzip -q -o "$INSTALL_DIR/agent.zip" -d "$INSTALL_DIR"
rm -f "$INSTALL_DIR/agent.zip"

echo "[2/3] Configuring systemd user service for background monitoring..."
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"
cat << EOF > "$SYSTEMD_USER_DIR/laptopmon.service"
[Unit]
Description=Laptop Productivity Monitoring Agent
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $INSTALL_DIR/agent/runner.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable laptopmon.service 2>/dev/null || true

echo "[3/3] Launching Setup Wizard..."
python3 "$INSTALL_DIR/agent/installer/gui_installer.py" --server="{server_url}" --token="{token}"
systemctl --user start laptopmon.service 2>/dev/null || true
echo "Setup complete. LaptopMon is running as a systemd user service."
"""
            resp = HttpResponse(script, content_type="text/x-shellscript")
            resp["Content-Disposition"] = 'attachment; filename="install-laptopmon-linux.sh"'
            return resp


class AgentBundleDownloadView(APIView):
    """Serve the complete desktop agent code bundle as a lightweight zip file."""

    permission_classes = [permissions.AllowAny]

    def perform_content_negotiation(self, request: Any, force: bool = False) -> tuple[Any, str]:
        return (None, "")

    def get(self, request: Request) -> Any:
        import io
        import os
        import zipfile
        from pathlib import Path
        from django.conf import settings
        from django.http import HttpResponse

        # Locate agent directory in repo root
        agent_root = Path(settings.BASE_DIR).parent / "agent"
        if not agent_root.exists():
            agent_root = Path(settings.BASE_DIR) / "agent"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root_dir, dirs, files in os.walk(agent_root):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests", ".pytest_cache")]
                for file_name in files:
                    if file_name.endswith((".pyc", ".pyo")):
                        continue
                    file_path = Path(root_dir) / file_name
                    arcname = "agent/" + str(file_path.relative_to(agent_root)).replace("\\", "/")
                    zf.write(file_path, arcname=arcname)

        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = 'attachment; filename="laptop-mon-agent.zip"'
        return resp
