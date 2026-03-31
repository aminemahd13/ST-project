from __future__ import annotations

from collections import Counter
from threading import Lock


class MetricsService:
    """Minimal in-process request metrics exporter."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.request_count = Counter()
        self.request_duration_ms = Counter()

    def record(self, path: str, status_code: int, duration_ms: float) -> None:
        key = f'{path}|{status_code}'
        with self._lock:
            self.request_count[key] += 1
            self.request_duration_ms[path] += int(duration_ms)

    def render_prometheus(self) -> str:
        lines = [
            "# HELP app_http_requests_total Count of HTTP requests by path and status.",
            "# TYPE app_http_requests_total counter",
        ]
        for key, value in self.request_count.items():
            path, status = key.split("|", maxsplit=1)
            lines.append(f'app_http_requests_total{{path="{path}",status="{status}"}} {value}')

        lines += [
            "# HELP app_http_request_duration_milliseconds_total Aggregated request duration per path.",
            "# TYPE app_http_request_duration_milliseconds_total counter",
        ]
        for path, value in self.request_duration_ms.items():
            lines.append(f'app_http_request_duration_milliseconds_total{{path="{path}"}} {value}')
        return "\n".join(lines) + "\n"
