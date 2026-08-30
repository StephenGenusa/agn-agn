"""Regenerate ``data/continents.json`` from AD1C country-file data.

Maintenance script; not part of the runtime path. Reads a ``cty.plist`` and
writes a pruned prefix-to-continent table.

country-files.com returns HTTP 403 to automated requests, so the input must be
supplied. A working source is the pyhamtools test fixture:
https://raw.githubusercontent.com/dh1tw/pyhamtools/master/test/fixtures/cty.plist

Usage:
    uv run python tools/build_continents.py path/to/cty.plist
"""

import json
import pathlib
import plistlib
import sys

OUTPUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "continents.json"


def longest_prefix(table: dict[str, str], callsign: str) -> str | None:
    """Return the continent for the longest matching prefix.

    Args:
        table: Prefix-to-continent mapping.
        callsign: Callsign or prefix to resolve.

    Returns:
        The continent code, or ``None`` if no prefix matches.
    """
    for length in range(len(callsign), 0, -1):
        found = table.get(callsign[:length])
        if found is not None:
            return found
    return None


def prune(table: dict[str, str]) -> dict[str, str]:
    """Drop entries already implied by a shorter prefix.

    Args:
        table: The full prefix-to-continent mapping.

    Returns:
        A smaller mapping producing identical lookups.
    """
    pruned = dict(table)
    for key in sorted(table, key=lambda k: -len(k)):
        value = pruned.pop(key)
        if longest_prefix(pruned, key) != value:
            pruned[key] = value
    return pruned


def main(argv: list[str]) -> int:
    """Read a cty.plist and write the pruned table.

    Args:
        argv: Command-line arguments; ``argv[0]`` is the cty.plist path.

    Returns:
        A process exit code.
    """
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 1
    source = pathlib.Path(argv[0])
    with source.open("rb") as handle:
        data = plistlib.load(handle)
    full = {
        key: str(entry["Continent"])
        for key, entry in data.items()
        if entry.get("Continent")
    }
    pruned = prune(full)
    for callsign, continent in full.items():
        if longest_prefix(pruned, callsign) != continent:
            print(f"pruning changed {callsign}", file=sys.stderr)
            return 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(pruned, separators=(",", ":"), sort_keys=True))
    print(f"{len(full)} entries -> {len(pruned)}, {OUTPUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
