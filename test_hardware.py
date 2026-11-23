"""PCIe link, headroom, RAM path, price sanity, needs-answers ranking, featuring, questions."""
import pytest

import rules

BASE = {"description": "Netzteil: be quiet Pure Power 12 M 750W | 1TB NVMe SSD | Gehäuse: Pop Air",
        "price_amount": 450, "price_type": "FIXED", "image_count": 4}


def assess(title: str, desc: str = "", **kw) -> dict:
    return rules.assess({**BASE, "id": title, "title": title, "description": BASE["description"] + "\n" + desc, **kw})


@pytest.mark.parametrize("title, text, reduced", [
    ("Ryzen 7 8700G RTX 3060 12GB 32GB DDR5 B650", "4.0 ×8", True),          # x16 card behind an x8 APU
    ("Ryzen 5 7600 RTX 5060 Ti 16GB 32GB DDR5 B650", "4.0 ×8", True),         # 5.0 x8 card in a 4.0 slot
    ("Ryzen 5 7600 RTX 5060 Ti 16GB 32GB DDR5 B650E", "5.0 ×8", False),
    ("Ryzen 5 7600 RTX 3060 12GB 32GB DDR5 B650", "4.0 ×16", False),
    ("Ryzen 7 5700X RTX 4060 Ti 16GB 64GB DDR4 B450", "3.0 ×8", True),        # x8 card on PCIe 3.0
    ("Ryzen 7 5700X RTX 3060 12GB 64GB DDR4 B450", "3.0 ×16", False),         # x16 cards are fine there
])
def test_pcie_link(title, text, reduced):
    r = assess(title)
    assert r["link"]["text"].startswith(text) and r["link"]["reduced"] == reduced
    assert ("pcie_link_reduced" in r["flags"]) == reduced


def test_unknown_board_link_is_marked_assumed():
    assert assess("Ryzen 5 7600 RTX 3060 12GB 32GB DDR5")["link"]["text"] == "4.0 ×16 (?)"


def test_headroom():
    h = assess("Ryzen 5 7600 RTX 3060 12GB 32GB DDR5 B650E", "2x16GB")["headroom"]
    assert h["psu"] and h["case"] and h["free_slots"] == 2 and h["pcie5"] and h["zen6"]
    assert "dead-end socket" in assess("Ryzen 7 5700X RTX 3060 12GB 64GB DDR4 B550")["headroom"]["text"]


def test_48gb_path_and_ai_tier():
    r = assess("Ryzen 5 7600 RTX 3060 12GB 48GB DDR5 B650", "2x24GB")
    assert r["path"]["to64"] is None and "2×24" in r["path"]["note"] and "borderline" in r["ai"]


@pytest.mark.parametrize("price, desc, reason", [
    (1, "", "placeholder_price"),
    (300, "Preis gilt nur für die Grafikkarte, Rest auf Anfrage", "price_not_for_whole_pc"),
    (300, "Preis pro Stück", "price_not_for_whole_pc"),
    (150, "", "price_below_parts_value"),       # RTX 3090 alone is worth ~750 €
])
def test_price_not_for_this_pc(price, desc, reason):
    r = assess("Ryzen 5 7600 RTX 3090 32GB DDR5 B650", desc, price_amount=price)
    assert r["reject"] == reason


def test_believable_cheap_price_passes_price_check():
    assert assess("Ryzen 5 7600 RTX 3060 12GB 32GB DDR5 B650", price_amount=400)["reject"] is None


def test_needs_answers_ranks_lower_within_tier():
    clear = assess("Ryzen 5 7600 RTX 3060 12GB 32GB DDR5 B650", "2x16GB")
    vague = assess("Ryzen 5 7600 RTX 3060 32GB DDR5 B650", "2x16GB")   # 3060: VRAM unstated (8 or 12 GB)
    assert vague["needs_answers"] and not clear["needs_answers"] and clear["tier"] == vague["tier"] == 2
    assert [r["ad_id"] for r in rules.finalize([vague, clear])] == [clear["ad_id"], vague["ad_id"]]


def test_needs_answers_featured_only_when_deal_is_good():
    vague_cheap = assess("Ryzen 5 7600 RTX 3060 32GB DDR5 B650", "2x16GB", price_amount=400)
    vague_dear = assess("Ryzen 5 7600 RTX 3060 32GB DDR5 B650", "2x16GB", price_amount=650, id="dear")
    out = {r["ad_id"]: r["featured"] for r in rules.finalize([vague_cheap, vague_dear])}
    assert out == {vague_cheap["ad_id"]: True, vague_dear["ad_id"]: False}   # target 600 €


def test_tier3_only_featured_when_ram_step_still_wins():
    tier2 = assess("Ryzen 5 7600 RTX 3060 12GB 32GB DDR5 B650", "2x16GB", price_amount=700)
    t3_cheap = assess("Ryzen 5 7600 RTX 3060 12GB 16GB DDR5 B650", "2x8GB", price_amount=180)  # 180 + 490 < 700
    t3_dear = assess("Ryzen 5 7600 RTX 3060 12GB 16GB DDR5 B650", "2x8GB", price_amount=300, id="t3_dear")
    out = {r["ad_id"]: r for r in rules.finalize([tier2, t3_cheap, t3_dear])}
    assert out[t3_cheap["ad_id"]]["featured"] and "beats_tier12_with_ram" in out[t3_cheap["ad_id"]]["flags"]
    assert not out[t3_dear["ad_id"]]["featured"] and "dominated_by_tier12" in out[t3_dear["ad_id"]]["flags"]


def test_finalize_does_not_mutate_inputs():
    r = assess("Ryzen 5 7600 RTX 3060 12GB 32GB DDR5 B650", "2x16GB")
    before = list(r["flags"])
    rules.finalize([r])
    assert r["flags"] == before and r["featured"] is False


def test_questions_merge_into_screenshot_and_label_photo():
    msg = rules.seller_message(["gpu_vram", "ram", "board", "psu"], ships=False, mining_flag=False)
    assert msg.count("CPU-Z") == 1 and "Typenschild" in msg and "bestückt" not in msg
    assert "bestückt" in rules.seller_message(["ram"], ships=False, mining_flag=False)


def test_am4_32gb_passes_as_tier5_by_default():
    r = assess("Ryzen 7 5700X RTX 3060 12GB 32GB DDR4 B550", "2x16GB", price_amount=400)
    assert r["reject"] is None and r["tier"] == 5 and r["ai"].startswith("Coder")


def test_am4_floor_follows_settings():
    strict = rules.Policy(am4_min_ram=64)   # the Brief's own rule
    r = rules.assess({**BASE, "id": "x", "title": "Ryzen 7 5700X RTX 3060 12GB 32GB DDR4 B550"}, strict)
    assert r["reject"] == "am4_under_64gb"


def test_tier5_ranks_after_am5():
    am5 = assess("Ryzen 5 7600 RTX 3060 12GB 32GB DDR5 B650", "2x16GB", price_amount=650)
    am4 = assess("Ryzen 7 5700X RTX 3060 12GB 32GB DDR4 B550", "2x16GB", price_amount=300)
    assert [r["ad_id"] for r in rules.finalize([am4, am5])] == [am5["ad_id"], am4["ad_id"]]
