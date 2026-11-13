"""Offline tests for the parsers and scoring in deals.py.  Run: python -m pytest -q"""
import pytest

import deals

from deals import bands, deal_score, evaluate, fatal_reason, market, parse_cpu, parse_gpu, parse_ram


@pytest.mark.parametrize("title, expected", [
    ("Gaming PC | RTX 3060 12GB | i7-11700 | 32GB RAM", "RTX 3060"),
    ("Gaming PC RTX 3060Ti Ryzen 5", "RTX 3060 Ti"),
    ("PC mit GeForce RTX 4070 Super", "RTX 4070 Super"),
    ("PC 4070S 32GB", "RTX 4070 Super"),
    ("RTX 4070 Ti Super Rechner", "RTX 4070 Ti Super"),
    ("Ryzen 7 7800X3D + RX 7900 XTX", "RX 7900 XTX"),
    ("Ryzen 9 7900X mit 7800XT", "RX 7800 XT"),
    ("Gaming PC GTX1660 Super", "GTX 1660 Super"),
    ("Upgrade: RTX 3070 (vorher GTX 1060)", "RTX 3070"),
    ("Intel Arc B580 PC", "ARC B580"),
    ("Gaming PC Ryzen 7 5800x | 1660 Super | 16GB DDR4", "GTX 1660 Super"),
    ("PC mit Radeon 6800", "RX 6800"),
])
def test_gpu(title, expected):
    assert parse_gpu(title, "")[0] == expected


@pytest.mark.parametrize("title", [
    "Ryzen 5 5600X B550 Office PC",       # CPU number, board chipset
    "Ryzen 5 7600 PC 32GB",               # 7600 is the CPU, not RX 7600
    "Monitor 1920x1080 inklusive",        # resolution, not GTX 1080
    "PC Full HD 1080p Gaming",
    "Ryzen 5 5600XT Gaming PC",           # CPU, not RX 5600 XT
    "Dell OptiPlex 5090 MT i5-10500",     # PC model number, not RTX 5090
    "Grafikkarte 5060",                   # bare number without brand
])
def test_gpu_no_false_positive(title):
    assert parse_gpu(title, "") is None


def test_gpu_from_description():
    gpu = parse_gpu("Gaming PC", "Grafikkarte: RTX 3080 10GB")
    assert gpu[0] == "RTX 3080" and gpu[3] is True


@pytest.mark.parametrize("title, label", [
    ("i7-11700 RTX 3060", "i7 11th gen"),
    ("Intel Core i5 12400F", "i5 12th gen"),
    ("i5-8400", "i5 8th gen"),
    ("Ryzen 7 5800X3D", "Ryzen 7 5800X3D"),
    ("R5 5600X", "Ryzen 5 5600X"),
    ("PC 7800X3D RTX 4080", "Ryzen 7 7800X3D"),
    ("Core Ultra 7 265K", "Core Ultra 7"),
    ("Ryzen 7 Gaming PC", "Ryzen 7 (gen?)"),
    ("Gaming-PC i7-5820K RTX 2080 Ti", "i7 5th gen"),
    ("Pc 32 GB ram i9900kf", "i9 9th gen"),
    ("Gaming Pc Amd Ryzen 5600x 64GB", "Ryzen 5 5600X"),
    ("Hp Z2 G4 - 32 gb Ram - i7 -512 gb ssd", "i7 (gen?)"),
    ("Gaming PC Ryzen 5500 RTX 5060", "Ryzen 5 5500"),
    ("Ryzen 9 5900X", "Ryzen 9 5900X"),
])
def test_cpu(title, label):
    assert parse_cpu(title, "")[0] == label


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
    ("Gaming PC / RTX 3060 / i5 / 16GB RAM", 16),
])
def test_ram(title, gb):
    assert parse_ram(title, "") == gb


@pytest.mark.parametrize("title, desc, reason", [
    ("Gaming PC ohne Grafikkarte", "", "no_gpu"),
    ("Gaming PC", "Die Grafikkarte ist nicht enthalten.", "no_gpu"),
    ("Gaming PC", "Startet nicht, defekt.", "defekt"),
    ("Suche Gaming PC", "", "wanted_ad"),
    ("Gaming Laptop RTX 4060", "", "not_desktop"),
    ("Gaming PC", "Alles funktioniert, nicht defekt.", None),
    ("Gaming PC", "Keine Defekte, Wärmeleitpaste ausgetauscht.", None),
    ("Gaming PC", "Vorteil: leise", None),
    ("Grafikkarte RTX 4080 Eagle Oc 16 Gb Vram", "", "gpu_only"),
    ("Gaming PC mit Grafikkarte RTX 3070", "", None),
])
def test_fatal(title, desc, reason):
    assert fatal_reason(title, desc, {}) == reason


def test_fatal_condition_attribute():
    assert fatal_reason("Gaming PC", "", {"Zustand": "Defekt"}) == "defekt"


def test_evaluate_value_and_flags():
    ad = {"id": "1", "title": "Gaming PC RTX 3060 i7-11700 32GB RAM", "description": "Top Zustand",
          "price_amount": 500, "price_type": "PLEASE_CONTACT", "attributes": {"Versand": "Versand möglich"}}
    l = evaluate(ad)
    assert l["parts_value"] == 190 + 105 + 32 * 3 + 120
    assert l["value_ratio"] == round(l["parts_value"] / 500, 2)
    assert "ships" in l["flags"] and "vb" in l["flags"] and l["fatal"] is None


def test_ram_value_capped():
    l = evaluate({"title": "Gaming PC RTX 3060 i7-11700 128GB RAM", "description": "", "price_amount": 500})
    assert l["parts_value"] == 190 + 105 + 32 * 3 + 120


def test_detailed_listing_without_specs_dropped():
    l = evaluate({"title": "4060 Ti 16GB", "description": "Top", "price_amount": 550, "attributes": {}})
    assert l["fatal"] == "no_cpu_ram_in_full_text"


def test_pickup_text_excluded():
    l = evaluate({"title": "Gaming PC RTX 3060", "description": "Nur an Selbstabholer!", "price_amount": 400})
    assert l["fatal"] == "pickup_text"


def test_local_listing_flagged_and_pickup_allowed():
    l = evaluate({"title": "Gaming PC RTX 3060", "description": "Nur an Selbstabholer!", "price_amount": 400,
                  "local": True})
    assert l["fatal"] is None and l["flags"][0] == "local"


def test_deal_score_is_peer_relative():
    peers = [{"gpu": "RTX 4070", "perf": 165, "price": 1000, "value_ratio": 0.6} for _ in range(4)]
    mkt = market(peers)
    assert deal_score({"gpu": "RTX 4070", "perf": 165, "value_ratio": 0.9}, mkt) == 1.5
    # unseen GPU in an unseen bracket falls back to the scan-wide median
    assert deal_score({"gpu": "RTX 4070 Super", "perf": 190, "value_ratio": 0.6}, mkt) == 1.0


def test_bands_span_budget():
    b = bands()
    assert b[0][0] == deals.BUDGET_MIN and b[-1][1] == deals.BUDGET_MAX and all(lo < hi for lo, hi in b)
