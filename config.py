"""search.toml -> validated, frozen Config. Fails with one clear message per bad field."""
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from policy import DEFAULT_POLICY, Policy

ROOT = Path(__file__).parent
DEFAULT_FILE = ROOT / "search.toml"
SORTS = {"DATE_DESCENDING", "PRICE_ASCENDING", "RECOMMENDED"}
# Policy field <- search.toml key. Missing keys fall back to the Policy default.
POLICY_KEYS = {
    "limit": "budget.limit_eur", "target": "budget.target_eur", "stretch": "budget.stretch_eur",
    "am4_max": "budget.am4_max_eur", "vb_discount": "budget.vb_discount", "special_max": "budget.special_max_eur",
    "am4_min_ram": "rules.am4_min_ram_gb", "min_vram": "rules.min_vram_gb", "allow_intel": "rules.allow_intel",
    "allow_arc": "rules.allow_arc", "allow_apu_x4": "rules.allow_apu_x4", "allow_sff": "rules.allow_sff",
    "allow_oem": "rules.allow_oem", "allow_mini_pc": "rules.allow_mini_pc",
    "misprice_share": "rules.misprice_share", "scam_signals_drop": "rules.scam_signals_drop",
    "fix_psu": "fixes.psu_eur", "fix_psu_24gb": "fixes.psu_24gb_eur", "fix_cooler": "fixes.cooler_eur",
    "fix_ssd": "fixes.ssd_eur", "fix_gpu": "fixes.gpu_eur", "fix_case": "fixes.case_eur",
}


@dataclass(frozen=True)
class Config:
    home_zip: str
    local_radius_km: int
    policy: Policy
    category: str
    ask_min: int
    ask_max: int
    sort: str
    pages_per_term: int
    max_requests: int
    max_details: int
    delay_s: float
    full_text_all: bool
    reuse_days: int
    terms: tuple[str, ...]
    broad_terms: tuple[str, ...]
    bundles_enabled: bool
    bundle_category: str
    bundle_terms: tuple[str, ...]
    prompt_file: Path
    attach: tuple[Path, ...]


def _get(data: dict, key: str, kind: type | tuple, errors: list[str]):
    section, name = key.split(".")
    value = data.get(section, {}).get(name)
    if value is None:
        errors.append(f"{key}: missing")
    elif not isinstance(value, kind) or isinstance(value, bool) and kind in (int, (int, float)):
        errors.append(f"{key}: expected {getattr(kind, '__name__', 'number')}, got {value!r}")
    return value


def load(path: Path | None = None) -> Config:
    path = path or DEFAULT_FILE   # resolved per call, so tests and tools can point elsewhere
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"{path.name} not found next to deals.py")
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path.name} is not valid TOML: {exc}")
    e: list[str] = []
    num = (int, float)
    cfg = dict(
        home_zip=_get(data, "location.home_zip", str, e), local_radius_km=_get(data, "location.local_radius_km", int, e),
        category=_get(data, "search.category", str, e), ask_min=_get(data, "search.ask_min_eur", int, e),
        ask_max=_get(data, "search.ask_max_eur", int, e), sort=_get(data, "search.sort", str, e),
        pages_per_term=_get(data, "search.pages_per_term", int, e), max_requests=_get(data, "search.max_requests", int, e),
        max_details=_get(data, "search.max_details", int, e), delay_s=_get(data, "search.delay_s", num, e),
        full_text_all=_opt(data, "search.full_text_all", True, e), reuse_days=_opt(data, "search.reuse_days", 7, e),
        terms=_get(data, "search.terms", list, e), broad_terms=_get(data, "search.broad_terms", list, e),
        bundles_enabled=_get(data, "bundles.enabled", bool, e),
        bundle_category=_get(data, "bundles.category", str, e), bundle_terms=_get(data, "bundles.terms", list, e),
        prompt_file=_get(data, "ai.prompt", str, e), attach=_get(data, "ai.attach", list, e),
    )
    policy = {f: _opt(data, key, getattr(DEFAULT_POLICY, f), e) for f, key in POLICY_KEYS.items()}
    if not e:
        e += _sanity(cfg, policy)
    if e:
        raise ValueError(f"{path.name} has problems:\n  - " + "\n  - ".join(e))
    return Config(**{**cfg, "terms": tuple(cfg["terms"]), "broad_terms": tuple(cfg["broad_terms"]),
                     "bundle_terms": tuple(cfg["bundle_terms"]),
                     "prompt_file": ROOT / cfg["prompt_file"], "attach": tuple(ROOT / a for a in cfg["attach"]),
                     "policy": Policy(**policy)})


def _opt(data: dict, key: str, default, errors: list[str]):
    """A setting that may be absent (default) but must have the default's type when present."""
    section, name = key.split(".")
    value = data.get(section, {}).get(name, default)
    kind = (int, float) if isinstance(default, float) else type(default)
    if not isinstance(value, kind) or (isinstance(value, bool) and not isinstance(default, bool)):
        errors.append(f"{key}: expected {type(default).__name__}, got {value!r}")
    return value


def _sanity(cfg: dict, policy: dict) -> list[str]:
    e = []
    if not (cfg["home_zip"].isdigit() and len(cfg["home_zip"]) == 5):
        e.append("location.home_zip: must be a 5-digit German postcode")
    if not 0 <= cfg["ask_min"] < cfg["ask_max"]:
        e.append("search.ask_min_eur must be below search.ask_max_eur")
    if cfg["sort"] not in SORTS:
        e.append(f"search.sort: one of {sorted(SORTS)}")
    if not 0 <= policy["vb_discount"] < 0.5:
        e.append("budget.vb_discount: a fraction such as 0.10")
    if policy["am4_min_ram"] not in (16, 32, 48, 64):
        e.append("rules.am4_min_ram_gb: one of 16, 32, 48, 64")
    if policy["min_vram"] not in (4, 6, 8, 10, 11, 12, 16, 20, 24):
        e.append("rules.min_vram_gb: a VRAM size such as 8, 12 or 16")
    if not 0 <= policy["misprice_share"] <= 1:
        e.append("rules.misprice_share: between 0 (off) and 1")
    if policy["scam_signals_drop"] < 1:
        e.append("rules.scam_signals_drop: at least 1")
    if any(policy[f] < 0 for f in POLICY_KEYS if f.startswith("fix_")) or cfg["reuse_days"] < 0:
        e.append("fixes / search.reuse_days: no negative values")
    if not policy["target"] <= policy["limit"]:
        e.append("budget.target_eur must not exceed budget.limit_eur")
    for key in ("pages_per_term", "max_requests", "max_details"):
        if cfg[key] < 1:
            e.append(f"search.{key}: must be at least 1")
    if not cfg["terms"] or not all(isinstance(t, str) and t.strip() for t in cfg["terms"]):
        e.append("search.terms: a non-empty list of words")
    if not all(isinstance(t, str) for t in cfg["broad_terms"] + cfg["bundle_terms"] + cfg["attach"]):
        e.append("search.broad_terms / bundles.terms / ai.attach: lists of text")
    return e


# ---- writing settings back (the launcher's form), keeping comments and layout ----
SECTION_RE = re.compile(r"^\[(\w+)\]")
LIST_WIDTH = 100


def raw(path: Path | None = None) -> dict:
    """search.toml as plain data, for filling the launcher's form."""
    path = path or DEFAULT_FILE
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    items = [json.dumps(v, ensure_ascii=False) for v in value]
    lines, line = [], "   "
    for item in items:
        if len(line) + len(item) + 2 > LIST_WIDTH:
            lines.append(line.rstrip())
            line = "   "
        line += f" {item},"
    return "[\n" + "\n".join(lines + [line.rstrip()]) + "\n]" if items else "[]"


def _split_comment(rest: str) -> tuple[str, str]:
    """('value', '   # comment') for one TOML line, '#' inside a string kept."""
    in_str = False
    for i, ch in enumerate(rest):
        if ch == '"':
            in_str = not in_str
        elif ch == "#" and not in_str:
            j = len(rest[:i].rstrip())
            return rest[:j], rest[j:]
    return rest.rstrip(), ""


def set_values(text: str, changes: dict) -> str:
    """Replace `section.key` values in TOML text; comments, order and spacing stay."""
    lines, out, section, i, done = text.splitlines(), [], None, 0, set()
    while i < len(lines):
        line = lines[i]
        if m := SECTION_RE.match(line):
            section = m.group(1)
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        full = f"{section}.{key}"
        if key and full in changes:
            value, comment = _split_comment(line.split("=", 1)[1])
            if value.strip().startswith("[") and value.count("[") > value.count("]"):
                while not lines[i].strip().startswith("]"):   # skip the rest of a multi-line list
                    i += 1
            new = f"{key} = {_toml(changes[full])}"
            comment_col = len(line) - len(comment.lstrip())   # keep comments aligned where they were
            out.append(new + (" " * max(1, comment_col - len(new)) + comment.lstrip() if comment else ""))
            done.add(full)
        else:
            out.append(line)
        i += 1
    missing = set(changes) - done
    if missing:
        raise ValueError(f"{DEFAULT_FILE.name}: no such setting {sorted(missing)}")
    return "\n".join(out) + "\n"


def save(changes: dict, path: Path | None = None) -> Config:
    """Write changed settings, but only if the result validates; the file is never left broken."""
    path = path or DEFAULT_FILE
    tmp = path.with_name(path.stem + ".tmp.toml")
    tmp.write_text(set_values(path.read_text(encoding="utf-8"), changes), encoding="utf-8")
    try:
        cfg = load(tmp)
    except ValueError as exc:
        tmp.unlink()
        raise ValueError(str(exc).replace(tmp.name, path.name)) from None
    tmp.replace(path)
    return cfg
