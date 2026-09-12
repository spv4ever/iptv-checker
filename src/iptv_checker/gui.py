"""Interfaz grafica para comprobar una lista de URLs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import messagebox, ttk

from .checker import CheckResult, PlaylistChecker
from .playlist import Channel, parse_urls


class CheckerApp(tk.Tk):
    """Ventana principal de la aplicacion."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Comprobador de URLs")
        self.geometry("900x620")
        self.minsize(700, 480)
        self.results: Queue[CheckResult | None] = Queue()
        self.total = 0
        self.completed = 0
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


def main() -> None:
    CheckerApp().mainloop()


if __name__ == "__main__":
    main()
