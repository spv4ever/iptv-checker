"""Comprobación concurrente de streams HTTP(S)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .playlist import Channel


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Resultado inmutable de comprobar un canal."""

    channel: Channel
    available: bool
    status: int | None
    elapsed_ms: int
    error: str | None = None


class PlaylistChecker:
    """Comprueba canales en paralelo con límites configurables."""

    def __init__(self, *, timeout: float = 10.0, workers: int = 10) -> None:
        if timeout <= 0:
            raise ValueError("timeout debe ser mayor que cero")
        if workers <= 0:
            raise ValueError("workers debe ser mayor que cero")
        self.timeout = timeout
        self.workers = workers

    def check(self, channel: Channel) -> CheckResult:
        started = monotonic()
        request = Request(
            channel.url,
            headers={"User-Agent": "iptv-checker/0.1", "Range": "bytes=0-0"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.status
                available = 200 <= status < 400
                error = None if available else f"HTTP {status}"
        except HTTPError as exc:
            status, available, error = exc.code, False, f"HTTP {exc.code}"
        except (URLError, TimeoutError, OSError) as exc:
            status, available, error = None, False, str(exc.reason if isinstance(exc, URLError) else exc)

        elapsed_ms = round((monotonic() - started) * 1000)
        return CheckResult(channel, available, status, elapsed_ms, error)

    def check_all(self, channels: tuple[Channel, ...] | list[Channel]) -> list[CheckResult]:
        """Comprueba todos los canales manteniendo el orden original."""

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            return list(executor.map(self.check, channels))
