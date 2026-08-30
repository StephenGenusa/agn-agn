# 📻 Agn Agn
### Amateur Radio Callsign Data

**Real callsigns, ranked by how active their operators really are — for CW
practice, contest logging, and anything else you want to do with the data.**

`AGN` is what you send in CW when you didn't copy and need it repeated. This is
the tool that helps you stop sending it. *Agn Agn* is the project; `callsigns`
is the command it installs.

[![CI](https://github.com/StephenGenusa/agn-agn/actions/workflows/ci.yml/badge.svg)](https://github.com/StephenGenusa/agn-agn/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)

---

## What this is, in plain English

Amateur radio has a lot of public scoreboards. POTA publishes who hunts the
most parks. SOTA publishes who climbs the most summits. Every big contest
publishes its logs. The Reverse Beacon Network publishes a running record of
every callsign its skimmers heard, all day, every day.

All of that is **evidence of who is actually on the air** — but it lives in 29
different places, in 29 different formats, behind pages that were designed for
a person with a browser rather than for a program.

This tool goes and gets it. It mirrors each source into a plain Excel workbook,
one sheet per source and period, and then exports the callsigns to the file
formats that CW trainers and contest loggers already know how to read.

```
  29 public sources          one workbook per source        the formats
  ───────────────────        ──────────────────────         your software reads
  POTA leaderboards    ┐                                  ┌ master.dta  (Morse Runner)
  SOTA honour rolls    │     data/POTA-Hunters.xlsx       │ .scp        (N1MM, Morserino)
  RBN skimmer spots    ├──▶  data/RBN-CW.xlsx        ──▶  ├ .lst        (PileupRunner)
  21 contests' logs    │     data/CQWW-CW.xlsx            │ .xlsx       (you, in a spreadsheet)
  4 CW clubs' sprints  ┘     …                            └ Roster.xlsx (all sources merged)
```

### Why it exists

It started as a practice problem. [Morse
Runner](https://www.dxatlas.com/morserunner/) — the CW pileup simulator — ships
with a `master.dta` file of callsigns to throw at you. It's a fine list, but
it's a *general* list. If the operating you actually do is POTA and SOTA, you
want to practise pulling **the callsigns you are actually going to hear**: the
hunters who chase parks every weekend, the activators who show up on 20m from a
summit, the contest regulars whose calls you'll meet in a pileup.

So the first job was: rank POTA hunters by activity, take the top 500, and
write a `master.dta` a CW trainer can load.

Then it became obvious the same pipeline was worth more than that. Once you are
mirroring activity data cleanly and keeping the raw bytes, you have a genuinely
interesting dataset — and the practice list is only one of the things you can
make out of it.

### What people use it for

| If you want to… | Do this |
|---|---|
| **Practise CW against realistic calls** | Export a `.dta` and drop it into Morse Runner, or a `.scp` for Morserino |
| **Pre-load a contest logger** | Export `.scp` for N1MM's super-check-partial, or `.dta` for Win-Test / CT / TRlog / WriteLog / CW Skimmer |
| **Practise pileups by continent** | Export `.lst` for PileupRunner — each call carries its continent |
| **Practise at a specific speed** | The RBN store carries min/median/max WPM per callsign, so you can build a list matched to the speed you're working on |
| **Analyse who's active, and where** | `callsigns roster` merges every source into one table: which callsigns appear in how many places, and how highly they rank in each |
| **Study a contest** | Contest stores hold true QSO counts — how often each callsign was actually worked, straight out of the submitted Cabrillo logs |
| **Build something else entirely** | Everything lands in `.xlsx`, and the raw upstream payloads are kept verbatim under `data/raw/` |

---

## Quick start

Requires **Python 3.14+** and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/StephenGenusa/agn-agn.git
cd agn-agn
uv sync
```

Then, three commands end to end:

```bash
# 1. What can I fetch?
uv run callsigns providers

# 2. Mirror the POTA hunter leaderboard into data/POTA-Hunters.xlsx
uv run callsigns refresh pota-hunters

# 3. Write the 500 most active CW hunters as a Morse Runner master.dta
uv run callsigns export pota-hunters dta -o cw -d 500
```

That last command prints the path it wrote — `data/POTA_Calls_CW.dta`. Copy it
into your `Afreet/MorseRunner` folder, rename it to `master.dta` (keep a copy of
the original), and start a run. You are now practising against the people who
actually hunt parks.

> **The `data/` directory is not in this repository.** Every workbook and export
> is fetched or generated, and the full set runs to hundreds of megabytes. You
> build your own with `refresh` or `harvest`. The only files kept in git are
> `data/continents.json` (a small vendored lookup table the `.lst` exporter
> needs) and `data/README.md`.

---

## How it works

Five ideas, and that's the whole tool.

**Providers** are the sources — one per scoreboard. `pota-hunters`, `rbn-cw`,
`cqww-cw` and 26 others. Each knows its own URL shape, its own quirks, and how
to turn what comes back into rows.

**The store** is the workbook of record: `data/POTA-Hunters.xlsx`,
`data/CQWW-CW.xlsx`, and so on. One sheet per period and mode, plus a `_meta`
sheet recording where each sheet came from, when it was fetched and how many
rows it holds. Open it in Excel; it's a normal spreadsheet with normal tables.

**Periods** are what a source slices its data by. Usually a year, sometimes
`all` for an all-time list, sometimes a date (`20251129`) or a month (`202511`)
or an event id. `callsigns providers` prints the syntax for each.

**Modes** (`-o`) are CW / phone / data. Here there's one wrinkle worth knowing:
for some sources a mode is a *filter* applied to data you already have (POTA
reports per-mode QSO counts in the same row), and for others a mode is a
*different download* (SOTA and RBN serve a different URL per mode). So `-o`
belongs on `export` for the first kind and on `refresh` for the second.
`callsigns providers` shows which is which, and passing it to the wrong
subcommand tells you where it belongs rather than silently doing nothing.

**Exports** read exactly one sheet, filter it, cap it, and write a file. They
never merge across sheets — see [Notes on the data](#notes-on-the-data) for why
that matters.

---

## The sources

29 providers, all public, all free.

### Activity and awards

| Provider | Source | Periods | What it measures |
|---|---|---|---|
| `pota-hunters` | POTA hunter leaderboard | `all`, 2016–2026 | Park QSOs, split by CW / phone / data |
| `sota-activator` | SOTA activator honour roll | `all`, 2002–2026 | Summit points ¹ |
| `sota-chaser` | SOTA chaser honour roll | `all`, 2002–2026 | Chaser points ¹ |
| `rbn-cw` | Reverse Beacon Network | `YYYYMMDD`, or a range | Times a skimmer heard them, plus continent and WPM |

¹ These two carry personal data — see [Personal data](#personal-data).

### CW clubs

| Provider | Source | Periods | What it measures |
|---|---|---|---|
| `cwops-cwopen` | CWops CW Open, logs received | 2012–2026 | Participation (entrants, not scores) |
| `fists-sprint` | FISTS Sprint results | Event id, e.g. `febsat25` | Sprint score |
| `naqcc-sprint` | NAQCC monthly sprint | `YYYYMM`, e.g. `202511` | Sprint score |
| `skcc-wes` | SKCC Weekend Sprintathon | Results id, e.g. `105` | WES score |

### Contest logs

These are the only sources with **true QSO counts** — how often each callsign
was actually worked, taken from the submitted Cabrillo logs rather than from a
scoreboard.

| Family | Providers |
|---|---|
| CQ | `cqww-cw`, `cqww-rtty`, `cqwpx-cw`, `cqwpx-rtty`, `cq160-cw` |
| ARRL HF | `arrl-dxcw`, `arrl-dxph`, `arrl-sscw`, `arrl-ssph`, `arrl-10m`, `arrl-160m`, `arrl-rttyru`, `arrl-dig`, `arrl-iaruhf` |
| ARRL VHF and up | `arrl-janvhf`, `arrl-junvhf`, `arrl-sepvhf`, `arrl-222`, `arrl-10g`, `arrl-eme` |
| Other | `ww-digi` |

Periods are contest years. Run `uv run callsigns providers` for the exact list
each one offers.

---

## Commands

### `providers` — what's available

```bash
uv run callsigns providers
```

Prints every provider with its store path, its valid periods and its modes.

### `refresh` — fetch now

```bash
uv run callsigns refresh pota-hunters                      # current year + all-time
uv run callsigns refresh pota-hunters -y 2025
uv run callsigns refresh rbn-cw -y 20251129 -o cw
uv run callsigns refresh cqww-cw -y 2025 --top-logs 200
```

Fetches at full speed and writes the result into the store. Good for one
source, one period. On an empty store, a provider with enumerable periods
backfills all of them; afterwards a bare `refresh` updates only the current
year and all-time.

### `harvest` — fetch politely, over days

```bash
uv run callsigns harvest --dry-run                   # what would this cost?
uv run callsigns harvest                             # everything, paced
uv run callsigns harvest cqww-cw arrl-sscw -y 2025
uv run callsigns harvest --pace 10                   # 10s between requests per host
```

This is the one to use for anything big. It is deliberately slow — roughly one
request every four to eight seconds per host by default, and one every twenty
to forty for sites that have signalled crawler trouble in their `robots.txt`.
Hosts are worked in parallel with one worker each, so a multi-site run isn't
serialised, but no single site ever sees more than its allowance.

`--dry-run` prints an estimate before you commit to it:

```
provider         period     host                    probes  pending  cached   estimate
pota-hunters     2026       api.pota.app                 0        1       0         6s
pota-hunters     all        api.pota.app                 0        1       0         6s
sota-activator   2026       api-db2.sota.org.uk          0        1       0         6s
sota-activator   all        api-db2.sota.org.uk          0        1       0         6s

4 tasks across 2 host(s), estimated 12s (one host at a time would be 24s)
```

Everything downloaded is cached, so a harvest **resumes**. Stop it, close the
laptop, run it again tomorrow and it picks up from what's on disk. If one
source is unreachable it is reported at the end and the rest of the run
continues — a dead site doesn't abandon a multi-day collection.

### `export` — write a file

```bash
uv run callsigns export pota-hunters dta  -o cw -d 500       # Morse Runner
uv run callsigns export pota-hunters scp  -o cw              # N1MM, Morserino
uv run callsigns export pota-hunters lst  -o cw              # PileupRunner
uv run callsigns export pota-hunters xlsx -o cw -y 2026      # spreadsheet
```

### `roster` — merge everything

```bash
uv run callsigns roster build                    # -> data/Roster.xlsx
uv run callsigns roster query --min-sources 3 --mode CW -d 500
uv run callsigns roster query --format dta --basename Roster-Top500-CW -d 500
uv run callsigns roster overlap                  # shared callsigns, source by source
```

A query prints the head of the table:

```
$ uv run callsigns roster query --min-sources 3 -d 15
read 29 sources: arrl-10g, arrl-10m, arrl-160m, arrl-222, arrl-dig, ...
callsign   conf  src  mean%  modes
K1ABC        20   20  0.171  CW,DATA,PHONE
W9XYZ        19   20  0.448  CW,DATA,PHONE
K3ABC        19   19  0.422  CW
N4XYZ        19   19  0.160  CW,DATA,PHONE
KC7ABC       18   19  0.372  CW
K9XYZ        18   19  0.347  CW,DATA,PHONE
N3ABC        18   19  0.287  CW,DATA,PHONE
K1XYZ        18   19  0.259  CW,DATA,PHONE
```

*Callsigns above are placeholders; your own run shows real operators.*

`conf` is how many sources confirm the operator took part; `src` also counts
sources that merely observed them; `mean%` is their average percentile across
the sources they appear in. A callsign turning up in twenty of twenty-nine
sources is not someone who won anything — it is someone who is *always on*.

The roster is the interesting one. Every source ranks callsigns by *something*,
but the somethings aren't comparable — spot counts, QSO counts, summit points
and sprint scores measure different things on different scales, and adding them
would be meaningless. So each source is ranked **within itself**, converted to a
percentile, and only then combined.

The signal no single source carries is **breadth**. A callsign that shows up in
four different contests is a different kind of operator from one that tops a
single scoreboard, and the roster surfaces that difference.

It also keeps two kinds of evidence apart:

- **Confirmed participation** — a contest log, a club score, an award roll. The
  operator entered.
- **Observed activity** — an RBN spot. A skimmer heard them, which is true of
  anyone on the band whether they entered anything or not.

During a big contest the two nearly coincide. During a small club sprint the
band is mostly people who aren't in it, so a spot can't stand in for having
entered. Ranking is on confirmed breadth first; observed activity contributes
to the score but not to the count.

`--min-sources 3` is a good filter for a practice list: it keeps operators
confirmed active in at least three independent places.

---

## Output formats

| Format | Extension | Read by | Default row cap |
|---|---|---|---|
| `dta` | `.dta` | Morse Runner (as `master.dta`), N1MM, Win-Test, CT, TRlog, WriteLog, CW Skimmer | no limit |
| `scp` | `.scp` | N1MM super-check-partial, Morserino | no limit |
| `lst` | `.lst` | PileupRunner (callsign + continent per line) | no limit |
| `xlsx` | `.xlsx` | You, in a spreadsheet | 500 |

`-d 0` means no limit; `-d 500` caps at 500. Because the store is already
sorted by activity, a cap gives you the *most active* N, which is the point —
row count is not.

`.dta` is the K1EA MASTER.DTA binary format, implemented from scratch here and
verified byte-for-byte against a known-good published file.

### Common flags

| Flag | Applies to | Meaning | Default |
|---|---|---|---|
| `-y`, `--year` | refresh, export, harvest | Period: a year, `all`, or a source-specific token | `all` on export; current year + `all` on refresh |
| `-o`, `--operating-mode` | refresh **or** export, per source | `all`, `cw`, `phone`, `data` | `all` |
| `-d`, `--download-rows` | export, roster | Row cap; `0` means no limit | `500` for `xlsx`, `0` otherwise |
| `--out` | export, roster | Output directory | `data/` |
| `--basename` | export, roster | Override the generated filename stem | derived from the provider |
| `--store` | refresh, export, harvest | Workbook location | `data/<Provider>.xlsx` |
| `--raw-dir` | refresh | Raw payload archive | `data/raw/` |
| `--cache` | refresh, harvest | Download cache, bulk sources only | `data/raw/<provider>/` |
| `--top-logs` | refresh, harvest | Contest logs to download; `0` = all | `200` |
| `--jobs` | refresh | Concurrent downloads, bulk sources only | `6` |
| `--pace` | harvest | Seconds between requests to one host | `4` (+ jitter) |
| `--dry-run` | harvest | Estimate and exit | off |
| `-v`, `--verbose` | all | Log progress to stderr | off |

---

## Recipes

**A Morse Runner list of the broadly active CW operators.** The best general
practice list this tool makes: people confirmed active in at least three
independent sources.

```bash
uv run callsigns harvest                      # go and make coffee. Or lunch.
uv run callsigns roster build
uv run callsigns roster query --min-sources 3 --mode CW \
    --format dta --basename Roster-Top500-CW -d 500
```

**A list from one contest weekend.** RBN on a contest day is the broadest
single snapshot available — everything a worldwide skimmer network heard.

```bash
uv run callsigns refresh rbn-cw -y 20251129 -o cw
uv run callsigns export  rbn-cw dta -o cw -y 20251129 -d 500
```

**A US-flavoured practice list.** Sweepstakes is US and VE domestic, so its
callsign pool looks quite different from a DX contest — you get the 1×2 and 2×1
structures a US operator actually hears.

```bash
uv run callsigns refresh arrl-sscw -y 2025 --top-logs 200
uv run callsigns export  arrl-sscw dta -o cw -y 2025 -d 500
```

**Practise pileups by continent.**

```bash
uv run callsigns export rbn-cw lst -o cw -y 20251129 -d 1000
```

**See how much two communities overlap.**

```bash
uv run callsigns roster overlap
```

---

## Notes on the data

Real-world data has edges. These are the ones worth knowing about.

**POTA's all-time list is not the sum of its yearly ones.** Each list is
independently filtered to hunters with at least ten parks, so 8,584 callsigns
appear in all-time and in no single year. Nothing in this tool merges rows
across sheets — an export reads exactly one sheet — precisely so this stays
visible rather than being quietly papered over.

**RBN's `mode` column is the spot *type*, not the modulation.** It holds `CQ`,
`DX`, `BEACON` and `NCDXF B`, and only `CQ` and `DX` mean a human operator was
there. Beacons are excluded; that drops 289 unattended transmitters from a
typical contest day.

**Contest days dominate RBN completely.** CQ WW CW on 2025-11-29 was a 67 MB
download yielding 38,162 callsigns; a quiet Wednesday is 4 MB and about 8,700.
File size alone tells you whether a contest ran.

**`--top-logs 200` is not a compromise.** The ranking stabilises long before
that: 24 of CQ WW's largest logs already gave a 464/500 overlap on the top 500
against 16 logs — at roughly 2% of the field. CQ WW 2025's 200 largest logs
took 45 seconds and yielded 29,171 callsigns. `--top-logs 0` fetches the full
8,109-log field if you want it. CQ serves a static directory so logs are
size-ranked and the biggest fetched first (size tracks QSO count); ARRL serves
dynamic pages reporting no size, so its logs come in listing order.

**Some Cabrillo logs write compound callsigns with a hyphen** rather than a
slash — the form a station uses when operating from another country, written
`5B-XXXXXX` where `5B/XXXXXX` was meant. Those are dropped as invalid rather
than rewritten, because the intent has to be inferred. It's 36 of 29,171 in
CQ WW 2025, all with low contact counts.

**SOTA's API validates nothing.** A year before 2002 returns HTTP 400 with a
non-JSON body; a future year or an unknown mode returns HTTP 200 with an empty
list. Both are rejected locally, so a typo is an error rather than a silently
empty sheet. Also note `-o phone` maps to SSB alone, not the union of SSB, FM,
AM and DV — their point totals can't be combined. Pass `-o FM`, `-o AM`,
`-o DV` or `-o SSB` if you want one specifically.

**SOTA's rolls are small but different.** 1,263 activators and 1,565 chasers
all-time, next to POTA's tens of thousands — but they're a different
population, weighted towards operators working portable from summits.

---

## Being a good neighbour

These are volunteer-run servers. Several of the sites this tool reads publish
results as static HTML because someone maintains them out of their own pocket.
The tool is built to be invisible to them:

- **Paced per host.** ~4–8 seconds between requests by default, ~20–40 for
  hosts whose `robots.txt` shows they've had crawler trouble before. Slower
  than a person clicking through by hand. Jittered, so a long run doesn't
  arrive as a regular pulse.
- **Cached and conditional.** Nothing is downloaded twice. Re-runs revalidate
  rather than re-fetch, and an interrupted harvest resumes.
- **`robots.txt` is read and reported.** A disallowed path produces one warning
  per host per run and the fetch proceeds — the tool informs rather than
  enforces, so honouring a site's stated preference stays your decision, made
  knowingly rather than by accident.
- **Honest headers.** The request headers say what the tool can actually
  accept and where a link was genuinely followed from. There's no fake browser
  version and no `Sec-Ch-Ua` brand claim, because those assert an identity the
  tool doesn't have.
- **The raw bytes are kept.** Every response is archived verbatim under
  `data/raw/`, so a store can be rebuilt — or new columns derived from data you
  already have — without going back to the network at all.

If you run a site this reads and you'd rather it didn't, or would rather it went
slower, please open an issue.

### Personal data

Two sources carry personal information, and it's stored and exported as
received:

- **SOTA activator and chaser rolls** carry `UserID` and `Username`, and
  `Username` often holds real names and email addresses.
- **SKCC Weekend Sprintathon results** carry operator first names.

So `SOTA-Activator.xlsx`, `SOTA-Chaser.xlsx`, `SKCC-WES.xlsx` and any `xlsx`
export made from them should be treated as personal data if you share them.

**The `scp`, `dta` and `lst` exports are callsign-only** and carry none of it.
If you're publishing a practice list, publish one of those.

---

## Repository layout

```
callsigns/
  cli.py             the command line: the only place that prints or catches
  providers/         one module per source
    pota.py  rbn.py  sota.py
    clubs/           CWops, FISTS, NAQCC, SKCC
    contest/         CQ and ARRL Cabrillo log providers, plus the parser
  exporters/         dta, scp, lst, xlsx
  store.py           the workbook of record
  roster.py          cross-source breadth ranking
  harvest.py         planning, estimating and resuming a long collection
  pacing.py          per-host rate limiting
  robots.py          robots.txt awareness
  http.py cache.py archive.py headers.py
  select.py          filtering, row caps, callsign hygiene
  continents.py      prefix -> continent, for the .lst format

tests/               unit tests, fixtures, and network-marked live tests
tools/               build_continents.py, to regenerate the lookup table
data/                generated; not in git (see data/README.md)
```

What lands in `data/` once you've run something:

```
data/
  POTA-Hunters.xlsx           store: one sheet per period, plus _meta
  RBN-CW.xlsx                 store: one sheet per date and mode
  CQWW-CW.xlsx                store: one sheet per contest year
  Roster.xlsx                 the merged cross-source roster
  POTA_Calls_CW.dta           exports
  RBN_Calls_CW_20251129.lst
  continents.json             vendored prefix -> continent table (in git)
  raw/pota-hunters/*.json     raw upstream payloads, exactly as received
  raw/rbn-cw/*.zip            download cache, with an index.json manifest
  raw/cqww-cw/*.log           cached Cabrillo logs
```

The workbook is the store of record. `data/raw/` is a convenience that lets a
store be rebuilt without re-fetching, and is safe to delete.

---

## Development

```bash
uv run pytest                     # unit tests
uv run pytest -m network          # live tests against real sites (opt-in)
uv run ruff check .
uv run ruff format --check .
uv run mypy callsigns
```

Network-marked tests are skipped by default. `mypy` runs in strict mode and
`ruff` enforces Google-style docstrings on everything in `callsigns/`.

### Adding a source

Subclass `Provider`, declare your columns, modes and period syntax, implement
`fetch()`, and decorate the class with `@register`. Import it in `cli.py`'s
registration block. If it downloads many files rather than one page, subclass
`ContestLogProvider` instead and you inherit listing, size-probing, caching,
pacing and resume for free.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Usage or validation error |
| 2 | Network or upstream error |
| 3 | Local I/O error |

---

## License

MIT — see [LICENSE](LICENSE). Do note that the *data* this tool fetches belongs
to the organisations that publish it, and each has its own terms; this licence
covers the code only.

## Credits

- **Morse Runner** by VE3NEA — the CW pileup simulator this started out
  feeding.
- **[Reverse Beacon Network](https://www.reversebeacon.net/)**, **[POTA](https://parksontheair.com/)**,
  **[SOTA](https://www.sota.org.uk/)**, **CQ Magazine**, **ARRL**, **CWops**,
  **FISTS**, **NAQCC** and **SKCC** — for publishing their data at all.
- **AD1C** — `data/continents.json` is derived from the country-file data, used
  under its terms for amateur radio use. See `data/README.md` to regenerate it.
- **ON6ZQ** — whose published `SOTA_Calls_CW.dta` made it possible to verify the
  MASTER.DTA encoder byte-for-byte.

73.
