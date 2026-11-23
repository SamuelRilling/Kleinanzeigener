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

MCP_DIR = r"C:\Users\Samuel\.config\opencode\mcp\kleinanzeigen-mcp"
RUNS_DIR = config.ROOT / "runs"
STATE_FILE = RUNS_DIR / "seen.json"
MARKET_MIN_SAMPLES = 4
INCOMPLETE_ERROR_SHARE = 0.2      # more failed detail fetches than this -> results marked INCOMPLETE
OVER_BUDGET_DETAIL_SLACK = 100    # snippet over budget by up to this may still pass with the full text

log = logging.getLogger("deals")

# Rejects that a fuller description cannot undo.
FINAL_AT_SNIPPET = {"intel_platform", "intel_arc", "not_desktop", "mini_pc_or_handheld", "wanted_ad", "trade_only",
                    "reserved", "oem_prebuilt", "gpu_only", "no_price"}


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


async def search(client, cfg: config.Config, stats: dict, label: str, extra: dict) -> dict:
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
        hits.update({a["id"]: a for a in (data or {}).get("results", [])})
        if not data or not data.get("has_more"):
            break
    stats["terms"][label] = len(hits)
    log.info("[%s] %d ads", label, len(hits))
    return hits


async def discover(client, cfg: config.Config, stats: dict) -> list[dict]:
    local = await search(client, cfg, stats, f"local {cfg.local_radius_km} km (all)",
                         {"zip_code": cfg.home_zip, "distance_km": cfg.local_radius_km})
    hits = {}
    for term in cfg.terms:
        hits.update(await search(client, cfg, stats, term, {"query": term}))
    if cfg.bundles_enabled:
        for term in cfg.bundle_terms:
            hits.update(await search(client, cfg, stats, f"bundle: {term}",
                                     {"query": term, "category": cfg.bundle_category}))
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


def needs_detail(r: dict, budget: rules.Budget) -> bool:
    """Whether the full text could change this snippet verdict."""
    if not r["reject"] or r["special"]:
        return True
    if r["reject"] in FINAL_AT_SNIPPET:
        return False
    if r["reject"] == "vram_under_12gb":   # an assumed 8 GB twin, or a §6.3 candidate
        return not r["build"]["gpu"]["vram_stated"] or r["build"]["ram_gb"]["v"] >= 48
    if r["reject"] == "over_budget":
        return r["effective"] <= budget.limit + budget.stretch + OVER_BUDGET_DETAIL_SLACK
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


async def fetch_details(client, cfg: config.Config, todo: list[dict], by_id: dict, medians: dict,
                        stats: dict) -> tuple[list[dict], dict]:
    final, raw = [], {}
    for r in todo[:cfg.max_details]:
        d = await call(client, "get_ad_detail", {"ad_id": int(r["ad_id"])}, stats)
        stats["details"] += 1
        await asyncio.sleep(cfg.delay_s)
        if d is None:
            stats["detail_errors"] += 1
            continue
        if d.get("ad_status"):  # no longer active
            count(stats, "inactive")
            continue
        merged = {**by_id[r["ad_id"]], **d}
        raw[r["ad_id"]] = merged
        gpu = (r["build"]["gpu"] or {}).get("name")
        final.append(rules.assess(merged, cfg.budget, medians.get(gpu)))
    return final, raw


async def scan(cfg: config.Config) -> dict:
    """Search + assess. Returns everything the report needs (no files written)."""
    sys.path.insert(0, MCP_DIR)
    import main as ka_main  # kleinanzeigen-mcp server module, run in-process
    from mcp import Client

    stats = {"run_time": datetime.now().isoformat(timespec="seconds"), "requests": 0, "details": 0,
             "detail_errors": 0, "detail_skipped": 0, "terms": {}, "errors": [], "capped": False, "rejects": {}}
    async with Client(ka_main.mcp) as client:
        hits = dedupe_reposts(await discover(client, cfg, stats))
        stats["unique"] = len(hits)
        by_id = {h["id"]: h for h in hits}
        snippet = [rules.assess(h, cfg.budget) for h in hits]
        medians = gpu_medians(snippet)
        todo = sorted((r for r in snippet if needs_detail(r, cfg.budget)), key=detail_priority)
        for r in snippet:
            if not needs_detail(r, cfg.budget):
                count(stats, r["reject"])
        stats["detail_skipped"] = max(0, len(todo) - cfg.max_details)
        log.info("[detail] %d of %d listings need the full text (cap %d)", len(todo), len(hits), cfg.max_details)
        final, raw = await fetch_details(client, cfg, todo, by_id, medians, stats)

    for r in final:
        if r["reject"]:
            count(stats, r["reject"])
    stats["incomplete"] = stats["details"] > 0 and stats["detail_errors"] / stats["details"] > INCOMPLETE_ERROR_SHARE
    passed = sorted((r for r in final if not r["reject"]), key=rules.sort_key)
    seen = load_seen()
    mark_seen(passed, seen)
    return {"cfg": cfg, "stats": stats, "hits": hits, "raw": raw, "snippet": snippet, "final": final,
            "passed": passed, "medians": medians, "seen": seen}


def run(cfg_path: Path = config.DEFAULT_FILE) -> dict:
    """Load settings, scan, write runs/<date_time>/. Returns a short summary."""
    cfg = config.load(cfg_path)
    result = asyncio.run(scan(cfg))
    RUNS_DIR.mkdir(exist_ok=True)
    folder = report.write_run(RUNS_DIR, result)
    save_seen(result["seen"], result["hits"])
    summary = report.summary(result, folder)
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
