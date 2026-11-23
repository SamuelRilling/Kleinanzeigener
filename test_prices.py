"""Fair-price table: shape check, fair price per listing, under/overpriced flags, VB target, export."""
import csv
from pathlib import Path

import pytest

import prices
import rules

TABLE = {"meta": {"whole_pc_factor": 1.0, "base_eur": 100},
         "gpu": {"RTX 4070": 400}, "cpu": {"Ryzen 5 7600": 120}, "ram": {"DDR5 32 GB": 180}, "board": {"B650": 100}}
FAIR = 1.0 * (400 + 120 + 180 + 100) + 100          # 900
TITLE, DESC = "PC Ryzen 5 7600 RTX 4070 32GB DDR5", "MSI B650, Netzteil be quiet Pure Power 750W, 1TB NVMe"


def assess(ask: int, table: dict = TABLE, **ad) -> dict:
    return rules.assess({"title": TITLE, "description": DESC, "price_amount": ask, "image_count": 3, **ad},
                        rules.DEFAULT_POLICY, table=table)


def test_table_shape_is_checked(tmp_path: Path):
    good = tmp_path / "prices.toml"
    good.write_text('[meta]\nwhole_pc_factor = 0.9\nbase_eur = 80\n[gpu]\n"RTX 4070" = { used = 400, n = 3 }\n',
                    encoding="utf-8")
    assert prices.load(good)["gpu"] == {"RTX 4070": 400}
    assert prices.load(tmp_path / "missing.toml") == {}
    bad = tmp_path / "bad.toml"
    bad.write_text('[meta]\nwhole_pc_factor = 3\n[gpu]\n"RTX 4070" = { new = 500 }\n', encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        prices.load(bad)
    assert "whole_pc_factor" in str(exc.value) and "base_eur" in str(exc.value) and "RTX 4070" in str(exc.value)


def test_sanity_check_marks_doubtful_parts(tmp_path: Path):
    path = tmp_path / "prices.toml"
    path.write_text('[meta]\nwhole_pc_factor = 1.0\nbase_eur = 100\nwarnings = ["only 40 rows"]\n'
                    '[gpu]\n"RTX 4070" = { used = 400, check = "off", note = "above new" }\n'
                    '[cpu]\n"Ryzen 5 7600" = { used = 120, check = "ok" }\n[ram]\n"DDR5 32 GB" = { used = 180 }\n'
                    '[board]\n"B650" = { used = 100 }\n', encoding="utf-8")
    table = prices.load(path)
    assert table["checks"]["gpu"] == {"RTX 4070": "off: above new"} and table["meta"]["warnings"] == ["only 40 rows"]
    r = assess(600, table)
    assert r["value"] == "under" and "fair_price_doubtful" in r["flags"]
    assert r["fair_doubts"] == ["gpu RTX 4070 (off: above new)"]
    assert "fair_price_doubtful" not in assess(600)["flags"]
    path.write_text('[meta]\nwhole_pc_factor = 1.0\nbase_eur = 100\n[gpu]\n"RTX 4070" = { used = 400, check = "bad" }\n',
                    encoding="utf-8")
    with pytest.raises(ValueError, match="check is one of"):
        prices.load(path)


def test_fair_price_from_parts():
    r = assess(800)
    assert r["fair"] == FAIR and r["fair_stated"] and r["fair_delta"] == round(800 / FAIR - 1, 3)
    assert r["value"] is None                              # 11 % under: inside the band


def test_underpriced_is_flagged_and_featured_even_with_open_questions():
    r = assess(600)
    assert r["value"] == "under" and "underpriced_33pct" in r["flags"]
    vague = rules.assess({"title": "PC Ryzen 5 7600 RTX 4070 32GB DDR5", "description": "", "price_amount": 600,
                          "image_count": 3}, rules.DEFAULT_POLICY, table={**TABLE, "board": {"AM5 board (unknown)": 100}})
    needs = {**vague, "needs_answers": True, "tier": 2, "budget": 690}
    assert rules.finalize([needs])[0]["featured"]


def test_overpriced_is_a_flag_not_a_reject():
    r = assess(1100)
    assert r["value"] == "over" and r["reject"] == "over_budget"   # rejected by the limit, not by the flag
    cheap_table = {**TABLE, "gpu": {"RTX 4070": 52}}       # fair 552; ask 690 is 25 % over
    r = assess(690, cheap_table)
    assert r["reject"] is None and "overpriced_25pct" in r["flags"]


def test_assumed_parts_get_a_fair_price_but_no_verdict():
    r = rules.assess({"title": "Gaming PC RTX 4070 Ryzen 5 7600", "description": "", "price_amount": 500,
                      "image_count": 3}, rules.DEFAULT_POLICY,
                     table={**TABLE, "ram": {"DDR5 16 GB": 90}, "board": {"AM5 board (unknown)": 100}})
    assert r["fair"] and not r["fair_stated"] and r["value"] is None


def test_missing_key_means_no_fair_price():
    r = assess(600, {**TABLE, "gpu": {}})
    assert r["fair"] is None and r["fair_missing"] == ["gpu: RTX 4070"] and r["value"] is None


def test_vb_target_uses_the_fair_price_within_limits():
    p = rules.DEFAULT_POLICY
    assert rules.vb_price(1000, None, p) == 900            # no table: the usual 10 %
    assert rules.vb_price(1000, 950, p) == 900             # fair above the usual haggle: the usual haggle
    assert rules.vb_price(1000, 870, p) == 870             # fair below: aim for it
    assert rules.vb_price(1000, 500, p) == 850             # never more than 15 % off
    r = assess(1000, price_type="PLEASE_CONTACT")
    assert r["price"] == 900 and "vb_target_from_fair_price" not in r["flags"]


def test_components_export_uses_table_names(tmp_path: Path):
    r = assess(800)
    path = tmp_path / "components.csv"
    prices.write_components(path, [r])
    row = next(csv.DictReader(path.open(encoding="utf-8")))
    assert (row["gpu"], row["cpu"], row["ram"], row["board"], row["stated"]) == \
        ("RTX 4070", "Ryzen 5 7600", "DDR5 32 GB", "B650", "1")
