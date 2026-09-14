"""Observability wiring (T020, R-09, R-10).

- OpenTelemetry SDK: FastAPI instrumentation, OTLP trace/metric export.
- Structured JSON logging with secret-pattern redaction (SC-006: no secrets
  in logs).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from datafoundry.controlplane.config.secret_scan import redact_text
from datafoundry.controlplane.config.settings import Settings, get_settings


class RedactingJsonFormatter(logging.Formatter):
    """Structured JSON log formatter that redacts secret patterns (R-09)."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = redact_text(self.formatException(record.exc_info))
        # Extra structured fields attached via `extra={...}`.
        for key, value in record.__dict__.items():
            if key in {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "taskName",
            }:
                continue
            entry[key] = redact_text(str(value)) if isinstance(value, str) else value
        return json.dumps(entry, default=str)


def configure_logging(settings: Settings | None = None) -> None:
    """Install root logging: JSON (prod/default) or plain (dev convenience)."""
    settings = settings or get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_json:
        handler.setFormatter(RedactingJsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    # Quiet noisy third-party loggers.
    for name in ("botocore", "urllib3", "google"):
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_telemetry(settings: Settings | None = None) -> None:
    """Wire OpenTelemetry traces/metrics + FastAPI instrumentation (R-10).

    No-op when otel_enabled is false or the SDK is unavailable (keeps unit
    tests dependency-light).
    """
    settings = settings or get_settings()
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:  # pragma: no cover - SDK is a hard dependency in prod
        logging.getLogger(__name__).warning("opentelemetry SDK not installed; tracing disabled")
        return

    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "service.version": settings.service_version,
        }
    )
    provider = TracerProvider(resource=resource)
    if settings.otel_exporter_otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
        )
    trace.set_tracer_provider(provider)


def instrument_app(app: Any, settings: Settings | None = None) -> None:
    """Attach OpenTelemetry FastAPI instrumentation to the app (R-10)."""
    settings = settings or get_settings()
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:  # pragma: no cover
        return
    FastAPIInstrumentor.instrument_app(app)


def setup_observability(app: Any | None = None, settings: Settings | None = None) -> None:
    """One-call wiring used by the app factory / entrypoint."""
    settings = settings or get_settings()
    configure_logging(settings)
    configure_telemetry(settings)
    if app is not None:
        instrument_app(app, settings)
