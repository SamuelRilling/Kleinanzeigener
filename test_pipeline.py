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
    assert cfg.policy.limit == 700 and cfg.terms and cfg.prompt_file.name == "ai_pass.md"


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
        else:   # the full listing of whichever ad was asked for
            base = HIT if str(args["ad_id"]) == "1" else {**HIT, "id": "7", "title": "PC i7-12700K RTX 3060",
                                                        "description": ""}
            body = {**base, "attributes": {"Versand": "Nur Abholung"}, "seller_rating": 0.9}
        return type("R", (), {"content": [type("C", (), {"text": json.dumps(body)})], "isError": False})


def test_scan_end_to_end_offline(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "main", types.SimpleNamespace(mcp=None))
    monkeypatch.setitem(sys.modules, "mcp", types.SimpleNamespace(Client=FakeClient))
    cfg = config.load()
    cfg = config.Config(**{**cfg.__dict__, "terms": ("3060",), "bundles_enabled": False, "delay_s": 0})
    import asyncio
    result = asyncio.run(deals.scan(cfg, cache={}))
    assert [r["ad_id"] for r in result["passed"]] == ["1", "7"]            # the strong Intel CPU is judged, not dropped
    assert result["stats"]["rejects"] == {} and result["stats"]["details"] == 2  # full text for all
    assert "pickup_only" in result["passed"][1]["flags"]
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
    rec = rules.finalize([rules.assess(HIT, cfg.policy)], cfg.policy)[0]
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


def test_am4_floor_setting_is_validated(tmp_path: Path):
    path = tmp_path / "search.toml"
    path.write_text(config.DEFAULT_FILE.read_text(encoding="utf-8").replace("am4_min_ram_gb = 32", "am4_min_ram_gb = 20"),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="am4_min_ram_gb"):
        config.load(path)


def test_settings_save_keeps_comments_and_refuses_bad_values(tmp_path: Path):
    path = tmp_path / "search.toml"
    path.write_text(config.DEFAULT_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = config.save({"search.ask_min_eur": 250, "search.broad_terms": ["PC", "Rechner"],
                       "bundles.enabled": False}, path)
    assert cfg.ask_min == 250 and cfg.broad_terms == ("PC", "Rechner") and not cfg.bundles_enabled
    text = path.read_text(encoding="utf-8")
    assert "ask_min_eur = 250             # asking price range searched" in text
    with pytest.raises(ValueError, match="ask_min_eur"):
        config.save({"search.ask_min_eur": 5000}, path)
    assert config.load(path).ask_min == 250 and not list(tmp_path.glob("*.tmp.toml"))


def test_progress_counts_unique_listings():
    seen = []
    p = deals.Progress(seen.append)
    p.found([{"id": "1"}, {"id": "2"}])
    p.found([{"id": "2"}, {"id": "3"}])
    p.detail(1, 5)
    assert seen[-1] == {"found": 3, "details_done": 1, "details_total": 5}


def _saved_run(tmp_path: Path, rows: list[dict]) -> Path:
    folder = tmp_path / "2026-11-20_120000"
    folder.mkdir()
    (folder / "raw.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (folder / "run.json").write_text(json.dumps({"stats": {"terms": {"3060": 2}}}), encoding="utf-8")
    return folder


def test_reevaluate_applies_new_rules_without_api(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(deals, "STATE_FILE", tmp_path / "seen.json")
    am4 = {**HIT, "id": "5", "title": "Ryzen 7 5700X RTX 3060 12GB 16GB DDR4 B550", "attributes": {}}
    folder = _saved_run(tmp_path, [{**HIT, "attributes": {}}, am4])
    cfg = config.load()
    strict = deals.reevaluate(folder, cfg)
    assert [r["ad_id"] for r in strict["passed"]] == ["1"] and strict["stats"]["rejects"] == {"ddr4_under_32gb": 1}
    loose = deals.reevaluate(folder, config.Config(**{**cfg.__dict__, "policy": rules.Policy(am4_min_ram=16)}))
    assert {r["ad_id"] for r in loose["passed"]} == {"1", "5"} and loose["stats"]["review_of"] == folder.name


def test_saved_full_text_is_reused_only_at_the_same_price():
    cached = {**HIT, "attributes": {}, "_fetched_at": "2026-11-23T10:00:00"}
    assert deals.reusable(HIT, cached)
    assert not deals.reusable({**HIT, "price_amount": 600}, cached)
    assert not deals.reusable(HIT, None)


def test_reuse_skips_the_api_call(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "main", types.SimpleNamespace(mcp=None))
    monkeypatch.setitem(sys.modules, "mcp", types.SimpleNamespace(Client=FakeClient))
    cfg = config.load()
    cfg = config.Config(**{**cfg.__dict__, "terms": ("3060",), "broad_terms": (), "bundles_enabled": False, "delay_s": 0})
    import asyncio
    cache = {"1": {**HIT, "attributes": {"Versand": "Versand möglich"}, "_fetched_at": "2026-11-23T10:00:00"}}
    result = asyncio.run(deals.scan(cfg, cache=cache))
    assert result["stats"]["reused"] == 1 and result["stats"]["details"] == 1   # only the uncached "7"
    assert result["passed"][0]["ships"]                                          # the saved text was used


def test_rules_changed_from_the_brief_are_listed():
    from policy import deviations
    text = " ".join(deviations(rules.Policy(am4_min_ram=16, price_basis="list", pickup_only="drop")))
    assert "from 16 GB RAM" in text and "Intel judged case by case" in text and "exceed the limit" in text
    assert "under 650 W" in text and "list price" in text and "pickup-only listings dropped" in text
    assert "only when the listing confirms" in text
    assert "Intel judged" not in " ".join(deviations(rules.Policy(allow_intel=False)))


def test_results_tab_groups_and_rule_counts():
    import ui_results
    import ui_rules
    good = rules.finalize([rules.assess(HIT)])[0]
    miss = rules.assess({**HIT, "id": "2", "price_amount": 840, "price_type": "FIXED"})
    junk = rules.assess({**HIT, "id": "3", "price_amount": 5})
    sections = [s for s, _ in ui_results.group([good, miss, junk])]
    assert sections == ["Featured", "Closest misses", "Filtered"]
    assert "Rejected: placeholder_price" in ui_results.details(junk)
    assert ui_rules.reject_count({"am4_under_32gb": 4, "intel_platform": 9}, "am4_under_") == 4
