# Used AI/Workstation PC — Deal Evaluation Brief

Nov 23, 2026 · Germany, Kleinanzeigen, used complete PCs

## 0. Purpose and how to use this

This brief is for judging any used PC listing against one goal: **the best local coding agent possible now (Qwen3.8-Flash-Next via the Strata engine), plus gaming, 3D and simulation, on a platform that can be upgraded rather than replaced.**

- **Budget:** about 600 € target, 700 € hard limit, for the PC as bought. RAM upgrades are tracked separately and fall outside this limit.
- **Priorities:** coding quality first, then speed. Below 20–30 tok/s is unacceptable.
- **Method:** don't judge components one by one. Every listing goes through three steps:
  1. **Hard rejects** (section 2). Any hit means the listing is out.
  2. **Effective price** = asking price + the cost of every fix needed to reach the baseline (section 5). The listing passes only if effective price ≤ 700 €. RAM fixes are shown separately as path cost.
  3. **Rank:** day-one AI tier (section 3), then upgrade headroom (section 4), then effective price.

## 1. The governing relationships (read first)

These six rules drive everything else.

1. **RAM capacity → model quality.** RAM decides which model version runs at all. It is the gate.
2. **GPU VRAM → speed.** VRAM matters more than GPU generation: each extra GB holds about 700 more experts. Every realistic card already clears 30 tok/s, so speed is never the bottleneck at this budget.
3. **RAM is currently the most expensive thing to upgrade.** 32 GB DDR5-6000 costs at least about 490 € new, 64 GB DDR5 about 900–1,000 €, and 32 GB DDR4 about 200–370 €. No price relief is expected before 2028. **RAM that comes with a used PC is the biggest hidden value in a listing:** sellers usually price a whole PC by its age, not by today's RAM prices.
4. **The platform (socket + board) is what you keep; GPU and RAM are what you swap.** Only AM5 has a confirmed CPU upgrade path: AMD supports it through 2029, and Zen 6 (Ryzen 10000) is confirmed for current AM5 boards. A wrong platform can only be fixed by replacing it.
5. **PSU and case limit the next GPU.** A weak PSU or a small case turns a cheap GPU swap into a GPU + PSU + case job. Judge both by the card you'll want next, not the one in the listing.
6. **The PCIe link between CPU, board and GPU affects AI speed.** Strata moves experts to the GPU over PCIe for every layer. Link width × generation matters, and it is set by the weakest of three parts: CPU, board slot and card.

## 2. Hard rejects (any one = discard)

- **Any GPU with less than 12 GB VRAM.** Watch for 8 GB variants with the same name: RTX 3060 8 GB, 4060 Ti 8 GB, 5060 Ti 8 GB. Also 3070/3070 Ti, 3080 10 GB, 2080 Ti 11 GB, every 4060/5060.
- **Intel Arc GPUs** (Strata supports them on Linux only) and **no dedicated GPU at all.**
- **Ryzen 5 8500G / Ryzen 3 8300G:** they run a graphics card at PCIe 4.0 x4 only.
- **AM4 with less than 64 GB RAM included.** You'd pay current DDR4 prices to upgrade a dead-end platform.
- **Intel LGA1700 / LGA1851:** no AVX-512, no upgrade path.
- **Unbranded or group-regulated PSU, or a PSU under 550 W.** Count it as a fix only if the rest of the listing is exceptional.
- **Mini-ITX boards and SFF cases:** 2 DIMM slots, short GPU clearance, weak cooling.
- **Laptops and OEM prebuilts with proprietary boards or PSUs** (some Dell, HP, Lenovo): standard parts don't fit, so the platform can't be upgraded.

## 3. RAM tier → what runs on day one

Rule: a model version fits when RAM ≥ its experts + about 10 GB. VRAM can cover some of the gap.

| RAM in PC | Best model version | Coding quality | Day-one verdict |
| --- | --- | --- | --- |
| 16 GB | none (Strata needs 32 GB minimum) | — | **No local agent.** Usable only with the RAM path cost added. |
| 32 GB | Coder (IQ1\_M), experts 23 GB | About 91% of the full model's SWE-bench Verified score; weak outside code | **Good coding agent.** Baseline target. |
| 48 GB (2×24) | IQ2\_XS (needs about 46 GB) | Good, general | Borderline fit; better than 32 GB. |
| 32 GB + 24 GB VRAM | IQ2\_XS | Good, general | Exception: a 3090-class card makes 32 GB enough. |
| 64 GB | IQ3\_S (experts 50 GB) | Matches the full model on published tests | **Ideal.** Quality plateau for this model. |
| 96–128 GB | UD-IQ4\_XS / UD-Q4\_K\_XL | Only marginally better than IQ3\_S for this model | Headroom for future, larger models only. |

**Consequence:** going from 32 to 64 GB is the one upgrade that matters for quality. Beyond 64 GB, extra RAM only pays off for future models.

## 4. Component relationship cards

Format for each part: **what it controls**, then under / right / over for this build, then **couples with** (what it forces elsewhere).

### 4.1 Platform: CPU socket + motherboard

Controls the upgrade path, maximum RAM, the PCIe link, and AVX-512 (Strata computes experts that don't fit on the GPU on the CPU, with AVX-512 or AVX2).

| Platform | Verdict | Why |
| --- | --- | --- |
| **AM5 (Ryzen 7000/9000)** | **Right (target)** | Zen 6 drop-in upgrade, AVX-512, DDR5 bandwidth, PCIe 5.0, up to 4 DIMMs / 128–256 GB |
| AM4 B550/X570 + Ryzen 5000 | Acceptable only with **64 GB or more included** | Dead socket, AVX2 only, PCIe 4.0; DDR4 is cheaper per GB to expand (128 GB max) |
| AM4 B450/A520 | Under | PCIe 3.0 halves the bandwidth to x8 cards |
| Intel any | Reject | See section 2 |

**AM5 chipsets:**

- **B650 / X670 / B850:** right. GPU slot is usually PCIe 4.0 x16 (B850 varies).
- **B650E / X670E / X870(E):** best, with a PCIe 5.0 GPU slot. Only pay extra for it if the GPU is a PCIe 5.0 x8 card (5060 Ti).
- **A620:** under. Weak power delivery, often only 2 DIMMs, poor for a Zen 6 upgrade. Accept only if very cheap, and add a board swap as a future cost.

**Board must-haves:** 4 DIMM slots, ATX or mATX. **Nice:** BIOS flashback (older AM5 boards may need a BIOS update for 9000-series and Zen 6 CPUs) and 2 M.2 slots.

### 4.2 CPU (on AM5)

For AI it barely matters: a Ryzen 5 7600 with an RTX 5070 already reaches 78.6 tok/s. It matters for simulation and 3D, and it can be swapped on the same board later.

- **Under:** none on AM5 except the 8000G APUs. The 8600G/8700G run the GPU at PCIe 4.0 x8. That's a penalty for x16 cards like the 3060, 4070 or 5070, and neutral for 4060 Ti / 5060 Ti. Fix: swap to a 7600 later.
- **Right:** Ryzen 5 7600/7600X/9600/9600X, Ryzen 7 7700/9700X. Zen 5 (9000) runs AVX-512 at full width.
- **Over:** 7800X3D/9800X3D (great for gaming, no AI benefit) and 7900/9900-class. Worth it only if the total price still fits.
- **Couples with the cooler:** 65 W parts (7600, 9600, 7700) are fine with a basic tower. 105 W+ parts (7600X, 7700X, X3D) need a decent single-tower cooler; a stock cooler on these = fix.

### 4.3 RAM (as included)

| Included | AM5 verdict | Upgrade path |
| --- | --- | --- |
| 2×8 GB | Under | Sticks are worthless; buy 2×16 or 2×32 new. Full path cost. |
| 2×16 GB, 4-slot board | **Right (target)** | Add a second 2×16 to reach 64 GB. With 4 DDR5 sticks the RAM runs slower, but capacity matters more than speed for this model, so it's the cheapest route to IQ3\_S. |
| 4×8 / 4×16 GB | Under / OK | Every slot is full; reaching 128 GB means replacing everything. |
| 2×24 GB | Right+ | 48 GB now; add a second 2×24 for 96 GB. |
| 2×32 GB | **Ideal** | 64 GB done; add a second 2×32 later for 128 GB. |

- **DDR4 on AM4:** same logic, 4×32 = 128 GB maximum.
- **Mixing kits:** prefer the identical kit model. Mixed kits may need lower speed settings.

### 4.4 GPU

Controls speed, gaming, 3D and simulation (NVIDIA preferred for CUDA). PSU minimum is a rough guide.

| GPU | VRAM / PCIe | Power | PSU min | AI | Gaming / 3D | Used € (Nov 2026) | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RTX 3060 12 GB | 12 / 4.0 x16 | 170 W | 550 W | about 62 tok/s measured | 1080p | 190–250 | **Floor, good value** |
| RTX 4060 Ti 16 GB | 16 / 4.0 x8 | 165 W | 550 W | good VRAM, narrow link | 1080p+ | (scan) | Right |
| **RTX 5060 Ti 16 GB** | 16 / 5.0 x8 | 180 W | 600 W | about 48 tok/s at IQ3\_S | 1440p | 395–420 | **Best fit** (pair with a PCIe 5.0 slot) |
| RTX 4070 / Super 12 GB | 12 / 4.0 x16 | 200–220 W | 650 W | 48 tok/s IQ2\_XS even with 32 GB DDR4 | 1440p | (scan) | Right for gaming, but VRAM-limited |
| RTX 5070 12 GB | 12 / 5.0 x16 | 250 W | 650 W | 78.6 tok/s IQ2\_XS / 53.3 IQ3\_S | 1440p+ | about 500–530 | Over budget inside a full PC |
| RTX 3080 12 GB | 12 / 4.0 x16 | 350 W | 750 W | fast | 1440p | (scan) | Meh: power-hungry for 12 GB |
| RTX 3090 24 GB | 24 / 4.0 x16 | 350 W, spikes | 850 W | about 140 tok/s (estimate, unmeasured); IQ2\_XS on 32 GB RAM | 4K | 750–1,000 | AI dream; only if the whole PC still fits |
| RX 9060 XT 16 / RX 9070 16 | 16 | 160–220 W | 550–650 W | 58.7 tok/s measured (9070) | good | (scan) | Secondary: weaker for CUDA tools |

**PCIe link check (GPU × CPU × slot):**

- **x8 cards (4060 Ti, 5060 Ti):** fine on AM5. On a PCIe 3.0 board they lose half their bandwidth (penalty).
- **5060 Ti:** best on a PCIe 5.0 slot (B650E/X670E/X870).
- **x16 cards:** fine everywhere except behind 8600G/8700G (runs at x8).

### 4.5 PSU — sized for the NEXT GPU

| PSU | Covers | Verdict |
| --- | --- | --- |
| 550–650 W, brand-name Gold | up to 5060 Ti / 4070 | **Under** for the upgrade path: the next big GPU means a PSU swap (fix: 80–110 €, estimate) |
| **750 W, brand-name Gold** | up to 5070 Ti / 4070 Ti Super class | **Right** |
| 850 W+ Gold, ATX 3.x, native 12V-2x6 cable | 3090 / 4080 class | Ideal headroom |

- **Brands/series to trust:** be quiet! (Pure Power 11/12, Straight Power), Corsair RMx/RMe, Seasonic Focus/Prime, MSI MAG A-GL, Cooler Master MWE Gold V2, FSP Hydro G.
- **Age:** a PSU older than about 8 years counts as under.

### 4.6 Case + cooling

- **Case:** mesh front, ATX/mATX, GPU clearance of at least 320–340 mm (fits 3090-class). A closed front or a short case = **under** (fix: case swap, 50–80 €, estimate).
- **CPU cooler:** a tower air cooler (Peerless Assassin / AK400 class) is **right**, and covers a future Zen 6 upgrade too. Stock coolers are fine only on 65 W CPUs. Used AIOs: worry about pump age; neutral at best.

### 4.7 Storage

- **Right:** 1 TB NVMe or more. Each model download is 66–76 GB, and Strata needs about 80 GB of free space.
- **Ideal:** 2 TB.
- **Under:** SATA SSD only, or under 500 GB. Fix: 1 TB NVMe (price: scan; SSD prices are up too).

## 5. Fix-cost ledger (for computing effective price)

Estimates for reaching the baseline. Check them against current listings during the sweep.

| Deficit | Fix | Approx. cost (€) | Counts toward 700 € limit? |
| --- | --- | --- | --- |
| 16 GB RAM (2×8) | 2×16 DDR5 new | about 490 (Oct 2026 retail) | No (path cost), but flag: no day-one agent |
| 2×16 → 64 GB | +2×16 DDR5 | about 490 | No (path cost) |
| 2×32 → 128 GB | +2×32 DDR5 | about 900–1,000 | No (path cost) |
| AM4 32 GB → 64 GB DDR4 | +2×16 DDR4 | about 200–370 | No (path cost) |
| PSU under 750 W | 750 W Gold | 80–110 (est.) | Yes |
| Stock cooler on a 105 W CPU | tower cooler | 25–40 (est.) | Yes |
| Bad case | airflow case | 50–80 (est.) | Yes |
| No / small NVMe | 1 TB NVMe | scan | Yes |
| 8700G/8600G with an x16 GPU | swap to a 7600, resell the APU | about 0–50 net (est.) | Optional |
| A620 board | board swap later | 100–150 (est.) | No (future), but rank lower |

## 6. Ranking order (after rejects and the 700 € check)

1. **AM5 + 32 GB or more + 16 GB NVIDIA GPU + 750 W PSU.** Top deal.
2. AM5 + 32 GB or more + 12 GB NVIDIA GPU (3060/4070).
3. AM5 + 16 GB + 12–16 GB GPU, only if effective price + the 490 € RAM path still beats tier 1–2 listings. Flag it: no agent on day one.
4. AM4 B550/X570 + **64 GB or more included** + 12 GB+ GPU, effective price ≤ about 550 €.
5. Anything with a 3090 that still fits under 700 €: jump to #1 regardless.

**Tie-breakers, in order:** more RAM included, more VRAM, PSU wattage/quality, 2-stick RAM layout, PCIe 5.0 slot, CPU core count.

## 7. The "500–700 € sweet spot" claim — ruling

- **True for this model's speed:** above about 700 €, the extra money mostly buys tokens per second you don't need.
- **False for "the complete model for less":** the full-quality version needs 64 GB of RAM, which alone costs about 1,000 € in DDR5 today. At 32 GB you get the Coder subset.
- **Doesn't hold for gaming, 3D and simulation:** those still scale with spending past 700 €.

## 8. Seller verification checklist

- **Exact GPU model and VRAM:** a GPU-Z screenshot, or the full model name.
- **RAM:** exact kit model, stick count and size; an HWiNFO or CPU-Z screenshot.
- **Motherboard model and BIOS version.**
- **PSU make, model and age:** a photo of the label.
- **Purchase receipt (Rechnung):** shows remaining warranty and that the PC isn't stolen.
- **Mining or 24/7 use history** of the GPU.
- **Pickup with a test run** (Abholung, ideally a 10-minute stress test), or PayPal Goods & Services. Never "Freunde & Familie" with a stranger.

## 9. Upgrade roadmap (after purchase)

1. RAM to 64 GB (full-quality model). Buy when DDR5 prices dip.
2. GPU to 16–24 GB (speed, gaming, 3D). The PSU and case must already allow it.
3. CPU to Zen 6 on the same board (simulation, longevity).
4. RAM to 128 GB or more (for future, larger models).

## Sources

- Strata repo and docs (MODELS.md, HOW\_IT\_WORKS.md, COMMUNITY\_BENCHMARKS.md): github.com/Niko1221/Strata
- SmartScope, Strata requirements and speeds (v0.1.42)
- Qwen3.8-Flash-Next benchmarks: DataCamp
- Sonnet 5.5 benchmarks: Anthropic system card via apidog / computingforgeeks
- RAM prices: PCGH (Oct 2026), BottleneckPC (Nov 10, 2026), 3DCenter via Guru3D
- AM5 / Zen 6 support: TechPowerUp, TechSpot (Aug 2026)
- Ryzen 8000G PCIe lanes: AnandTech, TechSpot
- Used GPU prices: eBay.de listings (Oct–Nov 2026)
