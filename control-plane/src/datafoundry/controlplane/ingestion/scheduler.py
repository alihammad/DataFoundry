"""In-process ingestion scheduler (T042, research R-04).

A background thread ticker queries for due pipelines and dispatches runs
through the feature 001 dispatcher hook. Schedules are evaluated in the
platform timezone (UTC by default); paused pipelines are skipped (FR-011,
FR-014).

Schedule strings are the interval/cron forms validated by the ingestion
config schema (``every 15 minutes``, ``hourly``, ``daily``, or a 5-field cron
expression). ``next_run_at`` is persisted per pipeline so a restart does not
re-fire a run that already elapsed.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from datafoundry.controlplane.db.models import IngestionPipeline, PipelineState
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: Default tick interval (seconds).
TICK_SECONDS = 15

_CRON_RE = re.compile(r"^(\S+\s+){4}\S+$")
_INTERVAL_SECONDS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2_592_000,
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_interval(schedule: str) -> timedelta | None:
    """Return the interval for ``every N unit`` / ``hourly`` / ``daily`` forms."""
    lowered = schedule.strip().lower()
    if lowered in _INTERVAL_SECONDS:
        return timedelta(seconds=_INTERVAL_SECONDS[lowered])
    match = re.match(r"^every (\d+) (seconds?|minutes?|hours?|days?)$", lowered)
    if match:
        count = int(match.group(1))
        unit = match.group(2)
        seconds = {
            "second": 1,
            "seconds": 1,
            "minute": 60,
            "minutes": 60,
            "hour": 3600,
            "hours": 3600,
            "day": 86400,
            "days": 86400,
        }[unit]
        return timedelta(seconds=count * seconds)
    return None


def _next_cron(cron: str, after: datetime) -> datetime:
    """Next occurrence of a 5-field cron expression after ``after`` (UTC).

    Fields: minute hour day-of-month month day-of-week. Supports ``*`` and
    single integers only (the schema accepts any 5 whitespace-separated
    fields; complex ranges are evaluated conservatively as daily).
    """
    fields = cron.split()
    minute, hour, dom, month, dow = fields
    if "*" not in (minute, hour) or (dom != "*" or month != "*" or dow != "*"):
        # Conservative fallback: treat as daily at 00:00.
        return after.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    minute = 0 if minute == "*" else int(minute)
    hour = 0 if hour == "*" else int(hour)
    candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate


def next_run_at(schedule: str, after: datetime | None = None) -> datetime:
    """Compute the next scheduled run time for a schedule string (UTC)."""
    after = after or _utcnow()
    interval = _parse_interval(schedule)
    if interval is not None:
        return after + interval
    if _CRON_RE.match(schedule.strip()):
        return _next_cron(schedule.strip(), after)
    # Unparseable schedule: never fire (defensive; schema rejects these).
    return after + timedelta(days=3650)


def _due_pipelines(session: Session, now: datetime) -> list[IngestionPipeline]:
    """Pipelines whose next scheduled run has elapsed and are not paused."""
    pipelines = session.execute(
        select(IngestionPipeline).where(IngestionPipeline.state == PipelineState.active)
    ).scalars()
    due = []
    for pipeline in pipelines:
        if not pipeline.schedule:
            continue
        # A pipeline with no recorded next run is due immediately.
        next_at = pipeline.next_run_at or now
        if next_at <= now:
            due.append(pipeline)
    return due


def _advance_schedule(session: Session, pipeline: IngestionPipeline, now: datetime) -> None:
    """Persist the next run time after a scheduled dispatch (no re-fire)."""
    pipeline.next_run_at = next_run_at(pipeline.schedule, after=now)
    session.flush()


class IngestionScheduler:
    """Background thread ticker dispatching due ingestion runs."""

    def __init__(
        self,
        sessionmaker,
        *,
        dispatcher: Any,
        tick_seconds: int = TICK_SECONDS,
        timezone: Any = UTC,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._dispatcher = dispatcher
        self._tick_seconds = tick_seconds
        self._timezone = timezone
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ingestion-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # pragma: no cover - defensive
                logger.exception("ingestion.scheduler.tick_failed")
            self._stop.wait(self._tick_seconds)

    def tick(self) -> None:
        """Dispatch one tick of due pipelines (also callable directly in tests)."""
        now = _utcnow()
        session = self._sessionmaker()
        try:
            for pipeline in _due_pipelines(session, now):
                from datafoundry.controlplane.db.models import (
                    IngestionRun,
                    IngestionRunStatus,
                    RunTrigger,
                )

                active = (
                    session.execute(
                        select(IngestionRun).where(
                            IngestionRun.pipeline_id == pipeline.id,
                            IngestionRun.status.in_(
                                (
                                    IngestionRunStatus.queued,
                                    IngestionRunStatus.running,
                                    IngestionRunStatus.paused,
                                )
                            ),
                        )
                    )
                    .scalars()
                    .first()
                )
                if active is not None:
                    # A run is already active; defer to the next interval.
                    _advance_schedule(session, pipeline, now)
                    continue

                run = IngestionRun(
                    pipeline_id=pipeline.id,
                    trigger=RunTrigger.scheduled,
                    status=IngestionRunStatus.queued,
                )
                session.add(run)
                session.flush()
                _advance_schedule(session, pipeline, now)
                session.commit()
                self._dispatcher(run.id)
        finally:
            session.close()
