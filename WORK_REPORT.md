# Kleinanzeigen AI/Workstation PC Search — Work Report (v3)

Finds used PCs on Kleinanzeigen.de and judges them by the Deal Evaluation Brief (`Target.md`), then writes
everything a final AI pass needs into one dated folder.

## Use

Double-click `launch.bat`. Four tabs:

1. **Settings:** `search.toml` as editable fields (home, budget, price range, limits, full text, reuse, bundles,
   the three term lists). **Save and start search** validates, saves (comments kept) and runs a new search.
2. **Selection rules:** what gets discarded (AM4 RAM floor, VRAM minimum, Intel / Arc / 8500G / small cases /
   OEM / mini-PCs on or off, mispricing share, scam signals) and the fix costs. Each rule shows how many listings
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
| `results.md` | Report in Priming Brief §9 order: A pick, B shortlist (+ relevant listing text), B2 bundles, C seller questions (top 5 only), D special cases, E market notes, F search log, G closest misses |
| `ai_prompt.md` | `prompts/ai_pass.md` (priming) + `Target.md` (binding rules) + `results.md` |
| `listings.jsonl` | Every assessed listing: parsed build with stated/assumed source per part, fixes, effective price, tier, verdict |
| `raw.jsonl` | Raw search hit + full detail per listing |
| `run.json` | Settings snapshot + run stats |

`runs/seen.json` remembers ids and prices between runs (flags `new_since_last_run`, `price_drop_from_X`).

## Code

| File | Role |
|---|---|
| `search.toml` / `config.py` | Settings; validated at load, every bad field reported at once; form saves are validated before the file is replaced |
| `policy.py` | Every knob that decides what passes (budget, rules, fixes) and the list of changes from the Brief |
| `text.py` | Shared primitives: clauses (spec lines), `Label:` lines, "not installed" context (limits, support notes, history), negation |
| `parse.py` | Text → parts: GPU + VRAM twins, CPU/platform, chipset, RAM size/layout/DDR, PSU, cooler, SSD, case, text rejects |
| `hardware.py` | Brief §1/§4 component knowledge: GPU cards (used value, PCIe lanes/gen, Brief note), PCIe link, upgrade headroom, parts-value floor |
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
- **Conflicts.** Title and description disagreeing (e.g. 32 vs 16 GB, two GPUs) mark the part assumed and
  add a `conflict_*` flag and a seller question; the listing is not dropped.
- **Assumptions decide price, not rejection** (Priming §6.2), and every assumed value shows `(?)`.

## Ranking and featuring

- **AM4 RAM floor** (`rules.am4_min_ram_gb`, default 32; the Brief's is 64). AM4 builds below 64 GB pass as
  tier 5, ranked after everything else, under the normal limit.

- **Needs answers ranks lower.** A listing whose GPU VRAM, CPU/platform or RAM size is unknown or contradicted
  ranks below clear listings of its tier, and is featured (shortlist, cards, seller message) only when the deal
  is good: tier 0-1 or effective at or under the target. Other unknowns are priced at their worst case instead.
- **Tier 3 (16 GB)** is featured only if effective + 490 € RAM still beats the best tier 0-2 PC.
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

- Fix costs and GPU/RAM prices in `rules.py` are the Brief's estimates; adjust them as prices move.
- The case is shown, never priced, for PCs (no reliable data without photos); bundles get a case fix if none is named.
- No images are read; the AI pass or the seller questions settle what only photos show.
