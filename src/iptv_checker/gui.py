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
from threading import Thread
import tkinter as tk
from tkinter import messagebox, ttk

from .checker import CheckResult, PlaylistChecker
from .playlist import Channel, normalize_url, parse_urls
from .xtream import XtreamAccount, XtreamClient, XtreamDatabase, XtreamDetails, parse_xtream_url


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
            text="Primero se comprueba cada stream. Sólo los accesibles se pueden abrir en VLC.",
        ).pack(anchor="w", pady=(6, 0))
        result_queue: Queue[tuple[XtreamDetails, list[CheckResult]] | Exception] = Queue()

        def play_channel(event: tk.Event[tk.Misc]) -> None:
            item = table.identify_row(event.y)
            if not item:
                return
            direct_url = table.set(item, "url")
            if "ok" not in table.item(item, "tags"):
                messagebox.showwarning(
                    "Canal no accesible",
                    "Este stream no superó la comprobación y no se enviará a VLC.",
                    parent=popup,
                )
                return
            try:
                opened = _open_stream(direct_url)
            except OSError as exc:
                messagebox.showerror(
                    "No se pudo reproducir",
                    f"No se pudo abrir el canal:\n{exc}",
                    parent=popup,
                )
                return
            if not opened:
                messagebox.showerror(
                    "No se pudo reproducir",
                    "No se encontró VLC. Instálalo o añádelo al PATH para reproducir canales.",
                    parent=popup,
                )

        table.bind("<Double-1>", play_channel)

        def load() -> None:
            try:
                details = XtreamClient(account).details()
                # La API puede anunciar canales que ya no tienen un stream
                # operativo. Se prueba cada URL antes de mostrársela al usuario.
                checks = _check_live_channels(details)
                result_queue.put((details, checks))
            except Exception as exc:  # Se comunica el error de la tarea al hilo de la interfaz.
                result_queue.put(exc)

        def poll() -> None:
            try:
                result = result_queue.get_nowait()
            except Empty:
                if popup.winfo_exists():
                    popup.after(100, poll)
                return
            if isinstance(result, Exception):
                failed(str(result))
            else:
                details, checks = result
                show(details, checks)

        def failed(error: str) -> None:
            if popup.winfo_exists():
                summary.configure(text=f"No se pudieron obtener los canales: {error}")
            if account_table.winfo_exists():
                account_table.set(account_item, "live", "Error")

        def show(details: XtreamDetails, checks: list[CheckResult]) -> None:
            if not popup.winfo_exists():
                return
            checked_by_url = {check.channel.url: check for check in checks}
            ordered_channels = sorted(
                details.channels,
                key=lambda channel: not checked_by_url[channel.direct_url].available,
            )
            for channel in ordered_channels:
                check = checked_by_url[channel.direct_url]
                access = "Accesible" if check.available else "No accesible"
                table.insert(
                    "", "end",
                    values=(channel.stream_id, channel.name, channel.category_name,
                            channel.container_extension, access, channel.direct_url),
                    tags=("ok" if check.available else "error",),
                )
            available = sum(check.available for check in checks)
            connections = _format_connections(details.active_connections, details.max_connections)
            summary.configure(
                text=(f"Estado: {details.status} · Caducidad: {_format_date(details.valid_until)} "
                      f"· Conexiones: {connections} · {available}/{len(details.channels)} "
                      "canal(es) accesible(s)")
            )
            if account_table.winfo_exists():
                account_table.set(account_item, "live", f"{available}/{len(details.channels)}")

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
    checker = PlaylistChecker(timeout=timeout, workers=min(10, max(1, len(channels))))
    return checker.check_all(channels)


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


def _open_stream(url: str) -> bool:
    """Reproduce directamente un stream autenticado mediante VLC."""

    executable = _vlc_executable()
    if executable is None:
        return False

    # La URL directa construida por XtreamClient ya incorpora el usuario y la
    # contraseña escapados. Se pasa como un único argumento (sin shell) para
    # que VLC pueda autenticarse sin abrir el navegador.
    subprocess.Popen(
        [executable, normalize_url(url)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True


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
