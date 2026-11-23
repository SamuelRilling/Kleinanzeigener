"""Fair used prices: the table an agent calibrates by hand (prompts/price_calibration.md)
from scraped listings, and the per-listing estimate built from it.

    fair € = whole_pc_factor × (GPU + CPU + RAM + board used prices) + base_eur

Part keys are exactly what `part_keys()` prints, and every run writes them per listing to
components.csv, so the table and the program always speak the same names. Pure, no I/O
except `load()`."""
import csv
import tomllib
from pathlib import Path

PARTS = ("gpu", "cpu", "ram", "board")
CSV_FIELDS = ("ad_id", "ask", "vb", "reject", "track", "gpu", "cpu", "ram", "board", "stated", "title", "url")


def load(path: Path) -> dict:
    """prices.toml -> {"meta": {...}, "gpu": {key: used €}, ...}; {} when the file does not
    exist yet. A wrong shape fails with one message per problem."""
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path.name} is not valid TOML: {exc}")
    meta, errors = data.get("meta", {}), []
    if not 0.5 <= meta.get("whole_pc_factor", 0) <= 1.5:
        errors.append("meta.whole_pc_factor: a number between 0.5 and 1.5")
    if not isinstance(meta.get("base_eur"), int) or meta["base_eur"] < 0:
        errors.append("meta.base_eur: a whole number of euros, 0 or more")
    table = {"meta": meta}
    for part in PARTS:
        table[part] = {}
        for key, entry in data.get(part, {}).items():
            used = entry.get("used") if isinstance(entry, dict) else None
            if not isinstance(used, int) or used <= 0:
                errors.append(f"{part}.\"{key}\": needs used = <euros>")
            else:
                table[part][key] = used
    if errors:
        raise ValueError(f"{path.name} has problems:\n  - " + "\n  - ".join(errors))
    return table


def part_keys(b: dict) -> dict:
    """The build's names in the price table: GPU model, CPU label, "DDR5 32 GB", chipset
    (or "<platform> board (unknown)"). None where the part is not known or is to be bought."""
    gpu, cpu = b["gpu"] or {}, b["cpu"] or {}
    platform = b["platform"]["v"]
    return {
        "gpu": None if gpu.get("to_buy") else gpu.get("name"),
        "cpu": cpu.get("label"),
        "ram": f"DDR{b['ddr']} {b['ram_gb']['v']} GB" if b["ddr"] else None,
        "board": b["chipset"] or (f"{platform} board (unknown)" if platform else None),
    }


def stated(b: dict) -> bool:
    """GPU (with VRAM), CPU model and RAM size all read from the text, none contradicted."""
    gpu, cpu = b["gpu"] or {}, b["cpu"] or {}
    return (bool(gpu) and gpu["vram_stated"] and not b["conflicts"] and bool(cpu.get("model"))
            and b["platform"]["src"] == "stated" and b["ram_gb"]["src"] == "stated")


def fair(b: dict, table: dict) -> dict | None:
    """{eur, parts {part: €}, stated} or {eur: None, missing [...]}; None without a table."""
    if not table:
        return None
    keys = part_keys(b)
    parts = {p: table[p].get(keys[p]) for p in PARTS}
    missing = [f"{p}: {keys[p]}" for p in PARTS if parts[p] is None]
    if missing:
        return {"eur": None, "missing": missing, "stated": False}
    meta = table["meta"]
    return {"eur": round(meta["whole_pc_factor"] * sum(parts.values()) + meta["base_eur"]), "parts": parts,
            "stated": stated(b)}


def write_components(path: Path, records: list[dict]) -> None:
    """One row per assessed listing with a GPU or CPU, in the price table's names: the
    agent's calibration data."""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, CSV_FIELDS)
        w.writeheader()
        for r in records:
            b = r["build"]
            if not (b["gpu"] or b["cpu"]):
                continue
            w.writerow({**part_keys(b), "ad_id": r["ad_id"], "ask": r["ask"], "vb": int(r["vb"]),
                        "reject": r["reject"] or "", "track": r["track"], "stated": int(stated(b)),
                        "title": r["title"], "url": r["url"]})
