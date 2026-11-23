"""The Deal Evaluation Brief (Target.md) as code: build extraction with sources,
hard rejects (§2), fix ledger -> effective price (§5), tiers (§3, §6),
tie-breakers, special cases (Priming §6.3), risk signals (Priming §7) and
seller questions (Priming §9C). Pure functions, no I/O."""
import re
from dataclasses import dataclass

import hardware
import parse


@dataclass(frozen=True)
class Budget:
    """Brief §0 / Priming §2. Defaults match the Brief; search.toml overrides them."""
    limit: int = 700            # hard limit on effective price
    target: int = 600           # "act fast" when a tier 0-2 deal lands at or below this
    stretch: int = 75           # tier 0-1 deals may exceed the limit by this much (flagged)
    am4_max: int = 550          # tier 4 cap (Brief §6)
    vb_discount: float = 0.10   # realistic haggle on "VB" listings (Priming §6.1: 5-15 %)
    special_max: int = 800      # §6.3 special case: effective + GPU fix must stay under this


DEFAULT_BUDGET = Budget()

# ---- fix ledger (Brief §5; € estimates, Nov 2026) ----
FIX_PSU = 95                 # 750 W Gold (80-110)
FIX_PSU_3090 = 120           # 850 W Gold for a 24 GB card
FIX_COOLER = 30              # tower cooler for a 105 W+ CPU (25-40)
FIX_SSD = 90                 # 1 TB NVMe ("scan" in the Brief; SSD prices are up)
FIX_GPU = 220                # used RTX 3060 12 GB: §6.3 special cases and the bundle track
FIX_CASE = 65                # airflow case (50-80), bundle track only: a PC's case is never priced
RAM_DDR5_2X16 = 490
RAM_DDR5_2X32 = 950          # 900-1,000
RAM_DDR4_2X16 = 285          # 200-370
BOARD_SWAP_A620 = 125        # future cost, not counted (100-150)

APU_X4 = {"8500", "8300"}           # Ryzen 5 8500G / 3 8300G: GPU at PCIe 4.0 x4 (hard reject)
PCIE5_CHIPSETS = hardware.PCIE5_CHIPSETS
# Unknowns that can flip the verdict (an 8 GB twin, the platform, the RAM). Others are
# already priced at their worst case, so they are asked about but cost no rank.
CRITICAL_UNKNOWNS = {"gpu_vram", "cpu", "ram"}
PLACEHOLDER_MAX = 20         # "1 €", "10 €": a price placeholder, never the real price
MISPRICE_SHARE = 0.5         # ask below half the GPU + RAM value alone: a part price, a typo or a scam
PRICE_SCOPE_RE = re.compile(
    r"preis\s+(?:gilt\s+)?(?:nur\s+)?f(?:ü|ue)r\s+(?:die\s+|den\s+|das\s+)?(?:grafikkarte|gpu|graka|cpu|prozessor|ram|"
    r"arbeitsspeicher|mainboard|netzteil|geh(?:ä|ae)use|einzel)|preis\s+pro\s+(?:st(?:ü|ue)ck|teil|komponente)|"
    r"st(?:ü|ue)ckpreis|einzelpreis|preise?\s+(?:siehe|laut)\s+(?:beschreibung|liste)|\bab\s+\d+\s*(?:€|euro)|anzahlung")
BUNDLE_RE = re.compile(r"aufr(?:ü|ue)st[\s-]*(?:kit|set|pc|paket)|\bbundle\b|\bkit\b")
TIER_NAMES = {0: "0 (24 GB NVIDIA)", 1: "1", 2: "2", 3: "3 (no day-one agent)", 4: "4 (AM4 64 GB+)"}

SHIP_ONLY_RE = re.compile(r"nur\s+(?:per\s+)?versand|keine?\s+abholung|abholung\s+(?:ist\s+)?nicht\s+möglich")
ABROAD_RE = re.compile(r"im\s+ausland|derzeit\s+(?:im\s+ausland|unterwegs)|beruflich\s+unterwegs")
OFFPLATFORM_RE = re.compile(r"whatsapp|paypal\s+freunde|freunde\s+(?:und|&)\s+familie|vorkasse|western\s+union|"
                            r"überweisung\s+(?:im\s+)?voraus")
MINING_RE = re.compile(r"\bmining|\bgemined|24/7")
SMOKER_RE = re.compile(r"raucher(?!frei)|nikotin")
RECEIPT_RE = re.compile(r"rechnung\s+(?:ist\s+)?(?:vorhanden|liegt|dabei|anbei)|mit\s+rechnung|\bovp\b")
SMOKE_FREE_RE = re.compile(r"nichtraucher|rauchfrei")


def _val(value, source: str) -> dict:
    return {"v": value, "src": source}


def extract(title: str, desc: str) -> dict:
    """Build with a source per part: 'stated' (text) or 'assumed' (Priming §6.2).
    A part the text contradicts (title 32 GB, description 16 GB) counts as assumed."""
    text = f"{title}\n{desc}"
    gpu, cpu = parse.parse_gpu(title, desc), parse.parse_cpu(title, desc)
    chipset, ddr = parse.parse_chipset(text), parse.parse_ddr(text)
    platform = (cpu or {}).get("platform") or parse.chipset_platform(chipset)
    platform_src = "stated" if platform and not (cpu or {}).get("conflict") else "assumed"
    if not platform and cpu and ddr:          # "Ryzen 7" + DDR5 -> AM5
        platform = "AM5" if ddr == 5 else "AM4"
    elif not platform and cpu and "Ryzen" in cpu["label"]:
        platform = "AM4"                      # worst case for an unnamed Ryzen generation

    ram_found = parse.ram_candidates(title, desc)
    ram = ram_found[0] if ram_found else None
    ram_conflict = len(set(ram_found)) > 1
    layout = parse.parse_ram_layout(title, desc)
    if layout and ram and layout[0] * layout[1] != ram:
        layout = None
    case = parse.parse_case(title, desc)
    two_slots = chipset == "A620" or case["sff"]
    if layout and not ram_conflict:
        ram_layout = _val(layout, "stated")
    elif ram:
        worst = (2, ram // 2) if ram in (48, 96) or ram <= 16 or two_slots else (4, ram // 4)
        ram_layout = _val(worst, "assumed")
    else:
        ram_layout = _val((2, 8), "assumed")

    psu = parse.parse_psu(title, desc) or {"watts": None, "trusted": False, "missing": False}
    storage = parse.parse_storage(title, desc)
    cooler = parse.parse_cooler(title, desc)
    return {
        "gpu": gpu, "cpu": cpu, "chipset": chipset, "case": case,
        "platform": _val(platform, platform_src),
        "ram_gb": _val(ram or 16, "stated" if ram and not ram_conflict else "assumed"),
        "ram_layout": ram_layout,
        "ddr": ddr or (5 if platform == "AM5" else 4 if platform == "AM4" else None),
        "two_slots": two_slots,
        "itx": case["sff"],
        "psu": _val(psu, "stated" if psu["watts"] or psu["trusted"] or psu["missing"] else "assumed"),
        "cooler": _val(cooler or "stock", "stated" if cooler else "assumed"),
        "storage": _val(storage, "stated" if (storage["gb"] and storage["nvme"]) or storage["missing"] else "assumed"),
        "conflicts": [p for p, bad in (("gpu", (gpu or {}).get("conflict")), ("cpu", (cpu or {}).get("conflict")),
                                       ("ram", ram_conflict)) if bad],
    }


def hard_reject(b: dict, ignore_vram: bool = False) -> str | None:
    """First Brief §2 hit, or None."""
    gpu, cpu, platform = b["gpu"], b["cpu"], b["platform"]["v"]
    if platform == "INTEL":
        return "intel_platform"
    if not cpu:
        return "cpu_unknown"
    if not gpu:
        return "gpu_unknown"
    if gpu["vendor"] == "intel":
        return "intel_arc"
    if gpu["vram"] < 12 and not ignore_vram:
        return "vram_under_12gb"
    if cpu.get("model") in APU_X4 and cpu.get("suffix") in ("G", "F"):
        return "apu_pcie_x4"
    if platform == "AM4" and b["ram_gb"]["v"] < 64:
        return "am4_under_64gb"
    if b["itx"]:
        return "itx_or_sff"
    return None


def as_bundle(b: dict, fatal: str | None, text: str) -> bool:
    """Priming §5.1 secondary track: an AM5 platform sold without a GPU (an
    "Aufrüstkit" or a GPU-less PC). It is priced with a GPU bought separately."""
    return (not b["gpu"] and b["platform"]["v"] == "AM5" and b["platform"]["src"] == "stated"
            and fatal in (None, "no_gpu") and (fatal == "no_gpu" or bool(BUNDLE_RE.search(text.lower()))))


def with_bought_gpu(b: dict) -> dict:
    """The build as it will be: a used RTX 3060 12 GB added (FIX_GPU)."""
    gpu = {"name": "RTX 3060", "vendor": "nvidia", "vram": 12, "vram_stated": True, "in_desc": False,
           "conflict": False, "to_buy": True}
    return {**b, "gpu": gpu}


def fixes(b: dict, bundle: bool = False) -> dict:
    """{deficit: €} counting toward the limit (Brief §5)."""
    out = {}
    psu, gpu = b["psu"]["v"], b["gpu"] or {}
    need = 850 if gpu.get("vram", 0) >= 24 else 750
    if not (psu["trusted"] and (psu["watts"] or 0) >= need):
        out["psu"] = FIX_PSU_3090 if need == 850 else FIX_PSU
    cpu = b["cpu"] or {}
    hot = cpu.get("suffix") == "X3D" or (cpu.get("suffix") == "X" and (cpu.get("model") or "")[:1] == "7") \
        or (cpu.get("model") or "") in ("9900", "9950")
    if hot and b["cooler"]["v"] != "tower":
        out["cooler"] = FIX_COOLER
    st = b["storage"]["v"]
    if not (st["nvme"] and (st["gb"] or 0) >= 960):
        out["ssd"] = FIX_SSD
    if bundle:
        out["gpu"] = FIX_GPU
        if not b["case"]["name"]:
            out["case"] = FIX_CASE
    return out


def ram_path(b: dict) -> dict:
    """€ to reach 32 GB and 64 GB (outside the budget, Brief §5). 2×24 GB has no
    64 GB step: its path is a second 2×24 kit to 96 GB, which the Brief does not price."""
    gb, (sticks, per) = b["ram_gb"]["v"], b["ram_layout"]["v"]
    if gb == 48 and sticks == 2:
        return {"to32": 0, "to64": None, "note": "48 → 96 GB: + 2×24 kit (price not in the Brief)"}
    if b["ddr"] == 4:
        return {"to32": 0 if gb >= 32 else RAM_DDR4_2X16, "to64": 0 if gb >= 64 else RAM_DDR4_2X16 * (1 if gb >= 32 else 2)}
    to32 = 0 if gb >= 32 else RAM_DDR5_2X16
    if gb >= 64:
        to64 = 0
    elif gb == 32 and sticks == 2 and not b["two_slots"]:
        to64 = RAM_DDR5_2X16
    else:
        to64 = RAM_DDR5_2X32
    return {"to32": to32, "to64": to64}


def ai_tier(b: dict) -> str:
    """Brief §3: model version that runs on day one."""
    gb, vram = b["ram_gb"]["v"], (b["gpu"] or {}).get("vram", 0)
    if gb >= 96:
        return "UD-IQ4 (headroom)"
    if gb >= 64:
        return "IQ3_S (ideal)"
    if gb >= 48:
        return "IQ2_XS (good, borderline fit)"
    if gb >= 32 and vram >= 24:
        return "IQ2_XS (good: 24 GB VRAM covers the gap)"
    if gb >= 32:
        return "Coder IQ1_M (good coding)"
    return "none (needs RAM)"


def tier(b: dict) -> int | None:
    """Brief §6 tier, or None when no tier applies."""
    gpu, gb, platform = b["gpu"], b["ram_gb"]["v"], b["platform"]["v"]
    psu = b["psu"]["v"]
    if gpu["vendor"] == "nvidia" and gpu["vram"] >= 24:
        return 0
    if platform == "AM4":
        return 4
    if platform != "AM5":
        return None
    if gb < 32:
        return 3
    if gpu["vendor"] == "nvidia" and gpu["vram"] >= 16 and psu["trusted"] and (psu["watts"] or 0) >= 750:
        return 1
    return 2


def sort_key(l: dict) -> tuple:
    """Tier, then "needs seller answers" (lower), then Brief §6 tie-breakers, then effective price."""
    b = l["build"]
    psu = b["psu"]["v"]
    return (l["tier"], l["needs_answers"], -b["ram_gb"]["v"], b["gpu"]["vendor"] != "nvidia", -b["gpu"]["vram"],
            b["chipset"] == "A620", -(psu["trusted"] * 1000 + (psu["watts"] or 0)),
            b["ram_layout"]["v"][0] != 2, b["chipset"] not in PCIE5_CHIPSETS,
            -((b["cpu"] or {}).get("tier") or 0), l["effective"])


def risk(desc: str, ad: dict) -> tuple[list[str], list[str]]:
    """(scam signals, condition flags). Priming §7.1 / §7.2."""
    d = desc.lower()
    scam = []
    if SHIP_ONLY_RE.search(d):
        scam.append("shipping_only")
    if ABROAD_RE.search(d):
        scam.append("seller_away")
    if OFFPLATFORM_RE.search(d):
        scam.append("offplatform_payment")
    if ad.get("image_count") == 0:
        scam.append("no_photos")
    cond = []
    if MINING_RE.search(d):
        cond.append("mining_or_24_7")
    if SMOKER_RE.search(d) and not SMOKE_FREE_RE.search(d):
        cond.append("smoker")
    if RECEIPT_RE.search(d):
        cond.append("receipt")
    return scam, cond


def unknowns(b: dict) -> list[str]:
    """Which parts are assumed or contradicted, in the order seller questions ask them."""
    out = []
    gpu = b["gpu"] or {}
    if gpu and not gpu.get("to_buy") and (not gpu["vram_stated"] or "gpu" in b["conflicts"]):
        out.append("gpu_vram")
    if b["platform"]["src"] == "assumed" or not (b["cpu"] or {}).get("model") or "cpu" in b["conflicts"]:
        out.append("cpu")
    if b["ram_gb"]["src"] == "assumed":
        out.append("ram")              # size unknown or contradicted
    elif b["ram_layout"]["src"] == "assumed":
        out.append("ram_layout")       # size known, sticks not: only the RAM path cost depends on it
    if not b["chipset"]:
        out.append("board")
    if b["psu"]["src"] == "assumed" or not b["psu"]["v"]["trusted"]:
        out.append("psu")
    if b["storage"]["src"] == "assumed":
        out.append("storage")
    if "cooler" in fixes(b) and b["cooler"]["src"] == "assumed":
        out.append("cooler")
    if not b["case"]["name"]:
        out.append("case")
    return out


QUESTIONS = {
    "gpu_vram": "Welche Grafikkarte genau (Modell, wie viel VRAM)?",
    "cpu": "Welcher Prozessor genau (Modell)?",
    "ram": "Wie viel Arbeitsspeicher ist verbaut, und wie ist er bestückt (z. B. 2×16 oder 4×8 GB, DDR4/DDR5)?",
    "ram_layout": "Wie ist der Arbeitsspeicher bestückt (z. B. 2×16 oder 4×8 GB)?",
    "board": "Welches Mainboard genau (Modell)?",
    "psu": "Welches Netzteil ist verbaut (Marke, Modell, Watt, ungefähres Alter)?",
    "storage": "Welche SSD ist verbaut (NVMe/M.2 oder SATA, Größe)?",
    "cooler": "Welcher CPU-Kühler ist verbaut?",
    "case": "Welches Gehäuse ist es (Modell), und wie lang darf die Grafikkarte sein?",
}


SCREENSHOT_PARTS = ("gpu_vram", "cpu", "ram", "ram_layout", "board")
SCREENSHOT_Q = "Könnten Sie Screenshots von CPU-Z (Reiter „Mainboard“ und „SPD“) und GPU-Z schicken?"
PSU_PHOTO_Q = "Könnten Sie ein Foto vom Typenschild des Netzteils schicken (Marke, Modell, Watt)?"


def seller_message(unknown: list[str], ships: bool, mining_flag: bool) -> str:
    """Short numbered questions. Two or more of GPU/CPU/RAM/board unknown -> one
    screenshot request answers them all; an unknown PSU -> a label photo."""
    shots = [u for u in unknown if u in SCREENSHOT_PARTS]
    qs = [SCREENSHOT_Q] if len(shots) >= 2 else [QUESTIONS[u] for u in shots]
    qs += [PSU_PHOTO_Q if u == "psu" else QUESTIONS[u] for u in unknown if u not in SCREENSHOT_PARTS]
    if not mining_flag:
        qs.append("Wurde die Grafikkarte zum Mining oder im 24/7-Betrieb genutzt?")
    qs.append("Ist eine Rechnung vorhanden?")
    qs.append("Wäre Versand mit „Sicher bezahlen“ möglich?" if ships else "Kann ich den PC bei Abholung kurz testen?")
    lines = "\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1))
    return f"Hallo,\n\nich interessiere mich für Ihren PC und hätte noch ein paar kurze Fragen:\n{lines}\n\nVielen Dank und viele Grüße"


TOO_CHEAP = 0.65             # ask below 65 % of the same-GPU median ask = scam signal (Priming §7.1)


def price_reject(ask: int, desc: str, floor: int) -> str | None:
    """The asking price is not the price of this whole PC: missing, a placeholder,
    explicitly a part price, or far below what its GPU + RAM alone are worth."""
    if not ask:
        return "no_price"
    if ask <= PLACEHOLDER_MAX:
        return "placeholder_price"
    if PRICE_SCOPE_RE.search(desc.lower()):
        return "price_not_for_whole_pc"
    if floor and ask < MISPRICE_SHARE * floor:
        return "price_below_parts_value"
    return None


def assess(ad: dict, budget: Budget = DEFAULT_BUDGET, gpu_median: float | None = None) -> dict:
    """One listing (search hit or detail) -> assessed record. `reject` is set when
    it fails; `special` for a §6.3 arbitrage case; `track` is "pc" or "bundle".
    `gpu_median`: median ask of PCs with the same GPU in this scan."""
    title, desc = ad.get("title", ""), ad.get("description", "")
    attrs = ad.get("attributes") or {}
    ask = round(ad.get("price_amount") or 0)
    vb = ad.get("price_type") == "PLEASE_CONTACT"
    b = extract(title, desc)
    fatal = parse.fatal_reason(title, desc, attrs)
    bundle = as_bundle(b, fatal, f"{title}\n{desc}")
    if bundle:
        b, fatal = with_bought_gpu(b), None
    scam, cond = risk(desc, ad)
    if gpu_median and ask and ask < TOO_CHEAP * gpu_median:
        scam.append("too_cheap_vs_market")
    rec = {
        "ad_id": ad.get("id"), "url": ad.get("url"), "title": title, "ask": ask, "vb": vb,
        "location": ad.get("location"), "zip": ad.get("zip_code"), "posted": ad.get("start_date"),
        "seller_id": ad.get("seller_id"), "seller_rating": ad.get("seller_rating"), "local": bool(ad.get("local")),
        "track": "bundle" if bundle else "pc",
        "ships": attrs.get("Versand") == "Versand möglich" or bool(ad.get("shipping_options")),
        "commercial": ad.get("seller_account_type") == "COMMERCIAL",
        "build": b, "scam": scam, "cond": cond, "description": desc,
        "reject": None, "special": False, "tier": None, "flags": [],
    }
    price = round(ask * (1 - budget.vb_discount)) if vb else ask
    fx = fixes(b, bundle)
    rec.update(price=price, fixes=fx, effective=price + sum(fx.values()), path=ram_path(b),
               ai=ai_tier(b), unknown=unknowns(b))
    rec.update(needs_answers=bool(CRITICAL_UNKNOWNS & set(rec["unknown"])), featured=False,
               link=hardware.pcie_link(b) if b["gpu"] else None, headroom=hardware.headroom(b),
               gpu_note=hardware.card(b["gpu"]).note, parts_floor=hardware.parts_floor(b))
    rec["reject"] = (fatal or price_reject(ask, desc, rec["parts_floor"]) or hard_reject(b)
                     or ("scam_signals" if len(scam) >= 2 else None))
    if rec["reject"] == "vram_under_12gb" and not hard_reject(b, ignore_vram=True) \
            and b["ram_gb"]["v"] >= 48 and rec["effective"] + FIX_GPU <= budget.special_max:
        rec["special"] = True
    if rec["reject"]:
        return rec
    t = tier(b)
    limit = budget.limit + (budget.stretch if t is not None and t <= 1 else 0)
    if t is None:
        rec["reject"] = "platform_unknown"
    elif t == 4 and rec["effective"] > budget.am4_max:
        rec["reject"] = "am4_over_550"
    elif rec["effective"] > limit:
        rec["reject"] = "over_budget"
    rec["tier"] = t
    rec["flags"] = _flags(rec, t, budget)
    return rec


def _flags(rec: dict, t: int | None, budget: Budget) -> list[str]:
    b, f = rec["build"], []
    if rec["effective"] > budget.limit:
        f.append(f"stretch_over_{budget.limit}")
    if t is not None and t <= 2 and rec["effective"] <= budget.target:
        f.append("act_fast")
    if b["chipset"] == "A620":
        f.append(f"a620_board_swap_later_{BOARD_SWAP_A620}")
    if rec["link"] and rec["link"]["reduced"]:
        f.append("pcie_link_reduced")
    if b["gpu"]["vendor"] == "amd":
        f.append("amd_gpu_secondary")
    if b["ram_layout"]["v"][0] == 4:
        f.append("ram_slots_full")
    if rec["needs_answers"]:
        f.append("needs_answers")
    f += [f"conflict_{p}" for p in b["conflicts"]]
    f += [f"{p}_missing" for p in ("psu", "storage") if b[p]["v"].get("missing")]
    return f + rec["scam"] + rec["cond"] + (["commercial"] if rec["commercial"] else [])


def finalize(passed: list[dict], budget: Budget = DEFAULT_BUDGET) -> list[dict]:
    """Rank the passing listings and decide which are featured (new records, inputs untouched).
    - Tier 3 (16 GB) counts only if effective + the RAM step still beats the best
      tier 0-2 PC (Brief §6.3); otherwise it is flagged and not featured.
    - A listing that needs seller answers is featured only when the deal is good:
      tier 0-1, or effective at or below the target."""
    best = min((r["effective"] for r in passed if r["track"] == "pc" and r["tier"] <= 2), default=None)
    out = []
    for r in sorted(passed, key=sort_key):
        flags, featured = list(r["flags"]), True
        if r["tier"] == 3 and best is not None:
            beats = r["effective"] + RAM_DDR5_2X16 < best
            flags.append("beats_tier12_with_ram" if beats else "dominated_by_tier12")
            featured = beats
        if r["needs_answers"] and not (r["tier"] <= 1 or r["effective"] <= budget.target):
            featured = False
        out.append({**r, "flags": flags, "featured": featured})
    return out
