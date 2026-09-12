"""Parseo y persistencia local de accesos Xtream Codes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .playlist import normalize_url


@dataclass(frozen=True, slots=True)
class XtreamAccount:
    """Credenciales segmentadas de una URL de acceso Xtream Codes."""

    server_name: str
    access_url: str
    username: str
    password: str
    is_valid: bool | None = None
    validated_at: datetime | None = None
    valid_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class XtreamChannel:
    """Canal en directo publicado por una cuenta Xtream."""

    stream_id: int
    name: str
    category_id: str
    category_name: str
    container_extension: str
    direct_url: str


@dataclass(frozen=True, slots=True)
class XtreamDetails:
    """Estado de una cuenta y sus canales en directo."""

    status: str
    valid_until: datetime | None
    active_connections: int | None
    max_connections: int | None
    channels: tuple[XtreamChannel, ...]


class XtreamApiError(RuntimeError):
    """Respuesta de red o formato no válido de una API Xtream."""


class XtreamClient:
    """Cliente mínimo para consultar datos y canales de una cuenta Xtream."""

    def __init__(self, account: XtreamAccount, *, timeout: float = 10.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout debe ser mayor que cero")
        self.account = account
        self.timeout = timeout

    def details(self) -> XtreamDetails:
        account_data = self._request()
        if not isinstance(account_data, dict):
            raise XtreamApiError("la API no devolvió información de la cuenta")
        user_info = account_data.get("user_info")
        if not isinstance(user_info, dict):
            raise XtreamApiError("la API no devolvió información de la cuenta")

        categories_data = self._request("get_live_categories")
        streams_data = self._request("get_live_streams")
        if not isinstance(categories_data, list) or not isinstance(streams_data, list):
            raise XtreamApiError("la API no devolvió una lista de canales válida")

        categories = {
            str(item.get("category_id")): str(item.get("category_name", ""))
            for item in categories_data
            if isinstance(item, dict) and item.get("category_id") is not None
        }
        channels = tuple(
            self._parse_channel(item, categories)
            for item in streams_data
            if isinstance(item, dict)
        )
        return XtreamDetails(
            status=str(user_info.get("status", "Desconocido")),
            valid_until=expiration_from_api(user_info.get("exp_date")),
            active_connections=_optional_int(user_info.get("active_cons")),
            max_connections=_optional_int(user_info.get("max_connections")),
            channels=channels,
        )

    def _request(self, action: str | None = None) -> object:
        query = {"username": self.account.username, "password": self.account.password}
        if action:
            query["action"] = action
        url = f"{self.account.access_url}/player_api.php?{urlencode(query)}"
        request = Request(url, headers={"User-Agent": "iptv-checker/0.1"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except HTTPError as exc:
            raise XtreamApiError(f"la API respondió HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            raise XtreamApiError(f"no se pudo conectar con la API: {reason}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise XtreamApiError("la API devolvió una respuesta no válida") from exc

    def _parse_channel(
        self, item: dict[str, object], categories: dict[str, str]
    ) -> XtreamChannel:
        try:
            stream_id = int(item["stream_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise XtreamApiError("un canal no contiene un identificador válido") from exc
        category_id = str(item.get("category_id", ""))
        extension = str(item.get("container_extension") or "ts")
        direct_url = (
            f"{self.account.access_url}/live/"
            f"{quote(self.account.username, safe='')}/{quote(self.account.password, safe='')}/"
            f"{stream_id}.{quote(extension, safe='')}"
        )
        return XtreamChannel(
            stream_id=stream_id,
            name=str(item.get("name") or f"Canal {stream_id}"),
            category_id=category_id,
            category_name=categories.get(category_id, "Sin categoría"),
            container_extension=extension,
            direct_url=direct_url,
        )


def parse_xtream_url(url: str, *, server_name: str | None = None) -> XtreamAccount:
    """Separa servidor y credenciales de una URL ``get.php``/``player_api.php``.

    La URL almacenada sólo contiene esquema, host y puerto; de este modo las
    credenciales no quedan duplicadas dentro del campo de acceso.
    """

    parsed = urlsplit(normalize_url(url))
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("la URL Xtream debe usar HTTP o HTTPS e incluir un servidor")

    query = parse_qs(parsed.query, keep_blank_values=True)
    username = query.get("username", [""])[0].strip()
    password = query.get("password", [""])[0].strip()

    # También admite enlaces directos: /live/usuario/contraseña/canal.ts.
    parts = [part for part in parsed.path.split("/") if part]
    if (not username or not password) and len(parts) >= 4 and parts[0].lower() in {
        "live",
        "movie",
        "series",
    }:
        username, password = parts[1], parts[2]

    if not username or not password:
        raise ValueError("la URL Xtream no contiene usuario y contraseña")

    host = parsed.hostname.lower()
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    access_url = urlunsplit((parsed.scheme.lower(), host, "", "", ""))
    return XtreamAccount(server_name or host, access_url, username, password)


def expiration_from_api(value: str | int | None) -> datetime | None:
    """Convierte ``user_info.exp_date`` (Unix) a una fecha UTC."""

    if value in (None, "", "null"):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("exp_date no es una marca de tiempo Unix válida") from exc


def _optional_int(value: object) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class XtreamDatabase:
    """Base SQLite de cuentas Xtream, con altas idempotentes."""

    def __init__(self, path: str | Path = "xtream.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        # La contraseña se guarda para poder configurar clientes Xtream.
        # En sistemas POSIX restringimos el fichero al usuario actual.
        if os.name == "posix":
            self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS xtream_accounts (
                    id INTEGER PRIMARY KEY,
                    server_name TEXT NOT NULL,
                    access_url TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password TEXT NOT NULL,
                    is_valid INTEGER,
                    validated_at TEXT,
                    valid_until TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (access_url, username)
                )
                """
            )

    def save(self, account: XtreamAccount) -> int:
        """Crea o actualiza una cuenta y devuelve su identificador."""

        is_valid = None if account.is_valid is None else int(account.is_valid)
        validated_at = _to_iso(account.validated_at)
        valid_until = _to_iso(account.valid_until)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO xtream_accounts
                    (server_name, access_url, username, password, is_valid,
                     validated_at, valid_until)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(access_url, username) DO UPDATE SET
                    server_name=excluded.server_name,
                    password=excluded.password,
                    is_valid=excluded.is_valid,
                    validated_at=excluded.validated_at,
                    valid_until=excluded.valid_until,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    account.server_name,
                    account.access_url,
                    account.username,
                    account.password,
                    is_valid,
                    validated_at,
                    valid_until,
                ),
            )
            row = connection.execute(
                "SELECT id FROM xtream_accounts WHERE access_url=? AND username=?",
                (account.access_url, account.username),
            ).fetchone()
        return int(row["id"])

    def all(self) -> tuple[XtreamAccount, ...]:
        """Devuelve las cuentas ordenadas por nombre de servidor."""

        with self._connect() as connection:
            rows = connection.execute(
                """SELECT server_name, access_url, username, password, is_valid,
                          validated_at, valid_until
                   FROM xtream_accounts ORDER BY server_name, username"""
            ).fetchall()
        return tuple(
            XtreamAccount(
                server_name=row["server_name"],
                access_url=row["access_url"],
                username=row["username"],
                password=row["password"],
                is_valid=None if row["is_valid"] is None else bool(row["is_valid"]),
                validated_at=_from_iso(row["validated_at"]),
                valid_until=_from_iso(row["valid_until"]),
            )
            for row in rows
        )


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("las fechas deben incluir zona horaria")
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
