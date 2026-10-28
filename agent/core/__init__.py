"""
agent/core package — Shared agent core with zero OS-specific imports.
"""

from agent.core.crypto import CryptoManager, FileKeyStore, InMemoryKeyStore
from agent.core.diagnostics import DiagnosticsCollector, NetworkDiagnostics, setup_agent_logger
from agent.core.journal import Journal, JournalEvent
from agent.core.lifecycle import LifecycleManager
from agent.core.policy import EffectivePolicy, PolicyManager, PolicyRule
from agent.core.privacy_filter import PrivacyFilter
from agent.core.scheduler import AgentScheduler
from agent.core.spool import ScreenshotSpool, SpooledScreenshot
from agent.core.status import AgentState, AgentStatusInfo, StatusTracker
from agent.core.sync import SyncWorker

__all__ = [
    "CryptoManager",
    "FileKeyStore",
    "InMemoryKeyStore",
    "Journal",
    "JournalEvent",
    "ScreenshotSpool",
    "SpooledScreenshot",
    "PolicyManager",
    "PolicyRule",
    "EffectivePolicy",
    "PrivacyFilter",
    "StatusTracker",
    "AgentState",
    "AgentStatusInfo",
    "DiagnosticsCollector",
    "NetworkDiagnostics",
    "setup_agent_logger",
    "SyncWorker",
    "LifecycleManager",
    "AgentScheduler",
]
