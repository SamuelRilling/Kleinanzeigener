"""Results tab: a saved run as a table (double-click opens the listing), the full card and
listing text of the selected row with clickable links, and one-click copy of the AI prompt."""
import json
import os
import re
import tkinter as tk
import webbrowser
from tkinter import ttk

import config
import deals
import report

URL_RE = re.compile(r"(https?://\S+)")
SECTIONS = ("Underpriced", "Featured", "Passing, not featured", "Bundles", "Special cases", "Closest misses",
            "Filtered")
PRICE_PROMPT = config.ROOT / "prompts" / "price_calibration.md"
MISSES_SHOWN = 15
COLUMNS = (("section", "Section", 140), ("ask", "List €", 55), ("eff", "Eff. €", 55), ("worst", "Worst €", 60),
           ("fair", "Fair €", 55), ("delta", "Δ", 45), ("tier", "Tier", 40), ("title", "Listing", 300),
           ("where", "Where", 210), ("flags", "Flags", 260))


def group(records: list[dict]) -> list[tuple[str, dict]]:
    """(section, record) in report order."""
    passed = [r for r in records if not r["reject"]]
    misses = sorted((r for r in records if r["reject"] in ("over_budget", "am4_over_550")),
                    key=lambda r: r.get("budget", r["effective"]))
    under = sorted((r for r in passed + misses if r.get("value") == "under"), key=lambda r: r["fair_delta"])
    return ([("Underpriced", r) for r in under]
            + [("Featured", r) for r in passed if r["track"] == "pc" and r.get("featured")]
            + [("Passing, not featured", r) for r in passed if r["track"] == "pc" and not r.get("featured")]
            + [("Bundles", r) for r in passed if r["track"] == "bundle"]
            + [("Special cases", r) for r in records if r["special"]]
            + [("Closest misses", r) for r in misses[:MISSES_SHOWN]]
            + [("Filtered", r) for r in records if r["reject"] in report.MISPRICE_REJECTS])


def details(r: dict) -> str:
    """The verification card for a passing listing, a short verdict + text for the rest."""
    if r["tier"] is not None and not r["reject"]:
        return report.card(1, r).replace("### 1. ", "", 1)
    c = report.build_cells(r)
    text = " · ".join(" ".join(p.split()) for p in report.CLAUSE_SPLIT_RE.split(r["description"]) if p.strip())
    why = r["reject"] + (f" (GPU + RAM alone worth ≥ {r['parts_floor']} €)" if r["reject"] == "price_below_parts_value" else "")
    return (f"{r['title']}\n{r['url']} · {report.ask_txt(r)} · {report.where(r)}\n- Rejected: {why}"
            f"{' (a special case: worth it with a GPU bought)' if r['special'] else ''}\n- CPU {c['cpu']} · RAM {c['ram']} "
            f"· GPU {c['gpu']} · PSU {c['psu']} · SSD {c['ssd']}\n- Fixes {report.fixes_txt(r)} → effective "
            f"{report.eff_txt(r)} € · flags: {', '.join(r['flags'] + r['scam']) or '—'}\n\n> {text}")


class ResultsTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app, self.rows, self.folder = app, {}, None
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Run:").pack(side="left")
        self.run_var = tk.StringVar()
        self.run_box = ttk.Combobox(top, textvariable=self.run_var, width=28, state="readonly")
        self.run_box.pack(side="left", padx=6)
        self.run_box.bind("<<ComboboxSelected>>", lambda _: self.show(deals.RUNS_DIR / self.run_var.get()))
        ttk.Button(top, text="Copy AI prompt", command=lambda: self.copy_prompt("ai_prompt.md")).pack(
            side="left", padx=(12, 0))
        ttk.Button(top, text="Copy offer prompt", command=lambda: self.copy_prompt("offer_prompt.md")).pack(
            side="left", padx=(6, 0))
        ttk.Button(top, text="Copy performance prompt",
                   command=lambda: self.copy_prompt("performance_prompt.md")).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Copy price prompt", command=self.copy_price_prompt).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Open results.md", command=lambda: self._open("results.md")).pack(side="left", padx=6)
        ttk.Button(top, text="Open folder", command=lambda: self._open("")).pack(side="left")
        self.summary = ttk.Label(self, text="", wraplength=940, justify="left")
        self.summary.pack(anchor="w", pady=(8, 4))
        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True)
        table = ttk.Frame(panes)
        self.tree = ttk.Treeview(table, columns=[c for c, *_ in COLUMNS], show="headings", height=12)
        for col, title, width in COLUMNS:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=col in ("title", "flags"))
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _: self._select())
        self.tree.bind("<Double-1>", lambda _: self._open_listing())
        colors = ("#c8e6c9", "#e8f5e9", "#fffde7", "#e3f2fd", "#f3e5f5", "#fff3e0", "#fbe9e7")
        for section, color in zip(SECTIONS, colors):
            self.tree.tag_configure(section, background=color)
        panes.add(table, weight=3)
        self.text = tk.Text(panes, wrap="word", font=("Segoe UI", 9), state="disabled")
        self.text.tag_config("link", foreground="#0b57d0", underline=True)
        self.text.tag_bind("link", "<Button-1>", self._click_link)
        self.text.tag_bind("link", "<Enter>", lambda _: self.text.configure(cursor="hand2"))
        self.text.tag_bind("link", "<Leave>", lambda _: self.text.configure(cursor=""))
        panes.add(self.text, weight=2)

    def refresh_runs(self, select: str | None = None) -> None:
        names = [p.name for p in deals.list_runs()]
        self.run_box.configure(values=names)
        if names:
            self.run_var.set(select if select in names else names[0])
            self.show(deals.RUNS_DIR / self.run_var.get())

    def show(self, folder) -> None:
        self.folder = folder
        run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        stats = run.get("stats", {})
        basis = run.get("settings", {}).get("policy", {}).get("price_basis", "effective")
        with (folder / "listings.jsonl").open(encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        grouped = group(records)
        counts = {s: sum(1 for g, _ in grouped if g == s) for s in SECTIONS}
        source = f"re-evaluation of {stats['review_of']}" if stats.get("review_of") else "search"
        self.summary.configure(text=f"{folder.name} ({source}): {stats.get('unique', len(records))} listings · "
                                    + " · ".join(f"{s}: {n}" for s, n in counts.items())
                                    + f"\nBudget judged on the {basis} price. Worst € adds the fixes the listing "
                                      "leaves open. Double-click a row to open the listing; links below are clickable.")
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        for i, (section, r) in enumerate(grouped):
            iid = str(i)
            tier = "" if r["tier"] is None else r["tier"]
            self.tree.insert("", "end", iid=iid, tags=(section,), values=(
                section, f"{r['ask']:g}", r["effective"], r.get("worst", r["effective"]), r.get("fair") or "",
                report.delta_txt(r), tier, r["title"][:90],
                report.where(r),
                ", ".join(r["flags"] + ([r["reject"]] if r["reject"] else []))))
            self.rows[iid] = r
        self._show_text("Select a row to see its card and full listing text." if grouped else
                        "Nothing to show in this run.")

    def _select(self) -> None:
        sel = self.tree.selection()
        if sel:
            self._show_text(details(self.rows[sel[0]]))

    def _show_text(self, body: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for part in URL_RE.split(body):   # URLs become clickable links
            self.text.insert("end", part, ("link",) if URL_RE.fullmatch(part) else ())
        self.text.configure(state="disabled")

    def _click_link(self, event) -> None:
        start = self.text.index(f"@{event.x},{event.y}")
        ranges = self.text.tag_prevrange("link", start + "+1c")
        if ranges:
            webbrowser.open(self.text.get(*ranges).strip())

    def _open_listing(self) -> None:
        sel = self.tree.selection()
        if sel and self.rows[sel[0]].get("url"):
            webbrowser.open(self.rows[sel[0]]["url"])

    def copy_price_prompt(self) -> None:
        """The calibration prompt, pointed at this run's components.csv and the current table."""
        if not self.folder:
            return
        table = config.ROOT / "prices.toml"
        current = table.read_text(encoding="utf-8") if table.exists() else "(none yet: start from the template)"
        text = (PRICE_PROMPT.read_text(encoding="utf-8") + f"\n\n---\n\nDataset: {self.folder / 'components.csv'}\n"
                f"Full listings: {self.folder / 'listings.jsonl'}\nWrite the result to: {table}\n\n"
                f"Current prices.toml:\n```toml\n{current}\n```\n")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.summary.configure(text="Price calibration prompt copied, pointed at " + self.folder.name + ".")

    def copy_prompt(self, name: str) -> None:
        """A prompt file of this run; runs made before the comparison prompts have only ai_prompt.md."""
        if not self.folder:
            return
        path = self.folder / name
        head = self.summary.cget("text").split("\n")[0]
        if not path.exists():
            self.summary.configure(text=head + f"\n{name} is not in this run (an older run): re-evaluate it to add it.")
            return
        self.clipboard_clear()
        self.clipboard_append(path.read_text(encoding="utf-8"))
        self.summary.configure(text=head + f"\n{name} copied to the clipboard.")

    def _open(self, name: str) -> None:
        if self.folder:
            os.startfile(self.folder / name if name else self.folder)

