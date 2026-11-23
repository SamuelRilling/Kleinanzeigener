"""Scan result -> runs/<date_time>/:
    results.md      human-readable report, Priming Brief §9 sections A-G
    ai_prompt.md    static AI instructions (prompts/ai_pass.md) + attached rules + results.md
    listings.jsonl  every assessed listing (parsed build, fixes, verdict)
    raw.jsonl       raw search hit + full detail per fetched listing
    run.json        settings snapshot + run stats
Everything computable is already computed, so the AI pass only verifies, judges and writes."""
import dataclasses
import json
import re
import statistics
from datetime import datetime
from pathlib import Path

import rules
from text import CLAUSE_SPLIT_RE

SHORTLIST = 10        # full rows + listing text
BUNDLES_SHOWN = 5
QUESTIONS_TOP = 5     # seller messages only for the best-ranked listings
ALSO_PASSING = 20     # compact one-liners after the shortlist
CLOSEST_MISSES = 5
EXCERPT_CHARS = 700
SHAPE_MIN_SAMPLES = 3
# Clauses worth showing the AI: parts, condition, logistics, payment, receipt.
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
    gpu_txt = f"{gpu['name']} {gpu['vram']} GB" + (" (to buy)" if gpu.get("to_buy") else "")
    return {
        "cpu": _q(f"{cpu.get('label', '?')} [{b['platform']['v'] or '?'}]", b["platform"]["src"]),
        "board": b["chipset"] or "? (?)",
        "ram": _q(f"{b['ram_gb']['v']} GB {ddr} ({sticks}×{per})",
                  "assumed" if "assumed" in (b["ram_gb"]["src"], b["ram_layout"]["src"]) else "stated"),
        "gpu": _q(gpu_txt, "stated" if gpu["vram_stated"] and "gpu" not in b["conflicts"] else "assumed"),
        "psu": _q(psu_txt, b["psu"]["src"]),
        "cooler": _q(b["cooler"]["v"], b["cooler"]["src"]),
        "case": b["case"]["name"] or "?",
        "ssd": _q(ssd, b["storage"]["src"]),
    }


def where(r: dict) -> str:
    place = f"{r['location'] or '?'} {r['zip'] or ''}".strip()
    return f"{place} · {'≤ local radius' if r['local'] else 'far'} · {'Versand' if r['ships'] else 'Abholung'}"


def ask_txt(r: dict) -> str:
    return f"{r['ask']:g} € VB→{r['price']}" if r["vb"] else f"{r['ask']:g} €"


def fixes_txt(r: dict) -> str:
    return " + ".join(f"{k} {v}" for k, v in r["fixes"].items()) or "0"


def rating_txt(r: dict) -> str:
    rating = r.get("seller_rating")
    return f"{rating:.0%}" if isinstance(rating, (int, float)) else "?"


HEADER = ("| # | Link | Ask | Where | Listed | Seller | CPU [platform] | Board | RAM (layout) | GPU (VRAM) | PSU | Cooler "
          "| Case | SSD | Tier | Day-one AI | Fixes € | Effective € | RAM path € | Unknowns | Flags |\n" + "|---" * 21 + "|")


def row(i: int, r: dict) -> str:
    c = build_cells(r)
    title = r["title"].replace("|", "/")[:60]
    cells = [i, f"[{title}]({r['url']})", ask_txt(r), where(r), (r["posted"] or "?")[:10], rating_txt(r),
             c["cpu"], c["board"], c["ram"], c["gpu"], c["psu"], c["cooler"], c["case"], c["ssd"],
             rules.TIER_NAMES[r["tier"]], r["ai"], fixes_txt(r), f"**{r['effective']}**",
             f"32: {r['path']['to32']} / 64: {r['path']['to64']}", ", ".join(r["unknown"]) or "—",
             ", ".join(r["flags"]) or "—"]
    return "| " + " | ".join(str(x).replace("|", "/") for x in cells) + " |"


def excerpt(desc: str) -> str:
    """The clauses that carry specs, condition, logistics or payment, in order."""
    parts = [" ".join(p.split()) for p in CLAUSE_SPLIT_RE.split(desc) if p.strip()]
    keep = [p for p in parts if RELEVANT_RE.search(p)] or parts
    text = " · ".join(keep)
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


def section_pick(pcs: list[dict]) -> str:
    if not pcs:
        return "## A. Pick\n\nNo PC listing passed. See B2 (bundles), D (special cases) and G (closest misses).\n"
    return "## A. Pick (rank 1 by code: the AI pass confirms or overrules)\n\n" + HEADER + "\n" + row(1, pcs[0]) + "\n"


def section_shortlist(pcs: list[dict]) -> str:
    out = ["## B. Shortlist (tier → RAM → NVIDIA → VRAM → board → PSU → 2 sticks → PCIe 5 → CPU → effective €)\n",
           "`(?)` = assumed (Priming §6.2) or contradicted by the listing. Effective € = ask (VB: haggled) + fixes.\n",
           HEADER, *[row(i, r) for i, r in enumerate(pcs[:SHORTLIST], 1)], "\n### Listing text (shortlist)\n"]
    out += [f"**{i}. {r['title']}** — {r['url']}\n> {excerpt(r['description'])}\n" for i, r in enumerate(pcs[:SHORTLIST], 1)]
    rest = pcs[SHORTLIST:SHORTLIST + ALSO_PASSING]
    if rest:
        out.append(f"### Also passing ({len(pcs) - SHORTLIST} more, best {len(rest)} shown)\n")
        out += [f"- {i}. [{r['title'][:55]}]({r['url']}) — {ask_txt(r)} → eff {r['effective']} · tier {r['tier']} · "
                f"{build_cells(r)['ram']} · {build_cells(r)['gpu']} · {where(r)}" for i, r in enumerate(rest, SHORTLIST + 1)]
    return "\n".join(out) + "\n"


def section_bundles(bundles: list[dict]) -> str:
    head = (f"## B2. Bundle track (Priming §5.1: AM5 platform without GPU; + {rules.FIX_GPU} € used RTX 3060 12 GB, "
            f"+ {rules.FIX_CASE} € case if none named)\n")
    if not bundles:
        return head + "\nNone passed.\n"
    lines = [HEADER, *[row(i, r) for i, r in enumerate(bundles[:BUNDLES_SHOWN], 1)], ""]
    lines += [f"**{i}. {r['title']}** — {r['url']}\n> {excerpt(r['description'])}\n" for i, r in enumerate(bundles[:BUNDLES_SHOWN], 1)]
    return head + "\n" + "\n".join(lines)


def section_questions(pcs: list[dict]) -> str:
    out = [f"## C. Seller questions (top {QUESTIONS_TOP} PCs with unknowns only; the user sends them)\n"]
    for i, r in enumerate(pcs[:QUESTIONS_TOP], 1):
        if r["unknown"]:
            msg = rules.seller_message(r["unknown"], r["ships"] and not r["local"], "mining_or_24_7" in r["flags"])
            out.append(f"**{i}. {r['title'][:60]}**\n```\n{msg}\n```\n")
    return "\n".join(out) if len(out) > 1 else out[0] + "\nNone needed.\n"


def section_special(final: list[dict], budget: rules.Budget) -> str:
    out = [f"## D. Special cases (Priming §6.3: lots of RAM, GPU under 12 GB; + {rules.FIX_GPU} € GPU ≤ {budget.special_max} €)\n"]
    for r in (r for r in final if r["special"]):
        c = build_cells(r)
        out.append(f"- [{r['title'][:60]}]({r['url']}) — {ask_txt(r)}, {c['cpu']}, {c['ram']}, {c['gpu']}; effective "
                   f"{r['effective']} + GPU {rules.FIX_GPU} = **{r['effective'] + rules.FIX_GPU} €** · {where(r)}")
    return "\n".join(out) + ("\n" if len(out) > 1 else "None found.\n")


def section_market(snippet: list[dict], medians: dict, stats: dict) -> str:
    shape_lines = [f"| {k} | {m:g} € | {n} |" for k, m, n in shapes(snippet)]
    gpu_lines = ", ".join(f"{g} {m:g} €" for g, m in sorted(medians.items())) or "too few listings"
    rejects = ", ".join(f"{k} {v}" for k, v in sorted(stats["rejects"].items(), key=lambda x: -x[1])) or "none"
    return ("## E. Market notes (median asking prices in this scan)\n\n| Shape (platform · RAM · GPU) | Median ask | n |\n"
            "|---|---|---|\n" + "\n".join(shape_lines) + f"\n\nBy GPU (all platforms): {gpu_lines}\n\n"
            f"Read: {stats['unique']} unique listings, {stats['details']} full details "
            f"({stats['detail_skipped']} skipped by the cap, {stats['detail_errors']} failed). Rejects: {rejects}\n")


def section_log(stats: dict, cfg) -> str:
    terms = ", ".join(f"{t} ({n})" for t, n in stats["terms"].items())
    errs = "\n".join(f"- {e}" for e in stats["errors"][:10]) or "none"
    return (f"## F. Search log\n\nRun {stats['run_time']} · {stats['requests']} search requests"
            f"{' (request cap hit)' if stats['capped'] else ''} · {cfg.category}, Angebote, {cfg.sort}, "
            f"{cfg.ask_min}–{cfg.ask_max} € ask.\n\nTerms (ads found): {terms}\n\nErrors:\n{errs}\n")


def section_misses(records) -> str:
    misses = sorted((r for r in records if r["reject"] in ("over_budget", "am4_over_550")), key=lambda r: r["effective"])
    lines = [f"- [{r['title'][:55]}]({r['url']}) — {ask_txt(r)} → eff **{r['effective']}** ({r['reject']}; fixes "
             f"{fixes_txt(r)}) · {build_cells(r)['ram']} · {build_cells(r)['gpu']}" for r in misses[:CLOSEST_MISSES]]
    return "## G. Closest misses (over the limit only)\n\n" + ("\n".join(lines) or "None.") + "\n"


def render(result: dict) -> str:
    cfg, stats, budget = result["cfg"], result["stats"], result["cfg"].budget
    pcs = [r for r in result["passed"] if r["track"] == "pc"]
    bundles = [r for r in result["passed"] if r["track"] == "bundle"]
    banner = ("> **INCOMPLETE RUN:** more than 20 % of full-listing fetches failed; results may miss listings.\n"
              if stats["incomplete"] else "")
    every = {**{r["ad_id"]: r for r in result["snippet"]}, **{r["ad_id"]: r for r in result["final"]}}.values()
    return "\n".join([
        f"# Kleinanzeigen search results — {stats['run_time'][:16]}\n", banner,
        f"{len(pcs)} PCs and {len(bundles)} bundles pass the Brief (effective ≤ {budget.limit} €, tier 0–1 stretch to "
        f"{budget.limit + budget.stretch} €). Code applied §2 rejects, §5 fixes and §6 tiers; verify against the text.\n",
        section_pick(pcs), section_shortlist(pcs), section_bundles(bundles), section_questions(pcs),
        section_special(result["final"], budget), section_market(result["snippet"], result["medians"], stats),
        section_log(stats, cfg), section_misses(every),
    ])


def ai_prompt(result_md: str, cfg) -> str:
    """Static instructions + attached rule files + this run's results, ready to paste."""
    parts = [cfg.prompt_file.read_text(encoding="utf-8") if cfg.prompt_file.exists()
             else f"(prompt file {cfg.prompt_file.name} not found)"]
    for path in cfg.attach:
        body = path.read_text(encoding="utf-8") if path.exists() else "(file not found)"
        parts.append(f"\n---\n\n# Attached: {path.name}\n\n{body}")
    parts.append(f"\n---\n\n# Search results (this run)\n\n{result_md}")
    return "\n".join(parts)


def _jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows)


def write_run(runs_dir: Path, result: dict) -> Path:
    folder = runs_dir / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder.mkdir(parents=True)
    md = render(result)
    (folder / "results.md").write_text(md, encoding="utf-8")
    (folder / "ai_prompt.md").write_text(ai_prompt(md, result["cfg"]), encoding="utf-8")
    final_ids = {r["ad_id"] for r in result["final"]}
    _jsonl(folder / "listings.jsonl", result["final"] + [r for r in result["snippet"] if r["ad_id"] not in final_ids])
    _jsonl(folder / "raw.jsonl", ({**result["raw"].get(h["id"], h)} for h in result["hits"]))
    settings = {k: (str(v) if isinstance(v, Path) else v) for k, v in dataclasses.asdict(result["cfg"]).items()}
    (folder / "run.json").write_text(json.dumps({"settings": settings, "stats": result["stats"]},
                                                ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return folder


def summary(result: dict, folder: Path) -> dict:
    """Short text for the console / launcher window."""
    stats, passed = result["stats"], result["passed"]
    pcs = [r for r in passed if r["track"] == "pc"]
    lines = [f"{'INCOMPLETE RUN — ' if stats['incomplete'] else ''}{stats['unique']} listings read, "
             f"{stats['details']} in full, {len(pcs)} PCs + {len(passed) - len(pcs)} bundles pass, "
             f"{sum(r['special'] for r in result['final'])} special cases."]
    lines += [f"  {i}. {r['effective']} € eff · tier {r['tier']} · {r['title'][:60]}" for i, r in enumerate(passed[:5], 1)]
    top = sorted(stats["rejects"].items(), key=lambda x: -x[1])[:5]
    lines.append("Top rejects: " + (", ".join(f"{k} {v}" for k, v in top) or "none"))
    lines.append(f"Output: {folder}")
    return {"text": "\n".join(lines), "folder": folder, "passed": len(passed)}
