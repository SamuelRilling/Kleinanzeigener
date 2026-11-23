"""Offline checks for config, dedupe, detail order, state file and the run folder."""
import json
from pathlib import Path

import pytest

import config
import deals
import report
import rules

HIT = {"id": "1", "title": "Gaming PC Ryzen 5 7600 RTX 4060 Ti 16GB 32GB DDR5", "price_amount": 650,
       "price_type": "PLEASE_CONTACT", "image_count": 6, "seller_id": "9", "url": "u1",
       "description": "B650, 2x16GB, be quiet Pure Power 12 M 750W, 1TB NVMe SSD\nGehäuse: Pop Air"}


def test_default_settings_load():
    cfg = config.load()
    assert cfg.budget.limit == 700 and cfg.terms and cfg.prompt_file.name == "ai_pass.md"


def test_bad_settings_list_every_problem(tmp_path: Path):
    bad = config.DEFAULT_FILE.read_text(encoding="utf-8").replace('home_zip = "78628"', 'home_zip = "7862"') \
        .replace("vb_discount = 0.10", 'vb_discount = "ten"')
    path = tmp_path / "search.toml"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        config.load(path)
    assert "budget.vb_discount" in str(exc.value)
    path.write_text(bad.replace('vb_discount = "ten"', "vb_discount = 0.10"), encoding="utf-8")
    with pytest.raises(ValueError, match="home_zip"):
        config.load(path)


def test_dedupe_same_title_keeps_cheapest():
    a, c = {**HIT, "id": "1", "price_amount": 650}, {**HIT, "id": "3", "price_amount": 600}
    assert [h["id"] for h in deals.dedupe_reposts([a, c])] == ["3"]


def test_dedupe_catches_cross_post_with_new_title():
    a = {**HIT, "id": "1"}
    b = {**HIT, "id": "2", "title": "Top PC 4060 Ti 16GB"}   # same seller, price and text
    assert len(deals.dedupe_reposts([a, b])) == 1


class FakeClient:
    """Stands in for the in-process MCP client: canned search pages and details."""
    def __init__(self, _server):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, tool, args):
        self.calls.append(tool)
        if tool == "search_kleinanzeigen":
            hits = [HIT, {**HIT, "id": "7", "title": "PC i7-12700K RTX 3060", "description": ""}]
            body = {"results": hits if args.get("query") == "3060" else [], "has_more": False}
        else:
            body = {**HIT, "attributes": {"Versand": "Nur Abholung"}, "seller_rating": 0.9}
        return type("R", (), {"content": [type("C", (), {"text": json.dumps(body)})], "isError": False})


def test_scan_end_to_end_offline(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "main", types.SimpleNamespace(mcp=None))
    monkeypatch.setitem(sys.modules, "mcp", types.SimpleNamespace(Client=FakeClient))
    cfg = config.load()
    cfg = config.Config(**{**cfg.__dict__, "terms": ("3060",), "bundles_enabled": False, "delay_s": 0})
    import asyncio
    result = asyncio.run(deals.scan(cfg))
    assert [r["ad_id"] for r in result["passed"]] == ["1"]
    assert result["stats"]["rejects"] == {"intel_platform": 1} and result["stats"]["details"] == 1
    assert result["passed"][0]["seller_rating"] == 0.9


def test_details_fetched_best_first():
    good = rules.assess(HIT)
    weak = rules.assess({**HIT, "id": "2", "title": "Ryzen 5 7600 RTX 3060 12GB 16GB DDR5"})
    over = rules.assess({**HIT, "id": "3", "price_amount": 840, "price_type": "FIXED"})
    assert [r["ad_id"] for r in sorted([over, weak, good], key=deals.detail_priority)] == ["1", "2", "3"]


def test_seen_file_is_atomic_and_survives_corruption(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(deals, "STATE_FILE", tmp_path / "seen.json")
    (tmp_path / "seen.json").write_text("{broken", encoding="utf-8")
    assert deals.load_seen() == {}
    deals.save_seen({}, [HIT])
    assert json.loads((tmp_path / "seen.json").read_text(encoding="utf-8")) == {"1": 650}


def test_run_folder_has_every_document(tmp_path: Path):
    cfg = config.load()
    rec = rules.finalize([rules.assess(HIT, cfg.budget)], cfg.budget)[0]
    stats = {"run_time": "2026-11-23T12:00:00", "requests": 1, "details": 1, "detail_errors": 0, "detail_skipped": 0,
             "terms": {"3060": 1}, "errors": [], "capped": False, "rejects": {}, "unique": 1, "incomplete": False}
    result = {"cfg": cfg, "stats": stats, "hits": [HIT], "raw": {"1": HIT}, "snippet": [rec], "final": [rec],
              "passed": [rec], "medians": {}, "seen": {}}
    folder = report.write_run(tmp_path, result)
    names = {p.name for p in folder.iterdir()}
    assert names == {"results.md", "ai_prompt.md", "listings.jsonl", "raw.jsonl", "run.json"}
    prompt = (folder / "ai_prompt.md").read_text(encoding="utf-8")
    assert prompt.startswith("# Used PC deal review") and "# Search results (this run)" in prompt and HIT["title"] in prompt
    assert json.loads((folder / "listings.jsonl").read_text(encoding="utf-8").splitlines()[0])["ad_id"] == "1"
    md = (folder / "results.md").read_text(encoding="utf-8")
    assert "1 featured PCs" in md and "### 1. " + HIT["title"] in md and "B650" in md
    assert "Output:" in report.summary(result, folder)["text"]


def test_excerpt_keeps_relevant_clauses():
    text = report.excerpt("Hallo zusammen!\nNetzteil: be quiet 750W\nSchönes Wochenende\nNur Abholung")
    assert "Netzteil" in text and "Abholung" in text and "Wochenende" not in text
