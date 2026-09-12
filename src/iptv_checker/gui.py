"""Interfaz grafica para comprobar una lista de URLs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
import os
import shutil
import sqlite3
import subprocess
import sys
from threading import Event, Thread
import tkinter as tk
from tkinter import messagebox, ttk

from .checker import CheckResult, PlaylistChecker
from .playlist import Channel, normalize_url, parse_urls
from .xtream import XtreamAccount, XtreamClient, XtreamDatabase, XtreamDetails, parse_xtream_url


LIVE_CHECK_WORKERS = 20
LIVE_RESULTS_PER_POLL = 200


class CheckerApp(tk.Tk):
    """Ventana principal de la aplicacion."""

    def __init__(self, database_path: str | Path = "xtream.db") -> None:
        super().__init__()
        self.title("Comprobador de URLs")
        self.geometry("900x620")
        self.minsize(700, 480)
        self.results: Queue[CheckResult | None] = Queue()
        self.total = 0
        self.completed = 0
        self.saved = 0
        self.database_path = Path(database_path)
        self.saved_window: tk.Toplevel | None = None
        self._build_ui()
        self._log("Aplicación iniciada. Esperando una lista o URL Xtream.")

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Comprobador de URLs",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            container,
            text="Pega una URL HTTP o HTTPS por línea y pulsa Comprobar.",
        ).pack(anchor="w", pady=(2, 10))

        self.input_text = tk.Text(container, height=10, wrap="none", font=("Consolas", 10))
        self.input_text.pack(fill="x")

        controls = ttk.Frame(container)
        controls.pack(fill="x", pady=10)
        ttk.Label(controls, text="Tiempo máximo (s):").pack(side="left")
        self.timeout = tk.StringVar(value="8")
        ttk.Spinbox(controls, from_=1, to=60, width=5, textvariable=self.timeout).pack(
            side="left", padx=(6, 14)
        )
        self.check_button = ttk.Button(controls, text="Comprobar", command=self.start_check)
        self.check_button.pack(side="left")
        ttk.Button(controls, text="Limpiar", command=self.clear).pack(side="left", padx=8)
        ttk.Button(
            controls,
            text="Base de datos guardados",
            command=self.open_saved_database,
        ).pack(side="right")

        columns = ("url", "status", "time")
        self.table = ttk.Treeview(container, columns=columns, show="headings")
        self.table.heading("url", text="URL")
        self.table.heading("status", text="Resultado")
        self.table.heading("time", text="Tiempo")
        self.table.column("url", width=590)
        self.table.column("status", width=130, anchor="center")
        self.table.column("time", width=90, anchor="center")
        self.table.tag_configure("ok", foreground="#14833b")
        self.table.tag_configure("error", foreground="#c62828")
        self.table.pack(fill="both", expand=True)

        self.progress = ttk.Progressbar(container, mode="determinate")
        self.progress.pack(fill="x", pady=(10, 4))
        self.status_label = ttk.Label(container, text="Listo")
        self.status_label.pack(anchor="w")

        ttk.Label(container, text="Actividad", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(8, 2)
        )
        self.log_text = tk.Text(container, height=5, wrap="word", state="disabled")
        self.log_text.pack(fill="x")

    def _log(self, message: str) -> None:
        """Añade una línea visible al registro de actividad."""

        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def open_saved_database(self) -> None:
        """Abre una ventana con las cuentas Xtream almacenadas localmente."""

        if self.saved_window is not None and self.saved_window.winfo_exists():
            self.saved_window.lift()
            self.saved_window.focus_force()
            return

        window = tk.Toplevel(self)
        self.saved_window = window
        window.title("Base de datos guardados")
        window.geometry("900x420")
        window.minsize(650, 300)
        window.transient(self)
        window.protocol("WM_DELETE_WINDOW", self._close_saved_database)

        container = ttk.Frame(window, padding=16)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="Cuentas Xtream guardadas", font=("Segoe UI", 15, "bold")).pack(
            anchor="w"
        )
        ttk.Label(container, text=f"Archivo: {self.database_path}").pack(anchor="w", pady=(2, 10))

        columns = ("server", "url", "username", "status", "live", "validated", "expires")
        table = ttk.Treeview(container, columns=columns, show="headings")
        headings = {
            "server": "Servidor",
            "url": "URL de acceso",
            "username": "Usuario",
            "status": "Estado",
            "live": "Canales live",
            "validated": "Última validación",
            "expires": "Caducidad",
        }
        widths = (135, 190, 105, 85, 100, 135, 135)
        for column, width in zip(columns, widths):
            table.heading(column, text=headings[column])
            table.column(column, width=width, anchor="center" if column == "status" else "w")
        table.pack(fill="both", expand=True)
        ttk.Label(
            container,
            text="Haz doble clic en una cuenta para consultar sus canales en directo.",
        ).pack(anchor="w", pady=(6, 0))

        footer = ttk.Frame(container)
        footer.pack(fill="x", pady=(10, 0))
        count_label = ttk.Label(footer)
        count_label.pack(side="left")
        accounts_by_item: dict[str, XtreamAccount] = {}

        def refresh() -> None:
            table.delete(*table.get_children())
            accounts_by_item.clear()
            try:
                accounts = XtreamDatabase(self.database_path).all()
            except (OSError, sqlite3.Error) as exc:
                messagebox.showerror("No se pudo abrir", str(exc), parent=window)
                return
            for account in accounts:
                item = table.insert("", "end", values=_account_row(account))
                accounts_by_item[item] = account
                table.set(item, "live", "Doble clic")
            count_label.configure(text=f"{len(accounts)} cuenta(s) guardada(s)")

        def open_channels(_event: tk.Event[tk.Misc]) -> None:
            item = table.focus()
            if not item:
                return
            try:
                account = accounts_by_item[item]
            except KeyError as exc:
                messagebox.showerror("No se pudo abrir", str(exc), parent=window)
                return
            table.set(item, "live", "Consultando…")
            self._open_channel_details(account, table, item)

        table.bind("<Double-1>", open_channels)

        ttk.Button(footer, text="Actualizar", command=refresh).pack(side="right")
        refresh()

    def _open_channel_details(
        self, account: XtreamAccount, account_table: ttk.Treeview, account_item: str
    ) -> None:
        popup = tk.Toplevel(self.saved_window or self)
        popup.title(f"Canales live — {account.server_name}")
        popup.geometry("1050x520")
        popup.minsize(720, 320)

        container = ttk.Frame(popup, padding=16)
        container.pack(fill="both", expand=True)
        title = ttk.Label(container, text=account.server_name, font=("Segoe UI", 15, "bold"))
        title.pack(anchor="w")
        summary = ttk.Label(container, text="Consultando la API Xtream…")
        summary.pack(anchor="w", pady=(2, 10))

        columns = ("id", "name", "category", "format", "availability", "url")
        table = ttk.Treeview(container, columns=columns, show="headings")
        for column, heading, width in (
            ("id", "ID", 65),
            ("name", "Canal", 240),
            ("category", "Categoría", 170),
            ("format", "Formato", 70),
            ("availability", "Acceso", 105),
            ("url", "URL directa", 335),
        ):
            table.heading(column, text=heading)
            table.column(
                column,
                width=width,
                anchor="center" if column in {"id", "format", "availability"} else "w",
            )
        table.tag_configure("ok", foreground="#14833b")
        table.tag_configure("error", foreground="#c62828")
        table.pack(fill="both", expand=True)
        ttk.Label(
            container,
            text=("Filtra la lista y pulsa Iniciar comprobación. Sólo se revisarán los "
                  "canales visibles. Doble clic abre un canal con mpv, ffplay o VLC."),
        ).pack(anchor="w", pady=(6, 0))
        channel_log = ttk.Label(container, text="Preparando descarga…")
        channel_log.pack(anchor="w", pady=(3, 0))
        filters = ttk.Frame(container)
        filters.pack(fill="x", pady=(8, 4), before=table)
        channel_filter = tk.StringVar()
        category_filter = tk.StringVar(value="Todas")
        ttk.Label(filters, text="Canal:").pack(side="left")
        channel_entry = ttk.Entry(filters, textvariable=channel_filter, width=28)
        channel_entry.pack(side="left", padx=(5, 14))
        ttk.Label(filters, text="Categoría:").pack(side="left")
        category_box = ttk.Combobox(
            filters, state="readonly", textvariable=category_filter, values=("Todas",), width=24
        )
        category_box.pack(side="left", padx=(5, 0))
        stop_event = Event()
        check_running = False

        def request_stop() -> None:
            if not check_running:
                return
            stop_event.set()
            stop_button.state(["disabled"])
            channel_log.configure(text="Deteniendo la comprobación…")

        stop_button = ttk.Button(filters, text="Parar comprobación", command=request_stop)
        stop_button.pack(side="right")
        stop_button.state(["disabled"])
        start_button = ttk.Button(filters, text="Iniciar comprobación")
        start_button.pack(side="right", padx=(0, 6))
        start_button.state(["disabled"])
        result_queue: Queue[tuple[str, object]] = Queue()
        all_channels: list[tuple[str, tuple[object, ...]]] = []
        channel_count = 0
        available_count = 0
        checked_count = 0

        def apply_filters(*_args: object) -> None:
            name = channel_filter.get().casefold().strip()
            category = category_filter.get()
            attached_items = set(table.get_children(""))
            matching_items = {
                item for item, _values in _filter_live_rows(all_channels, name, category)
            }
            for item, values in all_channels:
                visible = item in matching_items
                attached = item in attached_items
                if visible and not attached:
                    table.reattach(item, "", "end")
                elif not visible and attached:
                    table.detach(item)
            if all_channels and not check_running:
                visible_count = len(table.get_children(""))
                channel_log.configure(
                    text=f"{visible_count} de {len(all_channels)} canal(es) visibles."
                )

        channel_filter.trace_add("write", apply_filters)
        category_box.bind("<<ComboboxSelected>>", apply_filters)

        def play_channel(event: tk.Event[tk.Misc]) -> None:
            item = table.identify_row(event.y)
            if not item:
                return
            direct_url = table.set(item, "url")
            if not _available_players():
                messagebox.showerror(
                    "No se pudo reproducir",
                    "No se encontró un reproductor compatible. Instala mpv o ffplay "
                    "y añádelo al PATH.",
                    parent=popup,
                )
            else:
                # La ventana integrada elige automáticamente el primer motor
                # disponible, respetando la prioridad mpv -> ffplay.
                PlayerWindow(
                    popup,
                    direct_url,
                    table.set(item, "name"),
                    on_status=lambda status: channel_log.configure(text=status),
                )

        table.bind("<Double-1>", play_channel)

        def load() -> None:
            try:
                details = XtreamClient(account).details()
                result_queue.put(("details", details))
            except Exception as exc:  # Se comunica el error de la tarea al hilo de la interfaz.
                result_queue.put(("error", exc))

        def start_check() -> None:
            nonlocal channel_count, available_count, checked_count, check_running
            if check_running:
                return
            selected = [
                (item, Channel(str(values[1]), str(values[5])))
                for item, values in _filter_live_rows(
                    all_channels, channel_filter.get(), category_filter.get()
                )
                if table.exists(item)
            ]
            if not selected:
                messagebox.showinfo(
                    "Sin canales",
                    "El filtro actual no muestra ningún canal para comprobar.",
                    parent=popup,
                )
                return
            channel_count = len(selected)
            available_count = 0
            checked_count = 0
            check_running = True
            stop_event.clear()
            for item, _channel in selected:
                table.set(item, "availability", "Pendiente")
                table.item(item, tags=())
            start_button.state(["disabled"])
            stop_button.state(["!disabled"])
            _set_live_filters_enabled(channel_entry, category_box, enabled=False)
            channel_log.configure(text=f"Comprobando 0/{channel_count} canales visibles…")
            Thread(target=check_selected, args=(selected,), daemon=True).start()

        def check_selected(selected: list[tuple[str, Channel]]) -> None:
            checker = PlaylistChecker(timeout=8, workers=_live_worker_count(len(selected)))
            executor = ThreadPoolExecutor(max_workers=checker.workers)
            futures = {
                executor.submit(checker.check, channel): item for item, channel in selected
            }
            try:
                for future in as_completed(futures):
                    if stop_event.is_set():
                        for pending in futures:
                            pending.cancel()
                        result_queue.put(("stopped", None))
                        return
                    result_queue.put(("check", (futures[future], future.result())))
            finally:
                executor.shutdown(wait=not stop_event.is_set(), cancel_futures=True)
            result_queue.put(("done", None))

        start_button.configure(command=start_check)

        def poll() -> None:
            nonlocal check_running
            processed = 0
            while processed < LIVE_RESULTS_PER_POLL:
                try:
                    kind, payload = result_queue.get_nowait()
                except Empty:
                    break
                processed += 1
                if kind == "error":
                    failed(str(payload))
                    return
                if kind == "details":
                    show_list(payload)  # type: ignore[arg-type]
                elif kind == "check":
                    item, check = payload  # type: ignore[misc]
                    show_check(item, check)
                elif kind == "done":
                    check_running = False
                    channel_log.configure(
                        text=(f"Comprobación finalizada: {available_count}/"
                              f"{channel_count} accesibles")
                    )
                    stop_button.state(["disabled"])
                    start_button.state(["!disabled"])
                    _set_live_filters_enabled(channel_entry, category_box, enabled=True)
                elif kind == "stopped":
                    check_running = False
                    channel_log.configure(
                        text=f"Comprobación detenida: {checked_count}/{channel_count} comprobados"
                    )
                    stop_button.state(["disabled"])
                    start_button.state(["!disabled"])
                    _set_live_filters_enabled(channel_entry, category_box, enabled=True)
            if popup.winfo_exists():
                popup.after(25 if processed else 100, poll)

        def failed(error: str) -> None:
            if popup.winfo_exists():
                summary.configure(text=f"No se pudieron obtener los canales: {error}")
                start_button.state(["disabled"])
                stop_button.state(["disabled"])
            if account_table.winfo_exists():
                account_table.set(account_item, "live", "Error")

        def show_list(details: XtreamDetails) -> None:
            nonlocal channel_count, account
            if not popup.winfo_exists():
                return
            channel_count = len(details.channels)
            account = replace(
                account, is_valid=details.status.casefold() == "active",
                validated_at=datetime.now(timezone.utc), valid_until=details.valid_until,
            )
            try:
                XtreamDatabase(self.database_path).save(account)
            except (OSError, sqlite3.Error) as exc:
                self._log(f"No se pudo actualizar la validez de {account.server_name}: {exc}")
            for channel in details.channels:
                values = (channel.stream_id, channel.name, channel.category_name,
                          channel.container_extension, "Pendiente", channel.direct_url)
                item = table.insert(
                    "", "end", values=values,
                )
                all_channels.append((item, values))
            categories = sorted(
                {channel.category_name for channel in details.channels}, key=str.casefold
            )
            category_box.configure(values=("Todas", *categories))
            connections = _format_connections(details.active_connections, details.max_connections)
            summary.configure(
                text=(f"Estado: {details.status} · Caducidad: {_format_date(details.valid_until)} "
                      f"· Conexiones: {connections} · {channel_count} canal(es) descargados")
            )
            channel_log.configure(
                text=f"Lista descargada: {channel_count} canal(es). Aplica un filtro para comenzar."
            )
            start_button.state(["!disabled"])
            self._log(f"{account.server_name}: lista descargada ({channel_count} canales).")
            if account_table.winfo_exists():
                account_table.set(account_item, "live", str(channel_count))
                account_table.set(account_item, "status", _account_row(account)[3])
                account_table.set(account_item, "validated", _account_row(account)[5])
                account_table.set(account_item, "expires", _account_row(account)[6])

        def show_check(item: str, check: CheckResult) -> None:
            nonlocal available_count, checked_count
            if not item or not table.exists(item):
                return
            checked_count += 1
            if check.available:
                available_count += 1
            _apply_live_check(table, item, check)
            if not check.available:
                all_channels[:] = [row for row in all_channels if row[0] != item]
            else:
                apply_filters()
            channel_log.configure(
                text=f"Comprobando {checked_count}/{channel_count}: {check.channel.name}"
            )

        popup.protocol("WM_DELETE_WINDOW", lambda: (stop_event.set(), popup.destroy()))
        Thread(target=load, daemon=True).start()
        popup.after(100, poll)

    def _close_saved_database(self) -> None:
        if self.saved_window is not None:
            self.saved_window.destroy()
            self.saved_window = None

    def clear(self) -> None:
        if self.check_button.instate(["disabled"]):
            return
        self.input_text.delete("1.0", "end")
        self.table.delete(*self.table.get_children())
        self.progress.configure(value=0)
        self.status_label.configure(text="Listo")

    def start_check(self) -> None:
        try:
            timeout = float(self.timeout.get())
            if timeout <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Dato incorrecto", "El tiempo máximo debe ser mayor que cero.")
            return

        parsed = parse_urls(self.input_text.get("1.0", "end"))
        if not parsed.channels:
            messagebox.showinfo("Sin URLs", "Pega al menos una URL HTTP o HTTPS valida.")
            return
        if parsed.warnings:
            messagebox.showwarning("Líneas ignoradas", "\n".join(parsed.warnings))

        self.table.delete(*self.table.get_children())
        self.total = len(parsed.channels)
        self.completed = 0
        self.saved = 0
        self.progress.configure(maximum=self.total, value=0)
        self.status_label.configure(text=f"Comprobando 0 de {self.total}...")
        self._log(f"Iniciando comprobación de {self.total} URL(s), timeout {timeout:g} s.")
        self.check_button.state(["disabled"])

        Thread(target=self._check_in_background, args=(parsed.channels, timeout), daemon=True).start()
        self.after(100, self._read_results)

    def _check_in_background(self, channels: tuple[Channel, ...], timeout: float) -> None:
        checker = PlaylistChecker(timeout=timeout, workers=min(10, len(channels)))
        with ThreadPoolExecutor(max_workers=checker.workers) as executor:
            futures = [executor.submit(checker.check, channel) for channel in channels]
            for future in as_completed(futures):
                self.results.put(future.result())
        self.results.put(None)

    def _read_results(self) -> None:
        finished = False
        try:
            while True:
                result = self.results.get_nowait()
                if result is None:
                    finished = True
                    break
                self._add_result(result)
        except Empty:
            pass

        if finished:
            self.check_button.state(["!disabled"])
            self.status_label.configure(
                text=(
                    f"Finalizado: {self.completed} URLs comprobadas, "
                    f"{self.saved} cuenta(s) guardada(s)."
                )
            )
            self._log(
                f"Comprobación finalizada: {self.completed} URL(s), "
                f"{self.saved} cuenta(s) guardada(s)."
            )
        else:
            self.after(100, self._read_results)

    def _add_result(self, result: CheckResult) -> None:
        self.completed += 1
        try:
            if _save_available_account(result, self.database_path):
                self.saved += 1
        except (OSError, sqlite3.Error) as exc:
            messagebox.showerror(
                "No se pudo guardar",
                f"La URL es válida, pero no se pudo guardar en la base de datos:\n{exc}",
                parent=self,
            )
        detail = f"Disponible ({result.status})" if result.available else result.error or "No disponible"
        self.table.insert(
            "",
            "end",
            values=(result.channel.url, detail, f"{result.elapsed_ms} ms"),
            tags=("ok" if result.available else "error",),
        )
        self.progress.configure(value=self.completed)
        self.status_label.configure(text=f"Comprobando {self.completed} de {self.total}...")
        state = (
            "disponible"
            if result.available
            else f"no disponible ({result.error or 'sin respuesta'})"
        )
        self._log(f"{result.channel.url}: {state} en {result.elapsed_ms} ms.")


def _save_available_account(result: CheckResult, database_path: str | Path) -> bool:
    """Guarda una URL Xtream válida después de comprobar que está disponible."""

    if not result.available:
        return False
    try:
        account = parse_xtream_url(result.channel.url)
    except ValueError:
        # El comprobador también acepta URLs HTTP genéricas, que no contienen
        # las credenciales necesarias para crear una cuenta Xtream.
        return False
    validated_account = replace(
        account,
        is_valid=True,
        validated_at=datetime.now(timezone.utc),
    )
    XtreamDatabase(database_path).save(validated_account)
    return True


def _check_live_channels(details: XtreamDetails, *, timeout: float = 8) -> list[CheckResult]:
    """Comprueba los streams anunciados por la API Xtream."""

    channels = tuple(Channel(channel.name, channel.direct_url) for channel in details.channels)
    checker = PlaylistChecker(timeout=timeout, workers=_live_worker_count(len(channels)))
    return checker.check_all(channels)


def _live_worker_count(channel_count: int) -> int:
    """Dimensiona las comprobaciones de red sin crear hilos innecesarios."""

    return min(LIVE_CHECK_WORKERS, max(1, channel_count))


def _set_live_filters_enabled(
    channel_entry: ttk.Entry, category_box: ttk.Combobox, *, enabled: bool
) -> None:
    """Activa o bloquea los filtros mientras se comprueban canales live."""

    if enabled:
        channel_entry.state(["!disabled"])
        # Añadir ``readonly`` no elimina por sí solo el estado ``disabled`` de ttk.
        category_box.state(["!disabled", "readonly"])
    else:
        channel_entry.state(["disabled"])
        category_box.state(["disabled"])


def _channel_matches_filters(
    name: str, category: str, name_filter: str, category_filter: str
) -> bool:
    """Indica si un canal coincide con el texto libre y la categoría."""

    return name_filter.casefold().strip() in name.casefold() and (
        category_filter == "Todas" or category == category_filter
    )


def _filter_live_rows(
    rows: list[tuple[str, tuple[object, ...]]], name_filter: str, category_filter: str
) -> list[tuple[str, tuple[object, ...]]]:
    """Selecciona las filas live que se muestran con los filtros actuales."""

    return [
        (item, values)
        for item, values in rows
        if _channel_matches_filters(
            str(values[1]), str(values[2]), name_filter, category_filter
        )
    ]


def _apply_live_check(table: ttk.Treeview, item: str, check: CheckResult) -> None:
    """Conserva en la tabla sólo resultados pendientes o accesibles."""

    if check.available:
        table.set(item, "availability", "Accesible")
        table.item(item, tags=("ok",))
    else:
        table.delete(item)


def _account_row(account: XtreamAccount) -> tuple[str, ...]:
    status = {True: "Válida", False: "No válida", None: "Sin validar"}[account.is_valid]
    return (
        account.server_name,
        account.access_url,
        account.username,
        status,
        "—",
        _format_date(account.validated_at),
        _format_date(account.valid_until),
    )


def _format_date(value: datetime | None) -> str:
    return value.astimezone().strftime("%d/%m/%Y %H:%M") if value else "—"


def _format_connections(active: int | None, maximum: int | None) -> str:
    if active is None and maximum is None:
        return "—"
    return f"{active if active is not None else '—'} / {maximum if maximum is not None else '—'}"


def _open_stream(url: str) -> str | None:
    """Abre el stream con el primer reproductor multimedia disponible."""

    player = _player_command()
    if player is None:
        return None
    name, command = player

    # La URL directa construida por XtreamClient ya incorpora el usuario y la
    # contraseña escapados. Se pasa como un único argumento (sin shell) para
    # que el reproductor pueda autenticarse sin abrir el navegador.
    subprocess.Popen(
        [*command, normalize_url(url)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return name


class PlayerWindow(tk.Toplevel):
    """Reproductor integrado con controles comunes para mpv y ffplay."""

    def __init__(
        self,
        parent: tk.Misc,
        url: str,
        channel_name: str,
        *,
        on_status: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.url = normalize_url(url)
        self.channel_name = channel_name
        self.on_status = on_status
        self.process: subprocess.Popen[bytes] | None = None
        self.embedded_window: int | None = None
        self._embed_attempts = 0
        self.paused = False
        players = _available_players()

        self.title(f"Reproductor — {channel_name}")
        self.geometry("960x600")
        self.minsize(640, 420)
        self.protocol("WM_DELETE_WINDOW", self.close)

        shell = ttk.Frame(self, padding=14)
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text=channel_name, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(header, text="Reproducción integrada", foreground="#5f6368").pack(anchor="w")

        self.video = tk.Frame(shell, background="#101216", highlightthickness=1)
        self.video.pack(fill="both", expand=True)
        self.video.bind("<Configure>", self._resize_video)
        self.placeholder = tk.Label(
            self.video,
            text="Iniciando reproducción…",
            background="#101216",
            foreground="#d7dbe0",
            font=("Segoe UI", 12),
        )
        self.placeholder.place(relx=.5, rely=.5, anchor="center")

        bar = ttk.Frame(shell)
        bar.pack(fill="x", pady=(10, 0))
        self.players = [name for name, _command in players]
        self.engine = tk.StringVar(value=self.players[0])
        self.play_button = ttk.Button(bar, text="▶ Reproducir", command=self.play)
        self.play_button.pack(side="left")
        self.pause_button = ttk.Button(bar, text="⏸ Pausar", command=self.toggle_pause)
        self.pause_button.pack(side="left", padx=6)
        ttk.Button(bar, text="⏹ Parar", command=self.stop).pack(side="left")
        ttk.Button(bar, text="Cerrar", command=self.close).pack(side="right")

        self.volume = tk.DoubleVar(value=80)
        ttk.Scale(bar, from_=0, to=100, variable=self.volume, command=self.set_volume).pack(
            side="right", padx=(6, 12)
        )
        ttk.Label(bar, text="Volumen").pack(side="right")
        self.status = ttk.Label(shell, text="Listo para reproducir", foreground="#5f6368")
        self.status.pack(anchor="w", pady=(7, 0))
        self.after_idle(self.play)

    def play(self) -> None:
        """Inicia el motor seleccionado dentro del lienzo de vídeo."""

        self.stop(update_status=False)
        self.update_idletasks()
        errors: list[str] = []
        # El orden de _available_players es deliberado: mpv es la primera
        # opción y ffplay actúa automáticamente como respaldo.
        start = self.players.index(self.engine.get()) if self.engine.get() in self.players else 0
        for engine in self.players[start:]:
            self.engine.set(engine)
            try:
                command, environment = _embedded_player_command(
                    engine, self.video.winfo_id(), int(self.volume.get())
                )
                self.process = subprocess.Popen(
                    [*command, self.url], stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment,
                )
                if engine == "ffplay" and sys.platform == "win32":
                    # SDL_WINDOWID no siempre es respetado por las versiones de
                    # SDL que distribuye ffplay en Windows. En ese caso se
                    # incorpora su HWND explícitamente en cuanto sea creado.
                    self._embed_attempts = 0
                    self.after(50, self._attach_ffplay_window)
                break
            except OSError as exc:
                errors.append(f"{engine}: {exc}")
        else:
            messagebox.showerror("No se pudo reproducir", "\n".join(errors), parent=self)
            self._set_status("No se pudo iniciar ningún reproductor")
            return
        self.placeholder.place_forget()
        self.paused = False
        self.pause_button.configure(text="⏸ Pausar")
        self._set_status(f"Reproduciendo con {self.engine.get()}: {self.channel_name}")
        self.after(500, self._watch_process)

    def toggle_pause(self) -> None:
        if not self._running():
            return
        self.paused = not self.paused
        if self.engine.get() == "mpv":
            self._write_command(f"set pause {'yes' if self.paused else 'no'}\n")
        else:
            self._write_command("p")
        self.pause_button.configure(text="▶ Continuar" if self.paused else "⏸ Pausar")
        self._set_status("En pausa" if self.paused else f"Reproduciendo: {self.channel_name}")

    def set_volume(self, value: str) -> None:
        if not self._running():
            return
        volume = max(0, min(100, int(float(value))))
        if self.engine.get() == "mpv":
            self._write_command(f"set volume {volume}\n")
        else:
            # ffplay sólo expone ajustes incrementales durante la ejecución.
            previous = getattr(self, "_ffplay_volume", 80)
            key = "0" if volume > previous else "9"
            for _ in range(abs(volume - previous) // 5):
                self._write_command(key)
            self._ffplay_volume = volume

    def stop(self, *, update_status: bool = True) -> None:
        if self._running():
            self._write_command("quit\n" if self.engine.get() == "mpv" else "q")
            if self.process and self.process.poll() is None:
                self.process.terminate()
        self.process = None
        self.embedded_window = None
        self.paused = False
        if update_status:
            self.placeholder.place(relx=.5, rely=.5, anchor="center")
            self._set_status("Reproducción detenida")

    def close(self) -> None:
        self.stop(update_status=False)
        self.destroy()

    def _running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _write_command(self, command: str) -> None:
        try:
            if self.process and self.process.stdin:
                self.process.stdin.write(command.encode())
                self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            self._set_status("El reproductor dejó de responder")

    def _watch_process(self) -> None:
        if self._running():
            self.after(500, self._watch_process)
        elif self.winfo_exists() and self.process is not None:
            self.process = None
            self.placeholder.place(relx=.5, rely=.5, anchor="center")
            self._set_status("La reproducción ha finalizado")

    def _attach_ffplay_window(self) -> None:
        """Aloja la ventana nativa de ffplay en el marco Tk bajo Windows."""

        if not self._running() or self.process is None:
            return
        self.embedded_window = _embed_windows_process_window(
            self.process.pid,
            self.video.winfo_id(),
            self.video.winfo_width(),
            self.video.winfo_height(),
        )
        if self.embedded_window is None and self._embed_attempts < 40:
            self._embed_attempts += 1
            self.after(100, self._attach_ffplay_window)

    def _resize_video(self, _event: tk.Event[tk.Misc]) -> None:
        if self.embedded_window is not None:
            _resize_windows_child(
                self.embedded_window, self.video.winfo_width(), self.video.winfo_height()
            )

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)
        if callable(self.on_status):
            self.on_status(text)


def _available_players() -> list[tuple[str, str]]:
    """Devuelve los motores que admiten integración en la ventana."""

    return [(name, executable) for name in ("mpv", "ffplay")
            if (executable := shutil.which(name))]


def _embedded_player_command(
    engine: str, window_id: int, volume: int
) -> tuple[list[str], dict[str, str]]:
    """Construye el comando y entorno para alojar vídeo en un widget Tk."""

    executable = shutil.which(engine)
    if not executable or engine not in {"mpv", "ffplay"}:
        raise OSError(f"El motor {engine!r} ya no está disponible")
    environment = os.environ.copy()
    if engine == "mpv":
        return ([executable, f"--wid={window_id}", "--force-window=yes", "--no-fullscreen",
                 "--no-ontop", "--input-terminal=yes",
                 f"--volume={volume}"], environment)
    # SDL_WINDOWID hace que la ventana SDL de ffplay utilice el contenedor
    # nativo de Tk en plataformas compatibles (Windows y X11).
    environment["SDL_WINDOWID"] = str(window_id)
    return ([executable, "-autoexit", "-noborder", "-loglevel", "warning",
             "-volume", str(volume)],
            environment)


def _embed_windows_process_window(
    process_id: int, parent_id: int, width: int, height: int
) -> int | None:
    """Busca el HWND de un proceso y lo convierte en hijo del contenedor Tk."""

    if sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    # ctypes supone ``int`` cuando no se declara una firma. Eso trunca los HWND
    # de 64 bits y hace que SetParent parezca ejecutarse aunque ffplay conserve
    # su ventana independiente.
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    @callback_type
    def find_window(hwnd: int, _parameter: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(hwnd):
            matches.append(hwnd)
            return False
        return True

    user32.EnumWindows(find_window, 0)
    if not matches:
        return None

    hwnd = matches[0]
    user32.SetParent(hwnd, parent_id)
    # SetParent no comunica bien el fallo cuando la ventana no tenía padre:
    # en ambos casos devuelve NULL. GetParent permite verificar el resultado.
    if int(user32.GetParent(hwnd) or 0) != parent_id:
        return None

    style = user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE
    # Quita los adornos de ventana superior y activa WS_CHILD.
    style &= ~0x80CF0000  # WS_POPUP | WS_CAPTION | WS_THICKFRAME | controles
    style |= 0x40000000  # WS_CHILD
    user32.SetWindowLongW(hwnd, -16, style)
    # SWP_FRAMECHANGED obliga a SDL/Windows a aplicar el nuevo estilo. Sin él,
    # ffplay puede seguir dibujándose como una ventana superior aunque ya tenga
    # asignado el marco Tk como padre.
    user32.SetWindowPos(
        hwnd, 0, 0, 0, max(1, width), max(1, height),
        0x0020 | 0x0040,  # SWP_FRAMECHANGED | SWP_SHOWWINDOW
    )
    return int(hwnd)


def _resize_windows_child(window_id: int, width: int, height: int) -> None:
    """Mantiene el vídeo nativo ajustado al tamaño de su marco Tk."""

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        move_window = ctypes.windll.user32.MoveWindow
        move_window.argtypes = [
            wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.BOOL,
        ]
        move_window.restype = wintypes.BOOL
        move_window(
            window_id, 0, 0, max(1, width), max(1, height), True
        )


def _player_command() -> tuple[str, list[str]] | None:
    """Prioriza reproductores fiables y conserva VLC como último recurso."""

    for name, arguments in (("mpv", ["--force-window=yes"]),
                            ("ffplay", ["-autoexit", "-loglevel", "warning"])):
        executable = shutil.which(name)
        if executable:
            return name, [executable, *arguments]
    executable = _vlc_executable()
    return ("VLC", [executable]) if executable else None


def _vlc_executable() -> str | None:
    """Localiza VLC en el PATH o en sus ubicaciones de instalación habituales."""

    executable = shutil.which("vlc")
    if executable:
        return executable

    candidates: list[Path] = []
    if sys.platform == "win32":
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(variable)
            if base:
                candidates.append(Path(base) / "VideoLAN" / "VLC" / "vlc.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/VLC.app/Contents/MacOS/VLC"))

    return str(next((path for path in candidates if path.is_file()), "")) or None


def main() -> None:
    CheckerApp().mainloop()


if __name__ == "__main__":
    main()
