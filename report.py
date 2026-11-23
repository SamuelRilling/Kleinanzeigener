"""Scan result -> runs/<date_time>/:
    results.md      human-readable report, Priming Brief §9 order
    ai_prompt.md    static AI instructions (prompts/ai_pass.md) + attached rules + results.md
    offer_prompt.md / performance_prompt.md   the same with prompts/best_offer.md / best_performance.md
    listings.jsonl  every assessed listing (parsed build, fixes, verdict)
    components.csv  every listing's parts in the price table's names: data for price calibration
    raw.jsonl       raw search hit + full detail per fetched listing
    run.json        settings snapshot + run stats
Everything computable is already computed, so the AI pass only verifies, judges and writes."""
import dataclasses
import json
import re
import statistics
from datetime import datetime
from pathlib import Path

import prices
import rules
from policy import Policy, deviations
from text import CLAUSE_SPLIT_RE

# Comparison passes: run-folder file <- prompt file next to the main AI prompt.
EXTRA_PROMPTS = {"offer_prompt.md": "best_offer.md", "performance_prompt.md": "best_performance.md"}

SHORTLIST = 10        # featured listings shown with a card and full text
BUNDLES_SHOWN = 5
QUESTIONS_TOP = 5     # seller messages only for featured listings that need answers
NOT_FEATURED_SHOWN = 15
CLOSEST_MISSES = 5
FILTERED_SHOWN = 8
FULL_TEXT_CHARS = 2500
EXCERPT_CHARS = 400
SHAPE_MIN_SAMPLES = 3
MISPRICE_REJECTS = ("placeholder_price", "price_not_for_whole_pc", "price_below_parts_value", "scam_signals")
# Clauses worth showing in a one-line excerpt: parts, condition, logistics, payment, receipt.
RELEVANT_RE = re.compile(
    r"gpu|grafik|rtx|gtx|radeon|\brx\b|ryzen|intel|cpu|prozessor|ram|arbeitsspeicher|ddr|gb|tb|ssd|nvme|m\.2|"
    r"netzteil|psu|watt|\d\s*w\b|mainboard|board|b650|x670|b550|kühl|gehäuse|zustand|defekt|garantie|rechnung|"
    r"versand|abhol|paypal|überweis|whatsapp|mining|raucher|preis|vb|festpreis|tausch", re.I)


def _q(text: str, src: str) -> str:
    return f"{text} (?)" if src == "assumed" else text


def build_cells(r: dict) -> dict:
    b = r["build"]
    gpu, cpu, psu, st = b["gpu"], b["cpu"] or {}, b["psu"]["v"], b["storage"]["v"]
    sticks, per = b["ram_layout"]["v"]
    ddr = f"DDR{b['ddr']}" if b["ddr"] else "DDR?"
    psu_txt = "none" if psu.get("missing") else f"{psu['watts'] or '?'} W {'trusted' if psu['trusted'] else 'brand?'}"
    ssd = "none" if st.get("missing") else f"{'NVMe' if st['nvme'] else 'SATA?'} {st['gb'] or '?'} GB"
    gpu_txt = f"{gpu['name']} {gpu['vram']} GB" + (" (to buy)" if gpu.get("to_buy") else "") if gpu else "none"
    return {
        "cpu": _q(f"{cpu.get('label', '?')} [{b['platform']['v'] or '?'}]", b["platform"]["src"]),
        "board": b["chipset"] or "? (?)",
        "ram": _q(f"{b['ram_gb']['v']} GB {ddr} ({sticks}×{per})",
                  "assumed" if "assumed" in (b["ram_gb"]["src"], b["ram_layout"]["src"]) else "stated"),
        "gpu": _q(gpu_txt, "stated" if gpu and gpu["vram_stated"] and "gpu" not in b["conflicts"] else "assumed"),
        "psu": _q(psu_txt, b["psu"]["src"]),
        "cooler": _q(b["cooler"]["v"], b["cooler"]["src"]),
        "case": b["case"]["name"] or "? (?)",
        "ssd": _q(ssd, b["storage"]["src"]),
    }


def where(r: dict) -> str:
    place = f"{r['location'] or '?'} {r['zip'] or ''}".strip()
    ship = "nur Abholung" if r.get("pickup_only") else "Versand" if r["ships"] else "Abholung"
    return f"{place} · {'local' if r['local'] else 'far'} · {ship}"


def ask_txt(r: dict) -> str:
    return f"{r['ask']:g} € VB→{r['price']}" if r["vb"] else f"{r['ask']:g} €"


def fixes_txt(r: dict) -> str:
    """Counted fixes, then the ones the listing leaves open (worst case only)."""
    sure = " + ".join(f"{k} {v}" for k, v in r["fixes"].items()) or "0"
    maybe = " + ".join(f"{k} {v}" for k, v in r.get("maybe_fixes", {}).items())
    return sure + (f" (unconfirmed: {maybe})" if maybe else "")


def eff_txt(r: dict) -> str:
    worst = r.get("worst", r["effective"])
    return f"{r['effective']}" + (f" (worst {worst})" if worst != r["effective"] else "")


def fair_txt(r: dict) -> str:
    """Fair price line for cards; empty without a price table."""
    if r.get("fair"):
        parts = " + ".join(f"{p} {e}" for p, e in r["fair_parts"].items())
        sign = "+" if r["fair_delta"] >= 0 else "−"
        trust = "" if r["fair_stated"] else " (parts partly assumed: not judged)"
        trust += f" · ⚠ price check: {'; '.join(r['fair_doubts'])}" if r.get("fair_doubts") else ""
        tag = {"under": " · **underpriced**", "over": " · overpriced"}.get(r["value"], "")
        return f"- Fair price ≈ {r['fair']} € ({parts}, table factor and base) · ask {sign}{abs(r['fair_delta']):.0%}{tag}{trust}"
    if r.get("fair_missing"):
        return f"- Fair price: not in the price table ({'; '.join(r['fair_missing'])})"
    return ""


def delta_txt(r: dict) -> str:
    return "—" if r.get("fair_delta") is None else f"{r['fair_delta']:+.0%}"


def intel_txt(r: dict) -> str:
    """Intel facts and the AM5 alternative, for cards; empty for other platforms."""
    i = r["build"].get("intel")
    if not i:
        return ""
    on_cpu = rules.experts_on_cpu(r["build"])
    avx = "AVX-512 ✓" if i["avx512"] else (f"no AVX-512, {on_cpu} GB of experts on the CPU" if on_cpu
                                         else "no AVX-512, but the model fits in VRAM")
    best = f" (best AM5 deal here: {r['best_am5']} €)" if r.get("best_am5") is not None else ""
    return (f"- Intel: {i['socket']}, gen {i['gen']}{' (assumed)' if i['gen_src'] == 'assumed' else ''} · {avx} · "
            f"CPU {'strong: socket kept as is' if i['strong'] else 'not strong: dead socket counts'} · "
            f"AM5 swap ≈ {r['am5_swap']} € → {r['budget'] + r['am5_swap']} € as an AM5 PC{best}")


def path_txt(r: dict) -> str:
    p = r["path"]
    return p.get("note") or f"→32: {p['to32']} / →64: {p['to64']}"


def rating_txt(r: dict) -> str:
    rating = r.get("seller_rating")
    return f"{rating:.0%}" if isinstance(rating, (int, float)) else "?"


HEADER = ("| # | Listing | Ask | Where | Listed | CPU [platform] | RAM (layout) | GPU (VRAM) | PSU | Tier | Day-one AI "
          "| Fixes € | Effective € (worst) | RAM path € | PCIe link | Headroom | Flags |\n" + "|---" * 17 + "|")


def row(i: int, r: dict) -> str:
    c = build_cells(r)
    cells = [i, f"[{r['title'][:55]}]({r['url']})", ask_txt(r), where(r), (r["posted"] or "?")[:10], c["cpu"],
             c["ram"], c["gpu"], c["psu"], rules.TIER_NAMES[r["tier"]], r["ai"], fixes_txt(r), f"**{eff_txt(r)}**",
             path_txt(r), (r["link"] or {}).get("text", "—"), r["headroom"]["text"], ", ".join(r["flags"]) or "—"]
    return "| " + " | ".join(str(x).replace("|", "/") for x in cells) + " |"


def card(i: int, r: dict) -> str:
    """One listing for verification: every part with its source, the derived checks,
    and the full listing text to check them against."""
    c = build_cells(r)
    text = " · ".join(" ".join(p.split()) for p in CLAUSE_SPLIT_RE.split(r["description"]) if p.strip())
    text = text[:FULL_TEXT_CHARS] + ("…" if len(text) > FULL_TEXT_CHARS else "")
    unknown = ", ".join(r["unknown"]) or "none"
    return "\n".join([
        f"### {i}. {r['title']}", f"{r['url']} · {ask_txt(r)} · {where(r)} · listed {(r['posted'] or '?')[:10]} · "
        f"seller rating {rating_txt(r)}{' · commercial' if r['commercial'] else ''}",
        f"- CPU {c['cpu']} · board {c['board']} · RAM {c['ram']} · GPU {c['gpu']}",
        f"- PSU {c['psu']} · cooler {c['cooler']} · case {c['case']} · SSD {c['ssd']}",
        f"- GPU note: {r['gpu_note'] or '—'} · PCIe link {(r['link'] or {}).get('text', '—')}",
        f"- Headroom: {r['headroom']['text']}",
        f"- Tier {rules.TIER_NAMES[r['tier']]} · day-one AI {r['ai']} · fixes {fixes_txt(r)} → effective "
        f"**{eff_txt(r)} €** · RAM path {path_txt(r)}",
        *([intel_txt(r)] if intel_txt(r) else []),
        *([fair_txt(r)] if fair_txt(r) else []),
        f"- Unknowns: {unknown}{' (needs seller answers)' if r['needs_answers'] else ''} · flags: "
        f"{', '.join(r['flags']) or '—'}",
        f"\n> {text}\n",
    ])


def excerpt(desc: str) -> str:
    """The clauses that carry specs, condition, logistics or payment, in order."""
    parts = [" ".join(p.split()) for p in CLAUSE_SPLIT_RE.split(desc) if p.strip()]
    text = " · ".join([p for p in parts if RELEVANT_RE.search(p)] or parts)
    return text[:EXCERPT_CHARS] + ("…" if len(text) > EXCERPT_CHARS else "")


def shapes(records: list[dict]) -> list[tuple]:
    """Median ask per build shape (platform / RAM / GPU), stated values only."""
    groups = {}
    for r in records:
        b = r["build"]
        if b["gpu"] and not b["gpu"].get("to_buy") and r["ask"] and "stated" == b["platform"]["src"] == b["ram_gb"]["src"]:
            groups.setdefault(f"{b['platform']['v']} · {b['ram_gb']['v']} GB · {b['gpu']['name']}", []).append(r["ask"])
    return sorted(((k, statistics.median(v), len(v)) for k, v in groups.items() if len(v) >= SHAPE_MIN_SAMPLES),
                  key=lambda x: (x[0].split(" · ")[0], x[1]))


def section_pick(featured: list[dict]) -> str:
    if not featured:
        return "## A. Pick\n\nNo PC is featured. See B (not featured), B2 (bundles), D (special cases), G (misses).\n"
    r = featured[0]
    return (f"## A. Pick by code: B #1, {r['title'][:60]} — ask {r['ask']:g} €, effective {eff_txt(r)} €, "
            f"tier {r['tier']}"
            f"{', act fast' if 'act_fast' in r['flags'] else ''} (the AI pass confirms or overrules)\n")


def section_shortlist(featured: list[dict], others: list[dict]) -> str:
    out = ["## B. Shortlist: featured PCs\n",
           "Ranked tier → needs answers → RAM → NVIDIA → VRAM → board → PSU → 2 sticks → PCIe 5 → CPU → effective €. "
           "`(?)` = assumed or contradicted. Effective € = ask (VB: haggled) + the fixes the listing confirms; "
           "worst = + the fixes it leaves open.\n", HEADER,
           *[row(i, r) for i, r in enumerate(featured[:SHORTLIST], 1)], "\n## B1. Verification cards (featured)\n",
           *[card(i, r) for i, r in enumerate(featured[:SHORTLIST], 1)]]
    if others:
        out.append(f"## B3. Passing but not featured ({len(others)}): needs seller answers on a non-top deal, "
                   "or a 16 GB build the RAM step makes dearer than a tier 1-2 PC\n")
        out += [f"- [{r['title'][:55]}]({r['url']}) — {ask_txt(r)} → eff {eff_txt(r)} · tier {r['tier']} · "
                f"{build_cells(r)['ram']} · {build_cells(r)['gpu']} · unknowns: {', '.join(r['unknown']) or '—'} · "
                f"{', '.join(f for f in r['flags'] if f in ('needs_answers', 'dominated_by_tier12'))}"
                for r in others[:NOT_FEATURED_SHOWN]]
    return "\n".join(out) + "\n"


def section_underpriced(passed: list[dict], misses: list[dict], cfg) -> str:
    """Listings asked well below their fair price: the likely good deals, passing first."""
    meta = (cfg.prices or {}).get("meta")
    head = "## B0. Underpriced against the fair price (likely good deals)\n\n"
    if not meta:
        return head + (f"No price table yet: fill {cfg.prices_file.name} with prompts/price_calibration.md "
                       "(data: this run's components.csv).\n")
    under = sorted((r for r in passed + misses if r.get("value") == "under"), key=lambda r: r["fair_delta"])
    info = (f"Table {cfg.prices_file.name} from {meta.get('updated', '?')} (dataset {meta.get('dataset', '?')}). "
            f"Underpriced = ask at least {cfg.policy.underpriced_pct} % below the fair price, key parts stated. "
            f"Holdout error {meta.get('holdout_error', '?')}. ⚠ = a part's table price failed the sanity check.\n\n")
    warnings = "".join(f"- ⚠ Table warning: {w}\n" for w in meta.get("warnings", []))
    info += warnings + ("\n" if warnings else "")
    lines = [f"- {'⚠ ' if r.get('fair_doubts') else ''}[{r['title'][:55]}]({r['url']}) — {ask_txt(r)} vs fair {r['fair']} € (**{delta_txt(r)}**) · "
             f"{'passing, tier ' + str(r['tier']) if not r['reject'] else 'not passing: ' + r['reject']} · "
             f"{build_cells(r)['ram']} · {build_cells(r)['gpu']}" for r in under]
    return head + info + ("\n".join(lines) or "None in this run.") + "\n"


def section_bundles(bundles: list[dict], policy) -> str:
    head = (f"## B2. Bundle track (AM5 platform without GPU; + {policy.fix_gpu} € used RTX 3060 12 GB, "
            f"+ {policy.fix_case} € case if none named)\n")
    if not bundles:
        return head + "\nNone passed.\n"
    return head + "\n" + "\n".join([HEADER, *[row(i, r) for i, r in enumerate(bundles[:BUNDLES_SHOWN], 1)], "",
                                    *[card(i, r) for i, r in enumerate(bundles[:BUNDLES_SHOWN], 1)]])


def section_questions(featured: list[dict]) -> str:
    out = [f"## C. Seller questions (featured listings that need answers, top {QUESTIONS_TOP}; the user sends them)\n"]
    for i, r in enumerate(featured[:SHORTLIST], 1):
        if r["needs_answers"] and len(out) <= QUESTIONS_TOP:
            msg = rules.seller_message(r["unknown"], r["ships"] and not r["local"], "mining_or_24_7" in r["flags"])
            out.append(f"**{i}. {r['title'][:60]}**\n```\n{msg}\n```\n")
    return "\n".join(out) if len(out) > 1 else out[0] + "\nNone needed: the featured listings state their key parts.\n"


def section_special(final: list[dict], policy: Policy) -> str:
    out = [f"## D. Special cases (lots of RAM, GPU under 12 GB; + {policy.fix_gpu} € GPU ≤ {policy.special_max} €)\n"]
    for r in (r for r in final if r["special"]):
        c = build_cells(r)
        out.append(f"- [{r['title'][:60]}]({r['url']}) — {ask_txt(r)}, {c['cpu']}, {c['ram']}, {c['gpu']}; effective "
                   f"{r['budget']} + GPU {policy.fix_gpu} = **{r['budget'] + policy.fix_gpu} €** · {where(r)}")
    return "\n".join(out) + ("\n" if len(out) > 1 else "None found.\n")


def section_market(snippet: list[dict], medians: dict, stats: dict) -> str:
    shape_lines = [f"| {k} | {m:g} € | {n} |" for k, m, n in shapes(snippet)] or ["| too few listings | | |"]
    gpu_lines = ", ".join(f"{g} {m:g} €" for g, m in sorted(medians.items())) or "too few listings"
    rejects = ", ".join(f"{k} {v}" for k, v in sorted(stats["rejects"].items(), key=lambda x: -x[1])) or "none"
    return ("## E. Market notes (median asking prices of whole PCs in this scan)\n\n"
            "| Shape (platform · RAM · GPU) | Median ask | n |\n|---|---|---|\n" + "\n".join(shape_lines) +
            f"\n\nBy GPU (all platforms): {gpu_lines}\n\nRead: {stats['unique']} unique listings; full text: "
            f"{stats['details']} fetched, {stats.get('reused', 0)} reused from saved data, {stats['detail_skipped']} "
            f"skipped by the cap, {stats['detail_errors']} failed; {stats.get('preview_only', 0)} judged on the search "
            f"preview only. Rejects (first rule that hit): {rejects}\n")


def section_log(stats: dict, cfg) -> str:
    terms = ", ".join(f"{t} ({n})" for t, n in stats["terms"].items())
    errs = "\n".join(f"- {e}" for e in stats["errors"][:10]) or "none"
    review = (f"Re-evaluation of the saved run {stats['review_of']} with the current rules: no new search, so "
              "sold or new listings since then are not reflected.\n\n" if stats.get("review_of") else "")
    return (f"## F. Search log\n\n{review}Run {stats['run_time']} · {stats['requests']} search requests"
            f"{' (request cap hit)' if stats['capped'] else ''} · {cfg.category}, Angebote, {cfg.sort}, "
            f"{cfg.ask_min}–{cfg.ask_max} € ask.\n\nTerms (ads found): {terms}\n\nErrors:\n{errs}\n")


def section_misses(records) -> str:
    misses = sorted((r for r in records if r["reject"] in ("over_budget", "am4_over_550")), key=lambda r: r["budget"])
    lines = [f"- [{r['title'][:55]}]({r['url']}) — {ask_txt(r)} → eff **{eff_txt(r)}** ({r['reject']}; fixes "
             f"{fixes_txt(r)}) · {build_cells(r)['ram']} · {build_cells(r)['gpu']}" for r in misses[:CLOSEST_MISSES]]
    return "## G. Closest misses (over the limit only)\n\n" + ("\n".join(lines) or "None.") + "\n"


def section_filtered(records) -> str:
    """Price not for the whole PC, placeholder, far below parts value, or 2+ scam signals."""
    hits = [r for r in records if r["reject"] in MISPRICE_REJECTS]
    def why(r: dict) -> str:
        worth = f" (GPU + RAM alone worth ≥ {r['parts_floor']} €)" if r["reject"] == "price_below_parts_value" else ""
        return f"{r['reject']}{worth} · signals: {', '.join(r['scam']) or '—'}"

    lines = [f"- [{r['title'][:55]}]({r['url']}) — {ask_txt(r)} · {why(r)}" for r in hits[:FILTERED_SHOWN]]
    return f"## H. Filtered as mispriced or scam ({len(hits)})\n\n" + ("\n".join(lines) or "None.") + "\n"


def section_rules(policy: Policy) -> str:
    """The user's deliberate changes to the Brief, so neither the reader nor the AI mistakes them for errors."""
    changed = deviations(policy)
    lines = "\n".join(f"- {d}" for d in changed) or "- none: the Brief's rules apply as written"
    return f"**Selection rules changed from the Brief (user's choice):**\n{lines}\n"


def render(result: dict) -> str:
    cfg, stats, policy = result["cfg"], result["stats"], result["cfg"].policy
    pcs = [r for r in result["passed"] if r["track"] == "pc"]
    featured, others = [r for r in pcs if r["featured"]], [r for r in pcs if not r["featured"]]
    bundles = [r for r in result["passed"] if r["track"] == "bundle"]
    banner = ("> **INCOMPLETE RUN:** more than 20 % of full-listing fetches failed; results may miss listings.\n"
              if stats["incomplete"] else "")
    every = list({**{r["ad_id"]: r for r in result["snippet"]}, **{r["ad_id"]: r for r in result["final"]}}.values())
    return "\n".join([
        f"# Kleinanzeigen search results — {stats['run_time'][:16]}\n", banner,
        f"{len(featured)} featured PCs, {len(others)} more passing, {len(bundles)} bundles ({policy.price_basis} "
        f"price ≤ {policy.limit} €). Code applied the Brief's rejects, fixes and tiers.\n",
        section_rules(policy),
        section_pick(featured),
        section_underpriced(result["passed"], [r for r in every if r["reject"] in ("over_budget", "am4_over_550")], cfg),
        section_shortlist(featured, others), section_bundles(bundles, policy),
        section_questions(featured), section_special(result["final"], policy),
        section_market(result["snippet"], result["medians"], stats), section_log(stats, cfg), section_misses(every),
        section_filtered(every),
    ])


def ai_prompt(result_md: str, cfg, prompt_file: Path | None = None) -> str:
    """Static instructions (the main AI prompt unless given) + attached rule files + this run's results."""
    prompt_file = prompt_file or cfg.prompt_file
    parts = [prompt_file.read_text(encoding="utf-8") if prompt_file.exists()
             else f"(prompt file {prompt_file.name} not found)"]
    for path in cfg.attach:
        body = path.read_text(encoding="utf-8") if path.exists() else "(file not found)"
        parts.append(f"\n---\n\n# Attached: {path.name}\n\n{body}")
    parts.append(f"\n---\n\n# Search results (this run)\n\n{result_md}")
    return "\n".join(parts)


def _jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows)


def write_run(runs_dir: Path, result: dict, suffix: str = "") -> Path:
    folder = runs_dir / (datetime.now().strftime("%Y-%m-%d_%H%M%S") + suffix)
    folder.mkdir(parents=True)
    md = render(result)
    (folder / "results.md").write_text(md, encoding="utf-8")
    (folder / "ai_prompt.md").write_text(ai_prompt(md, result["cfg"]), encoding="utf-8")
    for name, source in EXTRA_PROMPTS.items():
        (folder / name).write_text(ai_prompt(md, result["cfg"], result["cfg"].prompt_file.parent / source),
                                   encoding="utf-8")
    passed_ids = {r["ad_id"] for r in result["passed"]}   # finalized: featured, ranks, cross-listing flags
    _jsonl(folder / "listings.jsonl", result["passed"] + [r for r in result["final"] if r["ad_id"] not in passed_ids])
    _jsonl(folder / "raw.jsonl", (result["raw"].get(h["id"], h) for h in result["hits"]))
    prices.write_components(folder / "components.csv", result["final"])
    settings = {k: (str(v) if isinstance(v, Path) else v) for k, v in dataclasses.asdict(result["cfg"]).items()}
    (folder / "run.json").write_text(json.dumps({"settings": settings, "stats": result["stats"]},
                                                ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return folder


def summary(result: dict, folder: Path) -> dict:
    """Short text for the console / launcher window."""
    stats, passed = result["stats"], result["passed"]
    featured = [r for r in passed if r["track"] == "pc" and r["featured"]]
    lines = [f"{'INCOMPLETE RUN — ' if stats['incomplete'] else ''}"
             f"{'Re-evaluated ' + stats['review_of'] + ': ' if stats.get('review_of') else ''}{stats['unique']} listings, "
             f"full text {stats['details']} fetched + {stats.get('reused', 0)} reused, {len(featured)} featured PCs, "
             f"{len(passed)} passing in total ({sum(r.get('value') == 'under' for r in passed)} underpriced), "
             f"{sum(r['special'] for r in result['final'])} special cases."]
    lines += [f"  {i}. {r['ask']:g} € ask · {eff_txt(r)} € eff · tier {r['tier']} · {r['title'][:60]}" for i, r in enumerate(featured[:5], 1)]
    top = sorted(stats["rejects"].items(), key=lambda x: -x[1])[:5]
    lines.append("Top rejects: " + (", ".join(f"{k} {v}" for k, v in top) or "none"))
    lines.append(f"Output: {folder}")
    return {"text": "\n".join(lines), "folder": folder, "passed": len(passed)}
