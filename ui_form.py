"""Form helpers shared by the launcher tabs: one field per search.toml key, typed
reading, and "what changed" against the file."""
import tkinter as tk
from tkinter import ttk


def get_key(data: dict, key: str):
    section, name = key.split(".")
    return data[section][name]


def make_field(parent, row: int, label: str, kind: type, choices: tuple | None = None, col: int = 0) -> tk.Variable:
    ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", pady=2)
    if kind is bool:
        var = tk.BooleanVar()
        ttk.Checkbutton(parent, variable=var).grid(row=row, column=col + 1, sticky="w")
    elif choices:
        var = tk.StringVar()
        ttk.Combobox(parent, textvariable=var, values=choices, width=8, state="readonly").grid(
            row=row, column=col + 1, sticky="w")
    else:
        var = tk.StringVar()
        ttk.Entry(parent, textvariable=var, width=10).grid(row=row, column=col + 1, sticky="w", padx=(6, 0))
    return var


def typed(var: tk.Variable, kind: type, label: str):
    """The field's value as `kind`; ValueError names the field."""
    try:
        return var.get() if kind is bool else kind(str(var.get()).strip().replace(",", "."))
    except (ValueError, tk.TclError):
        raise ValueError(f"{label}: not a valid {kind.__name__}") from None


def changed(fields: list[tuple], vars_: dict, data: dict) -> dict:
    """{key: new value} for fields (key, label, kind, ...) that differ from `data`."""
    out = {}
    for key, label, kind, *_ in fields:
        value = typed(vars_[key], kind, label)
        if value != get_key(data, key):
            out[key] = value
    return out


def parse_list(text: str) -> list[str]:
    """Comma- or line-separated words -> list, blanks dropped."""
    return [t.strip() for t in text.replace("\n", ",").split(",") if t.strip()]
