"""Listing text primitives shared by every parser: clauses, labelled spec lines,
"not the installed part" context, and negation. Pure functions, upper-case text."""
import re

# A clause is one spec line or bullet: sellers write "Netzteil: be quiet 750W | RAM: 32GB".
CLAUSE_SPLIT_RE = re.compile(r"[\n|;•·✅✔➤►]+|\s[-–]\s")

LABELS = {
    "gpu": r"GRAFIKKARTE|GRAFIK|GPU|GRAKA|VIDEOKARTE",
    "cpu": r"PROZESSOR|CPU",
    "ram": r"ARBEITSSPEICHER|RAM|SPEICHER",
    "board": r"MAINBOARD|MOTHERBOARD|BOARD",
    "psu": r"NETZTEIL|PSU|STROMVERSORGUNG",
    "storage": r"SSD|FESTPLATTE|SPEICHERPLATZ|NVME|M\.2|STORAGE",
    "cooler": r"CPU[\s-]*K(?:Ü|UE)HLER|K(?:Ü|UE)HLER|K(?:Ü|UE)HLUNG",
    "case": r"GEH(?:Ä|AE)USE|CASE|TOWER",
}
LABEL_RES = {part: re.compile(rf"^\W*(?:{names})\s*(?:\([^)]*\))?\s*[:=]") for part, names in LABELS.items()}

# Words that mean a number or model is NOT what is installed: limits, support, history.
NOT_INSTALLED_BEFORE_RE = re.compile(
    # limits sit right before the number ("max. 128GB", "erweiterbar auf 64GB"); "MAX" alone is also a
    # board name suffix ("B450 Tomahawk MAX, 32GB"), so it must touch the number
    r"(?:(?:ERWEITERBAR|AUFR(?:Ü|UE)STBAR)\s+(?:AUF|BIS)|BIS\s+(?:ZU|MAX\.?)|MAX\.|MAXIMAL|UNTERST(?:Ü|UE)TZT"
    r"|KOMPATIBEL\s+MIT)\W+(?:[\w.+-]+\W+)?$"
    r"|MAX\s+$"
    # history: the part that used to be there ("vorher GTX 1060", "statt der alten RTX 2060")
    r"|(?:VORHER|EHEMALS|ALTE[NRS]?|STATT|ERSETZT|FR(?:Ü|UE)HER|URSPR(?:Ü|UE)NGLICH|UPGRADE\s+VON)\W+(?:[\w.+-]+\W+){0,2}$")
NOT_INSTALLED_AFTER_RE = re.compile(
    # "32GB, erweiterbar auf 128GB" keeps the 32: only words that turn the number itself into a limit
    r"^\W*(?:[\w.+-]+\W+)?(?:M(?:Ö|OE)GLICH|UNTERST(?:Ü|UE)TZT|READY|SUPPORT|KOMPATIBEL)")
NEGATION_RE = re.compile(r"(?:KEIN\w*|OHNE|NICHT|NIE)\s+(?:[\w.+-]+\s+)?$")
CONTEXT_CHARS = 40


def clauses(title: str, desc: str) -> list[str]:
    """Title first, then description clauses, all upper-case and stripped."""
    parts = [title] + CLAUSE_SPLIT_RE.split(desc)
    return [p.strip().upper() for p in parts if p.strip()]


def labelled(cls: list[str], part: str) -> list[str]:
    """Clauses written as "<Label>: value" for `part`."""
    return [c for c in cls if LABEL_RES[part].match(c)]


def by_priority(cls: list[str], part: str) -> list[str]:
    """Labelled clauses first, then the title, then everything else (no repeats)."""
    first = labelled(cls, part)
    return first + [c for c in cls if c not in first]


def installed(clause: str, start: int, end: int) -> bool:
    """False when the match at clause[start:end] is a limit, support note or history."""
    before = clause[max(0, start - CONTEXT_CHARS):start]
    after = clause[end:end + CONTEXT_CHARS]
    return not (NOT_INSTALLED_BEFORE_RE.search(before) or NOT_INSTALLED_AFTER_RE.search(after))


def negated(clause: str, start: int) -> bool:
    """True for "kein Netzteil", "ohne SSD", "nicht defekt" (same clause, <= 1 word between)."""
    return bool(NEGATION_RE.search(clause[max(0, start - CONTEXT_CHARS):start]))
