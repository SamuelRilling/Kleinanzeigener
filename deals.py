"""Kleinanzeigen used AI/workstation PC search: no input after launch.

Settings: search.toml. Pipeline:
  1. local sweep: the whole category within local_radius_km (pickup is a plus)
  2. nationwide: every search term, newest first (+ the bundle track, Priming §5.1)
  3. dedupe, snippet-level rejects, full details for the best-ranked survivors
  4. the Brief as code (rules.py): rejects, effective price, tiers, ranking
  5. runs/<date_time>/: results.md, ai_prompt.md, listings.jsonl, raw.jsonl, run.json

Usage:  python deals.py            (or launch.bat for the window)
"""
import asyncio
import json
import logging
import statistics
import sys
from datetime import datetime
from pathlib import Path

import config
import report
import rules
from policy import Policy

MCP_DIR = r"C:\Users\Samuel\.config\opencode\mcp\kleinanzeigen-mcp"
RUNS_DIR = config.ROOT / "runs"
STATE_FILE = RUNS_DIR / "seen.json"
MARKET_MIN_SAMPLES = 4
INCOMPLETE_ERROR_SHARE = 0.2      # more failed detail fetches than this -> results marked INCOMPLETE
OVER_BUDGET_DETAIL_SLACK = 100    # snippet over policy by up to this may still pass with the full text

log = logging.getLogger("deals")

# Rejects that a fuller description cannot undo.
FINAL_AT_SNIPPET = {"intel_platform", "intel_arc", "not_desktop", "mini_pc_or_handheld", "wanted_ad", "trade_only",
                    "reserved", "oem_prebuilt", "gpu_only", "no_price", "placeholder_price", "price_not_for_whole_pc"}


class Progress:
    """Live counts for the launcher: unique listings found so far, full listings read."""

    def __init__(self, callback=None):
        self.callback, self.ids, self.done, self.total = callback, set(), 0, 0

    def found(self, ads: list[dict]) -> None:
        self.ids.update(a["id"] for a in ads)
        self._emit()

    def detail(self, done: int, total: int) -> None:
        self.done, self.total = done, total
        self._emit()

    def _emit(self) -> None:
        if self.callback:
            self.callback({"found": len(self.ids), "details_done": self.done, "details_total": self.total})


async def call(client, tool: str, args: dict, stats: dict) -> dict | None:
    """Tool call -> parsed dict, or None (logged + counted). The MCP server already
    retries 429/5xx with backoff, so a failure here is final for this item."""
    try:
        res = await client.call_tool(tool, args)
        text = res.content[0].text
        if getattr(res, "isError", False) or text.startswith("Error"):
            raise RuntimeError(text[:160])
        return json.loads(text)
    except Exception as exc:  # one bad ad must not kill the run
        stats["errors"].append(f"{tool} {args.get('query') or args.get('ad_id') or ''}: {str(exc)[:120]}")
        log.warning("  ! %s %s: %s", tool, args.get("query") or args.get("ad_id"), exc)
        return None


async def search(client, cfg: config.Config, stats: dict, label: str, extra: dict, progress: Progress) -> dict:
    """All pages of one search (up to pages_per_term) -> {id: hit}."""
    hits = {}
    for page in range(cfg.pages_per_term):
        if stats["requests"] >= cfg.max_requests:
            stats["capped"] = True
            break
        args = {"category": cfg.category, "min_price": cfg.ask_min, "max_price": cfg.ask_max, "sort": cfg.sort,
                "ad_type": "OFFERED", "rows": 30, "page": page, **extra}
        data = await call(client, "search_kleinanzeigen", args, stats)
        stats["requests"] += 1
        await asyncio.sleep(cfg.delay_s)
        ads = (data or {}).get("results", [])
        hits.update({a["id"]: a for a in ads})
        progress.found(ads)
        if not data or not data.get("has_more"):
            break
    stats["terms"][label] = len(hits)
    log.info("[%s] %d ads · %d listings found in total", label, len(hits), len(progress.ids))
    return hits


async def discover(client, cfg: config.Config, stats: dict, progress: Progress) -> list[dict]:
    """Local sweep, specific terms, bundles, then the broad terms last: they match the
    most listings, so the request cap cuts them first."""
    local = await search(client, cfg, stats, f"local {cfg.local_radius_km} km (all)",
                         {"zip_code": cfg.home_zip, "distance_km": cfg.local_radius_km}, progress)
    hits = {}
    for term in cfg.terms:
        hits.update(await search(client, cfg, stats, term, {"query": term}, progress))
    if cfg.bundles_enabled:
        for term in cfg.bundle_terms:
            hits.update(await search(client, cfg, stats, f"bundle: {term}",
                                     {"query": term, "category": cfg.bundle_category}, progress))
    for term in cfg.broad_terms:
        hits.update(await search(client, cfg, stats, f"broad: {term}", {"query": term}, progress))
    hits.update({i: {**a, "local": True} for i, a in local.items()})
    if not hits and stats["errors"]:
        raise RuntimeError("All searches failed. First error: " + stats["errors"][0])
    return list(hits.values())


def dedupe_reposts(hits: list[dict]) -> list[dict]:
    """One PC listed twice: same seller + same title, or same seller + same price +
    same opening text (a cross-post under a new title). Keep the cheapest."""
    best, alias = {}, {}
    for h in sorted(hits, key=lambda h: h.get("price_amount") or 0):
        seller = h.get("seller_id")
        keys = [(seller, h["title"].strip().lower()),
                (seller, h.get("price_amount"), " ".join((h.get("description") or "").lower().split())[:80])]
        if any(k in alias for k in keys):
            continue
        best[h["id"]] = h
        alias.update({k: h["id"] for k in keys})
    return list(best.values())


def gpu_medians(records: list[dict]) -> dict:
    groups = {}
    for r in records:
        gpu = r["build"]["gpu"]
        if gpu and not gpu.get("to_buy") and r["ask"]:
            groups.setdefault(gpu["name"], []).append(r["ask"])
    return {g: statistics.median(v) for g, v in groups.items() if len(v) >= MARKET_MIN_SAMPLES}


def needs_detail(r: dict, policy: Policy) -> bool:
    """Whether the full text could change this snippet verdict."""
    if not r["reject"] or r["special"]:
        return True
    if r["reject"] in FINAL_AT_SNIPPET:
        return False
    if r["reject"].startswith("vram_under_"):   # an assumed 8 GB twin, or a §6.3 candidate
        return not r["build"]["gpu"]["vram_stated"] or r["build"]["ram_gb"]["v"] >= 48
    if r["reject"] == "over_budget":
        return r["effective"] <= policy.limit + policy.stretch + OVER_BUDGET_DETAIL_SLACK
    return True


def detail_priority(r: dict) -> tuple:
    """Best provisional candidates first, so the max_details cap drops the weakest."""
    return (bool(r["reject"]) and not r["special"], r["tier"] if r["tier"] is not None else 9, r["effective"])


def load_seen() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.warning("! %s unreadable (%s): starting fresh", STATE_FILE.name, exc)
        return {}


def save_seen(seen: dict, hits: list[dict]) -> None:
    """Atomic: a crash mid-write never leaves a broken seen.json."""
    data = {**seen, **{str(h["id"]): h["price_amount"] for h in hits if h.get("price_amount")}}
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(STATE_FILE)


def mark_seen(records: list[dict], seen: dict) -> None:
    for r in records:
        old = seen.get(str(r["ad_id"]))
        if seen and old is None:
            r["flags"].append("new_since_last_run")
        elif old and r["ask"] < old:
            r["flags"].append(f"price_drop_from_{old:g}")


def count(stats: dict, reason: str) -> None:
    stats["rejects"][reason] = stats["rejects"].get(reason, 0) + 1


# ---- datasets: every run folder's raw.jsonl is a reusable dataset ----
RUN_NAME_FORMAT = "%Y-%m-%d_%H%M%S"


def list_runs() -> list[Path]:
    """Run folders that hold a dataset, newest first."""
    if not RUNS_DIR.exists():
        return []
    return sorted((p for p in RUNS_DIR.iterdir() if (p / "raw.jsonl").exists()), key=lambda p: p.name, reverse=True)


def _run_time(folder: Path) -> datetime:
    return datetime.strptime(folder.name[:17], RUN_NAME_FORMAT)


def load_dataset(folder: Path) -> list[dict]:
    """raw.jsonl rows: each a search hit, merged with its full listing when one was read
    ("attributes" present). Rows without `_fetched_at` date from the folder's run."""
    fetched = _run_time(folder).isoformat(timespec="seconds")
    with (folder / "raw.jsonl").open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [{**r, "_fetched_at": r.get("_fetched_at", fetched)} if "attributes" in r else r for r in rows]


def load_cache(max_age_days: int) -> dict:
    """Full listings from the newest dataset still young enough to reuse: {id: row}."""
    runs = list_runs()
    if not runs or max_age_days <= 0:
        return {}
    now = datetime.now()
    return {r["id"]: r for r in load_dataset(runs[0])
            if "attributes" in r and (now - datetime.fromisoformat(r["_fetched_at"])).days < max_age_days}


def reusable(hit: dict, cached: dict | None) -> bool:
    """Same listing at the same price: its saved full text still holds."""
    return bool(cached) and cached.get("price_amount") == hit.get("price_amount")


async def fetch_details(client, cfg: config.Config, todo: list[dict], by_id: dict, cache: dict,
                        stats: dict, progress: Progress) -> tuple[dict, set]:
    """{id: hit merged with its full listing}, reusing saved ones, and the ids found inactive."""
    details, inactive = {}, set()
    batch = todo[:cfg.max_details]
    for i, r in enumerate(batch, 1):
        hit, cached = by_id[r["ad_id"]], cache.get(r["ad_id"])
        if reusable(hit, cached):
            details[r["ad_id"]] = {**cached, "local": bool(hit.get("local"))}
            stats["reused"] += 1
        else:
            d = await call(client, "get_ad_detail", {"ad_id": int(r["ad_id"])}, stats)
            stats["details"] += 1
            await asyncio.sleep(cfg.delay_s)
            if d is None:
                stats["detail_errors"] += 1
            elif d.get("ad_status"):  # sold, reserved or deleted since the search
                inactive.add(r["ad_id"])
                count(stats, "inactive")
            else:
                details[r["ad_id"]] = {**hit, **d, "_fetched_at": datetime.now().isoformat(timespec="seconds")}
        progress.detail(i, len(batch))
    return details, inactive


def evaluate(cfg: config.Config, hits: list[dict], details: dict, stats: dict) -> dict:
    """Pure judging, no API calls: every listing is assessed on its full text when one was
    read, else on the search preview (flagged `preview_only` if it passes)."""
    stats = {**stats, "rejects": dict(stats.get("rejects", {}))}
    snippet = [rules.assess(h, cfg.policy) for h in hits]
    medians = gpu_medians(snippet)
    final = []
    for h, s in zip(hits, snippet):
        row = details.get(h["id"])
        gpu = (s["build"]["gpu"] or {}).get("name")
        final.append(rules.assess(row, cfg.policy, medians.get(gpu)) if row else s)
    for r in final:
        if r["reject"]:
            count(stats, r["reject"])
    stats["preview_only"] = sum(1 for r in final if not r["full_text"])
    attempted = stats.get("details", 0)
    stats["incomplete"] = attempted > 0 and stats.get("detail_errors", 0) / attempted > INCOMPLETE_ERROR_SHARE
    passed = rules.finalize([r for r in final if not r["reject"]], cfg.policy)
    seen = load_seen()
    mark_seen(passed, seen)
    return {"cfg": cfg, "stats": stats, "hits": hits, "raw": details, "snippet": snippet, "final": final,
            "passed": passed, "medians": medians, "seen": seen}


async def scan(cfg: config.Config, progress: Progress | None = None, cache: dict | None = None) -> dict:
    """Search, read full listings (reusing saved ones), then evaluate."""
    progress = progress or Progress()
    cache = load_cache(cfg.reuse_days) if cache is None else cache
    sys.path.insert(0, MCP_DIR)
    import main as ka_main  # kleinanzeigen-mcp server module, run in-process
    from mcp import Client

    stats = {"run_time": datetime.now().isoformat(timespec="seconds"), "requests": 0, "details": 0, "reused": 0,
             "detail_errors": 0, "detail_skipped": 0, "terms": {}, "errors": [], "capped": False, "rejects": {}}
    async with Client(ka_main.mcp) as client:
        hits = dedupe_reposts(await discover(client, cfg, stats, progress))
        by_id = {h["id"]: h for h in hits}
        snippet = [rules.assess(h, cfg.policy) for h in hits]
        todo = sorted((r for r in snippet if cfg.full_text_all or needs_detail(r, cfg.policy)), key=detail_priority)
        stats["detail_skipped"] = max(0, len(todo) - cfg.max_details)
        log.info("[detail] %d of %d listings need the full text (cap %d, %d saved ones reusable)",
                 len(todo), len(hits), cfg.max_details, sum(reusable(by_id[r["ad_id"]], cache.get(r["ad_id"]))
                                                           for r in todo[:cfg.max_details]))
        details, inactive = await fetch_details(client, cfg, todo, by_id, cache, stats, progress)
    hits = [h for h in hits if h["id"] not in inactive]
    stats["unique"] = len(hits)
    return evaluate(cfg, hits, details, stats)


def reevaluate(folder: Path, cfg: config.Config) -> dict:
    """Judge a saved dataset with the current rules: no searches, no API calls."""
    rows = load_dataset(folder)
    source = json.loads((folder / "run.json").read_text(encoding="utf-8")).get("stats", {})
    stats = {"run_time": datetime.now().isoformat(timespec="seconds"), "review_of": folder.name,
             "requests": 0, "details": 0, "reused": sum("attributes" in r for r in rows), "detail_errors": 0,
             "detail_skipped": 0, "terms": source.get("terms", {}), "errors": [], "capped": source.get("capped", False),
             "rejects": {}, "unique": len(rows)}
    return evaluate(cfg, rows, {r["id"]: r for r in rows if "attributes" in r}, stats)


def run(cfg_path: Path | None = None, on_progress=None) -> dict:
    """Load settings, search, write runs/<date_time>/. Returns a short summary.
    `on_progress(counts)` receives live counts (found, details_done, details_total)."""
    cfg = config.load(cfg_path)
    result = asyncio.run(scan(cfg, Progress(on_progress)))
    RUNS_DIR.mkdir(exist_ok=True)
    folder = report.write_run(RUNS_DIR, result)
    save_seen(result["seen"], result["hits"])
    summary = report.summary(result, folder)
    log.info("\n%s", summary["text"])
    return summary


def review(folder: Path, cfg_path: Path | None = None) -> dict:
    """Re-evaluate a saved run with the current settings into runs/<date_time>_review/."""
    result = reevaluate(folder, config.load(cfg_path))
    out = report.write_run(RUNS_DIR, result, suffix="_review")
    summary = report.summary(result, out)
    log.info("\n%s", summary["text"])
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "mcp", "main", "kleinanzeigen", "FastMCP"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        run()
    except ValueError as exc:  # bad search.toml: say what to fix, no traceback
        sys.exit(str(exc))
