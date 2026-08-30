# data/

Runtime data and generated deliverables. **Almost nothing here is in git** —
everything is fetched or generated, and a full harvest runs to several hundred
megabytes across thousands of files.

| Path | Contents | In git |
|---|---|---|
| `continents.json` | Pruned prefix-to-continent table (vendored) | yes |
| `README.md` | This file | yes |
| `*.xlsx` | Store workbooks and workbook exports | no |
| `*.dta`, `*.scp`, `*.lst` | Call-list exports | no |
| `raw/` | Raw upstream responses, exactly as received | no |

Rebuild any of it with `callsigns refresh`, `callsigns harvest` and
`callsigns export`. See the top-level `README.md`.

## continents.json

Derived from AD1C country-file data (`cty.plist`), used under its terms for
amateur radio use. The source has 27,583 prefix entries; pruning every entry
whose continent is already implied by a shorter prefix reduces it to 1,380
entries (15,130 bytes) with identical lookup results.

It is tracked because the `.lst` exporter needs it at runtime and it is small.

Regenerate with:

```bash
curl -sL -o data/raw/cty.plist \
  https://raw.githubusercontent.com/dh1tw/pyhamtools/master/test/fixtures/cty.plist
uv run python tools/build_continents.py data/raw/cty.plist
```

country-files.com returns HTTP 403 to automated requests, which is why the
input is supplied manually rather than fetched at runtime.

## raw/

Written by both `callsigns refresh` and `callsigns harvest`. Every provider
archives the exact bytes it parsed, so a store can be rebuilt, or new columns
derived, without going back to the network.

Safe to delete; it is a cache, not a source of truth. Deleting it only means
the next harvest has to fetch again.

`.gitattributes` marks this tree `-text` so that if any of it is ever committed
deliberately, git will not rewrite line endings: several sources send CRLF, and
a normalised copy would no longer match what the server actually sent.

Rough sizes, for planning a harvest:

| Contents | Size |
|---|---|
| Club and leaderboard payloads (`.html`, `.json`) | small, KB each |
| Cabrillo logs (`.log`) | ~3,000 files, ~300 MB |
| RBN daily archives (`.zip`) | ~67 MB per contest day, ~4 MB for a quiet day |
| `cty.plist` | 13 MB, one curl away |

A full collection is around 436 MB across 3,370 files. `callsigns harvest`
resumes from whatever is already present, so it does not have to be done in one
sitting.
