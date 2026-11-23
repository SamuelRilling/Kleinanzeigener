"""Text -> PC build. Every parser works on the listing's title + description and
returns plain values; `None` means "not stated". Pure functions, no I/O."""
import re

from text import by_priority, clauses, installed, labelled, negated

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

RAM_RES = [re.compile(r"(?<![\dX×])(?<![X×]\s)(\d{1,3})\s*GB\s*(?:DDR\d\S*\s*)?(?:RAM|ARBEITSSPEICHER|DDR\d)"),
           re.compile(r"(?<!\w)(?:RAM|ARBEITSSPEICHER)\s*:?\s*(\d{1,3})\s*GB"),
           # bare "32GB" (titles like "Ryzen 5 RTX 3060 32GB"), unless it names storage or VRAM
           re.compile(r"(?<![\d.,X×])(?<![X×]\s)(16|32|48|64|96|128)\s*GB(?!\s*(?:SSD|NVME|M\.2|M2|HDD|FESTPLATTE|SPEICHER\b|VRAM|V-RAM|GDDR))")]
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
WATT_NOT_PSU_RE = re.compile(r"(?:RTX|GTX|RX|RADEON|RYZEN|INTEL|CPU|GPU|TDP|GRAFIKKARTE|PROZESSOR)[^,]{0,15}$")

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
DEFEKT_RE = re.compile(r"DEFEKT\w*")




def _matches(clause: str, patterns: list) -> list[tuple]:
    """Non-overlapping (start, end, item) hits of `patterns` in one clause that name an
    installed part; at the same start the longest wins ("RTX 4070 Ti" over "RTX 4070")."""
    found = sorted(((m.start(), -m.end(), item) for item in patterns for m in item[1].finditer(clause)),
                   key=lambda h: (h[0], h[1]))
    out, last_end = [], -1
    for start, neg_end, item in found:
        end = -neg_end
        if start >= last_end and installed(clause, start, end) and not negated(clause, start):
            out.append((start, end, item))
            last_end = end
    return out


def parse_gpu(title: str, desc: str) -> dict | None:
    """{name, vendor, vram, vram_stated, in_desc, conflict} or None. A labelled
    "Grafikkarte:" line beats the title, the title beats the rest."""
    cls = clauses(title, desc)
    hits = [(c, h) for c in by_priority(cls, "gpu") for h in _matches(c, GPUS)]
    if not hits:
        return None
    clause, (_, _, (name, _, options, vendor)) = hits[0]
    stated = None
    for c, (_, e, item) in hits:
        said = VRAM_AFTER_RE.match(c[e:e + 25])
        if item[0] == name and said and int(said.group(1)) in options:
            stated = int(said.group(1))
            break
    vram = stated or (options[0] if len(options) == 1 else OPTIMISTIC_VRAM.get(name, min(options)))
    return {"name": name, "vendor": vendor, "vram": vram, "vram_stated": stated is not None or len(options) == 1,
            "in_desc": clause != cls[0], "conflict": len({h[2][0] for _, h in hits}) > 1}


def _cpu_hits(clause: str) -> list[dict]:
    hits = []
    for rx, bare in ((RYZEN_RE, False), (RYZEN_BARE_RE, True)):
        for m in rx.finditer(clause):
            if not installed(clause, m.start(), m.end()):
                continue
            model, suffix = (m.group(1), m.group(2)) if bare else (m.group(3), m.group(4) or "")
            tier = None if bare else int(m.group(1) or m.group(2) or 0) or None
            tier = tier or (3 if model[1] <= "3" else 5 if model[1] <= "6" else 7 if model[1] <= "8" else 9)
            hits.append((m.start(), {"label": f"Ryzen {tier} {model}{suffix}", "model": model, "suffix": suffix,
                                     "tier": tier, "platform": "AM5" if model[0] in "789" else "AM4"}))
    for m in INTEL_RE.finditer(clause):
        if installed(clause, m.start(), m.end()):
            hits.append((m.start(), {"label": "Intel", "model": None, "suffix": "", "tier": None, "platform": "INTEL"}))
    return [h for _, h in sorted(hits, key=lambda h: h[0])]


def parse_cpu(title: str, desc: str) -> dict | None:
    """{label, platform (AM5/AM4/INTEL/None), model, suffix, tier, conflict} or None."""
    cls = clauses(title, desc)
    hits = [h for c in by_priority(cls, "cpu") for h in _cpu_hits(c)]
    if hits:
        return {**hits[0], "conflict": len({h["label"] for h in hits}) > 1}
    text = "\n".join(cls)
    if INTEL_TIER_RE.search(text):
        return {"label": "Intel", "platform": "INTEL", "model": None, "suffix": "", "tier": None, "conflict": False}
    if m := RYZEN_TIER_RE.search(text):
        return {"label": f"Ryzen {m.group(1)} (gen?)", "platform": None, "model": None, "suffix": "",
                "tier": int(m.group(1)), "conflict": False}
    return None


def parse_chipset(text: str) -> str | None:
    m = CHIPSET_RE.search(text.upper())
    return m.group(1) if m else None


def chipset_platform(chipset: str | None) -> str | None:
    if not chipset:
        return None
    for platform, names in (("AM5", AM5_CHIPSETS), ("AM4", AM4_CHIPSETS), ("INTEL", INTEL_CHIPSETS)):
        if re.fullmatch(names, chipset):
            return platform
    return None


def _ram_in(clause: str, rx: re.Pattern, kit: bool = False) -> list[int]:
    out = []
    for m in rx.finditer(clause):
        gb = int(m.group(1)) * int(m.group(2)) if kit else int(m.group(1))
        is_vram = not kit and gb <= 24 and VRAM_CONTEXT_RE.search(clause[max(0, m.start() - 30):m.start()])
        if gb in RAM_VALID and not is_vram and installed(clause, m.start(), m.end()):
            out.append(gb)
    return out


def ram_candidates(title: str, desc: str) -> list[int]:
    """Installed-RAM sizes in priority order. Limits ("erweiterbar auf 64GB") and
    VRAM figures are dropped; a bare "32GB" is only read outside GPU/SSD lines."""
    cls = clauses(title, desc)
    not_ram = set(labelled(cls, "gpu")) | set(labelled(cls, "storage"))
    out = []
    for c in by_priority(cls, "ram"):
        out += _ram_in(c, RAM_RES[0]) + _ram_in(c, RAM_RES[1]) + _ram_in(c, RAM_KIT_RE, kit=True)
        if c not in not_ram:
            out += _ram_in(c, RAM_RES[2])
    return out


def parse_ram(title: str, desc: str) -> int | None:
    """Total installed GB, or None."""
    found = ram_candidates(title, desc)
    return found[0] if found else None


def parse_ram_layout(title: str, desc: str) -> tuple[int, int] | None:
    """(sticks, GB per stick) if written as "2x16GB", else None."""
    for c in by_priority(clauses(title, desc), "ram"):
        for m in RAM_KIT_RE.finditer(c):
            if installed(c, m.start(), m.end()):
                return int(m.group(1)), int(m.group(2))
    return None


def parse_ddr(text: str) -> int | None:
    m = DDR_RE.search(text.upper())
    return int(m.group(1)) if m else None


def parse_psu(title: str, desc: str) -> dict | None:
    """{watts, trusted, missing}; None if no PSU is mentioned. Watts come only from
    PSU clauses and never right after a GPU/CPU name (a "170W" TDP)."""
    cls = clauses(title, desc)
    psu_cls = by_priority([c for c in cls if PSU_KEY_RE.search(c) or labelled([c], "psu")], "psu")
    if not psu_cls:
        return None
    watts, trusted, missing = None, False, False
    for c in psu_cls:
        key = PSU_KEY_RE.search(c)
        missing = missing or bool(key and negated(c, key.start()))
        trusted = trusted or bool(PSU_TRUSTED_RE.search(c))
        for w in [*WATT_RE.finditer(c), *PSU_MODEL_WATT_RE.finditer(c)]:
            value = int(w.group(1) or w.group(2))
            tdp = WATT_NOT_PSU_RE.search(c[max(0, w.start() - 25):w.start()])
            if watts is None and 300 <= value <= 1600 and not tdp:
                watts = value
    return {"watts": watts, "trusted": trusted and not missing, "missing": missing}


def parse_cooler(title: str, desc: str) -> str | None:
    """'tower' (tower air or AIO), 'stock', or None."""
    text = "\n".join(by_priority(clauses(title, desc), "cooler"))
    return "tower" if TOWER_RE.search(text) else "stock" if STOCK_COOLER_RE.search(text) else None


STORAGE_WORD_RE = re.compile(r"SSD|NVME|M\.2|(?<!\w)M2(?!\w)|FESTPLATTE")


def parse_storage(title: str, desc: str) -> dict:
    """{nvme, gb, missing}; gb is the largest SSD capacity stated in a storage clause."""
    cls = [c for c in by_priority(clauses(title, desc), "storage") if STORAGE_WORD_RE.search(c)]
    gbs, nvme, missing = [], False, False
    for c in cls:
        if negated(c, STORAGE_WORD_RE.search(c).start()):
            missing = True
            continue
        nvme = nvme or bool(NVME_RE.search(c))
        for m in SSD_CAP_RE.finditer(c):
            num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            gbs.append(float(num.replace(",", ".")) * (1000 if unit == "TB" else 1))
    return {"nvme": nvme, "gb": int(max(gbs)) if gbs else None, "missing": missing and not gbs}


def parse_case(title: str, desc: str) -> dict:
    """{name, sff}: the "Gehäuse:" line (shown, never priced) and a small-form-factor flag."""
    cls = clauses(title, desc)
    line = next(iter(labelled(cls, "case")), None)
    name = line.split(":", 1)[1].strip()[:40] if line and ":" in line else None
    return {"name": name, "sff": any(ITX_RE.search(c) for c in cls)}


def fatal_reason(title: str, desc: str, attributes: dict) -> str | None:
    t, text = title.lower(), f"{title}\n{desc}".lower()
    if attributes.get("Zustand") == "Defekt":
        return "defekt"
    for reason, rx in FATAL_TITLE:
        if re.search(rx, t):
            return reason
    for reason, rx in FATAL_ANY:
        if re.search(rx, text):
            return reason
    for c in clauses(title, desc):
        if any(not negated(c, m.start()) for m in DEFEKT_RE.finditer(c)):
            return "defekt"
    return None
