"""
agent/runner.py — Desktop Agent Runtime Entrypoint.

Handles:
1. Loading configuration from config.json (or environment).
2. Auto-enrollment using enrollment token if device is not yet registered.
3. Bootstrapping OS adapter, local SQLite journal, and encrypted screenshot spool.
4. Starting the event-driven scheduler and background sync worker.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import socket
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict

# Ensure project root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.core.crypto import CryptoManager, FileKeyStore
from agent.core.diagnostics import DiagnosticsCollector, setup_agent_logger
from agent.core.journal import Journal
from agent.core.lifecycle import LifecycleManager
from agent.core.policy import PolicyManager
from agent.core.privacy_filter import PrivacyFilter
from agent.core.scheduler import AgentScheduler
from agent.core.spool import ScreenshotSpool
from agent.core.status import StatusTracker
from agent.core.sync import SyncWorker

logger = logging.getLogger("agent.runner")


def load_or_create_config(config_path: Path) -> Dict[str, Any]:
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Defaults
    local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    base_dir = Path(local_app_data) / "LaptopMon"
    return {
        "version": "1.0.0",
        "server_url": "https://monitor.saptasuryasolar.com",
        "enrollment_token": "",
        "data_dir": str(base_dir / "data"),
        "logs_dir": str(base_dir / "logs"),
        "device_id": None,
        "device_secret": None,
    }


def enroll_if_needed(config: Dict[str, Any], config_path: Path) -> Dict[str, Any]:
    """Enroll the device with the cloud backend using enrollment token if not yet enrolled."""
    if config.get("device_id") and config.get("device_secret"):
        return config

    server_url = config.get("server_url", "https://monitor.saptasuryasolar.com").rstrip("/")
    token = config.get("enrollment_token", "").strip()

    if not token:
        logger.warning("No enrollment token provided in config.json. Running in standalone local mode.")
        return config

    enroll_url = f"{server_url}/api/agent/enroll"
    hostname = socket.gethostname()
    os_name = "windows" if sys.platform == "win32" else ("macos" if sys.platform == "darwin" else "linux")
    hardware_id = f"HW-{abs(hash(hostname + platform.machine())) % 1000000:06d}"

    payload = {
        "token": token,
        "hostname": hostname,
        "os": os_name,
        "agent_version": config.get("version", "1.0.0"),
        "hardware_id": hardware_id,
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        enroll_url,
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"Connecting to {server_url} to enroll device '{hostname}'...")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = json.loads(resp.read().decode("utf-8"))
            config["device_id"] = resp_body.get("device_id")
            config["device_secret"] = resp_body.get("device_secret")
            if resp_body.get("policy"):
                config["initial_policy"] = resp_body.get("policy")

            # Persist updated config with device credentials
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)

            print(f"[SUCCESS] Device enrolled successfully! Device ID: {config['device_id']}")
    except urllib.error.HTTPError as err:
        err_msg = err.read().decode("utf-8")
        logger.error("Enrollment failed with status %d: %s", err.code, err_msg)
        print(f"[ERROR] Enrollment failed ({err.code}): {err_msg}")
    except Exception as exc:
        logger.exception("Enrollment network error: %s", exc)
        print(f"[ERROR] Could not connect to {enroll_url}: {exc}")

    return config


def get_os_adapter():
    """Dynamically load appropriate OS adapter based on current platform."""
    if sys.platform == "win32":
        from agent.adapters.windows.adapter import WindowsOSAdapter
        return WindowsOSAdapter()
    elif sys.platform == "darwin":
        from agent.adapters.macos.adapter import MacOSAdapter
        return MacOSAdapter()
    else:
        from agent.adapters.linux.adapter import LinuxAdapter
        return LinuxAdapter()


def run_agent(config_file: Optional[str] = None):
    local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    default_config_path = Path(local_app_data) / "LaptopMon" / "config.json"
    config_path = Path(config_file) if config_file else default_config_path

    config = load_or_create_config(config_path)

    # Enroll device if credentials are not yet present
    config = enroll_if_needed(config, config_path)
    if not config.get("device_id"):
        print("[ERROR] Agent enrollment required before monitoring can start.")
        print("Please run installer with a valid enrollment token:")
        print("  python agent/installer/install.py --server=<server_url> --token=<token>")
        return

    data_dir = Path(config.get("data_dir", Path(local_app_data) / "LaptopMon" / "data"))
    logs_dir = Path(config.get("logs_dir", Path(local_app_data) / "LaptopMon" / "logs"))
    keys_dir = data_dir / "keys"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    keys_dir.mkdir(parents=True, exist_ok=True)

    setup_agent_logger(str(logs_dir / "agent.log"))

    adapter = get_os_adapter()
    keystore = FileKeyStore(str(keys_dir / "agent.key"))
    crypto = CryptoManager(keystore)
    if not crypto.is_key_available():
        crypto.generate_and_save_key()

    journal = Journal(str(data_dir / "journal.db"), crypto=crypto)
    spool = ScreenshotSpool(str(data_dir / "spool"), crypto=crypto)
    policy_manager = PolicyManager(str(data_dir / "policy_cache.json"))
    if config.get("initial_policy"):
        policy_manager.update_policy(config["initial_policy"])
    privacy_filter = PrivacyFilter(policy_manager=policy_manager)
    status_tracker = StatusTracker(str(data_dir / "status.json"))
    if not status_tracker.first_run_acknowledged and not status_tracker.explicitly_stopped:
        status_tracker.acknowledge_first_run()

    lifecycle = LifecycleManager(str(data_dir), adapter, journal, status_tracker)
    diagnostics = DiagnosticsCollector()

    server_url = config.get("server_url", "https://monitor.saptasuryasolar.com")
    device_id = config.get("device_id") or "unregistered"
    device_secret = config.get("device_secret") or "none"

    # Fetch active policy from server on startup
    if device_id and device_secret and device_id != "unregistered":
        try:
            policy_url = f"{server_url}/api/agent/policy"
            req = urllib.request.Request(
                policy_url,
                headers={"Authorization": f"Bearer {device_secret}", "X-Device-Id": device_id},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                active_policy = json.loads(resp.read().decode("utf-8"))
                policy_manager.update_policy(active_policy)
                print(f"[POLICY] Active policy loaded: interval={active_policy.get('screenshot_interval_seconds')}s, version={active_policy.get('version')}")
        except Exception as ex:
            logger.warning("Could not fetch latest policy from server: %s", ex)

    sync_worker = SyncWorker(
        base_api_url=server_url,
        device_id=device_id,
        credential_token=device_secret,
        journal=journal,
        spool=spool,
        policy_manager=policy_manager,
        status_tracker=status_tracker,
    )

    scheduler = AgentScheduler(
        adapter=adapter,
        journal=journal,
        spool=spool,
        policy_manager=policy_manager,
        privacy_filter=privacy_filter,
        status_tracker=status_tracker,
        lifecycle=lifecycle,
        sync_worker=sync_worker,
        diagnostics=diagnostics,
    )

    print("=" * 60)
    print(" LaptopMon Productivity Monitoring Agent Active")
    print(f" Server:  {server_url}")
    print(f" Device:  {device_id}")
    print(f" Data:    {data_dir}")
    print(" Transparent, policy-driven monitoring is running.")
    print(" Press Ctrl+C to stop.")
    print("=" * 60)

    try:
        while True:
            scheduler.step()
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping LaptopMon Agent gracefully...")
        lifecycle.shutdown()
        journal.close()
        spool.close()
        print("Agent stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LaptopMon Desktop Agent Runner")
    parser.add_argument("--config", help="Path to config.json", default=None)
    args = parser.parse_args()
    run_agent(args.config)
