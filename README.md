# Kleinanzeigener

Finds used PCs on Kleinanzeigen.de for one goal, a local AI coding agent plus gaming on an upgradeable platform,
and judges every listing by the Deal Evaluation Brief in `Target.md`. The program does the bulk filtering and
pricing. A final AI pass, primed by the files it writes, picks the deal and drafts the seller messages.

## Requirements

- Windows, Python 3.11+ (standard library only; `pytest` for the tests).
- The `kleinanzeigen-mcp` server checked out locally, at the path in `deals.py` (`MCP_DIR`). Searches run it
  in-process. Re-evaluation, price calibration and the tests need no server and make no API calls.

## Start

Double-click `launch.bat` (or `python deals.py` for a console run with `search.toml` as is).

| Tab | What it does |
|---|---|
| Settings | `search.toml` as fields: home, budget, price range, request limits, search terms. **Save and start search**. |
| Selection rules | What passes: price basis (list / effective), DDR4 floor, VRAM minimum, Intel, pickup-only, scam signals, fix costs, PSU wattage, under/overpriced thresholds. Each rule shows how many listings it drops. **Save rules and re-evaluate** re-judges a saved run offline in seconds. |
| Run | Live counter and log. |
| Results | Any run as a table (underpriced, featured, passing, bundles, special cases, closest misses, filtered) with the full card and listing text. **Copy AI prompt**, **Copy price prompt**. |

## Workflow

1. **Search** (Settings tab). Writes `runs/<date_time>/`, a complete dataset. Repeat searches within a week reuse
   saved listing text, so they cost far fewer API calls.
2. **Tune the rules** (Selection rules tab) and re-evaluate the saved run. No new search needed.
3. **Calibrate prices** (optional, recommended). On the Results tab, select a run and press **Copy price
   prompt**. Give it to an agent, which fits used part prices to that run's `components.csv` by hand. It then
   sanity-checks them against expectations and writes `prices.toml`. Re-evaluate: every listing gets a fair
   price, and the underpriced ones (likely good deals) are flagged and listed first. Part prices the check found
   off, conflicting or thin are marked ⚠ on every listing that uses them.
4. **AI pass.** On the Results tab, press **Copy AI prompt** and give it to an AI. It verifies the shortlist
   against the listing text, picks one, and writes the seller messages.

## How a listing is judged

1. **Parse** title and description into parts (GPU + VRAM, CPU, platform, chipset, RAM, PSU, SSD, cooler, case).
   Each part is either stated or assumed, and conflicts are flagged, not guessed.
2. **Hard rejects** from the Brief (under 12 GB VRAM, AM4 below the RAM floor, old Intel, defects, scams,
   misprices …), each one switchable.
3. **Prices:** the list price, the effective price (VB haggle + confirmed fixes) and the worst price (+ the fixes
   the listing leaves open). The limits use the price basis you choose.
4. **Tier** by day-one AI capability, then upgrade headroom, then price. Intel is judged case by case: AVX-512
   and the dead socket count only where they matter, and the cost of an AM5 swap is compared.
5. **Feature** the best listings. Listings with open questions are featured only when the deal is good, and
   underpriced ones always are.

## Files

| Path | Contents |
|---|---|
| `Target.md` | The Deal Evaluation Brief: the binding rules |
| `search.toml` | All settings (edited by the Settings and Selection rules tabs) |
| `prices.toml` | Fair used part prices, written by the calibration agent (absent until the first calibration) |
| `prompts/ai_pass.md` | Priming for the final AI pass |
| `prompts/price_calibration.md` | The price-calibration procedure, the sanity check and the exact `prices.toml` shape |
| `runs/<date_time>/` | `results.md`, `ai_prompt.md`, `listings.jsonl`, `raw.jsonl`, `components.csv`, `run.json` |
| `WORK_REPORT.md` | Full reference: every rule, flag, output file, code module, safeguard and known limit |

Code: `config.py` / `policy.py` (settings), `text.py` / `parse.py` (text → parts), `hardware.py` (component
knowledge), `rules.py` (the Brief as code), `prices.py` (fair prices), `deals.py` (search pipeline), `report.py`
(run folder), `ui*.py` (window).

## Tests

```powershell
python -m pytest -q
```

Offline: no searches and no API calls.
