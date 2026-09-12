"""Interfaz de línea de comandos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .checker import CheckResult, PlaylistChecker
from .playlist import parse_m3u


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Comprueba los canales de una lista IPTV M3U")
    parser.add_argument("playlist", type=Path, help="ruta de la lista M3U")
    parser.add_argument("--timeout", type=float, default=10.0, help="segundos de espera por canal")
    parser.add_argument("--workers", type=int, default=10, help="comprobaciones simultáneas")
    parser.add_argument("--json", action="store_true", dest="as_json", help="genera salida JSON")
    return parser


def _as_dict(result: CheckResult) -> dict[str, object]:
    return {
        "name": result.channel.name,
        "url": result.channel.url,
        "available": result.available,
        "status": result.status,
        "elapsed_ms": result.elapsed_ms,
        "error": result.error,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        content = args.playlist.read_text(encoding="utf-8-sig")
        parsed = parse_m3u(content)
        checker = PlaylistChecker(timeout=args.timeout, workers=args.workers)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    for warning in parsed.warnings:
        print(f"Aviso: {warning}", file=sys.stderr)
    results = checker.check_all(parsed.channels)
    if args.as_json:
        print(json.dumps([_as_dict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        for result in results:
            marker = "OK" if result.available else "ERROR"
            detail = result.status if result.status is not None else result.error
            print(f"[{marker}] {result.channel.name} ({result.elapsed_ms} ms) - {detail}")
        available = sum(result.available for result in results)
        print(f"\nResumen: {available}/{len(results)} canales disponibles")
    return 0 if all(result.available for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
