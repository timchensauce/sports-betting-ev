"""Strict Kalshi-market <-> sportsbook-game matching."""
import re
from datetime import datetime, timedelta

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def norm(s):
    s = (s or "").lower().replace("&", "")
    s = re.sub(r"\bst\b\.?", "state", s)          # "Michigan St." -> "michigan state"
    return re.sub(r"[^a-z0-9 ]", " ", s).split()


def ticker_date(m):
    """Game date encoded in the ticker, e.g. KXNCAAFGAME-26NOV07MSUMICH-MSU -> 2026-11-07."""
    for t in (m.get("event_ticker"), m.get("ticker")):
        g = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", t or "")
        if g and g.group(2) in MONTHS:
            try:
                return datetime(2000 + int(g.group(1)), MONTHS[g.group(2)], int(g.group(3))).date()
            except ValueError:
                pass
    return None


def event_dates(ev):
    """Possible local US calendar dates (ET..PT) for a UTC start time. Never the raw UTC date."""
    start = datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
    return {(start - timedelta(hours=h)).date() for h in (4, 5, 6, 7, 8)}


def resolve(name, ev):
    """Which team of `ev` does `name` refer to? Returns the team or None if unclear.
    Exact full-name match beats school-name prefix (leftover = mascot words) beats mascot-only."""
    s = norm(name)
    if not s:
        return None
    scored = []
    for team in (ev["home"], ev["away"]):
        t = norm(team)
        if s == t:
            score = 0
        elif t[:len(s)] == s and len(t) - len(s) <= 3:
            score = len(t) - len(s)
        elif t[-len(s):] == s:
            score = 0.5
        else:
            continue
        scored.append((score, team))
    if not scored:
        return None
    scored.sort()
    if len(scored) == 2 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def split_title(title):
    t = re.sub(r"\s*(winner|wins?)\s*\??\s*$", "", title or "", flags=re.I).strip(" ?")
    parts = re.split(r"\s+(?:at|vs\.?|v\.?)\s+", t, maxsplit=1, flags=re.I)
    return parts if len(parts) == 2 else None


TIE = {"tie", "draw"}


def build_siblings(markets):
    """event_ticker -> team labels of every contract in that Kalshi event (the two sides of the game)."""
    sib = {}
    for m in markets:
        et = m.get("event_ticker") or m["ticker"].rsplit("-", 1)[0]
        name = m.get("yes_sub_title", "")
        if name and norm(name) and " ".join(norm(name)) not in TIE:
            sib.setdefault(et, []).append(name)
    return sib


def opponent_ok(m, ev, team, siblings):
    """Both sides of the Kalshi game must map to the two different teams of this sportsbook game."""
    et = m.get("event_ticker") or m["ticker"].rsplit("-", 1)[0]
    names = (siblings or {}).get(et, [])
    if len(names) >= 2:
        resolved = {resolve(n, ev) for n in names}
        return None not in resolved and resolved == {ev["home"], ev["away"]}
    parts = split_title(m.get("title", ""))
    if parts:
        a, b = resolve(parts[0], ev), resolve(parts[1], ev)
        return bool(a and b and a != b and team in (a, b))
    return False  # can't verify the opponent -> don't trade it


def match_market(m, events, siblings=None):
    """Returns ((event, yes_team), "ok") or (None, reason)."""
    d = ticker_date(m)
    if not d:
        return None, "no date in ticker"
    sub = m.get("yes_sub_title", "")
    cands, name_date_hits = [], 0
    for ev in events:
        if d not in event_dates(ev):
            continue
        team = resolve(sub, ev)
        if not team:
            continue
        name_date_hits += 1
        if opponent_ok(m, ev, team, siblings):
            cands.append((ev, team))
    if len(cands) == 1:
        return cands[0], "ok"
    if cands:
        return None, "ambiguous (multiple games)"
    if name_date_hits:
        return None, "team+date match but opponent doesn't (or can't be verified)"
    return None, "no sportsbook game with same date + team"
