"""Kleinanzeigen gaming-PC deals engine — single file, no input after launch.

Scans the "PCs" category across price bands (newest first), values each listing
as the sum of its parts (used GPU + CPU + RAM + base), ranks by value/price,
fetches full details only for the shortlist, and writes LLM-ready output to a
timestamped run folder:
    deals.jsonl  every scored listing that survived the filters
    digest.md    audit prompt with the top-N table filled in — paste into an LLM
    digest.json  run stats + top N
seen.json (next to this file) remembers ids and prices between runs, so later
runs flag NEW listings and PRICE DROPS.

Usage:  python deals.py
"""
import asyncio
import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

MCP_DIR = r"C:\Users\Samuel\.config\opencode\mcp\kleinanzeigen-mcp"

# ============ CONFIG — edit here ============
BUDGET_MIN, BUDGET_MAX = 800, 1500
N_BANDS = 6                  # price bands, geometric split of the budget
CATEGORY = 228               # Elektronik > PCs (keeps out bare GPUs and parts)
QUERY = None                 # optional keyword on top of the category, e.g. "gaming"
SORT = "DATE_DESCENDING"     # newest first: fresh listings are the ones still available
MAX_REQUESTS = 90            # search requests (30 ads each)
PAGES_PER_BAND = 20
DETAILS = 100                 # full-detail fetches, best pre-ranked listings only
DETAILS_UNPARSED = 40        # extra fetches: "gaming" listings whose GPU isn't in the snippet
MIN_GPU_PERF = 80            # drop GPUs weaker than ~RTX 2060 / GTX 1080 (RTX 3060 = 100)
TOP_N = 25
DELAY = 0.25                 # polite pause between requests (s)
HOME_ZIP = 78628              # listings within LOCAL_RADIUS_KM get the "local" flag (search stays nationwide)
LOCAL_RADIUS_KM = 30
EXCLUDE_PICKUP_TEXT = True   # drop non-local ads whose text says "nur Abholung"

# Valuation (EUR, used market, late 2026 — rough; adjust as prices move)
BASE_EUR = 120               # board + PSU + case + SSD + cooler
RAM_EUR_PER_GB = 3.0
RAM_DEFAULT_GB = 16          # assumed when not stated
RAM_VALUE_CAP_GB = 32        # more RAM adds little to a gaming PC's value
CPU_UNKNOWN_EUR = 60
MARKET_MIN_SAMPLES = 4       # same-GPU listings needed for a market median
TOO_CHEAP_VS_MARKET = 0.55   # price below 55% of market median -> check for scam
STATE_FILE = Path(__file__).with_name("seen.json")
OUT_DIR = Path(__file__).parent


GPU_LEADS = {"RTX": "(?:RTX|GTX|GEFORCE)", "GTX": "(?:RTX|GTX|GEFORCE)", "RX": "(?:RX|RADEON)", "ARC": "ARC"}


def _gpu(name, eur, perf, prefix=False):
    """(name, regex, used EUR, perf index RTX 3060 = 100). A bare model number
    ("3090", "580") needs its brand word, since PC models (OptiPlex 3090), chipsets
    and resolutions reuse those numbers; a suffix (Ti, Super, XT) makes the brand
    optional unless `prefix` (RX 5600 XT vs the Ryzen 5 5600XT CPU)."""
    brand, *model = name.upper().split()
    body = r"[\s-]*".join("(?:SUPER|S)" if t == "SUPER" else t for t in model)
    lead = GPU_LEADS[brand] + r"[\s-]*"
    if not (prefix or (len(model) == 1 and brand != "ARC")):
        lead = f"(?:{lead})?"
    return name, re.compile(rf"(?<![\w.]){lead}{body}(?!\w)"), eur, perf


GPUS = [
    _gpu("RTX 5090", 2000, 410), _gpu("RTX 5080", 900, 285), _gpu("RTX 5070 Ti", 650, 250),
    _gpu("RTX 5070", 450, 200), _gpu("RTX 5060 Ti", 320, 148), _gpu("RTX 5060", 240, 128),
    _gpu("RTX 4090", 1500, 330), _gpu("RTX 4080 Super", 850, 263), _gpu("RTX 4080", 800, 258),
    _gpu("RTX 4070 Ti Super", 650, 220), _gpu("RTX 4070 Ti", 580, 205),
    _gpu("RTX 4070 Super", 500, 190), _gpu("RTX 4070", 430, 165),
    _gpu("RTX 4060 Ti", 300, 128), _gpu("RTX 4060", 230, 108),
    _gpu("RTX 3090 Ti", 700, 212), _gpu("RTX 3090", 600, 198), _gpu("RTX 3080 Ti", 450, 192),
    _gpu("RTX 3080", 380, 175), _gpu("RTX 3070 Ti", 290, 148), _gpu("RTX 3070", 260, 140),
    _gpu("RTX 3060 Ti", 220, 125), _gpu("RTX 3060", 190, 100), _gpu("RTX 3050", 130, 70),
    _gpu("RTX 2080 Ti", 280, 150), _gpu("RTX 2080 Super", 220, 127), _gpu("RTX 2080", 200, 120),
    _gpu("RTX 2070 Super", 190, 112), _gpu("RTX 2070", 160, 100),
    _gpu("RTX 2060 Super", 150, 95), _gpu("RTX 2060", 120, 82),
    _gpu("GTX 1660 Ti", 100, 70), _gpu("GTX 1660 Super", 100, 70),
    _gpu("GTX 1660", 85, 64), _gpu("GTX 1650", 70, 48),
    _gpu("GTX 1080 Ti", 150, 112), _gpu("GTX 1080", 100, 88),
    _gpu("GTX 1070 Ti", 90, 80), _gpu("GTX 1070", 80, 72),
    _gpu("GTX 1060", 55, 52), _gpu("GTX 1050 Ti", 45, 36),
    _gpu("RX 9070 XT", 550, 260), _gpu("RX 9070", 480, 235), _gpu("RX 9060 XT", 280, 145),
    _gpu("RX 7900 XTX", 700, 290), _gpu("RX 7900 XT", 550, 250), _gpu("RX 7900 GRE", 450, 210),
    _gpu("RX 7800 XT", 400, 195), _gpu("RX 7700 XT", 320, 165),
    _gpu("RX 7600 XT", 250, 118), _gpu("RX 7600", 210, 112),
    _gpu("RX 6950 XT", 430, 225), _gpu("RX 6900 XT", 380, 212), _gpu("RX 6800 XT", 350, 200),
    _gpu("RX 6800", 300, 175), _gpu("RX 6750 XT", 250, 145), _gpu("RX 6700 XT", 230, 140),
    _gpu("RX 6700", 200, 128), _gpu("RX 6650 XT", 180, 120), _gpu("RX 6600 XT", 170, 115),
    _gpu("RX 6600", 150, 102), _gpu("RX 6500 XT", 80, 50),
    _gpu("RX 5700 XT", 120, 105, True), _gpu("RX 5700", 100, 95, True),
    _gpu("RX 5600 XT", 90, 85, True), _gpu("RX 580", 50, 58, True), _gpu("RX 570", 40, 50, True),
    _gpu("ARC B580", 220, 125), _gpu("ARC A770", 180, 115), _gpu("ARC A750", 140, 105),
]

# CPU used prices by generation, tiers (3, 5, 7, 9)
INTEL_EUR = {4: (5, 10, 20, 30), 5: (5, 15, 25, 40), 6: (10, 20, 35, 50), 7: (10, 25, 40, 60), 8: (15, 35, 60, 90),
             9: (20, 45, 75, 110), 10: (30, 60, 100, 140), 11: (35, 65, 105, 140),
             12: (50, 90, 140, 200), 13: (70, 130, 200, 280), 14: (80, 140, 220, 300)}
INTEL_ULTRA_EUR = (100, 150, 230, 380)
RYZEN_EUR = {1: (10, 20, 35, 50), 2: (15, 30, 45, 60), 3: (25, 45, 70, 110), 4: (30, 50, 80, 120),
             5: (40, 70, 110, 180), 7: (80, 120, 170, 280), 8: (60, 110, 160, 250),
             9: (100, 170, 230, 380)}
X3D_EUR = {"5600": 120, "5700": 150, "5800": 200, "7800": 300, "7900": 330, "7950": 400,
           "9800": 420, "9900": 480, "9950": 550}
TIER_ONLY_EUR = {"intel": (25, 50, 80, 150), "ryzen": (30, 60, 90, 150)}

INTEL_RE = re.compile(r"(?<!\w)(?:CORE\s*)?I([3579])[\s-]?(1[0-4]|[4-9])\d{2,3}[A-Z]{0,2}(?!\w)")
ULTRA_RE = re.compile(r"ULTRA\s*([3579])[\s-]*2\d\d[A-Z]{0,2}(?!\w)")
RYZEN_RE = re.compile(r"(?<!\w)(?:RYZEN\s*([3579])?|R([3579]))[\s-]*([1-9])(\d)\d\d\s*(X3D|XT|X|GT|G|F)?(?!\w)")
RYZEN_BARE_RE = re.compile(r"(?<![\w-])([1-9])(\d)\d0(X3D|X)(?!\w)")
TIER_RE = re.compile(r"(?<!\w)(?:(?:CORE\s*)?I([3579])|RYZEN\s*([3579]))(?![\d])")

RAM_RES = [re.compile(r"(?<!\d)(\d{1,3})\s*GB\s*(?:DDR\d\S*\s*)?(?:RAM|ARBEITSSPEICHER|DDR\d)"),
           re.compile(r"(?<!\w)(?:RAM|ARBEITSSPEICHER)\s*:?\s*(\d{1,3})\s*GB")]
RAM_KIT_RE = re.compile(r"(?<!\d)([1-4])\s*X\s*(\d{1,2})\s*GB")
RAM_VALID = {8, 12, 16, 24, 32, 48, 64, 96, 128}
VRAM_CONTEXT_RE = re.compile(r"(?:RTX|GTX|RX|RADEON|ARC)[\s-]*[AB]?\d{3,4}(?:\s*(?:TI|SUPER|XTX|XT|GRE))*\s*[(:-]?\s*$")

FATAL_ANY = [
    ("no_gpu", r"\bohne\s+(?:dedizierte\s+)?(?:gpu|grafikkarte|graka|grafik|gk)\b"),
    ("no_gpu", r"\b(?:gpu|grafikkarte|graka)\s+(?:ist\s+|wurde\s+|wird\s+)?(?:nicht\s+(?:enthalten|dabei|inklusive|verbaut|vorhanden|mit)|fehlt|bereits\s+verkauft|ausgebaut|separat)"),
    ("no_gpu", r"\bnur\s+(?:das\s+)?(?:gehäuse|mainboard|netzteil)\b"),
    ("bastler", r"\bbastler"),
]
FATAL_TITLE = [
    ("not_desktop", r"\b(?:laptop|notebook|macbook|imac|mac\s*mini|mac\s*studio)\b"),
    ("gpu_only", r"^(?!.*\b(?:pc|rechner|computer|system|tower|komplett\w*)\b).*\b(?:grafikkarte|gpu)\b"),
    ("wanted_ad", r"\b(?:suche|gesucht)\b"),
    ("trade_only", r"\b(?:tausch|tausche)\b(?!.*\bverkauf)"),
]
DEFEKT_RE = re.compile(r"defekt\w*")
DEFEKT_NEGATION = re.compile(r"(?:nicht|kein\w*|ohne|nie)\s+(?:\w+\s+)?$")  # same clause only
GAMING_RE = re.compile(r"gaming|gamer|zocken|\brtx\b|geforce|radeon")
PICKUP_RE = re.compile(r"\bnur\s+(?:an\s+)?(?:selbst)?abhol\w*|\bselbstabholer\b|\bkein\s+versand\b")
OFFPLATFORM_RE = re.compile(r"whatsapp|paypal\s+freunde|freunde\s+(?:und|&)\s+familie|vorkasse|western\s+union")
# ===============================================================


def _earliest(patterns, text):
    """The pattern match that starts earliest in `text`; ties go to the longest."""
    best = None
    for item in patterns:
        m = item[1].search(text)
        if m and (best is None or (m.start(), -len(m.group())) < (best[1].start(), -len(best[1].group()))):
            best = (item, m)
    return best


def parse_gpu(title, desc):
    """(name, used EUR, perf, found_in_description) or None."""
    for text, in_desc in ((title.upper(), False), (desc.upper(), True)):
        hit = _earliest(GPUS, text)
        if hit:
            name, _, eur, perf = hit[0]
            return name, eur, perf, in_desc
    return None


def _ryzen_tier(d2):
    return 3 if d2 <= 3 else 5 if d2 <= 6 else 7 if d2 <= 8 else 9


def _tier_idx(tier):
    return (3, 5, 7, 9).index(tier)


def _cpu_in(text):
    candidates = []
    if m := INTEL_RE.search(text):
        tier, gen = int(m.group(1)), int(m.group(2))
        eur = INTEL_EUR[max([k for k in INTEL_EUR if k <= gen] or [4])][_tier_idx(tier)]
        candidates.append((m.start(), f"i{tier} {gen}th gen", eur))
    if m := ULTRA_RE.search(text):
        tier = int(m.group(1))
        candidates.append((m.start(), f"Core Ultra {tier}", INTEL_ULTRA_EUR[_tier_idx(tier)]))
    for rx, bare in ((RYZEN_RE, False), (RYZEN_BARE_RE, True)):
        if m := rx.search(text):
            if bare:
                series, d2, suffix, tier = int(m.group(1)), int(m.group(2)), m.group(3), None
            else:
                series, d2, suffix = int(m.group(3)), int(m.group(4)), m.group(5)
                tier = int(m.group(1) or m.group(2) or 0) or None
            tier = tier or _ryzen_tier(d2)
            model = f"{series}{d2}00"
            eur = RYZEN_EUR.get(series, RYZEN_EUR[5])[_tier_idx(tier)]
            if suffix == "X3D":
                eur = X3D_EUR.get(model, eur * 2)
            candidates.append((m.start(), f"Ryzen {tier} {model}{suffix or ''}", eur))
    if candidates:
        _, label, eur = min(candidates)
        return label, eur
    if m := TIER_RE.search(text):
        brand, tier = ("intel", int(m.group(1))) if m.group(1) else ("ryzen", int(m.group(2)))
        return f"{'i' if brand == 'intel' else 'Ryzen '}{tier} (gen?)", TIER_ONLY_EUR[brand][_tier_idx(tier)]
    return None


def parse_cpu(title, desc):
    """(label, used EUR) or None — title first, then description."""
    return _cpu_in(title.upper()) or _cpu_in(desc.upper())


def parse_ram(title, desc):
    for text in (title.upper(), desc.upper()):
        for rx in RAM_RES:
            for m in rx.finditer(text):
                is_vram = VRAM_CONTEXT_RE.search(text[max(0, m.start() - 30):m.start()])
                if int(m.group(1)) in RAM_VALID and not is_vram:  # "RTX 3060 (12 GB RAM)"
                    return int(m.group(1))
        for m in RAM_KIT_RE.finditer(text):
            total = int(m.group(1)) * int(m.group(2))
            if total in RAM_VALID:
                return total
    return None


def fatal_reason(title, desc, attributes):
    t, text = title.lower(), f"{title}\n{desc}".lower()
    if attributes.get("Zustand") == "Defekt":
        return "defekt"
    for reason, rx in FATAL_TITLE:
        if re.search(rx, t):
            return reason
    for reason, rx in FATAL_ANY:
        if re.search(rx, text):
            return reason
    for m in DEFEKT_RE.finditer(text):
        if not DEFEKT_NEGATION.search(text[max(0, m.start() - 30):m.start()]):
            return "defekt"
    return None


def evaluate(ad):
    """Pure: one search hit or detail record -> scored listing (with `fatal` set
    when it must be dropped)."""
    title, desc = ad.get("title", ""), ad.get("description", "")
    attrs = ad.get("attributes") or {}
    price = ad.get("price_amount") or 0
    gpu, cpu, ram = parse_gpu(title, desc), parse_cpu(title, desc), parse_ram(title, desc)
    flags = []
    if gpu and gpu[3]:
        flags.append("gpu_from_description")
    if not cpu:
        flags.append("cpu_unknown")
    if not ram:
        flags.append("ram_unknown")
    elif ram < 16:
        flags.append("ram_under_16gb")
    if attrs.get("Versand") == "Versand möglich" or ad.get("shipping_options"):
        flags.append("ships")
    if ad.get("price_type") == "PLEASE_CONTACT":
        flags.append("vb")
    if ad.get("seller_account_type") == "COMMERCIAL":
        flags.append("commercial")
    if OFFPLATFORM_RE.search(desc.lower()):
        flags.append("offplatform_payment")
    if ad.get("local"):
        flags.insert(0, "local")
    fatal = fatal_reason(title, desc, attrs)
    if not fatal and "attributes" in ad and not cpu and not ram:
        fatal = "no_cpu_ram_in_full_text"  # a bare card, or too vague to judge
    if not fatal and EXCLUDE_PICKUP_TEXT and not ad.get("local") and PICKUP_RE.search(desc.lower()):
        fatal = "pickup_text"
    value = None
    if gpu:
        value = gpu[1] + (cpu[1] if cpu else CPU_UNKNOWN_EUR) + min(ram or RAM_DEFAULT_GB, RAM_VALUE_CAP_GB) * RAM_EUR_PER_GB + BASE_EUR
    return {
        "ad_id": ad.get("id"), "url": ad.get("url"), "title": title, "price": price,
        "location": ad.get("location"), "zip": ad.get("zip_code"), "posted": ad.get("start_date"),
        "seller_id": ad.get("seller_id"),
        "gpu": gpu[0] if gpu else None, "perf": gpu[2] if gpu else None, "cpu": cpu[0] if cpu else None, "ram_gb": ram,
        "condition": attrs.get("Zustand"), "seller_rating": ad.get("seller_rating"),
        "parts_value": round(value) if value else None,
        "value_ratio": round(value / price, 2) if value and price else None,
        "perf_per_100eur": round(gpu[2] / price * 100, 1) if gpu and price else None,
        "flags": flags, "fatal": fatal,
        "description": desc[:600],
    }


def _medians(listings, key, field):
    groups = {}
    for l in listings:
        groups.setdefault(key(l), []).append(l[field])
    return {k: statistics.median(v) for k, v in groups.items() if len(v) >= MARKET_MIN_SAMPLES}


def perf_bucket(l):
    return l["perf"] // 25


def market(listings):
    """Medians of this scan's asking prices and value ratios. Asking prices run far
    above parts value for high-end PCs, so a listing is judged against its peers
    (same GPU, else same performance bracket), not against the raw parts table."""
    return {"price": _medians(listings, lambda l: l["gpu"], "price"),
            "ratio_gpu": _medians(listings, lambda l: l["gpu"], "value_ratio"),
            "ratio_bucket": _medians(listings, perf_bucket, "value_ratio"),
            "ratio_all": statistics.median(l["value_ratio"] for l in listings) if listings else 1}


def deal_score(l, mkt):
    """Value ratio relative to comparable listings: 1.0 = typical, 1.3 = 30% better."""
    ref = mkt["ratio_gpu"].get(l["gpu"]) or mkt["ratio_bucket"].get(perf_bucket(l)) or mkt["ratio_all"]
    return round(l["value_ratio"] / ref, 2)


def with_market(listing, mkt, seen):
    median = mkt["price"].get(listing["gpu"])
    flags = list(listing["flags"])
    vs = round((1 - listing["price"] / median) * 100) if median else None
    if median and listing["price"] < TOO_CHEAP_VS_MARKET * median:
        flags.append("too_cheap_check")
    old = seen.get(str(listing["ad_id"]))
    if seen and old is None:
        flags.append("new")
    elif old and listing["price"] < old:
        flags.append(f"price_drop_from_{old:g}")
    return {**listing, "deal_score": deal_score(listing, mkt), "market_median": median,
            "vs_market_pct": vs, "flags": flags}


def bands():
    ratio = BUDGET_MAX / BUDGET_MIN
    edges = [round(BUDGET_MIN * ratio ** (i / N_BANDS)) for i in range(N_BANDS + 1)]
    return list(zip(edges, edges[1:]))


async def call(client, tool, args, stats):
    """Tool call -> parsed dict, or None (logged + counted) on any failure."""
    try:
        res = await client.call_tool(tool, args)
        text = res.content[0].text
        if getattr(res, "isError", False) or text.startswith("Error"):
            raise RuntimeError(text[:160])
        return json.loads(text)
    except Exception as exc:  # one bad ad or 429 must not kill the run
        stats["errors"] += 1
        print(f"  ! {tool} {args.get('ad_id') or args.get('page')}: {exc}")
        return None


async def discover(client, stats, location, label):
    """Round-robin pages across price bands so the request budget is spread evenly."""
    next_page = {band: 0 for band in bands()}
    hits = {}
    while next_page and stats["requests"] < MAX_REQUESTS:
        for (lo, hi), page in list(next_page.items()):
            if stats["requests"] >= MAX_REQUESTS:
                break
            args = {"category": CATEGORY, "min_price": lo, "max_price": hi, "sort": SORT,
                    "ad_type": "OFFERED", "rows": 30, "page": page, **location}
            if QUERY:
                args["query"] = QUERY
            data = await call(client, "search_kleinanzeigen", args, stats)
            stats["requests"] += 1
            ads = (data or {}).get("results", [])
            new = [a for a in ads if a["id"] not in hits]
            hits.update({a["id"]: a for a in new})
            print(f"[{label}] €{lo}-{hi} p{page}: {len(ads)} ads, {len(new)} new (total {len(hits)})")
            if not data or not ads or not data.get("has_more") or page + 1 >= PAGES_PER_BAND:
                del next_page[(lo, hi)]
            else:
                next_page[(lo, hi)] = page + 1
            await asyncio.sleep(DELAY)
    return hits


async def discover_all(client, stats):
    """A small local pass first (to know which listings are local), then nationwide."""
    local = {}
    if HOME_ZIP:
        local = await discover(client, stats, {"zip_code": str(HOME_ZIP), "distance_km": LOCAL_RADIUS_KM}, "local")
    hits = {**await discover(client, stats, {}, "discover"), **{i: {**a, "local": True} for i, a in local.items()}}
    if not hits and stats["errors"]:
        raise SystemExit("All searches failed — see the errors above (check the CONFIG values).")
    stats["local_listings"] = len(local)
    return list(hits.values())


def dedupe_reposts(hits):
    """Same seller + same title = repost; keep the cheapest."""
    best = {}
    for h in hits:
        key = (h.get("seller_id"), h["title"].strip().lower())
        if key not in best or (h.get("price_amount") or 0) < (best[key].get("price_amount") or 0):
            best[key] = h
    return list(best.values())


def count(stats, reason):
    stats["excluded"][reason] = stats["excluded"].get(reason, 0) + 1


def triage(listings, stats):
    keep = []
    for l in listings:
        if l["fatal"]:
            count(stats, l["fatal"])
        elif not l["gpu"]:
            count(stats, "gpu_not_detected")
        elif l["perf"] < MIN_GPU_PERF:
            count(stats, "gpu_too_weak")
        elif not BUDGET_MIN <= l["price"] <= BUDGET_MAX:
            count(stats, "outside_budget")
        else:
            keep.append(l)
    return keep


def fmt_row(i, l):
    flags = ", ".join(l["flags"]) or "—"
    vs = f"{l['vs_market_pct']:+d}%" if l["vs_market_pct"] is not None else "n/a"
    title = l["title"].replace("|", "/")[:70]
    return (f"| {i} | [{title}]({l['url']}) | €{l['price']:g} | {l['location']} | {l['gpu']} | "
            f"{l['cpu'] or '?'} | {l['ram_gb'] or '?'} | **{l['deal_score']}** | €{l['parts_value']} | {l['value_ratio']}× | "
            f"{vs} | {l['perf_per_100eur']} | {l['condition'] or '?'} | {flags} |")


LLM_PROMPT = """You are auditing {n} Kleinanzeigen.de gaming-PC listings (category "PCs", €{lo}–{hi}). A script parsed each listing's title and description:
- GPU / CPU / RAM: as detected ("?" = not found, "(gen?)" = generation unknown).
- Parts €: estimated used value of GPU + CPU + RAM + €{base} base (board, PSU, case, SSD).
- Value×: Parts € / price.
- Deal: Value× relative to comparable listings in this scan (same GPU, else same performance bracket). 1.0 = typical asking price, 1.3 = 30% better value than its peers. Rows are sorted by it.
- vs market: price vs the median asking price of other listings with the same GPU in this scan (+ = cheaper).
- Perf/100€: GPU performance index (RTX 3060 = 100) per €100 of price.
- Flags: local (within {radius} km of the buyer: preferred, pickup is easy), ships (shipping offered; most listings are pickup only), vb (negotiable), new / price_drop (since last run), too_cheap_check, offplatform_payment, gpu_from_description, cpu_unknown, ram_unknown, commercial.

For EACH listing evaluate:
1. Parse check: open the link if in doubt. Are GPU, CPU and RAM right, and is the GPU really included?
2. Price realism: is the Deal score plausible, or does a parse error or a too_cheap_check flag explain it?
3. Logistics: shipping vs pickup only.
4. Scam/trust: "NUR TAUSCH", off-platform payment, urgency, a price far below market.
5. Verdict: Strong candidate | Worth asking | Too good to be true — check first | Exclude (reason)

| # | Title | Price | Location | GPU | CPU | RAM GB | Deal | Parts € | Value× | vs market | Perf/100€ | Condition | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
{rows}

Output:
- Markdown table: # | Title | Price | Verdict | Key concerns / questions for the seller
- Top 3 strongest candidates
- Top 3 to avoid, and why
- Listings where the data is too incomplete to judge (say what's missing)

Run stats (context only):
{stats}
"""


def write_outputs(final, stats):
    folder = OUT_DIR / f"ka_run_{datetime.now():%Y%m%d_%H%M%S}"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "deals.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(l, ensure_ascii=False) + "\n" for l in final)
    top = final[:TOP_N]
    (folder / "digest.json").write_text(
        json.dumps({**stats, "top": top}, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "\n".join(fmt_row(i, l) for i, l in enumerate(top, 1))
    prompt = LLM_PROMPT.format(n=len(top), lo=BUDGET_MIN, hi=BUDGET_MAX, base=BASE_EUR, rows=rows, radius=LOCAL_RADIUS_KM,
                               stats=json.dumps(stats, ensure_ascii=False))
    (folder / "digest.md").write_text(prompt, encoding="utf-8")
    return folder


def load_seen():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        print(f"! {STATE_FILE.name} unreadable ({exc}); starting fresh")
        return {}


async def run():
    sys.path.insert(0, MCP_DIR)
    import main as ka_main  # kleinanzeigen-mcp server module, run in-process
    from mcp import Client

    stats = {"run_time": datetime.now().isoformat(timespec="seconds"), "budget": [BUDGET_MIN, BUDGET_MAX],
             "requests": 0, "details": 0, "errors": 0, "excluded": {}}
    seen = load_seen()
    async with Client(ka_main.mcp) as client:
        hits = dedupe_reposts(await discover_all(client, stats))
        stats["unique_listings"] = len(hits)
        by_id = {h["id"]: h for h in hits}

        # pre-rank on title + snippet; spend detail fetches only on the best
        pre = triage([evaluate(h) for h in hits], stats)
        mkt = market(pre)
        pre.sort(key=lambda l: -deal_score(l, mkt))
        stats["candidates"] = len(pre)
        stats["market_medians"] = {g: round(m) for g, m in sorted(mkt["price"].items())}
        # second chance: gaming listings whose GPU is only in the full description
        unparsed = [l for l in map(evaluate, hits) if not l["fatal"] and not l["gpu"]
                    and BUDGET_MIN <= l["price"] <= BUDGET_MAX
                    and GAMING_RE.search(f"{l['title']} {l['description']}".lower())][:DETAILS_UNPARSED]
        print(f"\n[rank] {len(pre)} candidates; details for top {DETAILS} + {len(unparsed)} unparsed")

        detailed = []
        for l in pre[:DETAILS] + unparsed:
            d = await call(client, "get_ad_detail", {"ad_id": int(l["ad_id"])}, stats)
            stats["details"] += 1
            await asyncio.sleep(DELAY)
            if d is None:
                continue
            if d.get("ad_status"):  # no longer active
                count(stats, "inactive")
                continue
            detailed.append(evaluate({**by_id[l["ad_id"]], **d}))

    final = sorted((with_market(l, mkt, seen) for l in triage(detailed, stats)),
                   key=lambda l: -l["deal_score"])
    STATE_FILE.write_text(json.dumps({**seen, **{h["id"]: h["price_amount"] for h in hits
                                                  if h.get("price_amount")}}), encoding="utf-8")
    folder = write_outputs(final, stats)

    print(f"\nExcluded: {stats['excluded']}")
    print(f"Output: {folder}  (paste digest.md into an LLM)\nTop {min(TOP_N, len(final))}:")
    for l in final[:TOP_N]:
        print(f"  {l['deal_score']:.2f} €{l['price']:g} {l['gpu']} / {l['cpu'] or '?'} / "
              f"{l['ram_gb'] or '?'}GB — {l['title'][:50]} {' '.join(l['flags'])}")
    return final, folder


if __name__ == "__main__":
    asyncio.run(run())
