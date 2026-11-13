"""Kleinanzeigen deals engine — single-file, standalone, LLM-ready output.

Edit the CONSTANTS block at the top to change scan scope. No input required
after launch. Output: digested.jsonl (one JSON per deal) + digest.json (run summary,
prepended with LLM system-audit text).

Usage:
    python deals.py
"""
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"C:\Users\Samuel\.config\opencode\mcp\kleinanzeigen-mcp")
import main as _ka_main  # kleinanzeigen-mcp server module

from mcp import Client

# ============ CONSTANTS — edit here to change scope ============
BUDGET_MIN = 300
BUDGET_MAX = 1500
MAX_REQUESTS = 60          # scan budget
PAGES_PER_COMBO = 3        # pages per (band × query × sort)
DELAY = 0.2                # polite delay between requests (seconds)
MAX_DETAILS = 120          # cap detail fetches (pre-filtered survivors only)
TOP_N = 20

BANDS = [(0, 400), (400, 600), (600, 800), (800, 1100), (1100, 1500), (1500, 10**9)]
QUERIES = ["Gaming PC", "Gaming Computer", "Komplett PC", "RTX", "RX", "Ryzen"]
SORTS = ["RECOMMENDED", "PRICE_ASCENDING"]

# Estimated used-market SYSTEM list prices (EUR) per GPU tier × CPU class.
# Base = GPU used price + rough floor for CPU/RAM/storage/PSU/case.
SYSTEM_LIST_PRICES = {
    ("rtx4090", "high"): 2400, ("rtx4090", "mid"): 2200,
    ("rtx4080super", "high"): 1600, ("rtx4080super", "mid"): 1450,
    ("rtx4080", "high"): 1700, ("rtx4080", "mid"): 1550,
    ("rtx4070tisuper", "high"): 1200, ("rtx4070tisuper", "mid"): 1050,
    ("rtx4070ti", "high"): 1100, ("rtx4070ti", "mid"): 980,
    ("rtx4070super", "high"): 950, ("rtx4070super", "mid"): 850,
    ("rtx4070", "high"): 1000, ("rtx4070", "mid"): 900,
    ("rtx4060ti16g", "mid"): 700, ("rtx4060ti", "mid"): 620, ("rtx4060", "mid"): 520,
    ("rtx3090", "high"): 1200, ("rtx3090", "mid"): 1050,
    ("rtx3080ti", "high"): 1050, ("rtx3080ti", "mid"): 920,
    ("rtx308012g", "high"): 900, ("rtx308012g", "mid"): 800,
    ("rtx3080", "high"): 850, ("rtx3080", "mid"): 750,
    ("rtx3070ti", "high"): 700, ("rtx3070ti", "mid"): 620,
    ("rtx3070", "high"): 650, ("rtx3070", "mid"): 580,
    ("rtx3060ti", "mid"): 500, ("rtx3060ti", "low"): 440,
    ("rtx306012g", "mid"): 440, ("rtx306012g", "low"): 390,
    ("rtx30608g", "mid"): 380, ("rtx30608g", "low"): 340,
    ("rtx3050", "low"): 280,
    ("gtx1660ti", "mid"): 320, ("gtx1660ti", "low"): 280,
    ("gtx1660super", "mid"): 290, ("gtx1660super", "low"): 260,
    ("gtx1660", "low"): 240,
    ("rx7900xtx", "high"): 1400, ("rx7900xtx", "mid"): 1250,
    ("rx7900xt", "high"): 1200, ("rx7900xt", "mid"): 1080,
    ("rx7800xt", "high"): 900, ("rx7800xt", "mid"): 800,
    ("rx7700xt", "mid"): 680,
    ("rx6950xt", "high"): 1100, ("rx6900xt", "high"): 1000,
    ("rx6800xt", "high"): 780, ("rx6800xt", "mid"): 700,
    ("rx6800", "mid"): 650,
    ("rx6750xt", "mid"): 560, ("rx6700xt", "mid"): 520,
    ("rx6650xt", "mid"): 440, ("rx6600", "mid"): 360,
    ("rx6500xt", "low"): 240, ("rx5600xt", "low"): 320,
}

# GPU-only fallback prices (when not a complete PC)
GPU_LIST_PRICES = {
    "rtx4090": 1300, "rtx4080super": 850, "rtx4080": 950,
    "rtx4070tisuper": 650, "rtx4070ti": 600, "rtx4070super": 480, "rtx4070": 520,
    "rtx4060ti16g": 360, "rtx4060ti": 320, "rtx4060": 280,
    "rtx3090": 650, "rtx3080ti": 550, "rtx308012g": 480, "rtx3080": 420,
    "rtx3070ti": 360, "rtx3070": 320, "rtx3060ti": 250, "rtx306012g": 210, "rtx30608g": 180,
    "rtx3050": 130, "gtx1660ti": 150, "gtx1660super": 130, "gtx1660": 110,
    "rx7900xtx": 750, "rx7900xt": 650, "rx7800xt": 450, "rx7700xt": 340,
    "rx6950xt": 600, "rx6900xt": 520, "rx6800xt": 380, "rx6800": 320,
    "rx6750xt": 280, "rx6700xt": 260, "rx6650xt": 220, "rx6600": 170,
    "rx6500xt": 110, "rx5600xt": 160,
}

FATAL_TITLE_KEYS = ["ohne gpu", "ohne grafikkarte", "gpu verkauft", "nur gehäuse",
                    "ohne karte", "ohne graka", "defekt", "bastler", "gesucht",
                    "suche", "laptop", "notebook", "nur grafik", "nur gpu",
                    "nur mainboard", "nur netzteil", "nur ram"]

LLM_SYSTEM_TEXT = """You are auditing 20 Kleinanzeigen.de gaming PC deals. Below is a pre-digested table extracted from live API results. Each row has: price (EUR), location, detected GPU model, my estimated used-market list price, savings % vs list, and any vet flags.

For EACH deal, evaluate:
1. Complete PC vs standalone GPU / part / trade — Is this actually a full gaming PC, or just a graphics card, MacBook trade-in, or component?
2. Price realism — Is the savings % plausible? Extreme negatives usually mean my list-price estimate is off, not a bargain.
3. GPU actually included — Look for "ohne GPU", "ohne Grafikkarte", "nur Gehäuse" in the description. Fatal exclusion.
4. Logistics — Shipping vs pickup only ("Nur Selbstabholer").
5. Scam/trust flags — "NUR TRADE", "WIRD NICHT FÜR X€ VERKAUFT", off-platform payment, urgency.
6. Verdict: Strong candidate | Worth asking | Too good to be true — check first | Exclude (reason)

| # | Title | Price | Location | GPU | List price | Savings % | Vet flags |
|---|-------|-------|----------|-----|------------|-----------|-----------|

[[PASTE MARKDOWN TABLE HERE]]

Output:
- Markdown table: # | Title | Price | Location | Verdict | Key concerns / seller questions
- Top 3 strongest candidates
- Top 3 to avoid and why
- Any deals where data is too incomplete to judge (list what's missing)

The raw `digest.json` run stats are here for context only:

[[PASTE digest.json CONTENTS HERE]]"""

# ===============================================================


def list_price_for(gpu_model: str | None) -> int | None:
    if not gpu_model:
        return None
    return GPU_LIST_PRICES.get(gpu_model.lower())


def system_list_price_for(gpu_model: str | None, cpu_tier: str = "mid") -> int | None:
    """Return estimated used-market SYSTEM list price (GPU + CPU + RAM + rest)."""
    if not gpu_model:
        return None
    key = gpu_model.lower()
    return SYSTEM_LIST_PRICES.get((key, cpu_tier))


def extract_gpu(title: str) -> str | None:
    upper = title.upper().replace(" ", "")
    for gpu in GPU_LIST_PRICES:
        if gpu.upper() in upper:
            return gpu.upper()
    return None


def extract_cpu_tier(title: str) -> str:
    """Classify CPU tier from title: 'high', 'mid', 'low', or 'unknown'."""
    upper = title.upper()
    high = ["I7", "I9", "RYZEN 7", "RYZEN 9", "R7", "R9", "X3D"]
    mid = ["I5", "RYZEN 5", "R5"]
    low = ["I3", "RYZEN 3", "R3", "PENTIUM", "CELERON", "ATHLON", "FX-", "A6", "A8", "A10"]
    if any(h in upper for h in high):
        return "high"
    if any(m in upper for m in mid):
        return "mid"
    if any(l in upper for l in low):
        return "low"
    return "unknown"


def extract_ram_gb(title: str) -> int | None:
    m = re.search(r"(\d+)\s*GB\s*(?:RAM|DDR4|DDR5)?", title.upper())
    if m:
        return int(m.group(1))
    return None


def classify_system_type(title: str, description: str = "") -> str:
    """Classify as complete_pc, gpu_only, part, trade, or unknown."""
    text = (title + " " + description).lower()
    if any(k in text for k in ["nur grafik", "nur gpu", "grafikkarte nur", "only gpu"]):
        return "gpu_only"
    if any(k in text for k in ["nur mainboard", "nur netzteil", "nur ram", "teil", "parts"]):
        return "part"
    if any(k in text for k in ["trade", "tausch", "eintausch"]):
        return "trade"
    if any(k in text for k in ["gaming pc", "komplett pc", "complete pc", "system", "komplettsystem"]):
        return "complete_pc"
    return "unknown"


def fatal_flags(title: str) -> list[str]:
    low = title.lower()
    return [k for k in FATAL_TITLE_KEYS if k in low]


def pickup_only_flag(description: str) -> bool:
    """True when 'nur abholung' appears in the user-entered description."""
    return "nur abholung" in description.lower()


def run_folder() -> Path:
    d = Path.cwd() / f"ka_run_{datetime.now():%Y%m%d_%H%M%S}_results-first"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def search(client, query, min_price=None, max_price=None,
                 sort="RECOMMENDED", page=0, rows=30):
    result = await client.call_tool("search_kleinanzeigen", {
        "query": query, "sort": sort, "min_price": min_price, "max_price": max_price,
        "rows": rows, "page": page,
    })
    return json.loads(result.content[0].text)


async def run():
    folder = run_folder()
    seen = set()
    hits = []
    requests = 0
    excluded_counts = {}

    async with Client(_ka_main.mcp) as client:
        # ---- 1. Discovery: band x query x sort ----
        for lo, hi in BANDS:
            if requests >= MAX_REQUESTS:
                break
            for q in QUERIES:
                if requests >= MAX_REQUESTS:
                    break
                for sort in SORTS:
                    if requests >= MAX_REQUESTS:
                        break
                    print(f"[discover] band={lo}-{hi} query='{q}' sort={sort}")
                    new_ids_run = 0
                    for page in range(PAGES_PER_COMBO):
                        if requests >= MAX_REQUESTS:
                            break
                        data = await search(client, q, min_price=lo,
                                            max_price=hi if hi < 10**9 else None,
                                            sort=sort, page=page)
                        requests += 1
                        ads = data.get("results", [])
                        new = [a for a in ads if a.get("id") not in seen]
                        for a in new:
                            seen.add(a["id"])
                            hits.append(a)
                            new_ids_run += 1
                        print(f"  page {page}: {len(ads)} ads, {len(new)} new")
                        if not ads or (page > 0 and new_ids_run / max(1, len(ads)) < 0.10):
                            break

        await asyncio.sleep(DELAY)

        # ---- 2. Prefilter: budget + fatal title keywords ----
        survivors = []
        for h in hits:
            price = h.get("price_amount") or 0
            if not (BUDGET_MIN <= price <= BUDGET_MAX):
                continue
            title = h.get("title", "")
            flags = fatal_flags(title)
            if flags:
                for f in flags:
                    excluded_counts[f] = excluded_counts.get(f, 0) + 1
                continue
            survivors.append(h)

        print(f"\n[prefilter] {len(survivors)} survivors after budget + fatal-keyword filter")

        # ---- 3. Detail fetch (capped) ----
        to_fetch = survivors[:MAX_DETAILS]
        if len(survivors) > MAX_DETAILS:
            print(f"[fetch] capping detail fetches at {MAX_DETAILS} of {len(survivors)} survivors")
        details = []
        for i, h in enumerate(to_fetch):
            d = await client.call_tool("get_ad_detail", {"ad_id": h["id"]})
            parsed = json.loads(d.content[0].text)
            details.append(parsed)
            print(f"  detail {i+1}/{len(to_fetch)}: ad {h['id']} €{parsed.get('price_amount')}")
            await asyncio.sleep(DELAY)

        # ---- 4. Extract + system savings ----
        extracted = []
        for d in details:
            title = d.get("title", "")
            description = d.get("description", "")

            # Pickup-only filter: "nur abholung" in user-entered description
            if pickup_only_flag(description):
                excluded_counts["nur_abholung"] = excluded_counts.get("nur_abholung", 0) + 1
                continue

            gpu_model = extract_gpu(title)
            cpu_tier = extract_cpu_tier(title)
            ram_gb = extract_ram_gb(title)
            system_type = classify_system_type(title, description)
            price = d.get("price_amount") or 0

            # System list price based on GPU tier + CPU class
            lp = system_list_price_for(gpu_model, cpu_tier)
            # Fallback to GPU-only price if no system price available
            if lp is None:
                lp = list_price_for(gpu_model)

            savings_pct = None
            if lp and price:
                savings_pct = round((1 - price / lp) * 100, 1)

            vet_flags = []
            if savings_pct is not None and savings_pct > 50:
                vet_flags.append("high_gap_unverified")
            if not gpu_model:
                vet_flags.append("gpu_not_detected")
            if system_type == "gpu_only":
                vet_flags.append("standalone_gpu_not_pc")
            if system_type == "trade":
                vet_flags.append("trade_not_sale")
            if ram_gb is not None and ram_gb < 16:
                vet_flags.append("low_ram_under16gb")
            if pickup_only_flag(description):
                vet_flags.append("pickup_only")

            extracted.append({
                "ad_id": d.get("id"),
                "url": d.get("url", ""),
                "title": title,
                "price": price,
                "location": d.get("location", ""),
                "gpu_model": gpu_model,
                "cpu_tier": cpu_tier,
                "ram_gb": ram_gb,
                "system_type": system_type,
                "list_price": lp,
                "savings_pct": savings_pct,
                "vet_flags": vet_flags,
                "description": description[:500],
            })

        # ---- 5. Sort by savings (highest first), no-ref last ----
        extracted.sort(key=lambda e: (e["savings_pct"] is None,
                                      -(e["savings_pct"] or 0)))

        # ---- 6. Output: digested.jsonl + digest.json ----
        jsonl_path = folder / "digested.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as f:
            for e in extracted:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        top = extracted[:TOP_N]
        digest = {
            "llm_system_text": LLM_SYSTEM_TEXT,
            "run_time": datetime.now(timezone.utc).isoformat(),
            "budget": [BUDGET_MIN, BUDGET_MAX],
            "requests": requests,
            "hits": len(hits),
            "survivors": len(survivors),
            "details_fetched": len(details),
            "excluded": excluded_counts,
            "top_20": top,
        }
        (folder / "digest.json").write_text(
            json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        print(f"\nReport: {folder / 'digested.jsonl'}")
        print(f"Summary: {folder / 'digest.json'}")
        print(f"Top {TOP_N}:")
        for e in top:
            savings = f"{e['savings_pct']}% below list" if e["savings_pct"] else "no ref"
            sys_type = f"[{e['system_type']}]" if e["system_type"] != "unknown" else ""
            print(f"  - {e['title'][:55]} — €{e['price']} | {e['gpu_model'] or '?'} | {savings} {sys_type}")

        return top, folder


async def main():
    await run()


if __name__ == "__main__":
    asyncio.run(main())