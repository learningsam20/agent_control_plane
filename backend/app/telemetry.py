"""Vendor-neutral OpenTelemetry setup for the control plane and its agents.

The control plane and its LangGraph agents emit OTel-compliant **MELT** data:
Metrics, Events, Logs, and Traces. Exporters are configurable and may point at
*any* OTLP-compliant collector (self-hosted, Jaeger, Grafana Tempo, Loki, etc.).
No cloud-vendor SDK is used. The default exporter writes JSON Lines to local
files so the whole stack runs offline.

Configuration (env vars, standard OTel where possible):

    CONTROLPLANE_TELEMETRY_EXPORTER   file (default) | otlp | console | none
    CONTROLPLANE_TELEMETRY_FILE       path for the trace file exporter
                                      (default: data/telemetry/traces.jsonl)
    CONTROLPLANE_TELEMETRY_METRIC_FILE path for the metric file exporter
                                      (default: data/telemetry/metrics.jsonl)
    CONTROLPLANE_TELEMETRY_LOG_FILE   path for the log/event file exporter
                                      (default: data/telemetry/logs.jsonl)
    OTEL_EXPORTER_OTLP_ENDPOINT       OTLP HTTP collector endpoint
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT  full traces endpoint override
    OTEL_EXPORTER_OTLP_METRICS_ENDPOINT full metrics endpoint override
    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT    full logs endpoint override
    OTEL_SERVICE_NAME / OTEL_SERVICE_VERSION / OTEL_DEPLOYMENT_ENVIRONMENT
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from opentelemetry import metrics, trace
from opentelemetry._logs import SeverityNumber, get_logger, set_logger_provider
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    ConsoleLogExporter,
    LogExporter,
    LogExportResult,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.semconv.resource import ResourceAttributes

_DEFAULT_EXPORTER = "file"
_DEFAULT_TRACE_FILE = "data/telemetry/traces.jsonl"
_DEFAULT_METRIC_FILE = "data/telemetry/metrics.jsonl"
_DEFAULT_LOG_FILE = "data/telemetry/logs.jsonl"
_OTLP_ENDPOINT = "http://localhost:4318"

_initialized = False


# --------------------------------------------------------------------------
# JSON Lines exporters (default) — a local file that any collector can ingest
# --------------------------------------------------------------------------

def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1e9, tz=timezone.utc).isoformat()


def _span_to_dict(span: ReadableSpan) -> dict:
    return {
        "kind": "span",
        "name": span.name,
        "trace_id": format(span.context.trace_id, "032x") if span.context else None,
        "span_id": format(span.context.span_id, "016x") if span.context else None,
        "parent_span_id": format(span.parent.span_id, "016x") if span.parent else None,
        "trace_state": str(span.context.trace_state) if span.context else None,
        "span_kind": span.kind.name,
        "start_time": _iso(span.start_time) if span.start_time else None,
        "end_time": _iso(span.end_time) if span.end_time else None,
        "duration_ms": round((span.end_time - span.start_time) / 1e6, 3) if span.start_time and span.end_time else None,
        "status": span.status.status_code.name,
        "status_message": span.status.description or "",
        "attributes": {k: _jsonable(v) for k, v in (span.attributes or {}).items()},
        "events": [
            {
                "name": e.name,
                "timestamp": _iso(e.timestamp) if e.timestamp else None,
                "attributes": {k: _jsonable(v) for k, v in (e.attributes or {}).items()},
            }
            for e in span.events
        ],
    }


def _jsonable(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _point_value(point):
    """Extract a JSON-able value from any metric data point type."""
    if hasattr(point, "value"):
        return point.value
    if hasattr(point, "sum"):
        return point.sum
    if hasattr(point, "count"):
        return {
            "count": point.count,
            "sum": point.sum,
            "min": point.min,
            "max": point.max,
            "bucket_counts": list(point.bucket_counts or []),
        }
    return None


class JsonlSpanExporter(SpanExporter):
    """Append spans to a JSON Lines file (default telemetry sink)."""

    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("CONTROLPLANE_TELEMETRY_FILE", _DEFAULT_TRACE_FILE)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def export(self, spans):
        for span in spans:
            self._fh.write(json.dumps(_span_to_dict(span), default=str) + "\n")
        self._fh.flush()
        return SpanExportResult.SUCCESS

    def shutdown(self, timeout_millis: float = 30_000, **kwargs):
        self._fh.flush()
        self._fh.close()


class JsonlMetricExporter(MetricExporter):
    """Append metric data points to a JSON Lines file (default metrics sink)."""

    def __init__(self, path: str | None = None):
        super().__init__()
        self.path = path or os.environ.get("CONTROLPLANE_TELEMETRY_METRIC_FILE", _DEFAULT_METRIC_FILE)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def export(self, metrics_data, timeout_millis=10_000, **kwargs):
        for resource_metric in metrics_data.resource_metrics:
            for scope_metric in resource_metric.scope_metrics:
                for metric in scope_metric.metrics:
                    for point in metric.data.data_points:
                        time_ns = getattr(point, "time_unix_nano", 0) or getattr(point, "record_timestamp", 0) or 0
                        rec = {
                            "kind": "metric",
                            "name": metric.name,
                            "description": metric.description or "",
                            "unit": metric.unit or "",
                            "instrument_type": type(metric.data).__name__,
                            "attributes": {k: _jsonable(v) for k, v in (point.attributes or {}).items()},
                            "timestamp": _iso(time_ns) if time_ns else None,
                            "value": _point_value(point),
                        }
                        self._fh.write(json.dumps(rec, default=str) + "\n")
        self._fh.flush()
        return True

    def force_flush(self, timeout_millis=10_000):
        self._fh.flush()
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs):
        self._fh.flush()
        self._fh.close()


class JsonlLogExporter(LogExporter):
    """Append OTel log records (logs + events) to a JSON Lines file."""

    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("CONTROLPLANE_TELEMETRY_LOG_FILE", _DEFAULT_LOG_FILE)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def export(self, log_records, timeout_millis=10_000, **kwargs):
        for rec0 in log_records:
            rec = getattr(rec0, "log_record", rec0)
            attrs = {k: _jsonable(v) for k, v in (rec.attributes or {}).items()}
            event_name = getattr(rec, "event_name", None)
            if event_name:
                attrs["event.name"] = event_name
            ts = rec.timestamp or rec.observed_timestamp
            entry = {
                "kind": "log",
                "timestamp": _iso(ts) if ts else None,
                "severity": rec.severity_text
                or (rec.severity_number.name if rec.severity_number else ""),
                "severity_number": rec.severity_number.name if rec.severity_number else None,
                "trace_id": format(rec.trace_id, "032x") if rec.trace_id else None,
                "span_id": format(rec.span_id, "016x") if rec.span_id else None,
                "body": _jsonable(rec.body),
                "attributes": attrs,
                "event.name": attrs.get("event.name"),
            }
            self._fh.write(json.dumps(entry, default=str) + "\n")
        self._fh.flush()
        return LogExportResult.SUCCESS

    def force_flush(self, timeout_millis=10_000):
        self._fh.flush()
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs):
        self._fh.flush()
        self._fh.close()


# --------------------------------------------------------------------------
# Initialization
# --------------------------------------------------------------------------

def _resource(service_name: str) -> Resource:
    return Resource.create(
        {
            ResourceAttributes.SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", service_name),
            ResourceAttributes.SERVICE_VERSION: os.environ.get("OTEL_SERVICE_VERSION", "0.1.0"),
            ResourceAttributes.DEPLOYMENT_ENVIRONMENT: os.environ.get(
                "OTEL_DEPLOYMENT_ENVIRONMENT", "development"
            ),
        }
    )


def _trace_processors(exporter: str):
    if exporter == "file":
        return [BatchSpanProcessor(JsonlSpanExporter())]
    if exporter == "otlp":
        return [BatchSpanProcessor(OTLPSpanExporter())]
    if exporter == "console":
        return [SimpleSpanProcessor(ConsoleSpanExporter())]
    return []


def _metric_reader(exporter: str):
    if exporter == "file":
        return PeriodicExportingMetricReader(JsonlMetricExporter(), export_interval_millis=15_000)
    if exporter == "otlp":
        return PeriodicExportingMetricReader(
            OTLPMetricExporter(), export_interval_millis=15_000
        )
    return None


def _otlp_log_exporter():
    try:
        from opentelemetry.exporter.otlp.proto.http.log_exporter import OTLPLogExporter
    except ImportError:  # OTel 1.44 keeps it under a private module
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    return OTLPLogExporter()


def _log_processors(exporter: str):
    if exporter == "file":
        return [BatchLogRecordProcessor(JsonlLogExporter())]
    if exporter == "otlp":
        return [BatchLogRecordProcessor(_otlp_log_exporter())]
    if exporter == "console":
        return [SimpleLogRecordProcessor(ConsoleLogExporter())]
    return []


def init_telemetry(service_name: str, version: str = "0.1.0") -> None:
    """Idempotently configure the global tracer, meter, and logger providers."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    exporter = os.environ.get("CONTROLPLANE_TELEMETRY_EXPORTER", _DEFAULT_EXPORTER)
    if exporter not in ("file", "otlp", "console", "none"):
        exporter = _DEFAULT_EXPORTER

    resource = _resource(service_name)

    provider = TracerProvider(resource=resource)
    for processor in _trace_processors(exporter):
        provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    reader = _metric_reader(exporter)
    if reader is not None:
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    log_provider = LoggerProvider(resource=resource)
    for processor in _log_processors(exporter):
        log_provider.add_log_record_processor(processor)
    set_logger_provider(log_provider)

    print(f"[telemetry] exporter={exporter} service={service_name} "
          f"traces->{_trace_target(exporter)} logs->{_log_target(exporter)}")


def _trace_target(exporter: str) -> str:
    if exporter == "file":
        return os.environ.get("CONTROLPLANE_TELEMETRY_FILE", _DEFAULT_TRACE_FILE)
    if exporter == "otlp":
        return os.environ.get(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", _OTLP_ENDPOINT) + "/v1/traces",
        )
    if exporter == "console":
        return "console (stdout)"
    return "disabled"


def _log_target(exporter: str) -> str:
    if exporter == "file":
        return os.environ.get("CONTROLPLANE_TELEMETRY_LOG_FILE", _DEFAULT_LOG_FILE)
    if exporter == "otlp":
        return os.environ.get(
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", _OTLP_ENDPOINT) + "/v1/logs",
        )
    if exporter == "console":
        return "console (stdout)"
    return "disabled"


def tracer(name: str = "controlplane") -> trace.Tracer:
    return trace.get_tracer(name, "0.1.0")


def meter(name: str = "controlplane") -> metrics.Meter:
    return metrics.get_meter(name, "0.1.0")


_LEVELS = {
    "DEBUG": SeverityNumber.DEBUG,
    "INFO": SeverityNumber.INFO,
    "WARN": SeverityNumber.WARN,
    "ERROR": SeverityNumber.ERROR,
}


def emit_log(service: str, message: str, level: str = "INFO", **attrs) -> None:
    """Emit a structured OTel log record to the configured logger provider."""
    severity = _LEVELS.get(level.upper(), SeverityNumber.INFO)
    get_logger(service).emit(
        body=message,
        severity_number=severity,
        severity_text=level.upper(),
        attributes={k: _jsonable(v) for k, v in attrs.items()} or None,
    )


def emit_event(service: str, name: str, level: str = "INFO", **attrs) -> None:
    """Emit an OTel event (log record with the ``event.name`` semantic attribute)."""
    severity = _LEVELS.get(level.upper(), SeverityNumber.INFO)
    get_logger(service).emit(
        body=f"event:{name}",
        event_name=name,
        severity_number=severity,
        severity_text=level.upper(),
        attributes={k: _jsonable(v) for k, v in attrs.items()} or None,
    )


def get_tracer_provider():
    return trace.get_tracer_provider()


def get_meter_provider():
    return metrics.get_meter_provider()
