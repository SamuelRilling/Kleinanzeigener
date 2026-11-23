"""Text -> PC build. Every parser works on the listing's title + description and
returns plain values; `None` means "not stated". Pure functions, no I/O."""
import re

GPU_LEADS = {"RTX": "(?:RTX|GTX|GEFORCE)", "GTX": "(?:RTX|GTX|GEFORCE)", "RX": "(?:RX|RADEON)", "ARC": "ARC"}
VENDOR = {"RTX": "nvidia", "GTX": "nvidia", "RX": "amd", "ARC": "intel"}


def _gpu(name, vram, prefix=False):
    """(name, regex, VRAM options in GB, vendor). A bare model number ("3090",
    "580") needs its brand word, since PC models (OptiPlex 3090), chipsets and
    resolutions reuse those numbers; a suffix (Ti, Super, XT) makes the brand
    optional unless `prefix` (RX 5600 XT vs the Ryzen 5 5600XT CPU)."""
    brand, *model = name.upper().split()
    body = r"[\s-]*".join("(?:SUPER|S)" if t == "SUPER" else t for t in model)
    lead = GPU_LEADS[brand] + r"[\s-]*"
    if not (prefix or (len(model) == 1 and brand != "ARC")):
        lead = f"(?:{lead})?"
    return name, re.compile(rf"(?<![\w.]){lead}{body}(?!\w)"), vram, VENDOR[brand]


GPUS = [
    _gpu("RTX 5090", (32,)), _gpu("RTX 5080", (16,)), _gpu("RTX 5070 Ti", (16,)), _gpu("RTX 5070", (12,)),
    _gpu("RTX 5060 Ti", (8, 16)), _gpu("RTX 5060", (8,)),
    _gpu("RTX 4090", (24,)), _gpu("RTX 4080 Super", (16,)), _gpu("RTX 4080", (16,)),
    _gpu("RTX 4070 Ti Super", (16,)), _gpu("RTX 4070 Ti", (12,)), _gpu("RTX 4070 Super", (12,)),
    _gpu("RTX 4070", (12,)), _gpu("RTX 4060 Ti", (8, 16)), _gpu("RTX 4060", (8,)),
    _gpu("RTX 3090 Ti", (24,)), _gpu("RTX 3090", (24,)), _gpu("RTX 3080 Ti", (12,)), _gpu("RTX 3080", (10, 12)),
    _gpu("RTX 3070 Ti", (8,)), _gpu("RTX 3070", (8,)), _gpu("RTX 3060 Ti", (8,)), _gpu("RTX 3060", (8, 12)),
    _gpu("RTX 3050", (8,)), _gpu("RTX 2080 Ti", (11,)), _gpu("RTX 2080 Super", (8,)), _gpu("RTX 2080", (8,)),
    _gpu("RTX 2070 Super", (8,)), _gpu("RTX 2070", (8,)), _gpu("RTX 2060 Super", (8,)), _gpu("RTX 2060", (6, 12)),
    _gpu("GTX 1660 Ti", (6,)), _gpu("GTX 1660 Super", (6,)), _gpu("GTX 1660", (6,)), _gpu("GTX 1650", (4,)),
    _gpu("GTX 1080 Ti", (11,)), _gpu("GTX 1080", (8,)), _gpu("GTX 1070 Ti", (8,)), _gpu("GTX 1070", (8,)),
    _gpu("GTX 1060", (3, 6)), _gpu("GTX 1050 Ti", (4,)),
    _gpu("RX 9070 XT", (16,)), _gpu("RX 9070", (16,)), _gpu("RX 9060 XT", (8, 16)),
    _gpu("RX 7900 XTX", (24,)), _gpu("RX 7900 XT", (20,)), _gpu("RX 7900 GRE", (16,)),
    _gpu("RX 7800 XT", (16,)), _gpu("RX 7700 XT", (12,)), _gpu("RX 7600 XT", (16,)), _gpu("RX 7600", (8,)),
    _gpu("RX 6950 XT", (16,)), _gpu("RX 6900 XT", (16,)), _gpu("RX 6800 XT", (16,)), _gpu("RX 6800", (16,)),
    _gpu("RX 6750 XT", (12,)), _gpu("RX 6700 XT", (12,)), _gpu("RX 6700", (10,)), _gpu("RX 6650 XT", (8,)),
    _gpu("RX 6600 XT", (8,)), _gpu("RX 6600", (8,)), _gpu("RX 6500 XT", (4,)),
    _gpu("RX 5700 XT", (8,), True), _gpu("RX 5700", (8,), True), _gpu("RX 5600 XT", (6,), True),
    _gpu("RX 580", (4, 8), True), _gpu("RX 570", (4, 8), True),
    _gpu("ARC B580", (12,)), _gpu("ARC A770", (8, 16)), _gpu("ARC A750", (8,)),
]
OPTIMISTIC_VRAM = {"RTX 3060": 12}   # Priming 6.2: assume 12 GB but flag; every other twin: assume the smaller
VRAM_AFTER_RE = re.compile(r"^[\s,/()\-:]*(?:MIT\s+)?(\d{1,2})\s*G(?:B)?(?![A-Z])")

INTEL_RE = re.compile(r"(?<!\w)(?:CORE\s*)?I[3579][\s-]?\d{4,5}|(?<!\w)ULTRA\s*[3579][\s-]*2\d\d|\bXEON\b|\bPENTIUM\b|\bCELERON\b")
INTEL_TIER_RE = re.compile(r"(?<!\w)(?:CORE\s*)?I[3579](?!\d)")
RYZEN_RE = re.compile(r"(?<!\w)(?:RYZEN\s*([3579])?|R([3579]))[\s-]*([1-9]\d{3})\s*(X3D|XT|X|GT|G|F)?(?!\w)")
RYZEN_BARE_RE = re.compile(r"(?<![\w-])([1-9]\d{3})(X3D|X|G|F)(?!\w)")
RYZEN_TIER_RE = re.compile(r"(?<!\w)RYZEN\s*([3579])(?![\d])")

AM5_CHIPSETS = "A620|B650E?|X670E?|B850|X870E?"
AM4_CHIPSETS = "A320|B350|X370|B450|X470|A520|B550|X570"
INTEL_CHIPSETS = ("H310|B360|B365|H370|Z370|Z390|H410|B460|H470|Z490|H510|B560|H570|Z590|"
                  "H610|B660|H670|Z690|B760|H770|Z790|B860|Z890|H810")
CHIPSET_RE = re.compile(rf"(?<![A-Z0-9])({AM5_CHIPSETS}|{AM4_CHIPSETS}|{INTEL_CHIPSETS})(?![0-9])")
ITX_RE = re.compile(r"(?<![A-Z])(?:MINI[\s-]?ITX|M-ITX|ITX|SFF|SMALL\s+FORM)(?![A-Z])")

RAM_RES = [re.compile(r"(?<!\d)(\d{1,3})\s*GB\s*(?:DDR\d\S*\s*)?(?:RAM|ARBEITSSPEICHER|DDR\d)"),
           re.compile(r"(?<!\w)(?:RAM|ARBEITSSPEICHER)\s*:?\s*(\d{1,3})\s*GB"),
           # bare "32GB" (titles like "Ryzen 5 RTX 3060 32GB"), unless it names storage or VRAM
           re.compile(r"(?<![\d.,])(16|32|48|64|96|128)\s*GB(?!\s*(?:SSD|NVME|M\.2|M2|HDD|FESTPLATTE|SPEICHER|VRAM|V-RAM|GDDR))")]
RAM_KIT_RE = re.compile(r"(?<!\d)([1-4])\s*[X×]\s*(\d{1,2})\s*GB")
RAM_VALID = {8, 12, 16, 24, 32, 48, 64, 96, 128}
VRAM_CONTEXT_RE = re.compile(r"(?:(?:RTX|GTX|RX|RADEON|ARC)[\s-]*[AB]?\d{3,4}(?:\s*(?:TI|SUPER|XTX|XT|GRE))*"
                             r"|\d{4}\s*(?:TI|SUPER|XTX|XT|GRE))\s*[(:-]?\s*(?:MIT\s*)?$")
DDR_RE = re.compile(r"DDR([345])")

PSU_KEY_RE = re.compile(r"NETZTEIL|PSU|POWER\s*SUPPLY|BE\s*QUIET|CORSAIR|SEASONIC|\bMWE\b|HYDRO\s*G|\bRM\d{3}|A\d{3,4}GL")
WATT_RE = re.compile(r"(?<!\d)(\d{3,4})\s*(?:W|WATT)(?![A-Z])")
PSU_TRUSTED_RE = re.compile(r"STRAIGHT\s*POWER|PURE\s*POWER|DARK\s*POWER|BE\s*QUIET(?!.{0,15}SYSTEM\s*POWER)|"
                            r"CORSAIR\s*(?:RM|HX|AX|SF)|\bRM\d{3,4}[EX]?\b|\bHX\d{3,4}|SEASONIC|"
                            r"MAG\s*A\d{3,4}GL|\bA\d{3,4}GL\b|MWE\s*(?:\d{3,4}\s*)?GOLD|HYDRO\s*G")
PSU_MODEL_WATT_RE = re.compile(r"(?<![A-Z0-9])(?:RM[XE]?|HX|CX|CV|AX|SF|MWE\s*(?:GOLD\s*)?)(\d{3,4})[XEMI]?(?![A-Z0-9])"
                               r"|(?<![A-Z0-9])A(\d{3,4})GL")  # watts in the model name: RM850x, CX650, A750GL
PSU_WINDOW = 60

TOWER_RE = re.compile(r"PEERLESS|ASSASSIN|PHANTOM\s*SPIRIT|\bAK\d{3}\b|DARK\s*ROCK|PURE\s*ROCK|SHADOW\s*ROCK|NOCTUA|"
                      r"NH-[DU]\d|FREEZER|HYPER\s*212|\bAIO\b|WASSERK(?:Ü|UE)HL|LIQUID|KRAKEN|RADIATOR|"
                      r"TURMK(?:Ü|UE)HLER|TOWER[\s-]*K(?:Ü|UE)HLER|LUFTK(?:Ü|UE)HLER")
STOCK_COOLER_RE = re.compile(r"BOXED|WRAITH|STOCK[\s-]*K(?:Ü|UE)HLER|ORIGINAL[\s-]*K(?:Ü|UE)HLER")

NVME_RE = re.compile(r"NVME|M\.2|(?<!\w)M2(?!\w)")
SSD_CAP_RE = re.compile(r"(\d+(?:[.,]\d)?) *(TB|GB) *(?:(?!\d+ *[GT]B|DDR)[A-Z0-9.+\-]+ *){0,3}?(?:NVME|M\.2|M2|SSD)|"
                        r"(?:NVME|M\.2|M2|SSD)\D{0,25}?(\d+(?:[.,]\d)?)\s*(TB|GB)")

OEM_RE = re.compile(r"\b(?:optiplex|vostro|precision\s*\d|alienware|elitedesk|prodesk|pavilion|victus|envy|hp\s*z\d|omen|"
                    r"thinkcentre|thinkstation|ideacentre|legion\s*(?:t|tower)|lenovo\s*loq|aspire|nitro\s*n|"
                    r"predator\s*orion|medion|erazer|esprimo|celsius)\b")
FATAL_ANY = [
    ("no_gpu", r"\bohne\s+(?:dedizierte\s+)?(?:gpu|grafikkarte|graka|grafik|gk)\b"),
    ("no_gpu", r"\b(?:gpu|grafikkarte|graka)\s+(?:ist\s+|wurde\s+|wird\s+)?(?:nicht\s+(?:enthalten|dabei|inklusive|verbaut|vorhanden|mit)|fehlt|bereits\s+verkauft|ausgebaut|separat)"),
    ("no_gpu", r"\bnur\s+(?:das\s+)?(?:gehäuse|mainboard|netzteil)\b"),
    ("bastler", r"\bbastler"),
    ("parted_out", r"nicht\s+mehr\s+(?:als\s+ganzes\s+)?verkauft|nur\s+noch\s+(?:die\s+)?(?:einzelnen\s+)?(?:komponenten|teile)"),
]
FATAL_TITLE = [
    ("not_desktop", r"\b(?:laptop|notebook|macbook|imac|mac\s*mini|mac\s*studio)\b"),
    ("mini_pc_or_handheld", r"\b(?:mini[\s-]?pc|nuc|minisforum|minis\s*forum|gmktec|geekom|beelink|szbox|"
                            r"handheld|steam\s*deck|rog\s*ally|legion\s*go|claw)\b|\b\d{4}h[sx]?\b"),
    ("gpu_only", r"^(?!.*\b(?:pc|rechner|computer|system|tower|komplett\w*)\b).*\b(?:grafikkarte|gpu)\b"),
    ("wanted_ad", r"\b(?:suche|gesucht)\b"),
    ("trade_only", r"\b(?:tausch|tausche)\b(?!.*\bverkauf)"),
    ("reserved", r"\breserviert\b"),
    ("oem_prebuilt", OEM_RE.pattern),
]
DEFEKT_RE = re.compile(r"defekt\w*")
DEFEKT_NEGATION = re.compile(r"(?:nicht|kein\w*|ohne|nie)\s+(?:\w+\s+)?$")  # same clause only


def _earliest(patterns, text):
    """The pattern match that starts earliest in `text`; ties go to the longest."""
    best = None
    for item in patterns:
        m = item[1].search(text)
        if m and (best is None or (m.start(), -len(m.group())) < (best[1].start(), -len(best[1].group()))):
            best = (item, m)
    return best


def parse_gpu(title, desc):
    """{name, vendor, vram, vram_stated, in_desc} or None. Title wins over description."""
    for text, in_desc in ((title.upper(), False), (desc.upper(), True)):
        hit = _earliest(GPUS, text)
        if not hit:
            continue
        (name, _, options, vendor), m = hit
        said = VRAM_AFTER_RE.match(text[m.end():m.end() + 25])
        stated = int(said.group(1)) if said and int(said.group(1)) in options else None
        vram = stated or (options[0] if len(options) == 1 else OPTIMISTIC_VRAM.get(name, min(options)))
        return {"name": name, "vendor": vendor, "vram": vram,
                "vram_stated": stated is not None or len(options) == 1, "in_desc": in_desc}
    return None


def _ryzen(text):
    """(model, suffix, tier) of the first Ryzen model number in `text`, or None."""
    hits = []
    if m := RYZEN_RE.search(text):
        hits.append((m.start(), m.group(3), m.group(4) or "", m.group(1) or m.group(2)))
    if m := RYZEN_BARE_RE.search(text):
        hits.append((m.start(), m.group(1), m.group(2), None))
    if not hits:
        return None
    _, model, suffix, tier = min(hits)
    return model, suffix, int(tier) if tier else None


def parse_cpu(title, desc):
    """{label, platform (AM5/AM4/INTEL/None), model, suffix, tier} or None."""
    for text in (title.upper(), desc.upper()):
        r, intel = _ryzen(text), INTEL_RE.search(text)
        if r and not (intel and intel.start() < text.find(r[0])):
            model, suffix, tier = r
            series = int(model[0])
            tier = tier or (3 if model[1] <= "3" else 5 if model[1] <= "6" else 7 if model[1] <= "8" else 9)
            platform = "AM5" if series in (7, 8, 9) else "AM4"
            return {"label": f"Ryzen {tier} {model}{suffix}", "platform": platform,
                    "model": model, "suffix": suffix, "tier": tier}
        if intel or INTEL_TIER_RE.search(text):
            return {"label": "Intel", "platform": "INTEL", "model": None, "suffix": "", "tier": None}
        if m := RYZEN_TIER_RE.search(text):
            return {"label": f"Ryzen {m.group(1)} (gen?)", "platform": None, "model": None,
                    "suffix": "", "tier": int(m.group(1))}
    return None


def parse_chipset(text):
    m = CHIPSET_RE.search(text.upper())
    return m.group(1) if m else None


def chipset_platform(chipset):
    if not chipset:
        return None
    for platform, names in (("AM5", AM5_CHIPSETS), ("AM4", AM4_CHIPSETS), ("INTEL", INTEL_CHIPSETS)):
        if re.fullmatch(names, chipset):
            return platform


def parse_ram(title, desc):
    """Total GB, title first."""
    for text in (title.upper(), desc.upper()):
        for rx in RAM_RES[:2]:
            if gb := _ram_hit(rx, text):
                return gb
        for m in RAM_KIT_RE.finditer(text):
            if int(m.group(1)) * int(m.group(2)) in RAM_VALID:
                return int(m.group(1)) * int(m.group(2))
        if gb := _ram_hit(RAM_RES[2], text):
            return gb
    return None


def _ram_hit(rx, text):
    """First RAM size in `text` that isn't a VRAM figure ("RTX 3060 (12 GB RAM)")."""
    for m in rx.finditer(text):
        gb = int(m.group(1))
        is_vram = gb <= 24 and VRAM_CONTEXT_RE.search(text[max(0, m.start() - 30):m.start()])
        if gb in RAM_VALID and not is_vram:
            return gb
    return None


def parse_ram_layout(text):
    """(sticks, GB per stick) if written as "2x16GB", else None."""
    m = RAM_KIT_RE.search(text.upper())
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_ddr(text):
    m = DDR_RE.search(text.upper())
    return int(m.group(1)) if m else None


def parse_psu(text):
    """{watts, trusted} from text near a PSU keyword; None if nothing said."""
    up = text.upper()
    watts, trusted, found = None, False, False
    for k in PSU_KEY_RE.finditer(up):
        found = True
        window = up[max(0, k.start() - PSU_WINDOW):k.end() + PSU_WINDOW]
        trusted = trusted or bool(PSU_TRUSTED_RE.search(window))
        for w in [*WATT_RE.finditer(window), *PSU_MODEL_WATT_RE.finditer(window)]:
            if 300 <= int(w.group(1) or w.group(2)) <= 1600:
                watts = max(watts or 0, int(w.group(1) or w.group(2)))
    return {"watts": watts, "trusted": trusted} if found else None


def parse_cooler(text):
    """'tower' (tower air or AIO), 'stock', or None."""
    up = text.upper()
    return "tower" if TOWER_RE.search(up) else "stock" if STOCK_COOLER_RE.search(up) else None


def parse_storage(text):
    """{nvme, gb}; gb is the largest SSD capacity stated."""
    up = text.upper()
    gbs = []
    for m in SSD_CAP_RE.finditer(up):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        gbs.append(float(num.replace(",", ".")) * (1000 if unit == "TB" else 1))
    return {"nvme": bool(NVME_RE.search(up)), "gb": int(max(gbs)) if gbs else None}


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
