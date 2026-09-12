"""Interfaz grafica para comprobar una lista de URLs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
import sqlite3
from threading import Thread
import tkinter as tk
from tkinter import messagebox, ttk

from .checker import CheckResult, PlaylistChecker
from .playlist import Channel, parse_urls
from .xtream import XtreamAccount, XtreamDatabase


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

        columns = ("server", "url", "username", "status", "validated", "expires")
        table = ttk.Treeview(container, columns=columns, show="headings")
        headings = {
            "server": "Servidor",
            "url": "URL de acceso",
            "username": "Usuario",
            "status": "Estado",
            "validated": "Última validación",
            "expires": "Caducidad",
        }
        widths = (145, 220, 120, 90, 145, 145)
        for column, width in zip(columns, widths):
            table.heading(column, text=headings[column])
            table.column(column, width=width, anchor="center" if column == "status" else "w")
        table.pack(fill="both", expand=True)

        footer = ttk.Frame(container)
        footer.pack(fill="x", pady=(10, 0))
        count_label = ttk.Label(footer)
        count_label.pack(side="left")

        def refresh() -> None:
            table.delete(*table.get_children())
            try:
                accounts = XtreamDatabase(self.database_path).all()
            except (OSError, sqlite3.Error) as exc:
                messagebox.showerror("No se pudo abrir", str(exc), parent=window)
                return
            for account in accounts:
                table.insert("", "end", values=_account_row(account))
            count_label.configure(text=f"{len(accounts)} cuenta(s) guardada(s)")

        ttk.Button(footer, text="Actualizar", command=refresh).pack(side="right")
        refresh()

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
            self.status_label.configure(text=f"Finalizado: {self.completed} URLs comprobadas.")
        else:
            self.after(100, self._read_results)

    def _add_result(self, result: CheckResult) -> None:
        self.completed += 1
        detail = f"Disponible ({result.status})" if result.available else result.error or "No disponible"
        self.table.insert(
            "",
            "end",
            values=(result.channel.url, detail, f"{result.elapsed_ms} ms"),
            tags=("ok" if result.available else "error",),
        )
        self.progress.configure(value=self.completed)
        self.status_label.configure(text=f"Comprobando {self.completed} de {self.total}...")


def _account_row(account: XtreamAccount) -> tuple[str, ...]:
    status = {True: "Válida", False: "No válida", None: "Sin validar"}[account.is_valid]
    return (
        account.server_name,
        account.access_url,
        account.username,
        status,
        _format_date(account.validated_at),
        _format_date(account.valid_until),
    )


def _format_date(value: datetime | None) -> str:
    return value.astimezone().strftime("%d/%m/%Y %H:%M") if value else "—"


def main() -> None:
    CheckerApp().mainloop()


if __name__ == "__main__":
    main()
