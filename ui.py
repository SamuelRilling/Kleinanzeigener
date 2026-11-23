"""Launcher window. Settings tab: search.toml as editable fields; "Save and start"
validates and saves, then switches to the Run tab, which shows a live counter, the
log and the summary. Stdlib only (tkinter)."""
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
# (section.key, label, type). Category, sort and AI files stay in search.toml ("Open file").
FIELDS = [
    ("Location", [("location.home_zip", "Home postcode", str),
                  ("location.local_radius_km", "Local radius (km, marks pickup-friendly)", int)]),
    ("Budget", [("budget.limit_eur", "Effective price limit (€)", int),
                ("budget.target_eur", "Act-fast target (€)", int),
                ("budget.stretch_eur", "Stretch for tier 0-1 deals (€)", int),
                ("budget.am4_max_eur", "Cap for AM4 + 64 GB (€)", int),
                ("budget.vb_discount", "Expected VB haggle (0.05-0.15)", float),
                ("budget.special_max_eur", "Special cases: max incl. GPU (€)", int),
                ("rules.am4_min_ram_gb", "AM4 minimum RAM (GB; Brief: 64)", int)]),
    ("Search", [("search.ask_min_eur", "Asking price from (€)", int),
                ("search.ask_max_eur", "Asking price to (€)", int),
                ("search.pages_per_term", "Pages per term (30 ads each)", int),
                ("search.max_requests", "Max search requests", int),
                ("search.max_details", "Max full listings read", int),
                ("search.delay_s", "Pause between requests (s)", float),
                ("bundles.enabled", "Search AM5 bundles too", bool)]),
]
LISTS = [("search.terms", "Search terms (GPUs, AM5, RAM)"), ("bundles.terms", "Bundle terms"),
         ("search.broad_terms", "Broad terms (searched last)")]
AM4_RAM_CHOICES = ("16", "32", "48", "64")


def _get(data: dict, key: str):
    section, name = key.split(".")
    return data[section][name]


def _parse_list(text: str) -> list[str]:
    """Comma- or line-separated words -> list, blanks dropped."""
    return [t.strip() for t in text.replace("\n", ",").split(",") if t.strip()]


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
        self.geometry("980x760")
        self.minsize(760, 560)
        self.q: queue.Queue = queue.Queue()
        self.folder = None
        self.vars: dict[str, tk.Variable] = {}
        self.texts: dict[str, tk.Text] = {}
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_settings()
        self._build_run()
        self.load_form()
        self.after(POLL_MS, self._poll)

    # ---- settings tab ----
    def _build_settings(self) -> None:
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="1. Settings")
        grid = ttk.Frame(tab)
        grid.pack(fill="x")
        for col, (title, fields) in enumerate(FIELDS):
            box = ttk.LabelFrame(grid, text=title, padding=8)
            box.grid(row=0, column=col, sticky="nsew", padx=4)
            grid.columnconfigure(col, weight=1)
            for row, (key, label, kind) in enumerate(fields):
                ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=2)
                if kind is bool:
                    var = tk.BooleanVar()
                    ttk.Checkbutton(box, variable=var).grid(row=row, column=1, sticky="w")
                elif key == "rules.am4_min_ram_gb":
                    var = tk.StringVar()
                    ttk.Combobox(box, textvariable=var, values=AM4_RAM_CHOICES, width=8,
                                 state="readonly").grid(row=row, column=1, sticky="w")
                else:
                    var = tk.StringVar()
                    ttk.Entry(box, textvariable=var, width=10).grid(row=row, column=1, sticky="w", padx=(6, 0))
                self.vars[key] = var
        for key, label in LISTS:
            ttk.Label(tab, text=f"{label} — separate with commas or new lines").pack(anchor="w", pady=(10, 2))
            text = tk.Text(tab, height=3, wrap="word", font=("Segoe UI", 9))
            text.pack(fill="x")
            self.texts[key] = text
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="Save and start search", command=self.save_and_start).pack(side="left")
        ttk.Button(bar, text="Save only", command=self.save).pack(side="left", padx=6)
        ttk.Button(bar, text="Undo changes", command=self.load_form).pack(side="left")
        ttk.Button(bar, text="Open file (advanced)", command=lambda: os.startfile(config.DEFAULT_FILE)).pack(side="right")
        self.form_msg = ttk.Label(tab, text="", foreground="#555", wraplength=900, justify="left")
        self.form_msg.pack(anchor="w", pady=(8, 0))

    def load_form(self) -> None:
        try:
            self.data = config.raw()
        except Exception as exc:  # unreadable TOML: say so, keep the window usable
            self.form_msg.configure(text=f"search.toml can't be read: {exc}", foreground="#b00020")
            return
        for key, var in self.vars.items():
            var.set(_get(self.data, key))
        for key, text in self.texts.items():
            text.delete("1.0", "end")
            text.insert("1.0", ", ".join(_get(self.data, key)))
        self.form_msg.configure(text="Edit the fields, then save. Category, sort and AI files: Open file.",
                                foreground="#555")

    def _changes(self) -> dict:
        """Only the fields that differ from the file, typed; ValueError names the bad field."""
        kinds = {key: kind for _, fields in FIELDS for key, _, kind in fields}
        changes = {}
        for key, var in self.vars.items():
            kind = int if key == "rules.am4_min_ram_gb" else kinds[key]
            try:
                value = var.get() if kind is bool else kind(str(var.get()).strip().replace(",", "."))
            except (ValueError, tk.TclError):
                label = next(lbl for _, f in FIELDS for k, lbl, _ in f if k == key)
                raise ValueError(f"{label}: not a valid {kind.__name__}")
            if value != _get(self.data, key):
                changes[key] = value
        for key, text in self.texts.items():
            value = _parse_list(text.get("1.0", "end"))
            if value != _get(self.data, key):
                changes[key] = value
        return changes

    def save(self) -> bool:
        try:
            changes = self._changes()
            if changes:
                config.save(changes)
            config.load()   # also validates an unchanged file
        except ValueError as exc:
            self.form_msg.configure(text=str(exc), foreground="#b00020")
            return False
        self.load_form()
        self.form_msg.configure(text=f"Saved ({len(changes)} change{'s' if len(changes) != 1 else ''}).",
                                foreground="#1b5e20")
        return True

    def save_and_start(self) -> None:
        if self.save():
            self.tabs.select(1)
            self.start()

    # ---- run tab ----
    def _build_run(self) -> None:
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="2. Run")
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        self.run_btn = ttk.Button(bar, text="Start search", command=self.start)
        self.run_btn.pack(side="left")
        self.open_btn = ttk.Button(bar, text="Open results", command=self.open_results, state="disabled")
        self.open_btn.pack(side="right")
        self.counter = ttk.Label(tab, text="Listings found: 0 · full listings read: 0", font=("Segoe UI", 12, "bold"))
        self.counter.pack(anchor="w", pady=(10, 2))
        self.status = ttk.Label(tab, text="Start from the Settings tab, or press Start search.", foreground="#555")
        self.status.pack(anchor="w")
        self.log = tk.Text(tab, wrap="word", font=("Consolas", 9), state="disabled")
        self.log.tag_config("error", foreground="#b00020")
        self.log.tag_config("summary", font=("Consolas", 10, "bold"))
        self.log.pack(fill="both", expand=True, pady=(8, 0))

    def _show(self, text: str, tag: str | None = None, replace: bool = False) -> None:
        self.log.configure(state="normal")
        if replace:
            self.log.delete("1.0", "end")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self) -> None:
        self.run_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.counter.configure(text="Listings found: 0 · full listings read: 0")
        self._show("Starting search…", replace=True)
        self.status.configure(text="Running. This takes a while; the site is queried politely.")
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        handler = QueueHandler(self.q)
        handler.setFormatter(logging.Formatter("%(message)s"))
        log = logging.getLogger("deals")
        log.addHandler(handler)
        try:
            self.q.put(("done", deals.run(on_progress=lambda counts: self.q.put(("progress", counts)))))
        except Exception as exc:  # shown in the window instead of a silent dead thread
            self.q.put(("error", f"{type(exc).__name__}: {exc}"))
        finally:
            log.removeHandler(handler)

    def _poll(self) -> None:
        while not self.q.empty():
            kind, payload = self.q.get()
            if kind == "progress":
                read = f"{payload['details_done']} / {payload['details_total']}" if payload["details_total"] else "0"
                self.counter.configure(text=f"Listings found: {payload['found']} · full listings read: {read}")
            elif kind == "log":
                self._show(payload)
            elif kind == "error":
                self._show(payload, "error")
                self.status.configure(text="Search failed. See the message above.")
                self.run_btn.configure(state="normal")
            else:
                self.folder = payload["folder"]
                self._show("\n" + payload["text"], "summary")
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
