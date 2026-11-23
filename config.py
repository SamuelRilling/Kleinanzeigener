"""search.toml -> validated, frozen Config. Fails with one clear message per bad field."""
import tomllib
from dataclasses import dataclass
from pathlib import Path

from rules import Budget

ROOT = Path(__file__).parent
DEFAULT_FILE = ROOT / "search.toml"
SORTS = {"DATE_DESCENDING", "PRICE_ASCENDING", "RECOMMENDED"}


@dataclass(frozen=True)
class Config:
    home_zip: str
    local_radius_km: int
    budget: Budget
    category: str
    ask_min: int
    ask_max: int
    sort: str
    pages_per_term: int
    max_requests: int
    max_details: int
    delay_s: float
    terms: tuple[str, ...]
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


def load(path: Path = DEFAULT_FILE) -> Config:
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
        terms=_get(data, "search.terms", list, e), bundles_enabled=_get(data, "bundles.enabled", bool, e),
        bundle_category=_get(data, "bundles.category", str, e), bundle_terms=_get(data, "bundles.terms", list, e),
        prompt_file=_get(data, "ai.prompt", str, e), attach=_get(data, "ai.attach", list, e),
    )
    budget = {f: _get(data, f"budget.{key}", num if f == "vb_discount" else int, e) for f, key in (
        ("limit", "limit_eur"), ("target", "target_eur"), ("stretch", "stretch_eur"), ("am4_max", "am4_max_eur"),
        ("vb_discount", "vb_discount"), ("special_max", "special_max_eur"))}
    if not e:
        e += _sanity(cfg, budget)
    if e:
        raise ValueError(f"{path.name} has problems:\n  - " + "\n  - ".join(e))
    return Config(**{**cfg, "terms": tuple(cfg["terms"]), "bundle_terms": tuple(cfg["bundle_terms"]),
                     "prompt_file": ROOT / cfg["prompt_file"], "attach": tuple(ROOT / a for a in cfg["attach"]),
                     "budget": Budget(**budget)})


def _sanity(cfg: dict, budget: dict) -> list[str]:
    e = []
    if not (cfg["home_zip"].isdigit() and len(cfg["home_zip"]) == 5):
        e.append("location.home_zip: must be a 5-digit German postcode")
    if not 0 <= cfg["ask_min"] < cfg["ask_max"]:
        e.append("search.ask_min_eur must be below search.ask_max_eur")
    if cfg["sort"] not in SORTS:
        e.append(f"search.sort: one of {sorted(SORTS)}")
    if not 0 <= budget["vb_discount"] < 0.5:
        e.append("budget.vb_discount: a fraction such as 0.10")
    if not budget["target"] <= budget["limit"]:
        e.append("budget.target_eur must not exceed budget.limit_eur")
    for key in ("pages_per_term", "max_requests", "max_details"):
        if cfg[key] < 1:
            e.append(f"search.{key}: must be at least 1")
    if not cfg["terms"] or not all(isinstance(t, str) and t.strip() for t in cfg["terms"]):
        e.append("search.terms: a non-empty list of words")
    if not all(isinstance(t, str) for t in cfg["bundle_terms"] + cfg["attach"]):
        e.append("bundles.terms / ai.attach: lists of text")
    return e
