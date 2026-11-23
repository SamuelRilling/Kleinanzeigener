"""Clause / label / context / negation behaviour of the parsers.  Run: python -m pytest -q"""
import pytest

import rules
from parse import parse_case, parse_cpu, parse_gpu, parse_psu, parse_ram, parse_storage, ram_candidates


@pytest.mark.parametrize("desc, gb", [
    ("RAM: 32GB DDR5, erweiterbar auf 128GB", 32),
    ("Board unterstützt max. 128GB RAM | 16GB DDR4", 16),
    ("bis zu 64GB möglich\nArbeitsspeicher: 16 GB DDR5", 16),
    ("Grafikkarte: RX 7600 XT 16GB\nRAM: 32GB", 32),
])
def test_ram_ignores_limits_and_vram(desc, gb):
    assert parse_ram("Gaming PC", desc) == gb


def test_ram_board_name_max_is_not_a_limit():
    assert parse_ram("B450 Tomahawk MAX, 32GB RAM", "") == 32


def test_ram_kit_not_double_counted():
    assert set(ram_candidates("PC 2x16GB DDR5", "")) == {32}


def test_gpu_history_is_skipped():
    assert parse_gpu("Gaming PC", "Neue RTX 4070 eingebaut, vorher GTX 1060")["name"] == "RTX 4070"
    assert parse_gpu("Gaming PC", "statt der alten RTX 2060 jetzt RTX 3060 12GB")["name"] == "RTX 3060"


def test_gpu_labelled_line_beats_title_and_flags_conflict():
    g = parse_gpu("Gaming PC RTX 3060", "Grafikkarte: RTX 4060 Ti 16GB")
    assert g["name"] == "RTX 4060 Ti" and g["vram"] == 16 and g["conflict"]


def test_cpu_support_note_is_skipped():
    c = parse_cpu("Gaming PC", "Mainboard: B650, Ryzen 9000 ready\nCPU: Ryzen 5 7600")
    assert c["model"] == "7600" and not c["conflict"]


def test_psu_ignores_gpu_tdp_and_reads_model_watts():
    assert parse_psu("PC", "RTX 3060 170W | Netzteil: Corsair RM750x")["watts"] == 750


@pytest.mark.parametrize("desc", ["Kein Netzteil dabei", "ohne Netzteil"])
def test_psu_missing(desc):
    assert parse_psu("PC", desc) == {"watts": None, "trusted": False, "missing": True}


def test_storage_missing_and_present():
    assert parse_storage("PC", "ohne SSD")["missing"]
    assert parse_storage("PC", "1TB NVMe SSD | ohne HDD") == {"nvme": True, "gb": 1000, "missing": False}


def test_case_line():
    assert parse_case("PC", "Gehäuse: Lian Li Lancool 216 Mesh") == {"name": "LIAN LI LANCOOL 216 MESH", "sff": False}
    assert parse_case("Mini-ITX PC", "")["sff"]


def test_conflict_becomes_an_unknown_not_a_reject():
    r = rules.assess({"title": "Ryzen 5 7600 RTX 3060 12GB 32GB DDR5", "description": "RAM: 16GB DDR5",
                      "price_amount": 300, "image_count": 3})
    assert "conflict_ram" in r["flags"] and "ram" in r["unknown"] and r["build"]["ram_gb"]["src"] == "assumed"


def test_missing_psu_is_priced():
    r = rules.assess({"title": "Ryzen 5 7600 RTX 3060 12GB 32GB DDR5", "description": "ohne Netzteil",
                      "price_amount": 300, "image_count": 3})
    assert r["fixes"]["psu"] == rules.DEFAULT_POLICY.fix_psu and "psu_missing" in r["flags"]


def test_bundle_track_prices_gpu_and_case():
    r = rules.assess({"title": "AM5 Aufrüstkit Ryzen 5 7600 + B650 + 32GB DDR5", "description": "2x16GB",
                      "price_amount": 200, "image_count": 3})
    assert r["track"] == "bundle" and r["reject"] is None and r["tier"] == 2
    assert r["fixes"]["gpu"] == rules.DEFAULT_POLICY.fix_gpu and r["fixes"]["case"] == rules.DEFAULT_POLICY.fix_case


def test_gpu_less_intel_is_not_a_bundle():
    r = rules.assess({"title": "Aufrüstkit i5-12400F B660 16GB", "description": "", "price_amount": 200, "image_count": 3})
    assert r["track"] == "pc" and r["reject"] == "gpu_unknown"


def test_budget_comes_from_config():
    tight = rules.Policy(limit=400, target=300)
    r = rules.assess({"title": "Ryzen 5 7600 RTX 3060 12GB 32GB DDR5", "description": "", "price_amount": 450,
                      "image_count": 3}, tight)
    assert r["reject"] == "over_budget"
