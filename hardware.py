"""Brief §1 + §4 component knowledge: what each GPU is worth and how it is linked,
how the parts constrain each other (PCIe link, PSU and case for the next GPU, RAM
slots, platform), and a parts-value floor for spotting mislabeled prices."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Card:
    used_eur: int     # low used price, Nov 2026 (Brief §4.4 where given, else estimate)
    lanes: int        # PCIe lanes the card uses
    gen: int          # PCIe generation of the card
    psu_min: int      # W, rough (Brief §4.4)
    note: str         # Brief §4.4 verdict, plain words


# Cards with 12 GB+ (the only ones that can pass) and the 16 GB twins.
CARDS = {
    "RTX 3060": Card(190, 16, 4, 550, "~62 tok/s · 1080p · floor, good value"),
    "RTX 3080": Card(380, 16, 4, 750, "fast · 1440p · power-hungry for 12 GB"),
    "RTX 3080 Ti": Card(450, 16, 4, 750, "fast · 1440p · power-hungry for 12 GB"),
    "RTX 3090": Card(750, 16, 4, 850, "~140 tok/s (estimate) · 4K · AI dream; IQ2_XS even on 32 GB RAM"),
    "RTX 3090 Ti": Card(800, 16, 4, 850, "AI dream class · 4K · 24 GB"),
    "RTX 4060 Ti": Card(330, 8, 4, 550, "16 GB on a ×8 link · 1080p+ · right"),
    "RTX 4070": Card(430, 16, 4, 650, "48 tok/s IQ2_XS · 1440p · VRAM-limited"),
    "RTX 4070 Super": Card(500, 16, 4, 650, "1440p · VRAM-limited"),
    "RTX 4070 Ti": Card(580, 16, 4, 700, "1440p · VRAM-limited"),
    "RTX 4070 Ti Super": Card(650, 16, 4, 750, "16 GB · 1440p+"),
    "RTX 4080": Card(800, 16, 4, 750, "16 GB · 4K"),
    "RTX 4080 Super": Card(850, 16, 4, 750, "16 GB · 4K"),
    "RTX 4090": Card(1500, 16, 4, 850, "24 GB · 4K"),
    "RTX 5060 Ti": Card(395, 8, 5, 600, "~48 tok/s IQ3_S · 1440p · best fit, wants a PCIe 5.0 slot"),
    "RTX 5070": Card(500, 16, 5, 650, "78.6 tok/s IQ2_XS / 53.3 IQ3_S · 1440p+"),
    "RTX 5070 Ti": Card(650, 16, 5, 750, "16 GB · 1440p+"),
    "RTX 5080": Card(900, 16, 5, 850, "16 GB · 4K"),
    "RTX 5090": Card(2000, 16, 5, 1000, "32 GB · 4K"),
    "RX 6700 XT": Card(230, 16, 4, 650, "12 GB · AMD: weaker for CUDA tools"),
    "RX 6750 XT": Card(250, 16, 4, 650, "12 GB · AMD: weaker for CUDA tools"),
    "RX 6800": Card(300, 16, 4, 650, "16 GB · AMD: weaker for CUDA tools"),
    "RX 6800 XT": Card(350, 16, 4, 750, "16 GB · AMD: weaker for CUDA tools"),
    "RX 6900 XT": Card(380, 16, 4, 750, "16 GB · AMD: weaker for CUDA tools"),
    "RX 6950 XT": Card(430, 16, 4, 850, "16 GB · AMD: weaker for CUDA tools"),
    "RX 7600 XT": Card(250, 8, 4, 550, "16 GB on a ×8 link · AMD: weaker for CUDA tools"),
    "RX 7700 XT": Card(320, 16, 4, 650, "12 GB · AMD: weaker for CUDA tools"),
    "RX 7800 XT": Card(400, 16, 4, 700, "16 GB · AMD: weaker for CUDA tools"),
    "RX 7900 GRE": Card(450, 16, 4, 700, "16 GB · AMD: weaker for CUDA tools"),
    "RX 7900 XT": Card(550, 16, 4, 750, "20 GB · AMD: weaker for CUDA tools"),
    "RX 7900 XTX": Card(700, 16, 4, 850, "24 GB · AMD: weaker for CUDA tools"),
    "RX 9060 XT": Card(280, 16, 5, 550, "16 GB · AMD: weaker for CUDA tools"),
    "RX 9070": Card(480, 16, 5, 650, "58.7 tok/s measured · AMD: weaker for CUDA tools"),
    "RX 9070 XT": Card(550, 16, 5, 750, "16 GB · AMD: weaker for CUDA tools"),
}
UNKNOWN_CARD = Card(0, 16, 4, 750, "")
AIRFLOW_CASE_RE = re.compile(r"\b(?:MESH|AIRFLOW|AIR|FLOW)\b")

PCIE5_CHIPSETS = {"B650E", "X670E", "X870", "X870E", "Z690", "Z790", "Z890", "B860"}
PCIE3_CHIPSETS = {"A320", "B350", "X370", "B450", "X470", "A520",
                  "H310", "B360", "B365", "H370", "Z370", "Z390", "H410", "B460", "H470", "Z490"}

# Intel: socket by board and by CPU generation (15 = Core Ultra 200).
INTEL_SOCKET_CHIPSETS = {
    "LGA1851": {"B860", "Z890", "H810"},
    "LGA1700": {"H610", "B660", "H670", "Z690", "B760", "H770", "Z790"},
    "LGA1200": {"H410", "B460", "H470", "Z490", "H510", "B560", "H570", "Z590"},
    "LGA1151": {"H310", "B360", "B365", "H370", "Z370", "Z390"},
}
SOCKET_OF_GEN = {15: "LGA1851", 14: "LGA1700", 13: "LGA1700", 12: "LGA1700", 11: "LGA1200", 10: "LGA1200"}
WORST_GEN_OF_SOCKET = {"LGA1851": 15, "LGA1700": 12, "LGA1200": 10, "LGA1151": 8}
INTEL_ASSUMED_GEN = 12        # generation not stated, board unknown: the oldest still judged (flagged, asked)
INTEL_OLDEST_OK = 11          # 10th gen and older: PCIe 3.0, no AVX-512, slow DDR4 platform -> rejected
INTEL_AVX512_GENS = {11}      # Rocket Lake; 12th gen and later desktop CPUs have AVX-512 disabled
# A CPU this strong already sits at the top of its socket's useful range, so a dead socket
# costs nothing: the upgrades that matter are RAM, GPU and PSU.
STRONG_I5 = {13: 600, 14: 600, 15: 245}   # i5-13600K / 14600K and up, Core Ultra 5 245 and up
RAPTOR_LAKE_GENS = {13, 14}   # i7/i9 and i5-x600: Vmin instability unless the BIOS has microcode 0x12B+
APU_LANES = {"8500": 4, "8300": 4, "8600": 8, "8700": 8, "8400": 8}   # 8000G/F: GPU lanes
# Used-RAM value per GB (about 60 % of the Brief's new prices: 32 GB DDR5 490 €, DDR4 285 €).
RAM_EUR_PER_GB = {5: 9, 4: 5}


def card(gpu: dict | None) -> Card:
    return CARDS.get((gpu or {}).get("name"), UNKNOWN_CARD)


def intel_facts(cpu: dict | None, chipset: str | None, ddr: int | None) -> dict:
    """Socket, generation and what they imply for an Intel build. An unstated generation
    is the worst one the board allows, else INTEL_ASSUMED_GEN (DDR3 means older)."""
    cpu = cpu or {}
    board_socket = next((s for s, names in INTEL_SOCKET_CHIPSETS.items() if chipset in names), None)
    gen, src = cpu.get("gen"), "stated"
    if gen is None:
        gen, src = WORST_GEN_OF_SOCKET.get(board_socket) or (0 if ddr == 3 else INTEL_ASSUMED_GEN), "assumed"
    tier, model = cpu.get("tier") or 0, cpu.get("model") or ""
    i5_floor = STRONG_I5.get(gen)
    upper_i5 = tier == 5 and i5_floor is not None and model.isdigit() and int(model[-3:]) >= i5_floor
    return {"gen": gen, "gen_src": src, "socket": SOCKET_OF_GEN.get(gen, "older"),
            "old": gen < INTEL_OLDEST_OK, "avx512": gen in INTEL_AVX512_GENS,
            "strong": src == "stated" and gen >= INTEL_OLDEST_OK and (tier >= 7 or upper_i5),
            "raptor_lake": gen in RAPTOR_LAKE_GENS and (tier >= 7 or upper_i5)}


def cpu_link(cpu: dict | None, platform: str | None, intel_gen: int | None = None) -> tuple[int, int]:
    """(PCIe gen, lanes) the CPU gives the GPU slot."""
    if platform == "INTEL":   # 10th gen and older 3.0, 11th 4.0, 12th and later 5.0
        gen = intel_gen or 0
        return (3 if gen < 11 else 4 if gen == 11 else 5), 16
    cpu = cpu or {}
    model, suffix = cpu.get("model") or "", cpu.get("suffix") or ""
    if model in APU_LANES and suffix in ("G", "F"):
        return 4, APU_LANES[model]
    if platform == "AM4":   # Ryzen 1000/2000 and the G-series APUs run PCIe 3.0
        return (3, 16) if model[:1] in ("1", "2") or suffix == "G" else (4, 16)
    return (5, 16) if platform == "AM5" else (4, 16)


def board_gen(chipset: str | None, platform: str | None, intel_gen: int | None = None) -> tuple[int, bool]:
    """(PCIe gen of the GPU slot, assumed?). Unknown boards: AM5 and Intel 11th gen+ 4.0,
    else 3.0 (worst case)."""
    if chipset in PCIE5_CHIPSETS:
        return 5, False
    if chipset in PCIE3_CHIPSETS:
        return 3, False
    if chipset:
        return 4, False
    return (4 if platform == "AM5" or (intel_gen or 0) >= 11 else 3), True


def pcie_link(b: dict) -> dict:
    """Brief §1.6: the GPU link is set by the weakest of CPU, board slot and card.
    `reduced` follows the Brief's penalty cases: an x16 card behind an x8 APU, an x8
    card on a slot older than the card (PCIe 3.0 board, or a 5.0 card in a 4.0 slot)."""
    c = card(b["gpu"])
    intel_gen = (b.get("intel") or {}).get("gen")
    cpu_gen, cpu_lanes = cpu_link(b["cpu"], b["platform"]["v"], intel_gen)
    slot, assumed = board_gen(b["chipset"], b["platform"]["v"], intel_gen)
    gen, lanes = min(cpu_gen, slot, c.gen), min(cpu_lanes, c.lanes)
    reduced = lanes < c.lanes or (c.lanes == 8 and gen < c.gen)
    text = f"{gen}.0 ×{lanes}" + (" (?)" if assumed else "") + (f", card wants {c.gen}.0 ×{c.lanes}" if reduced else "")
    return {"gen": gen, "lanes": lanes, "reduced": reduced, "text": text}


def headroom(b: dict) -> dict:
    """Brief §1.4-1.5 / §9: what the next upgrades need, as bought (fixes not applied)."""
    psu, gpu = b["psu"]["v"], b["gpu"] or {}
    need = 850 if gpu.get("vram", 0) >= 24 else 750
    case_name = (b["case"]["name"] or "").upper()
    sticks = b["ram_layout"]["v"][0]
    slots = 2 if b["two_slots"] else 4
    checks = {
        "psu": psu["trusted"] and (psu["watts"] or 0) >= need,
        "case": True if AIRFLOW_CASE_RE.search(case_name) else None,
        "free_slots": max(0, slots - sticks),
        "pcie5": b["chipset"] in PCIE5_CHIPSETS,
        "zen6": b["platform"]["v"] == "AM5",
    }
    mark = {True: "✓", False: "✗", None: "?"}
    intel = b.get("intel")
    if checks["zen6"]:
        socket = "Zen 6 ✓"
    elif intel:
        socket = f"{intel['socket']} dead end" + (" (CPU already strong)" if intel["strong"] else "")
    else:
        socket = "dead-end socket"
    text = (f"PSU {mark[checks['psu']]} · case {mark[checks['case']]} · {checks['free_slots']} RAM slots free · "
            f"PCIe5 {mark[checks['pcie5']]} · {socket}")
    return {**checks, "text": text}


def parts_floor(b: dict) -> int:
    """Lowest believable value of the stated GPU + RAM alone. A whole PC asked far
    below it is a part price, a typo or a scam."""
    gpu = b["gpu"] or {}
    gpu_eur = 0 if gpu.get("to_buy") or not gpu.get("vram_stated") else card(gpu).used_eur
    ram_eur = b["ram_gb"]["v"] * RAM_EUR_PER_GB.get(b["ddr"], 0) if b["ram_gb"]["src"] == "stated" else 0
    return gpu_eur + ram_eur
