# Kleinanzeigen Deals Engine — Work Report (v2)

**Files:** `deals.py` (engine, ~520 lines), `test_deals.py` (60 offline tests), `deals_v1_backup.py` (previous version)
**MCP server:** `C:\Users\Samuel\.config\opencode\mcp\kleinanzeigen-mcp` (run in-process)

```bash
python deals.py
python -m pytest -q test_deals.py
```

## Pipeline

| Step | What happens |
|---|---|
| 1. Discover | Searches category **228 "PCs"** (no bare GPUs or parts), `ad_type=OFFERED`, newest first. Budget split into 6 geometric price bands; pages are fetched **round-robin across bands**, so the 90-request budget covers the whole range. |
| 2. Dedupe | By ad id, then reposts (same seller + same title → keep the cheapest). |
| 3. Parse (snippet) | GPU (≈70 models: RTX 20–50, GTX 10/16, RX 5000–9000, Arc), CPU (Intel gen + tier, Core Ultra, Ryzen series + tier, X3D) and RAM, all regex-based with word boundaries. A bare GPU number needs its brand word (blocks "OptiPlex 5090"); VRAM isn't counted as RAM. |
| 4. Filter | Exclusions: laptops/Macs, wanted ads, trade-only, bastler, defekt (negation-aware: "nicht defekt" passes), "ohne Grafikkarte"/"GPU nicht enthalten", standalone GPU ads, GPUs below `MIN_GPU_PERF`, and "nur Abholung"/"Selbstabholer" in the description text. |
| 5. Value | Parts value = used GPU + CPU + RAM (capped at 32 GB) + €120 base. |
| 6. Deal score | Value/price ÷ the **median value/price of comparable listings in the same scan** (same GPU, else same performance bracket). 1.0 = typical, 1.5 = 50% better than peers. Self-calibrating: high-end PCs aren't penalised for the market's higher asking prices. |
| 7. Details | Full `get_ad_detail` only for the top 60 + 40 "gaming" listings whose GPU wasn't in the snippet. Re-parses the full text and adds Zustand, Versand and seller rating. |
| 8. Output | `ka_run_<ts>/digest.md` (LLM prompt + filled top-25 table, ready to paste), `deals.jsonl` (all scored), `digest.json` (stats + market medians). |
| 9. State | `seen.json` records ids and prices, so later runs flag `new` and `price_drop_from_X`. |

Flags per listing: `vb`, `ships`, `commercial`, `too_cheap_check` (<55% of same-GPU median), `offplatform_payment`, `gpu_from_description`, `cpu_unknown`, `ram_unknown`, `ram_under_16gb`, `new`, `price_drop_*`.

## API facts found while building (from live checks)

- Search hits only have a ~230-character description snippet, and their `ships` field is always false. Full text and the `Versand` attribute come from detail fetches only.
- The `pcs.versand` attribute filter is broken: `ja` returns 0 results, `nein` returns everything. The `pcs.condition` filter drops ads with no condition set, so it isn't used.
- Nearly every PC listing has `Versand: Nur Abholung`. Filtering on that field would remove ~90% of listings, so pickup exclusion uses the description text only (as originally specified). Setting `HOME_ZIP` instead searches only locally, with pickup allowed.

## Latest run (€300–1500, nationwide)

90 searches → 2,653 unique listings → 1,032 candidates → 100 details → 0 errors.
Top results span the budget: e.g. RTX 3070 PC €500 (1.60), RTX 4060 Ti + i7-14700KF €900 (1.52), RTX 3080 Ti + i7-10700KF €900 (1.42).

## Known limits

- The price tables (GPU/CPU used €, perf index) are hand estimates. Thanks to the peer-relative score, only the relative values between models matter much. Adjust them when the market moves.
- A listing with no GPU named in its title or snippet only gets a second chance if it reads as "gaming" (capped at 40 per run).
- CPUs written without a model number ("i7 8. Gen") get tier-only pricing.
- Scores rank against asking prices, not sold prices. The LLM audit step (digest.md) is still the final judge.
