"""Assessed listings -> search_results.md, the single input file for the final AI
pass. Laid out as Priming Brief §9 sections A-F; everything computable is
already computed, so the AI only verifies, judges and writes."""
import re
import statistics

import rules

SHORTLIST = 10        # full rows + description excerpt
QUESTIONS_TOP = 5     # seller messages only for the best-ranked listings
ALSO_PASSING = 20     # compact one-liners after the shortlist
CLOSEST_MISSES = 5
DESC_CHARS = 700
SHAPE_MIN_SAMPLES = 3


def _q(text, src):
    return f"{text} (?)" if src == "assumed" else text


def build_cells(r):
    b = r["build"]
    gpu, cpu, psu, st = b["gpu"], b["cpu"] or {}, b["psu"]["v"], b["storage"]["v"]
    sticks, per = b["ram_layout"]["v"]
    ddr = f"DDR{b['ddr']}" if b["ddr"] else "DDR?"
    psu_txt = f"{psu['watts'] or '?'} W {'trusted' if psu['trusted'] else 'brand?'}"
    ssd = f"{'NVMe' if st['nvme'] else 'SATA?'} {st['gb'] or '?'} GB"
    return {
        "cpu": _q(f"{cpu.get('label', '?')} [{b['platform']['v'] or '?'}]", b["platform"]["src"]),
        "board": b["chipset"] or "? (?)",
        "ram": _q(f"{b['ram_gb']['v']} GB {ddr} ({sticks}×{per})",
                  "assumed" if "assumed" in (b["ram_gb"]["src"], b["ram_layout"]["src"]) else "stated"),
        "gpu": _q(f"{gpu['name']} {gpu['vram']} GB", "stated" if gpu["vram_stated"] else "assumed"),
        "psu": _q(psu_txt, b["psu"]["src"]),
        "cooler": _q(b["cooler"]["v"], b["cooler"]["src"]),
        "ssd": _q(ssd, b["storage"]["src"]),
    }


def where(r):
    place = f"{r['location'] or '?'} {r['zip'] or ''}".strip()
    return f"{place} · {'≤30 km' if r['local'] else 'far'} · {'Versand' if r['ships'] else 'Abholung'}"


def ask_txt(r):
    return f"{r['ask']:g} € VB→{r['price']}" if r["vb"] else f"{r['ask']:g} €"


def fixes_txt(r):
    return " + ".join(f"{k} {v}" for k, v in r["fixes"].items()) or "0"


def row(i, r):
    c = build_cells(r)
    title = r["title"].replace("|", "/")[:60]
    cells = [i, f"[{title}]({r['url']})", ask_txt(r), where(r), (r["posted"] or "?")[:10],
             c["cpu"], c["board"], c["ram"], c["gpu"], c["psu"], c["cooler"], c["ssd"],
             rules.TIER_NAMES[r["tier"]], r["ai"], fixes_txt(r), f"**{r['effective']}**",
             f"32: {r['path']['to32']} / 64: {r['path']['to64']}", ", ".join(r["unknown"]) or "—",
             ", ".join(r["flags"]) or "—"]
    return "| " + " | ".join(str(x) for x in cells) + " |"


HEADER = ("| # | Link | Ask | Where | Listed | CPU [platform] | Board | RAM (layout) | GPU (VRAM) | PSU | Cooler | SSD "
          "| Tier | Day-one AI | Fixes € | Effective € | RAM path € | Unknowns | Flags |\n" + "|---" * 19 + "|")


def excerpt(desc):
    text = re.sub(r"\s+", " ", desc).strip()
    return text[:DESC_CHARS] + ("…" if len(text) > DESC_CHARS else "")


def shapes(records):
    """Median ask per build shape (platform / RAM / GPU), stated values only."""
    groups = {}
    for r in records:
        b = r["build"]
        if b["gpu"] and r["ask"] and b["platform"]["src"] == "stated" and b["ram_gb"]["src"] == "stated":
            key = f"{b['platform']['v']} · {b['ram_gb']['v']} GB · {b['gpu']['name']}"
            groups.setdefault(key, []).append(r["ask"])
    return sorted(((k, statistics.median(v), len(v)) for k, v in groups.items() if len(v) >= SHAPE_MIN_SAMPLES),
                  key=lambda x: (x[0].split(" · ")[0], x[1]))


def section_pick(passed):
    if not passed:
        return "## A. Pick\n\nNo listing passed. See D (special cases) and G (closest misses).\n"
    return "## A. Pick (rank 1 by code — the AI pass confirms or overrules)\n\n" + HEADER + "\n" + row(1, passed[0]) + "\n"


def section_shortlist(passed):
    out = ["## B. Shortlist (ranked: tier → RAM → NVIDIA → VRAM → board → PSU → 2 sticks → PCIe 5 → CPU → effective €)\n",
           "`(?)` = assumed per Priming §6.2. Effective € = ask (VB: −10 %) + fixes counted toward the 700 € limit.\n",
           HEADER]
    out += [row(i, r) for i, r in enumerate(passed[:SHORTLIST], 1)]
    out.append("\n### Listing text (shortlist)\n")
    for i, r in enumerate(passed[:SHORTLIST], 1):
        out.append(f"**{i}. {r['title']}** — {r['url']}\n> {excerpt(r['description'])}\n")
    return "\n".join(out)


def section_questions(passed):
    out = [f"## C. Seller questions (top {QUESTIONS_TOP} with unknowns only; the user sends them)\n"]
    for i, r in enumerate(passed[:QUESTIONS_TOP], 1):
        if r["unknown"]:
            msg = rules.seller_message(r["unknown"], r["ships"] and not r["local"], "mining_or_24_7" in r["flags"])
            out.append(f"**{i}. {r['title'][:60]}**\n```\n{msg}\n```\n")
    return "\n".join(out) if len(out) > 1 else out[0] + "\nNone needed.\n"


def section_special(final):
    special = [r for r in final if r["special"]]
    out = [f"## D. Special cases (Priming §6.3: lots of RAM, GPU under 12 GB; + {rules.FIX_GPU_SPECIAL} € GPU fix ≤ {rules.SPECIAL_MAX} €)\n"]
    for r in special:
        c = build_cells(r)
        out.append(f"- [{r['title'][:60]}]({r['url']}) — {ask_txt(r)}, {c['cpu']}, {c['ram']}, {c['gpu']}; "
                   f"effective {r['effective']} + GPU {rules.FIX_GPU_SPECIAL} = **{r['effective'] + rules.FIX_GPU_SPECIAL} €** · {where(r)}")
    return "\n".join(out) + ("\n" if special else "None found.\n")


def section_more(passed):
    rest = passed[SHORTLIST:SHORTLIST + ALSO_PASSING]
    if not rest:
        return ""
    lines = [f"- {i}. [{r['title'][:55]}]({r['url']}) — {ask_txt(r)} → eff {r['effective']} · tier {r['tier']} · "
             f"{build_cells(r)['ram']} · {build_cells(r)['gpu']} · {where(r)}"
             for i, r in enumerate(rest, SHORTLIST + 1)]
    return f"### Also passing ({len(passed) - SHORTLIST} more, best {len(rest)} shown)\n\n" + "\n".join(lines) + "\n"


def section_misses(records):
    misses = sorted((r for r in records if r["reject"] in ("over_budget", "am4_over_550")), key=lambda r: r["effective"])
    lines = [f"- [{r['title'][:55]}]({r['url']}) — {ask_txt(r)} → eff **{r['effective']}** ({r['reject']}; fixes {fixes_txt(r)}) · "
             f"{build_cells(r)['ram']} · {build_cells(r)['gpu']}" for r in misses[:CLOSEST_MISSES]]
    return "## G. Closest misses (over the limit only)\n\n" + ("\n".join(lines) or "None.") + "\n"


def section_market(snippet, medians, stats):
    shape_lines = [f"| {k} | {m:g} € | {n} |" for k, m, n in shapes(snippet)]
    gpu_lines = ", ".join(f"{g} {m:g} €" for g, m in sorted(medians.items()))
    rejects = ", ".join(f"{k} {v}" for k, v in sorted(stats["rejects"].items(), key=lambda x: -x[1]))
    return ("## E. Market notes (median asking prices in this scan)\n\n"
            "| Shape (platform · RAM · GPU) | Median ask | n |\n|---|---|---|\n" + "\n".join(shape_lines) +
            f"\n\nBy GPU (all platforms): {gpu_lines}\n\n"
            f"Read: {stats['unique']} unique listings, {stats['details']} full details. Rejects: {rejects}\n")


def section_log(stats):
    terms = ", ".join(f"{t} ({n})" for t, n in stats["terms"].items())
    errs = "\n".join(f"- {e}" for e in stats["errors"][:10]) or "none"
    return (f"## F. Search log\n\nRun {stats['run_time']} · {stats['requests']} search requests"
            f"{' (request cap hit)' if stats['capped'] else ''} · category PCs, Angebote, newest first.\n\n"
            f"Terms (ads found): {terms}\n\nErrors:\n{errs}\n")


def render(passed, final, snippet, medians, stats):
    return "\n".join([
        f"# Kleinanzeigen search results — {stats['run_time'][:16]}\n",
        f"{len(passed)} listings pass the Brief (effective ≤ {rules.BUDGET} €, tier 0–1 stretch to "
        f"{rules.BUDGET + rules.STRETCH} €). Code applied §2 rejects, §5 fixes and §6 tiers; verify against the text.\n",
        section_pick(passed), section_shortlist(passed), section_more(passed), section_questions(passed),
        section_special(final), section_market(snippet, medians, stats), section_log(stats), section_misses({**{r["ad_id"]: r for r in snippet}, **{r["ad_id"]: r for r in final}}.values()),
    ])
