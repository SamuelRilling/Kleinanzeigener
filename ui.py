"""Launcher window (stdlib tkinter), four tabs:
  1. Settings        search.toml as editable fields; "Save and start search"
  2. Selection rules what gets discarded, per-rule counts, re-evaluate a saved run offline
  3. Run             live counter and log of a search
  4. Results         a run as a table, card + full text with links, copy the AI prompt"""
import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

import config
import deals
from ui_form import changed, get_key, make_field, parse_list
from ui_results import ResultsTab
from ui_rules import RulesTab

POLL_MS = 100
NOISY_LOGGERS = ("httpx", "mcp", "main", "kleinanzeigen", "FastMCP")
# (key, label, type). Category, sort and AI files stay in search.toml ("Open file").
FIELDS = [
    ("Location", [("location.home_zip", "Home postcode", str),
                  ("location.local_radius_km", "Local radius (km, marks pickup-friendly)", int)]),
    ("Budget", [("budget.limit_eur", "Price limit (€; which price: Selection rules)", int),
                ("budget.target_eur", "Act-fast target (€)", int),
                ("budget.stretch_eur", "Stretch for tier 0-1 deals (€)", int),
                ("budget.am4_max_eur", "Cap for AM4 + 64 GB (€)", int),
                ("budget.vb_discount", "Expected VB haggle (0.05-0.15)", float),
                ("budget.special_max_eur", "Special cases: max incl. GPU (€)", int)]),
    ("Search", [("search.ask_min_eur", "Asking price from (€)", int),
                ("search.ask_max_eur", "Asking price to (€)", int),
                ("search.pages_per_term", "Pages per term (30 ads each)", int),
                ("search.max_requests", "Max search requests", int),
                ("search.max_details", "Max full listings read", int),
                ("search.delay_s", "Pause between requests (s)", float),
                ("search.full_text_all", "Read full text of every listing", bool),
                ("search.reuse_days", "Reuse saved full text up to (days)", int),
                ("bundles.enabled", "Search AM5 bundles too", bool)]),
]
LISTS = [("search.terms", "Search terms (GPUs, AM5, RAM)"), ("bundles.terms", "Bundle terms"),
         ("search.broad_terms", "Broad terms (searched last)")]


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
        self.geometry("1040x800")
        self.minsize(820, 600)
        self.q: queue.Queue = queue.Queue()
        self.vars: dict[str, tk.Variable] = {}
        self.texts: dict[str, tk.Text] = {}
        self.callback = None
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_settings()
        self.rules_tab = RulesTab(self.tabs, self)
        self.tabs.add(self.rules_tab, text="2. Selection rules")
        self._build_run()
        self.results_tab = ResultsTab(self.tabs, self)
        self.tabs.add(self.results_tab, text="4. Results")
        self.reload_settings()
        self.results_tab.refresh_runs()
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
                self.vars[key] = make_field(box, row, label, kind)
        for key, label in LISTS:
            ttk.Label(tab, text=f"{label} — separate with commas or new lines").pack(anchor="w", pady=(10, 2))
            text = tk.Text(tab, height=3, wrap="word", font=("Segoe UI", 9))
            text.pack(fill="x")
            self.texts[key] = text
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="Save and start search", command=self.save_and_start).pack(side="left")
        ttk.Button(bar, text="Save only", command=self.save).pack(side="left", padx=6)
        ttk.Button(bar, text="Undo changes", command=self.reload_settings).pack(side="left")
        ttk.Button(bar, text="Open file (advanced)", command=lambda: os.startfile(config.DEFAULT_FILE)).pack(side="right")
        self.form_msg = ttk.Label(tab, text="", foreground="#555", wraplength=940, justify="left")
        self.form_msg.pack(anchor="w", pady=(8, 0))

    def reload_settings(self) -> None:
        try:
            self.data = config.raw()
        except Exception as exc:  # unreadable TOML: say so, keep the window usable
            self.form_msg.configure(text=f"search.toml can't be read: {exc}", foreground="#b00020")
            return
        for key, var in self.vars.items():
            var.set(get_key(self.data, key))
        for key, text in self.texts.items():
            text.delete("1.0", "end")
            text.insert("1.0", ", ".join(get_key(self.data, key)))
        self.rules_tab.load(self.data)
        self.form_msg.configure(text="Edit the fields, then save. Category, sort and AI files: Open file.",
                                foreground="#555")

    def _changes(self) -> dict:
        edits = changed([f for _, fields in FIELDS for f in fields], self.vars, self.data)
        for key, text in self.texts.items():
            value = parse_list(text.get("1.0", "end"))
            if value != get_key(self.data, key):
                edits[key] = value
        return edits

    def save(self) -> bool:
        try:
            edits = self._changes()
            if edits:
                config.save(edits)
            config.load()   # also validates an unchanged file
        except ValueError as exc:
            self.form_msg.configure(text=str(exc), foreground="#b00020")
            return False
        self.reload_settings()
        self.form_msg.configure(text=f"Saved ({len(edits)} change{'s' if len(edits) != 1 else ''}).",
                                foreground="#1b5e20")
        return True

    def save_and_start(self) -> None:
        if self.save():
            self.tabs.select(2)
            self.start()

    # ---- run tab ----
    def _build_run(self) -> None:
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="3. Run")
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        self.run_btn = ttk.Button(bar, text="Start search", command=self.start)
        self.run_btn.pack(side="left")
        self.counter = ttk.Label(tab, text="Listings found: 0 · full listings: 0", font=("Segoe UI", 12, "bold"))
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
        self.counter.configure(text="Listings found: 0 · full listings: 0")
        self._show("Starting search…", replace=True)
        self.status.configure(text="Running. This takes a while; the site is queried politely.")
        self.start_job(lambda: deals.run(on_progress=lambda counts: self.q.put(("progress", counts))),
                       self._search_done)

    def _search_done(self, summary: dict | None, error: str | None) -> None:
        self.run_btn.configure(state="normal")
        if error:
            self.status.configure(text="Search failed. See the message above.")
            return
        self.status.configure(text=f"Done. Results in {summary['folder'].name}; see the Results tab.")
        self.rules_tab.refresh_runs(select=summary["folder"].name)

    def start_job(self, work, callback) -> None:
        """Run `work()` off the UI thread with the log attached; `callback(summary, error)` after."""
        self.callback = callback

        def job() -> None:
            handler = QueueHandler(self.q)
            handler.setFormatter(logging.Formatter("%(message)s"))
            log = logging.getLogger("deals")
            log.addHandler(handler)
            try:
                self.q.put(("done", work()))
            except Exception as exc:  # shown in the window instead of a silent dead thread
                self.q.put(("error", f"{type(exc).__name__}: {exc}"))
            finally:
                log.removeHandler(handler)

        threading.Thread(target=job, daemon=True).start()

    def _poll(self) -> None:
        while not self.q.empty():
            kind, payload = self.q.get()
            if kind == "progress":
                read = f"{payload['details_done']} / {payload['details_total']}" if payload["details_total"] else "0"
                self.counter.configure(text=f"Listings found: {payload['found']} · full listings: {read}")
            elif kind == "log":
                self._show(payload)
            elif kind == "error":
                self._show(payload, "error")
                self.callback(None, payload)
            else:
                self._show("\n" + payload["text"], "summary")
                self.callback(payload, None)
                self.results_tab.refresh_runs(select=payload["folder"].name)
                self.tabs.select(3)
        self.after(POLL_MS, self._poll)


def main() -> None:
    logging.getLogger("deals").setLevel(logging.INFO)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    App().mainloop()


if __name__ == "__main__":
    main()
