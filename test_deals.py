"""Offline tests for parse.py and rules.py.  Run: python -m pytest -q"""
import pytest

import rules
from parse import (fatal_reason, parse_chipset, parse_cpu, parse_gpu, parse_psu, parse_ram, parse_ram_layout,
                   parse_storage)


@pytest.mark.parametrize("title, expected", [
    ("Gaming PC | RTX 3060 12GB | Ryzen 5 7600 | 32GB RAM", "RTX 3060"),
    ("Gaming PC RTX 3060Ti Ryzen 5", "RTX 3060 Ti"),
    ("PC 4070S 32GB", "RTX 4070 Super"),
    ("RTX 4070 Ti Super Rechner", "RTX 4070 Ti Super"),
    ("Ryzen 9 7900X mit 7800XT", "RX 7800 XT"),
    ("Upgrade: RTX 3070 (vorher GTX 1060)", "RTX 3070"),
    ("Intel Arc B580 PC", "ARC B580"),
])
def test_gpu_name(title, expected):
    assert parse_gpu(title, "")["name"] == expected


@pytest.mark.parametrize("title", [
    "Ryzen 5 7600 PC 32GB",               # 7600 is the CPU, not RX 7600
    "Monitor 1920x1080 inklusive",
    "Ryzen 5 5600XT Gaming PC",           # CPU, not RX 5600 XT
    "Dell OptiPlex 5090 MT i5-10500",
    "Grafikkarte 5060",                   # bare number without brand
])
def test_gpu_no_false_positive(title):
    assert parse_gpu(title, "") is None


@pytest.mark.parametrize("title, vram, stated", [
    ("PC RTX 3060", 12, False),            # Priming 6.2: assume 12 GB, flag
    ("PC RTX 3060 8GB", 8, True),
    ("PC RTX 4060 Ti", 8, False),          # assume 8 GB until shown otherwise
    ("PC RTX 4060 Ti 16GB", 16, True),
    ("PC RTX 5060 Ti 16 GB", 16, True),
    ("PC RTX 3080", 10, False),
    ("PC RTX 3090", 24, True),             # single variant counts as stated
])
def test_gpu_vram(title, vram, stated):
    g = parse_gpu(title, "")
    assert (g["vram"], g["vram_stated"]) == (vram, stated)


@pytest.mark.parametrize("title, platform, model", [
    ("Ryzen 5 7600 RTX 3060", "AM5", "7600"),
    ("R7 7800X3D", "AM5", "7800"),
    ("Ryzen 7 8700G", "AM5", "8700"),
    ("Ryzen 5 5600X", "AM4", "5600"),
    ("Gaming Pc Amd 9700X", "AM5", "9700"),
    ("i7-12700K RTX 3060", "INTEL", "12700"),
    ("Core Ultra 7 265K", "INTEL", "265"),
    ("Ryzen 7 Gaming PC", None, None),
])
def test_cpu_platform(title, platform, model):
    c = parse_cpu(title, "")
    assert (c["platform"], c["model"]) == (platform, model)


def test_cpu_ignores_ddr5():
    assert parse_cpu("32GB DDR5 RTX 4070", "") is None


@pytest.mark.parametrize("title, gb", [
    ("RTX 3060 12GB | 32GB RAM", 32),
    ("16 GB DDR4", 16),
    ("RAM: 64GB", 64),
    ("2x16GB Corsair", 32),
    ("RTX 3070 8GB VRAM", None),
    ("1TB SSD 512GB", None),
    ("NVIDIA GeForce RTX 3060 (12 GB RAM), 32GB DDR4", 32),
    ("Ryzen 5 5600X RTX 3060 32GB", 32),
    ("RTX 4060 Ti 16GB", None),
    ("4060 Ti 16GB Gaming PC", None),
    ("1TB NVMe, 32 GB", 32),
])
def test_ram(title, gb):
    assert parse_ram(title, "") == gb


def test_ram_layout_and_chipset():
    assert parse_ram_layout("PC", "Corsair Vengeance 2×16GB DDR5") == (2, 16)
    assert parse_chipset("MSI B650M Gaming") == "B650"
    assert parse_chipset("ASUS X670E Hero") == "X670E"


@pytest.mark.parametrize("text, watts, trusted", [
    ("Netzteil: be quiet! Pure Power 12 M 750W", 750, True),
    ("750W Netzteil", 750, False),
    ("Corsair RM850x", 850, True),
    ("be quiet System Power 10 650W Netzteil", 650, False),
    ("Corsair CX650 Netzteil", 650, False),
])
def test_psu(text, watts, trusted):
    assert parse_psu("PC", text) == {"watts": watts, "trusted": trusted, "missing": False}


def test_psu_unmentioned():
    assert parse_psu("Ryzen 5 7600, RTX 3060", "") is None


@pytest.mark.parametrize("text, nvme, gb", [
    ("1TB NVMe SSD", True, 1000),
    ("Samsung 980 Pro M.2 2TB", True, 2000),
    ("1 TB SSD", False, 1000),
    ("500GB SSD + 2TB HDD", False, 500),
])
def test_storage(text, nvme, gb):
    assert parse_storage("PC", text) == {"nvme": nvme, "gb": gb, "missing": False}


@pytest.mark.parametrize("title, desc, reason", [
    ("Gaming PC ohne Grafikkarte", "", "no_gpu"),
    ("Gaming PC", "Die Grafikkarte ist nicht enthalten.", "no_gpu"),
    ("Gaming PC", "Startet nicht, defekt.", "defekt"),
    ("Suche Gaming PC", "", "wanted_ad"),
    ("Gaming Laptop RTX 4060", "", "not_desktop"),
    ("Gaming PC", "Alles funktioniert, nicht defekt.", None),
    ("Grafikkarte RTX 4080 Eagle Oc 16 Gb Vram", "", "gpu_only"),
    ("Lenovo Legion Tower 5 RTX 3060", "", "oem_prebuilt"),
    ("Gaming PC RESERVIERT", "", "reserved"),
])
def test_fatal(title, desc, reason):
    assert fatal_reason(title, desc, {}) == reason


GOOD = {"id": "1", "title": "Gaming PC Ryzen 5 7600 RTX 4060 Ti 16GB 32GB DDR5",
        "description": "MSI B650 Tomahawk, 2x16GB, be quiet Pure Power 12 M 750W, 1TB NVMe SSD, Arctic Freezer 36\n"
                       "Gehäuse: Fractal Pop Air",
        "price_amount": 650, "price_type": "PLEASE_CONTACT", "image_count": 6}


def test_tier1_passes_with_vb_price():
    r = rules.assess(GOOD)
    assert r["reject"] is None and r["tier"] == 1 and r["fixes"] == {}
    assert r["price"] == 585 and r["effective"] == 585 and "act_fast" in r["flags"]
    assert r["path"] == {"to32": 0, "to64": rules.RAM_DDR5_2X16} and r["unknown"] == []


def test_unmentioned_parts_are_flagged_not_priced():
    r = rules.assess({**GOOD, "description": "Top Zustand", "price_type": "FIXED", "price_amount": 450})
    assert r["reject"] is None and r["fixes"] == {} and r["effective"] == 450
    assert r["maybe_fixes"] == {"psu": rules.DEFAULT_POLICY.fix_psu, "ssd": rules.DEFAULT_POLICY.fix_ssd}
    assert r["worst"] == 450 + 95 + 90 and {"psu_unstated", "ssd_unstated"} <= set(r["flags"])
    assert r["tier"] == 2  # 16 GB card, but the PSU is unverified -> not tier 1
    assert r["build"]["ram_layout"] == {"v": (4, 8), "src": "assumed"}  # worst case for "32 GB"
    assert {"ram_layout", "board", "psu", "storage", "case"} <= set(r["unknown"]) and not r["needs_answers"]


@pytest.mark.parametrize("title, reason", [
    ("PC i7-9700K RTX 3060 32GB", "intel_old"),
    ("PC Ryzen 5 7600 RTX 3070 32GB", "vram_under_12gb"),
    ("PC Ryzen 5 7600 RTX 4060 Ti 32GB", "vram_under_12gb"),   # VRAM unstated -> 8 GB
    ("PC Ryzen 5 5600X RTX 3060 16GB", "ddr4_under_32gb"),
    ("PC Ryzen 5 8500G RTX 3060 32GB DDR5", "apu_pcie_x4"),
    ("Mini-ITX PC Ryzen 5 7600 RTX 3060 32GB", "itx_or_sff"),
    ("PC Ryzen 5 7600 Arc B580 32GB", "intel_arc"),
])
def test_hard_rejects(title, reason):
    assert rules.assess({"title": title, "description": "", "price_amount": 400, "image_count": 3})["reject"] == reason


def test_am4_64gb_is_tier4_under_550():
    r = rules.assess({"title": "Ryzen 7 5700X RTX 3060 12GB 64GB DDR4 B550", "description": "",
                      "price_amount": 300, "image_count": 3})
    assert r["reject"] is None and r["tier"] == 4 and r["effective"] == 300 and r["worst"] == 300 + 95 + 90


def test_3090_jumps_to_tier0_and_may_stretch():
    r = rules.assess({"title": "Ryzen 7 7700 RTX 3090 32GB DDR5", "description": "",
                      "price_amount": 740, "image_count": 3})
    assert r["tier"] == 0 and r["reject"] is None and "stretch_over_700" in r["flags"]


def test_special_case_big_ram_weak_gpu():
    r = rules.assess({"title": "Ryzen 5 7600 RTX 3070 64GB DDR5", "description": "1TB NVMe, Corsair RM750x",
                      "price_amount": 550, "image_count": 3})
    assert r["reject"] == "vram_under_12gb" and r["special"]


def test_two_scam_signals_drop():
    r = rules.assess({**GOOD, "description": GOOD["description"] + " Nur Versand, bitte per WhatsApp melden."})
    assert r["reject"] == "scam_signals"


def test_too_cheap_vs_market_is_one_signal():
    r = rules.assess(GOOD, gpu_median=1200)
    assert r["reject"] is None and "too_cheap_vs_market" in r["flags"]


def test_ranking_prefers_ram_over_vram():
    a = rules.assess({**GOOD, "id": "a"})
    b = rules.assess({**GOOD, "id": "b", "title": "Ryzen 5 7600 RTX 3060 12GB 64GB DDR5"})
    assert sorted([a, b], key=rules.sort_key)[0]["ad_id"] == "a"  # tier 1 beats tier 2 first
    c = rules.assess({**GOOD, "id": "c", "title": "Ryzen 5 7600 RTX 4060 Ti 16GB 64GB DDR5",
                      "description": GOOD["description"].replace("2x16GB", "2x32GB")})
    assert sorted([a, c], key=rules.sort_key)[0]["ad_id"] == "c"  # same tier: more RAM wins


def test_seller_message_lists_unknowns():
    msg = rules.seller_message(["psu", "ram"], ships=False, mining_flag=False)
    assert msg.startswith("Hallo,") and "Netzteil" in msg and "bestückt" in msg and "testen" in msg


@pytest.mark.parametrize("title, desc, reason", [
    ("HP Victus 15L Gaming-PC RTX 3060", "", "oem_prebuilt"),
    ("GMKtec M7 Mini PC Ryzen 7 6850H 32GB DDR5", "", "mini_pc_or_handheld"),
    ("Gaming PC Ryzen 9 7945HX", "", "mini_pc_or_handheld"),
    ("Gaming PC RTX 3060", "UPDATE: Der PC als Ganzes wird nicht mehr verkauft, nur noch die einzelnen Komponenten.",
     "parted_out"),
])
def test_fatal_more(title, desc, reason):
    assert fatal_reason(title, desc, {}) == reason
