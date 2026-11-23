"""Selection rules tab: what gets discarded, with how many listings each rule drops in
the chosen saved run, and a re-evaluation of that run with no API calls."""
import json
import tkinter as tk
from tkinter import ttk

import config
import deals
from ui_form import changed, get_key, make_field

# (key, label, kind, choices, reject reason it drives; a trailing "_" matches a prefix)
RULES = [
    ("budget.price_basis", "Price the limits are judged on", str, ("effective", "list"), None),
    ("rules.am4_min_ram_gb", "DDR4 (AM4, DDR4 Intel) minimum RAM, GB (Brief: 64)", int, ("16", "32", "48", "64"),
     "ddr4_under_"),
    ("rules.min_vram_gb", "Minimum GPU VRAM, GB (Brief: 12)", int, ("6", "8", "10", "12", "16"), "vram_under_"),
    ("rules.allow_intel", "Judge Intel case by case (off: drop all; 10th gen and older always dropped)", bool, None,
     "intel_"),
    ("rules.allow_arc", "Allow Intel Arc GPUs", bool, None, "intel_arc"),
    ("rules.allow_apu_x4", "Allow Ryzen 8500G / 8300G", bool, None, "apu_pcie_x4"),
    ("rules.allow_sff", "Allow Mini-ITX / small cases", bool, None, "itx_or_sff"),
    ("rules.allow_oem", "Allow OEM prebuilts (Dell, HP, Lenovo…)", bool, None, "oem_prebuilt"),
    ("rules.allow_mini_pc", "Allow mini-PCs / handhelds", bool, None, "mini_pc_or_handheld"),
    ("rules.pickup_only", "Pickup-only listings (Nur Abholung)", str, ("keep", "local_only", "drop"), "pickup_"),
    ("rules.misprice_share", "Mispriced below share of GPU + RAM value (0 = off)", float, None, "price_below_parts_value"),
    ("rules.scam_signals_drop", "Scam signals that drop a listing", int, None, "scam_signals"),
]
FIXES = [
    ("fixes.psu_min_w", "Stated PSU below this is a fix (W)", int),
    ("fixes.psu_min_24gb_w", "… for a 24 GB card (W)", int),
    ("fixes.psu_eur", "PSU fix (€)", int), ("fixes.psu_24gb_eur", "PSU fix for 24 GB cards (€)", int),
    ("fixes.cooler_eur", "Cooler fix (€)", int), ("fixes.ssd_eur", "SSD fix (€)", int),
    ("fixes.gpu_eur", "GPU for bundles / special cases (€)", int), ("fixes.case_eur", "Case for bundles (€)", int),
]


def reject_count(rejects: dict, reason: str | None) -> int:
    if not reason:
        return 0
    return sum(n for r, n in rejects.items() if (r.startswith(reason) if reason.endswith("_") else r == reason))


class RulesTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app, self.vars, self.counts = app, {}, {}
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Saved run to judge:").pack(side="left")
        self.run_var = tk.StringVar()
        self.run_box = ttk.Combobox(top, textvariable=self.run_var, width=28, state="readonly")
        self.run_box.pack(side="left", padx=6)
        self.run_box.bind("<<ComboboxSelected>>", lambda _: self.show_counts())
        self.btn = ttk.Button(top, text="Save rules and re-evaluate (no search)", command=self.reevaluate)
        self.btn.pack(side="left")
        ttk.Label(self, text="Numbers on the right: listings this rule throws out in the selected run "
                             "(each listing counts under the first rule that hits it).",
                  foreground="#555").pack(anchor="w", pady=(8, 4))
        body = ttk.Frame(self)
        body.pack(fill="x")
        rules_box = ttk.LabelFrame(body, text="What gets discarded", padding=8)
        rules_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        for row, (key, label, kind, choices, _) in enumerate(RULES):
            self.vars[key] = make_field(rules_box, row, label, kind, choices)
            self.counts[key] = ttk.Label(rules_box, text="", width=14, foreground="#7a4b00")
            self.counts[key].grid(row=row, column=2, sticky="w", padx=(10, 0))
        fix_box = ttk.LabelFrame(body, text="Fix costs added to the price", padding=8)
        fix_box.grid(row=0, column=1, sticky="nsew")
        for row, (key, label, kind) in enumerate(FIXES):
            self.vars[key] = make_field(fix_box, row, label, kind)
        body.columnconfigure(0, weight=1)
        ttk.Label(self, text="All rejects in the selected run", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        self.all_rejects = tk.Text(self, height=6, wrap="word", font=("Consolas", 9), state="disabled")
        self.all_rejects.pack(fill="both", expand=True)
        self.msg = ttk.Label(self, text="", wraplength=900, justify="left")
        self.msg.pack(anchor="w", pady=(6, 0))

    def load(self, data: dict) -> None:
        self.data = data
        for key, var in self.vars.items():
            var.set(get_key(data, key))
        self.refresh_runs()

    def refresh_runs(self, select: str | None = None) -> None:
        names = [p.name for p in deals.list_runs()]
        self.run_box.configure(values=names)
        if names:
            self.run_var.set(select if select in names else self.run_var.get() if self.run_var.get() in names else names[0])
        self.show_counts()

    def _stats(self) -> dict:
        name = self.run_var.get()
        path = deals.RUNS_DIR / name / "run.json" if name else None
        return json.loads(path.read_text(encoding="utf-8")).get("stats", {}) if path and path.exists() else {}

    def show_counts(self) -> None:
        rejects = self._stats().get("rejects", {})
        for key, *_, reason in RULES:
            n = reject_count(rejects, reason)
            self.counts[key].configure(text=f"drops {n}" if n else "—")
        lines = "\n".join(f"{n:5}  {r}" for r, n in sorted(rejects.items(), key=lambda x: -x[1])) or "No saved run yet."
        self.all_rejects.configure(state="normal")
        self.all_rejects.delete("1.0", "end")
        self.all_rejects.insert("1.0", lines)
        self.all_rejects.configure(state="disabled")

    def changes(self) -> dict:
        fields = [(k, lbl, kind) for k, lbl, kind, *_ in RULES] + FIXES
        return changed(fields, self.vars, self.data)

    def reevaluate(self) -> None:
        if not self.run_var.get():
            self.msg.configure(text="No saved run yet: run a search first.", foreground="#b00020")
            return
        try:
            edits = self.changes()
            if edits:
                config.save(edits)
            config.load()
        except ValueError as exc:
            self.msg.configure(text=str(exc), foreground="#b00020")
            return
        self.app.reload_settings()
        self.btn.configure(state="disabled")
        self.msg.configure(text="Re-evaluating…", foreground="#555")
        folder = deals.RUNS_DIR / self.run_var.get()   # read on the UI thread, not in the worker
        self.app.start_job(lambda: deals.review(folder), self.done)

    def done(self, summary: dict | None, error: str | None) -> None:
        self.btn.configure(state="normal")
        if error:
            self.msg.configure(text=error, foreground="#b00020")
            return
        self.refresh_runs(select=summary["folder"].name)
        self.msg.configure(text=summary["text"].splitlines()[0], foreground="#1b5e20")
