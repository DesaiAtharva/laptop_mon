"""Deterministic timeline reconstruction engine adhering strictly to §9.1 and REQ-9-1 to REQ-9-4."""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import uuid
from zoneinfo import ZoneInfo

from django.utils import timezone
from apps.analytics.models import AppUsageInterval, IntervalState
from apps.devices.models import Device
from apps.ingestion.models import ActivityEvent
from apps.policies.models import AppClassification, AppRule, MonitoringPolicy
from apps.tenancy.models import Tenant

logger = logging.getLogger(__name__)


@dataclass
class IntervalDraft:
    """In-memory draft of a timeline interval before database persistence."""
    app_identifier: str
    app_classification: str
    app_classification_version: int
    started_at: datetime.datetime
    ended_at: datetime.datetime
    state: str
    is_inferred: bool = False

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.ended_at - self.started_at).total_seconds())


class TimelineState:
    """Internal state tracker for deterministic state machine."""

    def __init__(self) -> None:
        self.session_open: bool = False
        self.session_id: Optional[str] = None
        self.current_app: str = "unknown"
        self.is_idle: bool = False
        self.is_locked: bool = False
        self.is_asleep: bool = False
        self.is_unobserved: bool = False
        self.last_state_at: Optional[datetime.datetime] = None
        self.anomalies: List[str] = []

    def get_current_state(self) -> str:
        if not self.session_open:
            return IntervalState.OFFLINE
        if self.is_asleep:
            return IntervalState.ASLEEP
        if self.is_locked:
            return IntervalState.LOCKED
        if self.is_idle:
            return IntervalState.IDLE
        if self.is_unobserved:
            return IntervalState.UNOBSERVED
        return IntervalState.ACTIVE


def split_interval_by_local_midnight(
    draft: IntervalDraft,
    tz: ZoneInfo,
) -> List[IntervalDraft]:
    """Splits an interval if it spans across local midnight in the tenant timezone (E27, E28).
    
    Guarantees no interval crosses a local day boundary for exact daily aggregation.
    """
    if draft.ended_at <= draft.started_at:
        return []

    start_local = draft.started_at.astimezone(tz)
    end_local = draft.ended_at.astimezone(tz)

    if start_local.date() == end_local.date():
        return [draft]

    result: List[IntervalDraft] = []
    curr_start = draft.started_at

    while True:
        curr_local = curr_start.astimezone(tz)
        next_midnight_local = datetime.datetime.combine(
            curr_local.date() + datetime.timedelta(days=1),
            datetime.time.min,
            tzinfo=tz,
        )
        next_midnight_utc = next_midnight_local.astimezone(datetime.timezone.utc)

        if next_midnight_utc >= draft.ended_at:
            result.append(
                IntervalDraft(
                    app_identifier=draft.app_identifier,
                    app_classification=draft.app_classification,
                    app_classification_version=draft.app_classification_version,
                    started_at=curr_start,
                    ended_at=draft.ended_at,
                    state=draft.state,
                    is_inferred=draft.is_inferred,
                )
            )
            break
        else:
            result.append(
                IntervalDraft(
                    app_identifier=draft.app_identifier,
                    app_classification=draft.app_classification,
                    app_classification_version=draft.app_classification_version,
                    started_at=curr_start,
                    ended_at=next_midnight_utc,
                    state=draft.state,
                    is_inferred=draft.is_inferred,
                )
            )
            curr_start = next_midnight_utc

    return result


class TimelineReconstructionEngine:
    """Deterministic timeline reconstruction state machine (§9.1)."""

    def __init__(self, tenant: Tenant, calc_version: int = 1) -> None:
        self.tenant = tenant
        self.calc_version = calc_version
        self.tz = ZoneInfo(getattr(tenant, "timezone", "UTC") or "UTC")

        # Load app classification rules
        self.app_rules: Dict[str, Tuple[str, int]] = {}
        for rule in AppRule.objects.filter(tenant=tenant):
            self.app_rules[rule.app_identifier.lower().strip()] = (
                rule.classification,
                rule.version,
            )

    def classify_app(self, app_id: Optional[str]) -> Tuple[str, str, int]:
        clean_app = (app_id or "unknown").strip()
        if not clean_app or clean_app.lower() in ("unknown", ""):
            return "unknown", AppClassification.NEUTRAL, 1

        lookup = clean_app.lower()
        if lookup in self.app_rules:
            cls, ver = self.app_rules[lookup]
            return clean_app, cls, ver

        return clean_app, AppClassification.NEUTRAL, 1

    def reconstruct_device_timeline(
        self,
        device: Device,
        events: List[ActivityEvent],
        window_start: Optional[datetime.datetime] = None,
        window_end: Optional[datetime.datetime] = None,
    ) -> List[IntervalDraft]:
        """Reconstructs non-overlapping intervals from raw activity events.
        
        Sorts deterministically by (occurred_at, source_sequence, event_id) (REQ-9-1, E29, E30).
        Guarantees:
        - No overlapping intervals (REQ-9-2, E73).
        - Telemetry gaps are explicit unknowns (REQ-9-3).
        - No negative durations (REQ-9-4, E72).
        """
        if not events:
            return []

        # Deterministic sorting (§9.1, E29, E30)
        sorted_events = sorted(
            events,
            key=lambda e: (
                e.occurred_at,
                int(e.payload.get("source_sequence", 0) if isinstance(e.payload, dict) else 0),
                str(e.id),
            ),
        )

        state = TimelineState()
        raw_intervals: List[IntervalDraft] = []

        def close_interval(to_time: datetime.datetime, is_inferred: bool = False) -> None:
            if state.last_state_at is None:
                state.last_state_at = to_time
                return
            if to_time <= state.last_state_at:
                # Discard zero or clock jump backwards (REQ-9-4, E72)
                return

            current_st = state.get_current_state()
            app_id, app_cls, app_ver = self.classify_app(state.current_app)

            draft = IntervalDraft(
                app_identifier=app_id if current_st == IntervalState.ACTIVE else "system",
                app_classification=app_cls if current_st == IntervalState.ACTIVE else AppClassification.NEUTRAL,
                app_classification_version=app_ver,
                started_at=state.last_state_at,
                ended_at=to_time,
                state=current_st,
                is_inferred=is_inferred,
            )
            raw_intervals.append(draft)
            state.last_state_at = to_time

        for event in sorted_events:
            ev_type = event.event_type
            ev_time = event.occurred_at
            payload = event.payload if isinstance(event.payload, dict) else {}

            if state.last_state_at is None:
                state.last_state_at = ev_time

            # 1. Session events
            if ev_type == "session.start":
                close_interval(ev_time)
                state.session_open = True
                state.session_id = payload.get("session_id")
                state.is_locked = False
                state.is_asleep = False
                state.is_idle = False

            elif ev_type == "session.end":
                close_interval(ev_time)
                state.session_open = False
                state.session_id = None
                state.is_idle = False
                state.is_locked = False
                state.is_asleep = False

            # 2. Foreground application focus
            elif ev_type in ("app.focus", "app.active"):
                close_interval(ev_time)
                # Auto-open session if missing (inferred E71)
                if not state.session_open:
                    state.session_open = True
                    state.anomalies.append("app.focus_without_session_start")
                state.current_app = (
                    payload.get("app")
                    or payload.get("app_identifier")
                    or payload.get("process_name")
                    or "unknown"
                )
                state.is_idle = False

            # 3. Idle events
            elif ev_type in ("idle.start", "session.idle_start"):
                close_interval(ev_time)
                state.is_idle = True

            elif ev_type in ("idle.end", "session.idle_end"):
                if not state.is_idle:
                    # Impossible sequence: idle.end without idle.start (E72)
                    state.anomalies.append("idle.end_without_idle_start")
                close_interval(ev_time)
                state.is_idle = False

            # 4. Session Lock / Unlock
            elif ev_type == "session.lock":
                close_interval(ev_time)
                state.is_locked = True

            elif ev_type == "session.unlock":
                if not state.is_locked:
                    state.anomalies.append("session.unlock_without_lock")
                close_interval(ev_time)
                state.is_locked = False

            # 5. Sleep / Wake (E58)
            elif ev_type in ("system.sleep", "session.sleep"):
                close_interval(ev_time)
                state.is_asleep = True

            elif ev_type in ("system.wake", "session.wake", "session.resume"):
                if not state.is_asleep:
                    state.anomalies.append("system.wake_without_sleep")
                close_interval(ev_time)
                state.is_asleep = False

            # 6. Telemetry gaps (REQ-9-3)
            elif ev_type in ("gap.telemetry", "telemetry.gap"):
                close_interval(ev_time)
                # Emit explicit telemetry gap interval
                gap_duration = float(payload.get("gap_seconds", 0.0))
                gap_end = ev_time + datetime.timedelta(seconds=gap_duration) if gap_duration > 0 else ev_time
                raw_intervals.append(
                    IntervalDraft(
                        app_identifier="gap",
                        app_classification=AppClassification.NEUTRAL,
                        app_classification_version=1,
                        started_at=ev_time,
                        ended_at=gap_end,
                        state=IntervalState.TELEMETRY_GAP,
                        is_inferred=False,
                    )
                )
                state.last_state_at = gap_end

            # 7. Permission Denied (E56)
            elif ev_type == "permission.denied":
                close_interval(ev_time)
                state.is_unobserved = True

            elif ev_type == "permission.granted":
                close_interval(ev_time)
                state.is_unobserved = False

        # Close final open interval (E71: unclosed session provisionally labeled inferred)
        if state.session_open and state.last_state_at:
            last_ev_time = sorted_events[-1].occurred_at
            # If last event was at state.last_state_at, close with inferred grace (e.g. 60s)
            close_to = max(last_ev_time, state.last_state_at + datetime.timedelta(seconds=60))
            if window_end and window_end < close_to:
                close_to = window_end
            close_interval(close_to, is_inferred=True)

        # Split across midnight boundaries (E27, E28)
        split_intervals: List[IntervalDraft] = []
        for raw in raw_intervals:
            for piece in split_interval_by_local_midnight(raw, self.tz):
                split_intervals.append(piece)

        # Filter by window if requested
        final_intervals: List[IntervalDraft] = []
        for interval in split_intervals:
            if window_start and interval.ended_at <= window_start:
                continue
            if window_end and interval.started_at >= window_end:
                continue
            final_intervals.append(interval)

        return final_intervals
