"""Cabrillo log parsing.

Only two things are needed from a log: who submitted it, and which callsigns
they worked. Everything else — scores, categories, soapbox — is ignored.

Finding the worked callsign is the one subtle part. A ``QSO:`` line is::

    QSO: freq mode date time <sent exchange> <received exchange> [tx]

The sent exchange begins with the entrant's own callsign and the received
exchange begins with the worked callsign, and the two are the same length. So
the worked callsign sits halfway through the tokens that follow the time. A
fixed index does not work: most contests send two exchange fields, but ARRL
Sweepstakes sends four, which would put the check number where the callsign is
expected — two alphanumeric characters that survive every hygiene rule.
"""

from collections.abc import Sequence
from dataclasses import dataclass

#: Inclusive kHz ranges mapped to their band label.
BANDS: tuple[tuple[int, int, str], ...] = (
    (1800, 2000, "160m"),
    (3500, 4000, "80m"),
    (5250, 5450, "60m"),
    (7000, 7300, "40m"),
    (10100, 10150, "30m"),
    (14000, 14350, "20m"),
    (18068, 18168, "17m"),
    (21000, 21450, "15m"),
    (24890, 24990, "12m"),
    (28000, 29700, "10m"),
    (50000, 54000, "6m"),
    (144000, 148000, "2m"),
)

#: Tokens before the exchanges: ``QSO:``, frequency, mode, date, time.
_PREFIX_TOKENS: int = 5

#: The shortest plausible QSO line: prefix, a one-field sent exchange, and a
#: one-field received exchange.
_MIN_TOKENS: int = 7


@dataclass(frozen=True, slots=True)
class Qso:
    """One logged contact, reduced to what the aggregation needs."""

    callsign: str
    band: str
    when: str


def worked_index(tokens: Sequence[str]) -> int:
    """Return the index of the worked callsign in a split ``QSO:`` line.

    The sent and received exchanges are equal length, so the received one
    starts halfway through the tokens that follow the time. Integer division
    discards CQ's optional trailing transmitter-ID field.

    Args:
        tokens: The whitespace-split line.

    Returns:
        The index of the worked callsign.
    """
    return _PREFIX_TOKENS + (len(tokens) - _PREFIX_TOKENS) // 2


def band_for(khz: str) -> str:
    """Map a frequency in kHz to a band label.

    Args:
        khz: The frequency field, which may carry a fractional part.

    Returns:
        The band label, or the empty string if the frequency is unparseable or
        outside every known band.
    """
    try:
        value = int(float(khz))
    except TypeError, ValueError:
        return ""
    for low, high, label in BANDS:
        if low <= value <= high:
            return label
    return ""


def parse_qso_line(line: str) -> Qso | None:
    """Parse one ``QSO:`` line.

    Args:
        line: A single line of a Cabrillo log.

    Returns:
        The contact, or ``None`` if the line is not a usable ``QSO:`` record.
        Malformed lines are skipped rather than raising: one bad line must not
        cost the whole log.
    """
    if not line.startswith("QSO:"):
        return None
    tokens = line.split()
    if len(tokens) < _MIN_TOKENS:
        return None
    index = worked_index(tokens)
    if index >= len(tokens):
        return None
    callsign = tokens[index].strip().upper()
    if not callsign:
        return None
    return Qso(
        callsign=callsign,
        band=band_for(tokens[1]),
        when=f"{tokens[3]} {tokens[4]}",
    )


def parse_log(text: str) -> tuple[str, list[Qso]]:
    """Parse a whole Cabrillo log.

    Args:
        text: The decoded log file.

    Returns:
        A tuple of the entrant's callsign, empty if the header lacks one, and
        every parsed contact in log order, duplicates included so that they can
        be counted.
    """
    entrant = ""
    qsos: list[Qso] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not entrant and line.upper().startswith("CALLSIGN:"):
            entrant = line.split(":", 1)[1].strip().upper()
            continue
        qso = parse_qso_line(line)
        if qso is not None:
            qsos.append(qso)
    return entrant, qsos
