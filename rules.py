"""The Deal Evaluation Brief (Target.md) as code: build extraction with sources,
hard rejects (§2), fix ledger -> effective price (§5), tiers (§3, §6),
tie-breakers, special cases (Priming §6.3), risk signals (Priming §7) and
seller questions (Priming §9C). Pure functions, no I/O."""
import re

import hardware
import parse
import prices
from policy import DEFAULT_POLICY, Policy

# RAM prices (Brief §5): path costs only, never counted toward the limit
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
PRICE_SCOPE_RE = re.compile(
    r"preis\s+(?:gilt\s+)?(?:nur\s+)?f(?:ü|ue)r\s+(?:die\s+|den\s+|das\s+)?(?:grafikkarte|gpu|graka|cpu|prozessor|ram|"
    r"arbeitsspeicher|mainboard|netzteil|geh(?:ä|ae)use|einzel)|preis\s+pro\s+(?:st(?:ü|ue)ck|teil|komponente)|"
    r"st(?:ü|ue)ckpreis|einzelpreis|preise?\s+(?:siehe|laut)\s+(?:beschreibung|liste)|\bab\s+\d+\s*(?:€|euro)|anzahlung")
BUNDLE_RE = re.compile(r"aufr(?:ü|ue)st[\s-]*(?:kit|set|pc|paket)|\bbundle\b|\bkit\b")
TIER_NAMES = {0: "0 (24 GB NVIDIA)", 1: "1", 2: "2", 3: "3 (no day-one agent)",
              4: "4 (AM4 64 GB+, or Intel with one drawback)",
              5: "5 (dead end: AM4 under 64 GB, or Intel with both drawbacks)"}
# Brief §3 table: (min RAM GB, min VRAM GB, day-one model, its experts in GB). UD-IQ4's
# experts are not in the Brief: an estimate from its 66-76 GB download.
AI_TIERS = [(96, 0, "UD-IQ4 (headroom)", 65), (64, 0, "IQ3_S (ideal)", 50),
            (48, 0, "IQ2_XS (good, borderline fit)", 36), (32, 24, "IQ2_XS (good: 24 GB VRAM covers the gap)", 36),
            (32, 0, "Coder IQ1_M (good coding)", 23), (0, 0, "none (needs RAM)", 23)]
VRAM_RESERVE_GB = 1          # estimate: attention + KV cache kept on the GPU next to the experts
# Moving an Intel PC onto AM5 (€, used, Nov 2026 estimates): board + CPU bought, Intel board + CPU sold.
AM5_SWAP_BOARD = 120         # used B650
AM5_SWAP_CPU = 140           # used Ryzen 5 7600
INTEL_RESALE = {"LGA1851": 180, "LGA1700": 120, "LGA1200": 70}
INTEL_RESALE_STRONG = 100    # extra for a strong CPU (i5-13600K / i7 / i9 / Ultra 7 class)
# Text rejects a policy switch can turn off.
FATAL_SWITCHES = {"oem_prebuilt": "allow_oem", "mini_pc_or_handheld": "allow_mini_pc"}

PICKUP_ONLY_RE = re.compile(r"nur\s+(?:an\s+|für\s+|gegen\s+|bei\s+)?(?:selbst)?abhol\w*|selbstabholer|"
                            r"kein(?:en)?\s+versand|versand\s+(?:ist\s+)?(?:nicht\s+möglich|ausgeschlossen)|"
                            r"(?:wird\s+)?nicht\s+versendet|keine?\s+versendung|versende\s+nicht")
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
    intel = hardware.intel_facts(cpu, chipset, ddr) if platform == "INTEL" else None
    return {
        "intel": intel, "ddr_stated": ddr is not None,
        "gpu": gpu, "cpu": cpu, "chipset": chipset, "case": case,
        "platform": _val(platform, platform_src),
        "ram_gb": _val(ram or 16, "stated" if ram and not ram_conflict else "assumed"),
        "ram_layout": ram_layout,
        # unstated DDR: AM5 and Core Ultra 5, else 4 (the worst case on LGA1700)
        "ddr": ddr or (5 if platform == "AM5" or (intel and intel["gen"] >= parse.ULTRA_GEN)
                       else 4 if platform in ("AM4", "INTEL") else None),
        "two_slots": two_slots,
        "itx": case["sff"],
        "psu": _val(psu, "stated" if psu["watts"] or psu["trusted"] or psu["missing"] else "assumed"),
        "cooler": _val(cooler or "stock", "stated" if cooler else "assumed"),
        "storage": _val(storage, "stated" if (storage["gb"] and storage["nvme"]) or storage["missing"] else "assumed"),
        "conflicts": [p for p, bad in (("gpu", (gpu or {}).get("conflict")), ("cpu", (cpu or {}).get("conflict")),
                                       ("ram", ram_conflict)) if bad],
    }


def hard_reject(b: dict, policy: Policy, ignore_vram: bool = False) -> str | None:
    """First Brief §2 hit the policy still enforces, or None."""
    gpu, cpu, platform = b["gpu"], b["cpu"], b["platform"]["v"]
    if platform == "INTEL" and not policy.allow_intel:
        return "intel_platform"
    if platform == "INTEL" and b["intel"]["old"]:
        return "intel_old"
    if not cpu:
        return "cpu_unknown"
    if not gpu:
        return "gpu_unknown"
    if gpu["vendor"] == "intel" and not policy.allow_arc:
        return "intel_arc"
    if gpu["vram"] < policy.min_vram and not ignore_vram:
        return f"vram_under_{policy.min_vram}gb"
    if platform != "INTEL" and cpu.get("model") in APU_X4 and cpu.get("suffix") in ("G", "F") and not policy.allow_apu_x4:
        return "apu_pcie_x4"
    ddr4_dead_end = platform == "AM4" or (platform == "INTEL" and b["ddr"] == 4 and b["ddr_stated"])
    if ddr4_dead_end and b["ram_gb"]["v"] < policy.am4_min_ram:
        return f"ddr4_under_{policy.am4_min_ram}gb"
    if b["itx"] and not policy.allow_sff:
        return "itx_or_sff"
    return None


def as_bundle(b: dict, fatal: str | None, text: str) -> bool:
    """Priming §5.1 secondary track: an AM5 platform sold without a GPU (an
    "Aufrüstkit" or a GPU-less PC). It is priced with a GPU bought separately."""
    return (not b["gpu"] and b["platform"]["v"] == "AM5" and b["platform"]["src"] == "stated"
            and fatal in (None, "no_gpu") and (fatal == "no_gpu" or bool(BUNDLE_RE.search(text.lower()))))


def with_bought_gpu(b: dict) -> dict:
    """The build as it will be: a used RTX 3060 12 GB added (policy.fix_gpu)."""
    gpu = {"name": "RTX 3060", "vendor": "nvidia", "vram": 12, "vram_stated": True, "in_desc": False,
           "conflict": False, "to_buy": True}
    return {**b, "gpu": gpu}


def fix_ledger(b: dict, policy: Policy = DEFAULT_POLICY, bundle: bool = False) -> dict:
    """{part: (€, confirmed)} (Brief §5). Confirmed: the listing says the part is missing or
    too weak, so the fix counts toward the price. Unconfirmed: the part is not mentioned, or
    its brand, size or type is not, on a PC sold as working; flagged and in the worst case only."""
    out = {}
    psu, gpu = b["psu"]["v"], b["gpu"] or {}
    big = gpu.get("vram", 0) >= 24
    need, eur = (policy.psu_min_24gb_w, policy.fix_psu_24gb) if big else (policy.psu_min_w, policy.fix_psu)
    if psu["missing"] or (psu["watts"] and psu["watts"] < need):
        out["psu"] = (eur, True)
    elif not (psu["trusted"] and psu["watts"]):
        out["psu"] = (eur, False)
    cpu = b["cpu"] or {}
    model, suffix = cpu.get("model") or "", cpu.get("suffix") or ""
    if cpu.get("platform") == "INTEL":
        hot = "K" in suffix                       # 125 W+ unlocked parts
    else:
        hot = suffix == "X3D" or (suffix == "X" and model[:1] == "7") or model in ("9900", "9950")
    if hot and b["cooler"]["v"] != "tower":
        out["cooler"] = (policy.fix_cooler, b["cooler"]["src"] == "stated")   # a stated stock cooler
    st = b["storage"]["v"]
    if not (st["nvme"] and (st["gb"] or 0) >= 960):
        out["ssd"] = (policy.fix_ssd, st["missing"] or (st["gb"] is not None and st["gb"] < 960))
    if bundle:
        out["gpu"] = (policy.fix_gpu, True)
        if not b["case"]["name"]:
            out["case"] = (policy.fix_case, True)
    return out


def fixes(b: dict, policy: Policy = DEFAULT_POLICY, bundle: bool = False) -> dict:
    """{deficit: €} counting toward the price: the confirmed fixes."""
    return {k: eur for k, (eur, sure) in fix_ledger(b, policy, bundle).items() if sure}


def maybe_fixes(b: dict, policy: Policy = DEFAULT_POLICY, bundle: bool = False) -> dict:
    """{part: €} the listing leaves open: only in the worst-case price."""
    return {k: eur for k, (eur, sure) in fix_ledger(b, policy, bundle).items() if not sure}


def unconfirmed_flags(b: dict, maybe: dict) -> list[str]:
    out = []
    if "psu" in maybe:
        psu = b["psu"]["v"]
        out.append("psu_unstated" if b["psu"]["src"] == "assumed" else
                   "psu_watts_unknown" if psu["trusted"] else "psu_brand_unknown")
    if "ssd" in maybe:
        out.append("ssd_unstated" if b["storage"]["src"] == "assumed" else "ssd_type_or_size_unknown")
    if "cooler" in maybe:
        out.append("cooler_unstated")
    return out


def ram_path(b: dict) -> dict:
    """€ to reach 32 GB and 64 GB (outside the policy, Brief §5). 2×24 GB has no
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


def _ai(b: dict) -> tuple:
    gb, vram = b["ram_gb"]["v"], (b["gpu"] or {}).get("vram", 0)
    return next(t for t in AI_TIERS if gb >= t[0] and vram >= t[1])


def ai_tier(b: dict) -> str:
    """Brief §3: model version that runs on day one."""
    return _ai(b)[2]


def experts_on_cpu(b: dict) -> int:
    """GB of the day-one model's experts that do not fit in VRAM: Strata computes them on
    the CPU, where AVX-512 matters (Brief §4.1). 0 = everything fits on the GPU."""
    return max(0, _ai(b)[3] + VRAM_RESERVE_GB - (b["gpu"] or {}).get("vram", 0))


def intel_penalties(b: dict) -> list[str]:
    """The Brief's two Intel objections, each only where it bites:
    - no AVX-512, while part of the model runs on the CPU;
    - a dead socket, under a CPU that is not already strong enough to keep."""
    i, out = b["intel"], []
    if not i["avx512"] and experts_on_cpu(b) > 0:
        out.append("no_avx512_offload")
    if not i["strong"]:
        out.append("dead_socket")
    return out


def am5_swap(b: dict) -> int:
    """€ to move an Intel PC onto AM5: board + CPU (+ DDR5 for DDR4) bought, Intel parts sold."""
    i = b["intel"]
    resale = INTEL_RESALE.get(i["socket"], 0) + (INTEL_RESALE_STRONG if i["strong"] else 0)
    ram = 0
    if b["ddr"] != 5:
        gb = b["ram_gb"]["v"]
        ram = (RAM_DDR5_2X32 if gb > 32 else RAM_DDR5_2X16) - gb * hardware.RAM_EUR_PER_GB[4]
    return AM5_SWAP_BOARD + AM5_SWAP_CPU + ram - resale


def tier(b: dict) -> int | None:
    """Brief §6 tier, or None when no tier applies. Intel ranks like AM5 when neither
    Intel objection applies, tier 4 with one and tier 5 with both."""
    gpu, gb, platform = b["gpu"], b["ram_gb"]["v"], b["platform"]["v"]
    psu = b["psu"]["v"]
    if gpu["vendor"] == "nvidia" and gpu["vram"] >= 24:
        return 0
    if platform == "AM4":
        return 4 if gb >= 64 else 5   # 5: AM4 below the Brief's 64 GB, allowed by settings
    if platform not in ("AM5", "INTEL"):
        return None
    if gb < 32:
        base = 3
    elif gpu["vendor"] == "nvidia" and gpu["vram"] >= 16 and psu["trusted"] and (psu["watts"] or 0) >= 750:
        base = 1
    else:
        base = 2
    drawbacks = len(intel_penalties(b)) if platform == "INTEL" else 0
    return max(base, 3 + drawbacks) if drawbacks else base


def sort_key(l: dict) -> tuple:
    """Tier, then "needs seller answers" (lower), then Brief §6 tie-breakers, then effective price."""
    b = l["build"]
    psu = b["psu"]["v"]
    return (l["tier"], l["needs_answers"], -b["ram_gb"]["v"], b["gpu"]["vendor"] != "nvidia", -b["gpu"]["vram"],
            b["chipset"] == "A620", -(psu["trusted"] * 1000 + (psu["watts"] or 0)),
            b["ram_layout"]["v"][0] != 2, b["chipset"] not in PCIE5_CHIPSETS,
            -((b["cpu"] or {}).get("tier") or 0), l["budget"])


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
    if "cooler" in fix_ledger(b) and b["cooler"]["src"] == "assumed":
        out.append("cooler")
    if not b["case"]["name"]:
        out.append("case")
    if (b.get("intel") or {}).get("raptor_lake"):
        out.append("intel_bios")
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
    "intel_bios": "Ist das BIOS aktuell, mit Intels Microcode-Update 0x12B oder neuer (Stabilität 13./14. Generation)?",
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


VB_MAX_HAGGLE = 0.15         # most a VB seller is expected to come down, even when the fair price is lower
TOO_CHEAP = 0.65            # ask below 65 % of the same-GPU median ask = scam signal (Priming §7.1)


def price_reject(ask: int, desc: str, floor: int, share: float = DEFAULT_POLICY.misprice_share) -> str | None:
    """The asking price is not the price of this whole PC: missing, a placeholder,
    explicitly a part price, or far below what its GPU + RAM alone are worth."""
    if not ask:
        return "no_price"
    if ask <= PLACEHOLDER_MAX:
        return "placeholder_price"
    if PRICE_SCOPE_RE.search(desc.lower()):
        return "price_not_for_whole_pc"
    if floor and ask < share * floor:
        return "price_below_parts_value"
    return None


def pickup_reject(rec: dict, policy: Policy) -> str | None:
    """The user's filter on "Nur Abholung" listings: keep, keep only local ones, or drop."""
    if not rec["pickup_only"] or policy.pickup_only == "keep":
        return None
    if policy.pickup_only == "drop":
        return "pickup_only"
    return None if rec["local"] else "pickup_only_not_local"


def value(delta: float | None, trusted: bool, policy: Policy) -> str | None:
    """"under" / "over" against the fair price, only when the key parts were read, not assumed."""
    if delta is None or not trusted:
        return None
    if delta <= -policy.underpriced_pct / 100:
        return "under"
    return "over" if delta >= policy.overpriced_pct / 100 else None


def vb_price(ask: int, fair: int | None, policy: Policy) -> int:
    """Expected price of a VB listing: the usual haggle, or down to the fair price when that
    is lower, but never more than VB_MAX_HAGGLE off the ask."""
    usual = ask * (1 - policy.vb_discount)
    return round(usual if fair is None else max(ask * (1 - VB_MAX_HAGGLE), min(usual, fair)))


def assess(ad: dict, policy: Policy = DEFAULT_POLICY, gpu_median: float | None = None,
           table: dict | None = None) -> dict:
    """One listing (search hit or detail) -> assessed record. `reject` is set when
    it fails; `special` for a §6.3 arbitrage case; `track` is "pc" or "bundle".
    `gpu_median`: median ask of PCs with the same GPU in this scan."""
    title, desc = ad.get("title", ""), ad.get("description", "")
    attrs = ad.get("attributes") or {}
    ask = round(ad.get("price_amount") or 0)
    vb = ad.get("price_type") == "PLEASE_CONTACT"
    b = extract(title, desc)
    fatal = parse.fatal_reason(title, desc, attrs)
    if fatal in FATAL_SWITCHES and getattr(policy, FATAL_SWITCHES[fatal]):
        fatal = None
    bundle = as_bundle(b, fatal, f"{title}\n{desc}")
    if bundle:
        b, fatal = with_bought_gpu(b), None
    scam, cond = risk(desc, ad)
    if gpu_median and ask and ask < TOO_CHEAP * gpu_median:
        scam.append("too_cheap_vs_market")
    pickup_only = attrs.get("Versand") == "Nur Abholung" or bool(PICKUP_ONLY_RE.search(desc.lower()))
    rec = {
        "ad_id": ad.get("id"), "url": ad.get("url"), "title": title, "ask": ask, "vb": vb,
        "location": ad.get("location"), "zip": ad.get("zip_code"), "posted": ad.get("start_date"),
        "seller_id": ad.get("seller_id"), "seller_rating": ad.get("seller_rating"), "local": bool(ad.get("local")),
        "track": "bundle" if bundle else "pc", "pickup_only": pickup_only,
        "ships": (attrs.get("Versand") == "Versand möglich" or bool(ad.get("shipping_options"))) and not pickup_only,
        "commercial": ad.get("seller_account_type") == "COMMERCIAL",
        "build": b, "scam": scam, "cond": cond, "description": desc, "full_text": "attributes" in ad,
        "reject": None, "special": False, "tier": None, "flags": [],
    }
    fp = prices.fair(b, table) if table and not bundle else None
    rec.update(fair=(fp or {}).get("eur"), fair_parts=(fp or {}).get("parts"), fair_missing=(fp or {}).get("missing"),
               fair_stated=bool(fp and fp["stated"]))
    rec.update(fair_delta=round(ask / rec["fair"] - 1, 3) if rec["fair"] and ask else None)
    rec["value"] = value(rec["fair_delta"], rec["fair_stated"], policy)
    price = vb_price(ask, rec["fair"] if rec["fair_stated"] else None, policy) if vb else ask
    fx, maybe = fixes(b, policy, bundle), maybe_fixes(b, policy, bundle)
    effective = price + sum(fx.values())
    rec.update(price=price, fixes=fx, maybe_fixes=maybe, effective=effective, worst=effective + sum(maybe.values()),
               budget=ask if policy.price_basis == "list" else effective, path=ram_path(b),
               ai=ai_tier(b), unknown=unknowns(b), am5_swap=am5_swap(b) if b["intel"] else None)
    rec.update(needs_answers=bool(CRITICAL_UNKNOWNS & set(rec["unknown"])), featured=False,
               link=hardware.pcie_link(b) if b["gpu"] else None, headroom=hardware.headroom(b),
               gpu_note=hardware.card(b["gpu"]).note, parts_floor=hardware.parts_floor(b))
    rec["reject"] = (fatal or price_reject(ask, desc, rec["parts_floor"], policy.misprice_share)
                     or hard_reject(b, policy) or ("scam_signals" if len(scam) >= policy.scam_signals_drop else None)
                     or pickup_reject(rec, policy))
    if (rec["reject"] or "").startswith("vram_under_") and not hard_reject(b, policy, ignore_vram=True) \
            and b["ram_gb"]["v"] >= 48 and rec["budget"] + policy.fix_gpu <= policy.special_max:
        rec["special"] = True
    if rec["reject"]:
        return rec
    t = tier(b)
    limit = policy.limit + (policy.stretch if t is not None and t <= 1 else 0)
    if t is None:
        rec["reject"] = "platform_unknown"
    elif t == 4 and b["platform"]["v"] == "AM4" and rec["budget"] > policy.am4_max:
        rec["reject"] = "am4_over_550"
    elif rec["budget"] > limit:
        rec["reject"] = "over_budget"
    rec["tier"] = t
    rec["flags"] = _flags(rec, t, policy)
    return rec


def _flags(rec: dict, t: int | None, policy: Policy) -> list[str]:
    b, f = rec["build"], []
    if rec["budget"] > policy.limit:
        f.append(f"stretch_over_{policy.limit}")
    if t is not None and t <= 2 and rec["budget"] <= policy.target:
        f.append("act_fast")
    if b["chipset"] == "A620":
        f.append(f"a620_board_swap_later_{BOARD_SWAP_A620}")
    if rec["link"] and rec["link"]["reduced"]:
        f.append("pcie_link_reduced")
    if b["gpu"]["vendor"] == "amd":
        f.append("amd_gpu_secondary")
    if b["gpu"]["vram"] < 12:
        f.append("vram_below_brief")
    if b["intel"]:
        i = b["intel"]
        f += [f"intel_{p}" for p in intel_penalties(b)]
        f += [name for name, on in (("intel_cpu_strong", i["strong"]), ("intel_gen_assumed", i["gen_src"] == "assumed"),
                                    ("lga1851_no_next_gen_cpus", i["socket"] == "LGA1851"),
                                    ("raptor_lake_check_bios", i["raptor_lake"])) if on]
    if rec["pickup_only"]:
        f.append("pickup_only")
    if rec["value"]:
        f.append(f"{rec['value']}priced_{abs(round(rec['fair_delta'] * 100))}pct")
    if rec["vb"] and rec["fair_stated"] and rec["price"] < round(rec["ask"] * (1 - policy.vb_discount)):
        f.append("vb_target_from_fair_price")
    f += unconfirmed_flags(b, rec["maybe_fixes"])
    if not rec["full_text"]:
        f.append("preview_only")
    if b["ram_layout"]["v"][0] == 4:
        f.append("ram_slots_full")
    if rec["needs_answers"]:
        f.append("needs_answers")
    f += [f"conflict_{p}" for p in b["conflicts"]]
    f += [f"{p}_missing" for p in ("psu", "storage") if b[p]["v"].get("missing")]
    return f + rec["scam"] + rec["cond"] + (["commercial"] if rec["commercial"] else [])


def finalize(passed: list[dict], policy: Policy = DEFAULT_POLICY) -> list[dict]:
    """Rank the passing listings and decide which are featured (new records, inputs untouched).
    - Tier 3 (16 GB) counts only if effective + the RAM step still beats the best
      tier 0-2 PC (Brief §6.3); otherwise it is flagged and not featured.
    - A listing that needs seller answers is featured only when the deal is good:
      tier 0-1, a budget price at or below the target, or underpriced against the fair price.
    - An Intel PC gets the cost of moving it onto AM5, compared with the best AM5 deal."""
    pcs = [r for r in passed if r["track"] == "pc" and r["tier"] <= 2]
    best = min((r["budget"] for r in pcs), default=None)
    best_am5 = min((r["budget"] for r in pcs if r["build"]["platform"]["v"] == "AM5"), default=None)
    out = []
    for r in sorted(passed, key=sort_key):
        flags, featured = list(r["flags"]), True
        if r["tier"] == 3 and best is not None:
            beats = r["budget"] + RAM_DDR5_2X16 < best
            flags.append("beats_tier12_with_ram" if beats else "dominated_by_tier12")
            featured = beats
        if r["needs_answers"] and not (r["tier"] <= 1 or r["budget"] <= policy.target or r.get("value") == "under"):
            featured = False
        if r["am5_swap"] is not None and best_am5 is not None:
            flags.append("am5_swap_beats_best_am5" if r["budget"] + r["am5_swap"] < best_am5 else "am5_swap_dearer")
        out.append({**r, "flags": flags, "featured": featured, "best_am5": best_am5})
    return out
