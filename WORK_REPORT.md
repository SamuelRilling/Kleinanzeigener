# Kleinanzeigen AI/Workstation PC Search — Work Report (v3)

Finds used PCs on Kleinanzeigen.de and judges them by the Deal Evaluation Brief (`Target.md`), then writes
everything a final AI pass needs into one dated folder.

## Use

Double-click `launch.bat`. Four tabs:

1. **Settings:** `search.toml` as editable fields (home, budget, price range, limits, full text, reuse, bundles,
   the three term lists). **Save and start search** validates, saves (comments kept) and runs a new search.
2. **Selection rules:** which price the limits use (effective or list), what gets discarded (DDR4 RAM floor, VRAM
   minimum, Intel judged or dropped, Arc / 8500G / small cases / OEM / mini-PCs on or off, pickup-only listings
   keep / local only / drop, mispricing share, scam signals), the PSU wattage below which a fix counts, and the fix
   costs. Each rule shows how many listings
   it drops in the chosen saved run. **Save rules and re-evaluate** judges that saved run again with no search and
   no API calls (seconds), into `runs/<date_time>_review/`.
3. **Run:** live counter (listings found, full listings read) and log.
4. **Results:** any run as a table (featured, passing, bundles, special cases, closest misses, filtered).
   Selecting a row shows its card and full listing text with clickable links; double-click opens the listing.
   **Copy AI prompt** puts `ai_prompt.md` on the clipboard.

Search order: local sweep, specific terms, bundles, then the broad terms ("PC", "Rechner", …) last.
Console alternative: edit `search.toml`, then `python deals.py`.

## Saved data and updates

- **Every run folder is a dataset.** `raw.jsonl` holds every listing found, merged with its full text.
  `full_text_all = true` reads the full text of every listing, so any rule can be loosened later offline.
- **Re-evaluation** (Selection rules tab) applies the current rules to a saved dataset. It cannot see
  listings sold or posted since that search, or listings outside its price range and terms.
- **Updates instead of rescraping:** a new search always runs the searches (they find new listings, price
  changes and removals), but reuses the saved full text of a listing with the same id and price read within
  `reuse_days` (default 7). Full-text fetches were about 75 % of a run's API calls, so a repeat run within the
  week needs only the searches plus the new or changed listings. Listings missing from the new search drop out.

Tests (offline, no searches): `python -m pytest -q`

## Output: `runs/<date_time>/`

| File | Contents |
|---|---|
| `results.md` | Report in Priming Brief §9 order: A pick, B0 underpriced, B shortlist (+ relevant listing text), B2 bundles, C seller questions (top 5 only), D special cases, E market notes, F search log, G closest misses |
| `ai_prompt.md` | `prompts/ai_pass.md` (priming) + `Target.md` (binding rules) + `results.md` |
| `listings.jsonl` | Every assessed listing: parsed build with stated/assumed source per part, fixes, effective price, tier, verdict |
| `raw.jsonl` | Raw search hit + full detail per listing |
| `run.json` | Settings snapshot + run stats |
| `components.csv` | Each listing's GPU / CPU / RAM / board in the price table's names: price calibration data |

`runs/seen.json` remembers ids and prices between runs (flags `new_since_last_run`, `price_drop_from_X`).

## Code

| File | Role |
|---|---|
| `search.toml` / `config.py` | Settings; validated at load, every bad field reported at once; form saves are validated before the file is replaced |
| `policy.py` | Every knob that decides what passes (budget, rules, fixes) and the list of changes from the Brief |
| `text.py` | Shared primitives: clauses (spec lines), `Label:` lines, "not installed" context (limits, support notes, history), negation |
| `parse.py` | Text → parts: GPU + VRAM twins, CPU/platform, chipset, RAM size/layout/DDR, PSU, cooler, SSD, case, text rejects |
| `hardware.py` | Brief §1/§4 component knowledge: GPU cards (used value, PCIe lanes/gen, Brief note), PCIe link, upgrade headroom, parts-value floor |
| `prices.py` | Fair-price table (`prices.toml`): shape check, part names, fair price per listing, components.csv |
| `rules.py` | The Brief as code: hard rejects, price sanity, fix ledger → effective price, RAM path, tiers, tie-breakers, needs-answers ranking, featuring, special cases, bundle track, risk signals, seller questions |
| `prompts/ai_pass.md` | The AI-pass priming: goal, user, market, how the program works and where it is weak, what to do, answer format |
| `deals.py` | Search, dedupe, full-text fetch with reuse, pure evaluation, re-evaluation of saved runs |
| `report.py` | Run folder writer and launcher summary |
| `ui.py` / `ui_rules.py` / `ui_results.py` / `ui_form.py` / `launch.bat` | Tkinter launcher (stdlib): settings, selection rules, run, results tabs |

## How parsing stays robust

- **Clauses and labels.** Text is split into spec lines; a `Grafikkarte:` / `Netzteil:` / `RAM:` line beats the
  title, the title beats loose text. Wattage is read only from PSU lines and never right after a GPU/CPU name.
- **Not-installed context.** "erweiterbar auf 64GB", "max. 128GB", "Ryzen 9000 ready", "vorher GTX 1060" are
  skipped; "B450 Tomahawk MAX, 32GB" is not mistaken for a limit.
- **Negation.** "kein Netzteil", "ohne SSD" become missing parts (priced as fixes); "nicht defekt" passes.
- **Intel CPUs** are read to the model: i5-13600KF → 13th gen, Core Ultra 7 265K → LGA1851. "i5 9400F" is not
  mistaken for a Ryzen. A bare "i7" gets the oldest generation its board allows, else 12th (flagged, asked).
- **Pickup only.** "nur Abholung", "kein Versand", "Selbstabholer", "wird nicht versendet" or the listing's
  `Versand: Nur Abholung` set `pickup_only`.
- **Conflicts.** Title and description disagreeing (e.g. 32 vs 16 GB, two GPUs) mark the part assumed and
  add a `conflict_*` flag and a seller question; the listing is not dropped.
- **Assumptions decide price, not rejection** (Priming §6.2), and every assumed value shows `(?)`.

## Prices

- **List €** (the ask), **Effective €** (VB haggle + confirmed fixes) and **Worst €** (+ the fixes the listing
  leaves open) are shown everywhere. `budget.price_basis` picks which one the limits, target and ranking use.
- **Fixes count only when confirmed:** no PSU / a stated PSU under `fixes.psu_min_w` (650 W; 850 W for 24 GB
  cards), no SSD / under 1 TB, a stated stock cooler on a hot CPU. A PC sold as working that does not mention a part
  has one: flagged (`psu_unstated`, `psu_brand_unknown`, `ssd_unstated`, `cooler_unstated`, …) and in Worst € only.
  This changes the Brief, which counts every unconfirmed part, and is listed in every report.

## Fair prices (hand-calibrated)

- An agent runs `prompts/price_calibration.md` ("Copy price prompt" on the Results tab points it at the selected
  run) and writes `prices.toml`: used € per GPU, CPU, RAM amount and board, plus a whole-PC factor and a base for
  the small parts. The prompt fixes the file's shape; `prices.py` validates it at load.
- Procedure in the prompt: seed at 70 % of today's new price (RAM 85 %), then refit round by round: each listing's
  error is shared among its parts by value, each part moves to the median of its implied prices, shrunk toward
  its seed (weight 5 listings), halfway per round, outliers > 60 % excluded, every fifth listing held out to
  measure the error.
- Every run writes `components.csv`: each listing's parts in the table's names, the calibration data.
- With a table, every listing gets **Fair €** and **Δ**. `prices.underpriced_pct` (15) and `overpriced_pct` (20)
  set the `underpriced_…` / `overpriced_…` flags, only when GPU, CPU and RAM were stated. Flags only: nothing is
  dropped. Underpriced listings get section B0 and the Results tab's first group, and are featured even when they
  need seller answers.
- After the fit the agent sanity-checks every key against expectations (used/new ratio, depreciation by age, family
  order, spread, the rows' own text) and marks it `ok` / `off` / `conflict` / `missing` with a note, plus data-level
  `meta.warnings`. Listings relying on a flagged price get `fair_price_doubtful` and a ⚠ in B0; warnings show above B0.
- VB listings: expected price = the fair price when it is below the usual haggle, but at most 15 % off the ask.

## Ranking and featuring

- **DDR4 RAM floor** (`rules.am4_min_ram_gb`, default 32; the Brief's is 64 for AM4). Applies to AM4 and to Intel
  with stated DDR4. AM4 builds below 64 GB pass as tier 5, ranked after everything else.
- **Intel, case by case** (`rules.allow_intel`, default on; the Brief rejects all Intel):
  - 10th gen and older: rejected (PCIe 3.0, no AVX-512, slow DDR4).
  - No AVX-512 counts only while the day-one model's experts spill to the CPU (experts + 1 GB reserve > VRAM).
    For this model that is nearly always the case; 11th gen has AVX-512.
  - The dead socket counts only under a CPU that is not already strong (i5-13600K/14600K+, 11th-14th gen i7/i9,
    Core Ultra 5 245+ / 7 / 9).
  - Neither: tiered like AM5. One: tier 4. Both: tier 5.
  - AM5 swap per Intel PC: used B650 120 € + Ryzen 5 7600 140 € (+ DDR5 for DDR4) minus the Intel board + CPU
    resale (estimates in `rules.py`), compared with the best AM5 deal of the run.
  - 13th/14th gen i7/i9 and i5-x600 get a BIOS/microcode question (Vmin instability).

- **Needs answers ranks lower.** A listing whose GPU VRAM, CPU/platform or RAM size is unknown or contradicted
  ranks below clear listings of its tier, and is featured (shortlist, cards, seller message) only when the deal
  is good: tier 0-1 or the budget price at or under the target. Other unknowns are flagged and in Worst €.
- **Tier 3 (16 GB)** is featured only if its price + 490 € RAM still beats the best tier 0-2 PC.
- **Pickup only** (`rules.pickup_only`): keep with a flag (default), keep only local ones, or drop.
- **Price sanity.** Placeholder prices, prices stated for one part ("Preis gilt nur für die Grafikkarte",
  "pro Stück"), and asks below half of the stated GPU + RAM value are filtered and listed in section H.
- **System view per listing:** PCIe link (weakest of CPU, slot, card), headroom for the next GPU and RAM, and the
  Brief's note on the card.
- **Seller questions** merge into one CPU-Z/GPU-Z screenshot request when 2+ core parts are unknown, and a PSU
  label photo instead of "which PSU?".

## Pipeline safeguards

- Full listings are fetched best-ranked first, so the `max_details` cap drops the weakest; skips are counted.
- Reposts: same seller + title, or same seller + price + opening text, keep the cheapest.
- More than 20 % failed detail fetches marks the run **INCOMPLETE** in the report and summary.
- `seen.json` is written atomically and a corrupt file starts fresh instead of crashing.
- Rate limits: the MCP server already retries 429/5xx with backoff.

## API facts (from earlier live checks)

- Search hits carry a ~230-character description snippet; full text, `Versand` and seller rating come from
  detail fetches only.
- The `pcs.versand` attribute filter is broken; shipping is read from the detail's `Versand` attribute.
- Seller profiles (account age) return 403 from some IP ranges; the listing's seller rating is used instead.

## Known limits

- Fix costs and GPU/RAM prices in `rules.py` are the Brief's estimates; adjust them as prices move. The AM5-swap
  and Intel resale figures and the 1 GB VRAM reserve are estimates too.
- Intel's strong-CPU list and AVX-512 by generation are fixed in `hardware.py`, not settings.
- The case is shown, never priced, for PCs (no reliable data without photos); bundles get a case fix if none is named.
- No images are read; the AI pass or the seller questions settle what only photos show.
