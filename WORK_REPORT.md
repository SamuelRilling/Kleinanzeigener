# Kleinanzeigen AI/Workstation PC Search — Work Report (v3)

Finds used PCs on Kleinanzeigen.de and judges them by the Deal Evaluation Brief (`Target.md`), then writes
everything a final AI pass needs into one dated folder.

## Use

1. Edit `search.toml` (home, budget, price range, search terms, limits, bundle track, AI prompt files).
2. Double-click `launch.bat`: the window shows the settings, **Confirm and start search** runs it in the
   same window with a live log, then shows a summary and **Open results**.
   Console alternative: `python deals.py`.
3. Paste `runs/<date_time>/ai_prompt.md` into the AI.

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
| `search.toml` / `config.py` | Settings; validated at load, every bad field reported at once |
| `text.py` | Shared primitives: clauses (spec lines), `Label:` lines, "not installed" context (limits, support notes, history), negation |
| `parse.py` | Text → parts: GPU + VRAM twins, CPU/platform, chipset, RAM size/layout/DDR, PSU, cooler, SSD, case, text rejects |
| `hardware.py` | Brief §1/§4 component knowledge: GPU cards (used value, PCIe lanes/gen, Brief note), PCIe link, upgrade headroom, parts-value floor |
| `rules.py` | The Brief as code: hard rejects, price sanity, fix ledger → effective price, RAM path, tiers, tie-breakers, needs-answers ranking, featuring, special cases, bundle track, risk signals, seller questions |
| `prompts/ai_pass.md` | The AI-pass priming: goal, user, market, how the program works and where it is weak, what to do, answer format |
| `deals.py` | Search (local sweep + terms + bundles), dedupe, snippet triage, best-first detail fetch, run |
| `report.py` | Run folder writer and launcher summary |
| `ui.py` / `launch.bat` | Tkinter launcher (stdlib) |

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
