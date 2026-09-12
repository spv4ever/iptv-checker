"""Lectura tolerante de listas de reproducción M3U."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from urllib.parse import urlparse

ATTRIBUTE_RE = re.compile(r'([\w-]+)="([^"]*)"')
SUPPORTED_SCHEMES = {"http", "https"}


@dataclass(frozen=True, slots=True)
class Channel:
    """Una entrada reproducible de una lista M3U."""

    name: str
    url: str
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Entradas válidas y avisos encontrados durante el parseo."""

    channels: tuple[Channel, ...]
    warnings: tuple[str, ...]


def _metadata(line: str) -> tuple[str, dict[str, str]]:
    header, separator, title = line.partition(",")
    attributes = dict(ATTRIBUTE_RE.findall(header))
    fallback = attributes.get("tvg-name", "Canal sin nombre")
    return (title.strip() if separator and title.strip() else fallback), attributes


def parse_m3u(content: str) -> ParseResult:
    """Convierte texto M3U en canales HTTP(S), conservando avisos no fatales."""

    channels: list[Channel] = []
    warnings: list[str] = []
    pending: tuple[str, dict[str, str]] | None = None

    for number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line == "#EXTM3U":
            continue
        if line.startswith("#EXTINF:"):
            pending = _metadata(line)
            continue
        if line.startswith("#"):
            continue

        name, attributes = pending or ("Canal sin nombre", {})
        pending = None
        scheme = urlparse(line).scheme.lower()
        if scheme not in SUPPORTED_SCHEMES:
            warnings.append(f"Línea {number}: esquema no soportado en {line!r}")
            continue
        channels.append(Channel(name=name, url=line, attributes=attributes))

    if pending is not None:
        warnings.append("La última entrada #EXTINF no tiene URL")
    return ParseResult(tuple(channels), tuple(warnings))


def parse_urls(content: str) -> ParseResult:
    """Lee una URL HTTP(S) por línea e informa de las líneas no válidas."""

    channels: list[Channel] = []
    warnings: list[str] = []
    for number, raw_line in enumerate(content.splitlines(), start=1):
        url = raw_line.strip()
        if not url:
            continue
        if urlparse(url).scheme.lower() not in SUPPORTED_SCHEMES:
            warnings.append(f"Línea {number}: no es una URL HTTP o HTTPS válida")
            continue
        channels.append(Channel(name=url, url=url))
    return ParseResult(tuple(channels), tuple(warnings))
