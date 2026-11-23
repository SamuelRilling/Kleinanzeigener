"""Intel judged case by case, fixes counted only when confirmed, list vs effective price, pickup only."""
import pytest

import hardware
import rules
from parse import parse_cpu


def assess(title: str, desc: str = "", policy: rules.Policy = rules.DEFAULT_POLICY, **ad) -> dict:
    return rules.assess({"title": title, "description": desc, "price_amount": 500, "image_count": 3, **ad}, policy)


@pytest.mark.parametrize("text, label, gen", [
    ("PC i5-13600KF RTX 4070", "Core i5-13600KF", 13),
    ("Intel Core i7 12700K", "Core i7-12700K", 12),
    ("Core Ultra 5 245K", "Core Ultra 5 245K", 15),
    ("i5 9400F GTX 1660", "Core i5-9400F", 9),
    ("Gaming PC i7", "Core i7 (gen?)", None),
])
def test_intel_model_and_generation(text, label, gen):
    c = parse_cpu(text, "")
    assert (c["label"], c["gen"], c["conflict"]) == (label, gen, False)


def test_unstated_generation_is_the_worst_the_board_allows():
    assert hardware.intel_facts({"gen": None, "tier": 7}, "B460", None)["old"]          # LGA1200 -> 10th gen
    i = hardware.intel_facts({"gen": None, "tier": 7}, None, None)
    assert i["gen"] == hardware.INTEL_ASSUMED_GEN and i["gen_src"] == "assumed" and not i["strong"]


def test_old_intel_is_rejected():
    assert assess("PC i7-10700K RTX 3060 12GB 32GB")["reject"] == "intel_old"


def test_strong_cpu_waives_the_dead_socket_but_not_avx512():
    r = assess("PC i7-13700K RTX 4070 32GB DDR5")
    assert r["reject"] is None and r["tier"] == 4
    assert "intel_no_avx512_offload" in r["flags"] and "intel_dead_socket" not in r["flags"]
    assert {"intel_cpu_strong", "raptor_lake_check_bios"} <= set(r["flags"]) and "intel_bios" in r["unknown"]


def test_weak_cpu_gets_both_drawbacks():
    r = assess("PC i5-12400F RTX 4070 32GB DDR5")
    assert r["tier"] == 5 and {"intel_no_avx512_offload", "intel_dead_socket"} <= set(r["flags"])


def test_no_drawback_ranks_like_am5(monkeypatch):
    monkeypatch.setattr(rules, "experts_on_cpu", lambda b: 0)   # a model that fits in VRAM
    intel = assess("PC i7-13700K RTX 4070 32GB DDR5")
    am5 = assess("PC Ryzen 7 7700 RTX 4070 32GB DDR5")
    assert intel["tier"] == am5["tier"] == 2


def test_rocket_lake_has_avx512():
    assert hardware.intel_facts({"gen": 11, "tier": 7, "model": "11700"}, None, 4)["avx512"]


def test_ddr4_intel_follows_the_ram_floor():
    assert assess("PC i7-12700K RTX 4070 16GB DDR4")["reject"] == "ddr4_under_32gb"


def test_am5_swap_is_compared_with_the_best_am5_deal():
    intel = assess("PC i7-13700K RTX 4070 32GB DDR5")
    am5 = rules.assess({"title": "PC Ryzen 7 7700 RTX 4070 32GB DDR5", "description": "", "price_amount": 650,
                        "image_count": 3})
    out = {r["ad_id"]: r for r in rules.finalize([{**intel, "ad_id": "i"}, {**am5, "ad_id": "a"}])}
    assert intel["am5_swap"] == rules.AM5_SWAP_BOARD + rules.AM5_SWAP_CPU - 120 - rules.INTEL_RESALE_STRONG
    assert "am5_swap_beats_best_am5" in out["i"]["flags"] and out["i"]["best_am5"] == 650


@pytest.mark.parametrize("desc, fixes, maybe", [
    ("", {}, {"psu", "ssd"}),                                   # nothing stated: flags only
    ("Netzteil 550W, 1TB NVMe", {"psu"}, set()),                # stated under 650 W: counted
    ("Netzteil 700W, 1TB NVMe", {}, {"psu"}),                   # enough watts, brand unknown
    ("be quiet Pure Power 12 M 650W, 1TB NVMe", {}, set()),     # trusted and 650 W: no fix
    ("ohne Netzteil, SSD 512GB NVMe", {"psu", "ssd"}, set()),   # stated missing / too small: counted
])
def test_fixes_count_only_when_confirmed(desc, fixes, maybe):
    r = assess("PC Ryzen 5 7600 RTX 4070 32GB DDR5", desc)
    assert set(r["fixes"]) == set(fixes) and set(r["maybe_fixes"]) == maybe
    assert r["worst"] == r["effective"] + sum(r["maybe_fixes"].values())


def test_price_basis_picks_list_or_effective():
    vb = {"price_type": "PLEASE_CONTACT", "price_amount": 740}
    title, desc = "PC Ryzen 5 7600 RTX 4070 32GB DDR5", "Netzteil 500W, 1TB NVMe"
    eff = rules.assess({"title": title, "description": desc, "image_count": 3, **vb})
    lst = rules.assess({"title": title, "description": desc, "image_count": 3, **vb}, rules.Policy(price_basis="list"))
    assert eff["budget"] == eff["effective"] == round(740 * 0.9) + 95 and eff["reject"] == "over_budget"
    assert lst["budget"] == 740 and lst["reject"] == "over_budget"
    assert rules.assess({"title": title, "description": "1TB NVMe", "image_count": 3, "price_amount": 690},
                        rules.Policy(price_basis="list"))["reject"] is None


@pytest.mark.parametrize("desc, pickup", [
    ("Nur Abholung in Rottweil", True), ("Kein Versand!", True), ("Nur an Selbstabholer", True),
    ("Wird nicht versendet.", True), ("Abholung oder Versand möglich", False),
])
def test_pickup_only_detected(desc, pickup):
    r = assess("PC Ryzen 5 7600 RTX 4070 32GB DDR5", desc)
    assert r["pickup_only"] == pickup and ("pickup_only" in r["flags"]) == pickup and not (pickup and r["ships"])


def test_pickup_filter():
    title, desc = "PC Ryzen 5 7600 RTX 4070 32GB DDR5", "Nur Abholung"
    assert assess(title, desc)["reject"] is None
    assert assess(title, desc, rules.Policy(pickup_only="drop"))["reject"] == "pickup_only"
    assert assess(title, desc, rules.Policy(pickup_only="local_only"))["reject"] == "pickup_only_not_local"
    assert assess(title, desc, rules.Policy(pickup_only="local_only"), local=True)["reject"] is None
