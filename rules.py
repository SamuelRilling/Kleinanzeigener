"""The Deal Evaluation Brief (Target.md) as code: build extraction with sources,
hard rejects (§2), fix ledger -> effective price (§5), tiers (§3, §6),
tie-breakers, special cases (Priming §6.3), risk signals (Priming §7) and
seller questions (Priming §9C). Pure functions, no I/O."""
import re

import parse

# ---- budget (Brief §0 / Priming §2) ----
BUDGET = 700                 # hard limit on effective price
TARGET = 600                 # "act fast" when a tier 0-2 deal lands at or below this
STRETCH = 75                 # tier 0-1 deals may exceed BUDGET by this much (flagged)
AM4_MAX = 550                # tier 4 cap (Brief §6)
VB_DISCOUNT = 0.10           # realistic haggle on "VB" listings (Priming §6.1: 5-15 %)
SPECIAL_MAX = 800            # §6.3 special case: effective + GPU fix must stay under this

# ---- fix ledger (Brief §5; € estimates, Nov 2026) ----
FIX_PSU = 95                 # 750 W Gold (80-110)
FIX_PSU_3090 = 120           # 850 W Gold for a 24 GB card
FIX_COOLER = 30              # tower cooler for a 105 W+ CPU (25-40)
FIX_SSD = 90                 # 1 TB NVMe ("scan" in the Brief; SSD prices are up)
FIX_GPU_SPECIAL = 220        # used RTX 3060 12 GB, for §6.3 special cases
RAM_DDR5_2X16 = 490
RAM_DDR5_2X32 = 950          # 900-1,000
RAM_DDR4_2X16 = 285          # 200-370
BOARD_SWAP_A620 = 125        # future cost, not counted (100-150)

X8_GPUS = {"RTX 4060 Ti", "RTX 5060 Ti", "RX 7600 XT"}
APU_X4 = {"8500", "8300"}           # Ryzen 5 8500G / 3 8300G: GPU at PCIe 4.0 x4
APU_X8 = {"8600", "8700", "8400"}   # 8600G/8700G (and 8400F/8700F): x8
PCIE5_CHIPSETS = {"B650E", "X670E", "X870", "X870E"}
TIER_NAMES = {0: "0 (24 GB NVIDIA)", 1: "1", 2: "2", 3: "3 (no day-one agent)", 4: "4 (AM4 64 GB+)"}

SHIP_ONLY_RE = re.compile(r"nur\s+(?:per\s+)?versand|keine?\s+abholung|abholung\s+(?:ist\s+)?nicht\s+möglich")
ABROAD_RE = re.compile(r"im\s+ausland|derzeit\s+(?:im\s+ausland|unterwegs)|beruflich\s+unterwegs")
OFFPLATFORM_RE = re.compile(r"whatsapp|paypal\s+freunde|freunde\s+(?:und|&)\s+familie|vorkasse|western\s+union|"
                            r"überweisung\s+(?:im\s+)?voraus")
MINING_RE = re.compile(r"\bmining|\bgemined|24/7")
SMOKER_RE = re.compile(r"raucher(?!frei)|nikotin")
RECEIPT_RE = re.compile(r"rechnung\s+(?:ist\s+)?(?:vorhanden|liegt|dabei|anbei)|mit\s+rechnung|\bovp\b")
SMOKE_FREE_RE = re.compile(r"nichtraucher|rauchfrei")


def _val(value, source):
    return {"v": value, "src": source}


def extract(title, desc):
    """Build with a source per part: 'stated' (text) or 'assumed' (Priming §6.2)."""
    text = f"{title}\n{desc}"
    gpu, cpu = parse.parse_gpu(title, desc), parse.parse_cpu(title, desc)
    chipset, ddr = parse.parse_chipset(text), parse.parse_ddr(text)
    platform = (cpu or {}).get("platform") or parse.chipset_platform(chipset)
    platform_src = "stated" if platform else "assumed"
    if not platform and cpu and ddr:          # "Ryzen 7" + DDR5 -> AM5
        platform = "AM5" if ddr == 5 else "AM4"
    elif not platform and cpu and "Ryzen" in cpu["label"]:
        platform = "AM4"                      # worst case for an unnamed Ryzen generation

    ram = parse.parse_ram(title, desc)
    layout = parse.parse_ram_layout(text)
    if layout and ram and layout[0] * layout[1] != ram:
        layout = None
    two_slots = chipset == "A620" or bool(parse.ITX_RE.search(text.upper()))
    if layout:
        ram_layout = _val(layout, "stated")
    elif ram:
        worst = (2, ram // 2) if ram in (48, 96) or ram <= 16 or two_slots else (4, ram // 4)
        ram_layout = _val(worst, "assumed")
    else:
        ram_layout = _val((2, 8), "assumed")

    psu = parse.parse_psu(text) or {"watts": None, "trusted": False}
    storage = parse.parse_storage(text)
    return {
        "gpu": gpu, "cpu": cpu, "chipset": chipset,
        "platform": _val(platform, platform_src),
        "ram_gb": _val(ram or 16, "stated" if ram else "assumed"),
        "ram_layout": ram_layout,
        "ddr": ddr or (5 if platform == "AM5" else 4 if platform == "AM4" else None),
        "two_slots": two_slots,
        "itx": bool(parse.ITX_RE.search(text.upper())),
        "psu": _val(psu, "stated" if psu["watts"] or psu["trusted"] else "assumed"),
        "cooler": _val(parse.parse_cooler(text) or "stock", "stated" if parse.parse_cooler(text) else "assumed"),
        "storage": _val(storage, "stated" if storage["gb"] and storage["nvme"] else "assumed"),
    }


def hard_reject(b, ignore_vram=False):
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


def fixes(b):
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
    return out


def ram_path(b):
    """€ to reach 32 GB and 64 GB (outside the budget, Brief §5)."""
    gb, (sticks, per) = b["ram_gb"]["v"], b["ram_layout"]["v"]
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


def ai_tier(b):
    """Brief §3: model version that runs on day one."""
    gb, vram = b["ram_gb"]["v"], (b["gpu"] or {}).get("vram", 0)
    if gb >= 96:
        return "UD-IQ4 (headroom)"
    if gb >= 64:
        return "IQ3_S (ideal)"
    if gb >= 48 or (gb >= 32 and vram >= 24):
        return "IQ2_XS (good)"
    if gb >= 32:
        return "Coder IQ1_M (good coding)"
    return "none (needs RAM)"


def tier(b):
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


def sort_key(l):
    """Tier, then Brief §6 tie-breakers, then effective price."""
    b = l["build"]
    psu = b["psu"]["v"]
    return (l["tier"], -b["ram_gb"]["v"], b["gpu"]["vendor"] != "nvidia", -b["gpu"]["vram"],
            b["chipset"] == "A620", -(psu["trusted"] * 1000 + (psu["watts"] or 0)),
            b["ram_layout"]["v"][0] != 2, b["chipset"] not in PCIE5_CHIPSETS,
            -((b["cpu"] or {}).get("tier") or 0), l["effective"])


def risk(desc, ad):
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


def unknowns(b):
    """Which parts are assumed, in the order seller questions should ask them."""
    out = []
    gpu = b["gpu"] or {}
    if gpu and not gpu["vram_stated"]:
        out.append("gpu_vram")
    if b["platform"]["src"] == "assumed" or not (b["cpu"] or {}).get("model"):
        out.append("cpu")
    if b["ram_gb"]["src"] == "assumed" or b["ram_layout"]["src"] == "assumed":
        out.append("ram")
    if not b["chipset"]:
        out.append("board")
    if b["psu"]["src"] == "assumed" or not b["psu"]["v"]["trusted"]:
        out.append("psu")
    if b["storage"]["src"] == "assumed":
        out.append("storage")
    if "cooler" in fixes(b) and b["cooler"]["src"] == "assumed":
        out.append("cooler")
    return out


QUESTIONS = {
    "gpu_vram": "Welche Grafikkarte genau (Modell, wie viel VRAM)?",
    "cpu": "Welcher Prozessor genau (Modell)?",
    "ram": "Wie ist der Arbeitsspeicher bestückt (z. B. 2×16 oder 4×8 GB, DDR4/DDR5)?",
    "board": "Welches Mainboard genau (Modell)?",
    "psu": "Welches Netzteil ist verbaut (Marke, Modell, Watt, ungefähres Alter)?",
    "storage": "Welche SSD ist verbaut (NVMe/M.2 oder SATA, Größe)?",
    "cooler": "Welcher CPU-Kühler ist verbaut?",
}


def seller_message(unknown, ships, mining_flag):
    qs = [QUESTIONS[u] for u in unknown]
    if not mining_flag:
        qs.append("Wurde die Grafikkarte zum Mining oder im 24/7-Betrieb genutzt?")
    qs.append("Ist eine Rechnung vorhanden?")
    qs.append("Wäre Versand mit „Sicher bezahlen“ möglich?" if ships else "Kann ich den PC bei Abholung kurz testen?")
    lines = "\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1))
    return f"Hallo,\n\nich interessiere mich für Ihren PC und hätte noch ein paar kurze Fragen:\n{lines}\n\nVielen Dank und viele Grüße"


TOO_CHEAP = 0.65             # ask below 65 % of the same-GPU median ask = scam signal (Priming §7.1)


def assess(ad, gpu_median=None):
    """One listing (search hit or detail) -> assessed record. `reject` is set when
    it fails; `special` when it is a §6.3 arbitrage case. `gpu_median`: median ask
    of PCs with the same GPU in this scan."""
    title, desc = ad.get("title", ""), ad.get("description", "")
    attrs = ad.get("attributes") or {}
    ask = round(ad.get("price_amount") or 0)
    vb = ad.get("price_type") == "PLEASE_CONTACT"
    b = extract(title, desc)
    scam, cond = risk(desc, ad)
    if gpu_median and ask and ask < TOO_CHEAP * gpu_median:
        scam.append("too_cheap_vs_market")
    rec = {
        "ad_id": ad.get("id"), "url": ad.get("url"), "title": title, "ask": ask, "vb": vb,
        "location": ad.get("location"), "zip": ad.get("zip_code"), "posted": ad.get("start_date"),
        "seller_id": ad.get("seller_id"), "local": bool(ad.get("local")),
        "ships": attrs.get("Versand") == "Versand möglich" or bool(ad.get("shipping_options")),
        "commercial": ad.get("seller_account_type") == "COMMERCIAL",
        "build": b, "scam": scam, "cond": cond, "description": desc,
        "reject": None, "special": False, "tier": None, "flags": [],
    }
    price = round(ask * (1 - VB_DISCOUNT)) if vb else ask
    fx = fixes(b)
    rec.update(price=price, fixes=fx, effective=price + sum(fx.values()), path=ram_path(b),
               ai=ai_tier(b), unknown=unknowns(b))
    rec["reject"] = (parse.fatal_reason(title, desc, attrs) or ("no_price" if not ask else None)
                     or hard_reject(b) or ("scam_signals" if len(scam) >= 2 else None))
    if rec["reject"] == "vram_under_12gb" and not hard_reject(b, ignore_vram=True) \
            and b["ram_gb"]["v"] >= 48 and rec["effective"] + FIX_GPU_SPECIAL <= SPECIAL_MAX:
        rec["special"] = True
    if rec["reject"]:
        return rec
    t = tier(b)
    limit = BUDGET + (STRETCH if t is not None and t <= 1 else 0)
    if t is None:
        rec["reject"] = "platform_unknown"
    elif t == 4 and rec["effective"] > AM4_MAX:
        rec["reject"] = "am4_over_550"
    elif rec["effective"] > limit:
        rec["reject"] = "over_budget"
    rec["tier"] = t
    rec["flags"] = _flags(rec, t)
    return rec


def _flags(rec, t):
    b, f = rec["build"], []
    if rec["effective"] > BUDGET:
        f.append("stretch_over_700")
    if t is not None and t <= 2 and rec["effective"] <= TARGET:
        f.append("act_fast")
    if b["chipset"] == "A620":
        f.append(f"a620_board_swap_later_{BOARD_SWAP_A620}")
    cpu = b["cpu"] or {}
    if cpu.get("model") in APU_X8 and cpu.get("suffix") in ("G", "F") and b["gpu"]["name"] not in X8_GPUS:
        f.append("apu_x8_link")
    if b["gpu"]["vendor"] == "amd":
        f.append("amd_gpu_secondary")
    if b["gpu"]["name"] == "RTX 5060 Ti" and b["chipset"] not in PCIE5_CHIPSETS:
        f.append("5060ti_without_pcie5_slot")
    if b["chipset"] in ("B450", "A520", "B350", "A320"):
        f.append("pcie3_board")
    return f + rec["scam"] + rec["cond"] + (["commercial"] if rec["commercial"] else [])
