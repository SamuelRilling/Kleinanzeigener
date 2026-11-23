"""Kleinanzeigen used AI/workstation PC search — no input after launch.

Runs the Deal Evaluation Brief (Target.md) over Kleinanzeigen "PCs":
  1. local sweep: the whole category within LOCAL_RADIUS_KM of HOME_ZIP (pickup is a plus)
  2. nationwide: every SEARCH_TERMS entry, newest first
  3. dedupe, snippet-level hard rejects, full details for the survivors
  4. Brief rules in code (rules.py): rejects, effective price, tiers, ranking
  5. one file, RESULTS_FILE in the repo root, for the final AI pass
seen.json remembers ids and prices between runs (NEW / price-drop flags).

Usage:  python deals.py
"""
import asyncio
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

import report
import rules

MCP_DIR = r"C:\Users\Samuel\.config\opencode\mcp\kleinanzeigen-mcp"

# ============ CONFIG — edit here ============
CATEGORY = 228               # Elektronik > PCs
ASK_MIN, ASK_MAX = 100, 850  # asking price; ASK_MAX leaves room for VB haggling and stretch deals
HOME_ZIP, LOCAL_RADIUS_KM = "78628", 30
SORT = "DATE_DESCENDING"     # newest first: good deals go within hours to days
PAGES_PER_TERM = 10          # 30 ads per page
MAX_REQUESTS = 250           # search requests, all terms together
MAX_DETAILS = 300            # full-detail fetches
DELAY = 0.3                  # polite pause between requests (s)
MARKET_MIN_SAMPLES = 4
# Every term is matched against title + description. GPUs first (a listing that
# can pass must name a >= 12 GB card), then AM5 platform words, then big-RAM
# words for Priming §6.3 special cases. 8 GB twins (3060, 4060 Ti...) are kept:
# parsing decides the VRAM.
SEARCH_TERMS = [
    "3060", "4060 Ti", "5060 Ti", "4070", "5070", "3080", "3090", "4080", "5080", "4090",
    "6700 XT", "6750 XT", "6800", "6900 XT", "6950 XT", "7600 XT", "7700 XT", "7800 XT", "7900",
    "9060 XT", "9070",
    "AM5", "DDR5", "B650", "X670", "B850", "X870", "A620",
    "7600", "7600X", "9600X", "7700X", "9700X", "7800X3D", "9800X3D", "8700G",
    "64GB", "64 GB", "2x32",
]
STATE_FILE = Path(__file__).with_name("seen.json")
RESULTS_FILE = Path(__file__).with_name("search_results.md")
# ===============================================================


async def call(client, tool, args, stats):
    """Tool call -> parsed dict, or None (logged + counted) on any failure."""
    try:
        res = await client.call_tool(tool, args)
        text = res.content[0].text
        if getattr(res, "isError", False) or text.startswith("Error"):
            raise RuntimeError(text[:160])
        return json.loads(text)
    except Exception as exc:  # one bad ad or 429 must not kill the run
        stats["errors"].append(f"{tool} {args.get('query') or args.get('ad_id') or ''}: {str(exc)[:120]}")
        print(f"  ! {tool} {args.get('query') or args.get('ad_id')}: {exc}")
        return None


async def search(client, stats, label, extra):
    """All pages of one search (up to PAGES_PER_TERM) -> {id: hit}."""
    hits = {}
    for page in range(PAGES_PER_TERM):
        if stats["requests"] >= MAX_REQUESTS:
            stats["capped"] = True
            break
        args = {"category": CATEGORY, "min_price": ASK_MIN, "max_price": ASK_MAX, "sort": SORT,
                "ad_type": "OFFERED", "rows": 30, "page": page, **extra}
        data = await call(client, "search_kleinanzeigen", args, stats)
        stats["requests"] += 1
        await asyncio.sleep(DELAY)
        ads = (data or {}).get("results", [])
        hits.update({a["id"]: a for a in ads})
        if not data or not data.get("has_more"):
            break
    stats["terms"][label] = len(hits)
    print(f"[{label}] {len(hits)} ads")
    return hits


async def discover(client, stats):
    local = await search(client, stats, f"local {LOCAL_RADIUS_KM} km (all)",
                         {"zip_code": HOME_ZIP, "distance_km": LOCAL_RADIUS_KM})
    hits = {}
    for term in SEARCH_TERMS:
        hits.update(await search(client, stats, term, {"query": term}))
    hits.update({i: {**a, "local": True} for i, a in local.items()})
    if not hits and stats["errors"]:
        raise SystemExit("All searches failed — see the errors above.")
    return list(hits.values())


def dedupe_reposts(hits):
    """Same seller + same title = repost; keep the cheapest."""
    best = {}
    for h in hits:
        key = (h.get("seller_id"), h["title"].strip().lower())
        if key not in best or (h.get("price_amount") or 0) < (best[key].get("price_amount") or 0):
            best[key] = h
    return list(best.values())


def gpu_medians(records):
    groups = {}
    for r in records:
        if r["build"]["gpu"] and r["ask"]:
            groups.setdefault(r["build"]["gpu"]["name"], []).append(r["ask"])
    return {g: statistics.median(v) for g, v in groups.items() if len(v) >= MARKET_MIN_SAMPLES}


# Rejects that a fuller description cannot undo. A snippet "vram_under_12gb" is
# only final when the GPU has no >= 12 GB twin (parse handles that: the 4060 Ti
# is assumed 8 GB and would be rejected here, so it is re-checked in detail).
FINAL_AT_SNIPPET = {"intel_platform", "intel_arc", "not_desktop", "wanted_ad", "trade_only", "reserved",
                    "oem_prebuilt", "gpu_only", "no_price"}


def needs_detail(r):
    if not r["reject"] or r["special"]:
        return True
    if r["reject"] in FINAL_AT_SNIPPET:
        return False
    if r["reject"] == "vram_under_12gb":
        return not r["build"]["gpu"]["vram_stated"] or r["build"]["ram_gb"]["v"] >= 48
    if r["reject"] == "over_budget":
        return r["effective"] <= rules.BUDGET + rules.STRETCH + 100   # fixes may shrink with full text
    return True


def mark_seen(records, seen):
    for r in records:
        old = seen.get(str(r["ad_id"]))
        if seen and old is None:
            r["flags"].append("new_since_last_run")
        elif old and r["ask"] < old:
            r["flags"].append(f"price_drop_from_{old:g}")


async def run():
    sys.path.insert(0, MCP_DIR)
    import main as ka_main  # kleinanzeigen-mcp server module, run in-process
    from mcp import Client

    stats = {"run_time": datetime.now().isoformat(timespec="seconds"), "requests": 0, "details": 0,
             "terms": {}, "errors": [], "capped": False, "rejects": {}}
    seen = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    async with Client(ka_main.mcp) as client:
        hits = dedupe_reposts(await discover(client, stats))
        stats["unique"] = len(hits)
        by_id = {h["id"]: h for h in hits}
        snippet = [rules.assess(h) for h in hits]
        medians = gpu_medians(snippet)
        todo = [r for r in snippet if needs_detail(r)]
        for r in snippet:
            if not needs_detail(r):
                stats["rejects"][r["reject"]] = stats["rejects"].get(r["reject"], 0) + 1
        print(f"\n[detail] {len(todo)} of {len(hits)} listings need the full text (cap {MAX_DETAILS})")
        final = []
        for r in todo[:MAX_DETAILS]:
            d = await call(client, "get_ad_detail", {"ad_id": int(r["ad_id"])}, stats)
            stats["details"] += 1
            await asyncio.sleep(DELAY)
            if d is None:
                continue
            if d.get("ad_status"):  # no longer active
                stats["rejects"]["inactive"] = stats["rejects"].get("inactive", 0) + 1
                continue
            gpu = (r["build"]["gpu"] or {}).get("name")
            final.append(rules.assess({**by_id[r["ad_id"]], **d}, medians.get(gpu)))

    for r in final:
        if r["reject"]:
            stats["rejects"][r["reject"]] = stats["rejects"].get(r["reject"], 0) + 1
    passed = sorted((r for r in final if not r["reject"]), key=rules.sort_key)
    mark_seen(passed, seen)
    STATE_FILE.write_text(json.dumps({**seen, **{str(h["id"]): h["price_amount"] for h in hits
                                                  if h.get("price_amount")}}), encoding="utf-8")
    RESULTS_FILE.write_text(report.render(passed, final, snippet, medians, stats), encoding="utf-8")
    print(f"\n{len(passed)} passed, {sum(r['special'] for r in final)} special. Rejects: {stats['rejects']}")
    print(f"Output: {RESULTS_FILE}")
    return passed


if __name__ == "__main__":
    asyncio.run(run())
