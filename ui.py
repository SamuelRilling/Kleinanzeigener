"""Launcher window: shows search.toml for confirmation, runs the search in the same
window with a live log, then shows the summary and opens the results. Stdlib only."""
import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

import config
import deals

POLL_MS = 100
NOISY_LOGGERS = ("httpx", "mcp", "main", "kleinanzeigen", "FastMCP")


def describe(cfg: config.Config) -> str:
    b = cfg.budget
    return "\n".join([
        f"Home: {cfg.home_zip}, local radius {cfg.local_radius_km} km (marks pickup-friendly listings, no filter)",
        f"Budget: effective ≤ {b.limit} € (target {b.target} €, very good deals up to {b.limit + b.stretch} €), "
        f"AM4 ≤ {b.am4_max} €, VB haggle {b.vb_discount:.0%}",
        f"Search: {cfg.category}, asking {cfg.ask_min}–{cfg.ask_max} €, {cfg.sort}, {len(cfg.terms)} terms, "
        f"≤ {cfg.pages_per_term} pages each",
        f"Limits: {cfg.max_requests} search requests, {cfg.max_details} full listings, {cfg.delay_s} s pause",
        f"Bundles: {'on, ' + str(len(cfg.bundle_terms)) + ' terms in ' + cfg.bundle_category if cfg.bundles_enabled else 'off'}",
        f"Terms: {', '.join(cfg.terms)}",
    ])


class QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put(("log", self.format(record)))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Kleinanzeigen PC search")
        self.geometry("900x640")
        self.minsize(640, 420)
        self.q: queue.Queue = queue.Queue()
        self.folder = None
        self._build()
        self.reload()
        self.after(POLL_MS, self._poll)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Settings (search.toml)", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.settings = tk.Text(top, height=7, wrap="word", font=("Segoe UI", 9), relief="flat", background="#f4f4f4")
        self.settings.pack(fill="x", pady=(4, 8))
        bar = ttk.Frame(top)
        bar.pack(fill="x")
        self.run_btn = ttk.Button(bar, text="Confirm and start search", command=self.start)
        self.run_btn.pack(side="left")
        ttk.Button(bar, text="Edit settings", command=lambda: os.startfile(config.DEFAULT_FILE)).pack(side="left", padx=6)
        ttk.Button(bar, text="Reload", command=self.reload).pack(side="left")
        self.open_btn = ttk.Button(bar, text="Open results", command=self.open_results, state="disabled")
        self.open_btn.pack(side="right")
        self.status = ttk.Label(top, text="", foreground="#555")
        self.status.pack(anchor="w", pady=(6, 0))
        self.log = tk.Text(self, wrap="word", font=("Consolas", 9), state="disabled")
        self.log.tag_config("error", foreground="#b00020")
        self.log.tag_config("summary", font=("Consolas", 10, "bold"))
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _show(self, widget: tk.Text, text: str, tag: str | None = None, replace: bool = False) -> None:
        widget.configure(state="normal")
        if replace:
            widget.delete("1.0", "end")
        widget.insert("end", text + "\n", tag or ())
        widget.see("end")
        widget.configure(state="disabled")

    def reload(self) -> None:
        try:
            cfg = config.load()
        except ValueError as exc:
            self._show(self.settings, str(exc), replace=True)
            self.settings.tag_add("error", "1.0", "end")
            self.run_btn.configure(state="disabled")
            self.status.configure(text="Fix search.toml, save, then press Reload.")
            return
        self._show(self.settings, describe(cfg), replace=True)
        self.run_btn.configure(state="normal")
        self.status.configure(text="Check the settings, then confirm.")

    def start(self) -> None:
        self.run_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self._show(self.log, "Starting search…", replace=True)
        self.status.configure(text="Running. This takes a few minutes; the site is queried politely.")
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        handler = QueueHandler(self.q)
        handler.setFormatter(logging.Formatter("%(message)s"))
        log = logging.getLogger("deals")
        log.addHandler(handler)
        try:
            self.q.put(("done", deals.run()))
        except Exception as exc:  # shown in the window instead of a silent dead thread
            self.q.put(("error", f"{type(exc).__name__}: {exc}"))
        finally:
            log.removeHandler(handler)

    def _poll(self) -> None:
        while not self.q.empty():
            kind, payload = self.q.get()
            if kind == "log":
                self._show(self.log, payload)
            elif kind == "error":
                self._show(self.log, payload, "error")
                self.status.configure(text="Search failed. See the message above.")
                self.run_btn.configure(state="normal")
            else:
                self.folder = payload["folder"]
                self._show(self.log, "\n" + payload["text"], "summary")
                self.status.configure(text=f"Done. Results in {self.folder.name}.")
                self.run_btn.configure(state="normal")
                self.open_btn.configure(state="normal")
        self.after(POLL_MS, self._poll)

    def open_results(self) -> None:
        if self.folder:
            os.startfile(self.folder / "results.md")
            os.startfile(self.folder)


def main() -> None:
    logging.getLogger("deals").setLevel(logging.INFO)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    App().mainloop()


if __name__ == "__main__":
    main()
