"""Every knob that decides what passes: budget, selection rules, fix costs.
Defaults follow the Deal Evaluation Brief (Target.md) except where marked; search.toml
overrides them, and `deviations()` lists what differs from the Brief for the AI pass."""
from dataclasses import dataclass, fields

PRICE_BASES = ("effective", "list")
PICKUP_CHOICES = ("keep", "local_only", "drop")


@dataclass(frozen=True)
class Policy:
    # budget (Brief §0 / §6)
    limit: int = 700            # hard limit on the budget price (see price_basis)
    target: int = 600           # "act fast" when a tier 0-2 deal lands at or below this
    stretch: int = 75           # user addition: tier 0-1 deals may exceed the limit by this much
    am4_max: int = 550          # tier 4 (AM4 + 64 GB) cap
    vb_discount: float = 0.10   # realistic haggle on "VB" listings (5-15 %)
    special_max: int = 800      # §6.3 special case: budget price + GPU fix must stay under this
    price_basis: str = "effective"  # user addition: "effective" (haggle + confirmed fixes) or "list" (ask as listed)
    # selection rules (Brief §2 hard rejects)
    am4_min_ram: int = 32       # user default; the Brief says 64. Applies to every DDR4 platform (AM4, DDR4 Intel)
    min_vram: int = 12
    allow_intel: bool = True    # user default; the Brief rejects all Intel. Judged case by case (rules.intel_penalties)
    allow_arc: bool = False     # Intel Arc: Strata supports it on Linux only
    allow_apu_x4: bool = False  # Ryzen 8500G/8300G: GPU at PCIe 4.0 x4
    allow_sff: bool = False     # Mini-ITX / SFF: 2 DIMM slots, short GPU clearance
    allow_oem: bool = False     # Dell/HP/Lenovo/... prebuilts with proprietary parts
    allow_mini_pc: bool = False # mini-PCs and handhelds (mobile CPUs, no GPU slot)
    pickup_only: str = "keep"   # "Nur Abholung" listings: keep (flag only), local_only, or drop
    # price sanity and risk (Priming §7.1)
    misprice_share: float = 0.5 # ask below this share of GPU + RAM value alone = a part price or a scam
    scam_signals_drop: int = 2  # this many scam signals drop a listing
    # fix ledger (Brief §5, € estimates Nov 2026). Counted only when the listing confirms the deficit.
    psu_min_w: int = 650        # user default; the Brief says 750. A stated PSU below this is a counted fix
    psu_min_24gb_w: int = 850   # the same for a 24 GB card
    fix_psu: int = 95           # 750 W Gold (80-110)
    fix_psu_24gb: int = 120     # 850 W Gold for a 24 GB card
    fix_cooler: int = 30        # tower cooler for a 105 W+ CPU (25-40)
    fix_ssd: int = 90           # 1 TB NVMe
    fix_gpu: int = 220          # used RTX 3060 12 GB: special cases and bundles
    fix_case: int = 65          # airflow case (50-80), bundles only


DEFAULT_POLICY = Policy()
BRIEF = Policy(am4_min_ram=64, stretch=0, allow_intel=False, psu_min_w=750)   # the Brief exactly

DEVIATION_TEXT = {
    "am4_min_ram": lambda p: f"DDR4 platforms (AM4, DDR4 Intel) allowed from {p.am4_min_ram} GB RAM (Brief: AM4 "
                             "needs 64 GB); AM4 below 64 GB is tier 5",
    "min_vram": lambda p: f"GPUs allowed from {p.min_vram} GB VRAM (Brief: 12 GB)",
    "allow_intel": lambda p: "Intel judged case by case (Brief: reject all Intel): 10th gen and older rejected; "
                             "tier 0-3 like AM5 with no drawback, 4 with one, 5 with both (no AVX-512 while "
                             "the model spills to the CPU; dead socket under a CPU that is not already strong)",
    "allow_arc": lambda p: "Intel Arc GPUs allowed (Brief: reject)",
    "allow_apu_x4": lambda p: "Ryzen 8500G/8300G allowed (Brief: reject)",
    "allow_sff": lambda p: "Mini-ITX/SFF allowed (Brief: reject)",
    "allow_oem": lambda p: "OEM prebuilts allowed (Brief: reject)",
    "allow_mini_pc": lambda p: "mini-PCs and handhelds allowed (Brief: reject)",
    "stretch": lambda p: f"tier 0-1 deals may exceed the limit by {p.stretch} € (user addition)",
    "psu_min_w": lambda p: f"PSU fix counted only for a stated PSU under {p.psu_min_w} W (Brief: 750 W)",
    "price_basis": lambda p: "budget judged on the list price as asked, not the effective price (user choice)",
    "pickup_only": lambda p: ("pickup-only listings dropped" if p.pickup_only == "drop"
                              else "pickup-only listings dropped unless local") + " (user filter)",
}
# Always in force (not a setting), so always reported.
STANDING = ["Fixes count toward the price only when the listing confirms the part is missing or too weak; "
            "unmentioned parts of a PC sold as working are flagged and shown in the worst-case price (Brief: "
            "every unconfirmed part counts as a fix)"]


def deviations(p: Policy) -> list[str]:
    """Plain-language list of the selection rules that differ from the Brief."""
    return [DEVIATION_TEXT[f.name](p) for f in fields(Policy)
            if f.name in DEVIATION_TEXT and getattr(p, f.name) != getattr(BRIEF, f.name)] + STANDING
