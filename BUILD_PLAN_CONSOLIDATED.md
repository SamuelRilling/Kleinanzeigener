# Kleinanzeigen Deals Engine — Consolidated Build Plan

## Goal
One standalone Python file (`deals.py`) that scans Kleinanzeigen for gaming PC deals end-to-end with no input after launch, and outputs a pre-digested JSONL for an LLM to study.

## Design (ponytail rules applied)
- **One file.** `deals.py` only. No `mcp_client.py`, `extractor.py`, `comps.py`, `verifier.py`, `reporter.py`.
- **No argparse.** Initial conditions are hardcoded constants at the top of the file.
- **In-process MCP client.** `Client(_ka_main.mcp)` — stdio subprocess is blocked by sandbox.
- **Stdlib only.** `argparse` removed; `json`, `statistics`, `asyncio`, `pathlib`, `datetime` suffice.
- **Pre-digested output.** `digested.jsonl` (one JSON object per deal) + `digest.json` (run summary). No markdown fluff.
- **Dedup by `ad_id`.** Across all combos before detail fetch.
- **Fatal exclusions.** `ohne GPU`, `ohne Grafikkarte`, `defekt`, `wanted`, `laptop`, accessory-only — logged, not silently dropped.

## File: `deals.py`

### Constants (edit here to change scope)
```python
BUDGET_MIN = 300
BUDGET_MAX = 1500
MAX_REQUESTS = 200      # scan budget
PAGES_PER_COMBO = 5     # deeper scan
DELAY = 0.4             # polite delay between requests
BANDS = [(0,400),(400,600),(600,800),(800,1100),(1100,1500),(1500,10**9)]
QUERIES = ["Gaming PC","Gaming Computer","Komplett PC","RTX","RX","Ryzen","i7 Gaming","i9 Gaming"]
SORTS = ["RECOMMENDED","PRICE_ASCENDING","DATE_DESCENDING"]
```

### Pipeline (9 steps, one file)
1. **Connect** — `Client(_ka_main.mcp)`, list tools.
2. **Discover** — band × query × sort, up to `PAGES_PER_COMBO` pages each, stop when <10% new IDs for 2 pages or cap hit. Dedup by `ad_id` as we go.
3. **Prefilter** — budget band, drop obvious non-targets (wanted, defekt, laptop, accessory) using title keywords.
4. **Detail fetch** — `get_ad_detail` for every survivor, 0.4s delay, checkpointed.
5. **Extract** — title, price, location, gpu_model (from title), cpu, ram_gb, storage, condition, verbatim quotes for GPU/price/status.
6. **Fatal exclusions** — `ohne GPU`, `gpu_included=no`, not complete PC — excluded with reason logged.
7. **Savings calc** — `savings_pct = (1 - price / list_price) * 100` per GPU variant from `LIST_PRICES`.
8. **Sort** — by savings_pct descending, no-list-price refs last.
9. **Output** — `digested.jsonl` (one JSON per deal, LLM-ready) + `digest.json` (run stats, excluded counts, top 20).

### Output format
`digested.jsonl` — one line per deal:
```json
{"ad_id":"3568610954","url":"...","title":"Gaming PC RTX 3080...","price":849,"location":"Gaggenau","gpu_model":"RTX3080","cpu":"i7-11700K","ram_gb":32,"storage":"1TB SSD","savings_pct":18.0,"vet_flags":["high_gap_unverified"],"search_combo":"band=300-400|query=Gaming PC|sort=RECOMMENDED|page=0"}
```

`digest.json`:
```json
{"run_time":"...","budget":[300,1500],"requests":120,"hits":450,"survivors":300,"excluded":{"no_gpu":12,"defekt":5,"wanted":3},"top_20":[...]}
```

### Not included (out of scope, ponytail)
- No photo review (`get_ad_images`) — host vision dependent.
- No seller info (`get_seller_info`) — partial from datacenter IPs.
- No cross-marketplace adapter.
- No packaging, no CLI, no tests, no persistent infra.

### Effort
~2 hours, ~200 lines single file.

## Approval
Ready to implement. Edit `deals.py` in place.