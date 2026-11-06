"""Kalshi Sports +EV Scanner (Streamlit)."""
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from core import assess, devig_power, kalshi_fee
from matching import build_siblings, match_market

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
ODDS = "https://api.the-odds-api.com/v4"
SPORTS = {
    "NBA": ("KXNBAGAME", "basketball_nba"),
    "NFL": ("KXNFLGAME", "americanfootball_nfl"),
    "NHL": ("KXNHLGAME", "icehockey_nhl"),
    "MLB": ("KXMLBGAME", "baseball_mlb"),
    "NCAAF": ("KXNCAAFGAME", "americanfootball_ncaaf"),
    "NCAAB": ("KXNCAAMBGAME", "basketball_ncaab"),
}
BOOK_WEIGHT = {
    "pinnacle": 2.0, "lowvig": 1.0,                                   # sharp / low-margin
    "draftkings": 1.0, "fanduel": 1.0, "betmgm": 1.0, "williamhill_us": 1.0, "caesars": 1.0,
    "betrivers": 1.0, "espnbet": 1.0, "thescore": 1.0, "fanatics": 1.0, "hardrockbet": 1.0,
    "ballybet": 0.75, "betparx": 0.75, "unibet_us": 0.75, "superbook": 0.75,
    "bovada": 0.5, "betonlineag": 0.5, "mybookieag": 0.5, "betus": 0.5,  # softer offshore lines
}
BOOK_NAMES = {"pinnacle": "Pinnacle", "lowvig": "LowVig", "draftkings": "DraftKings", "fanduel": "FanDuel",
              "betmgm": "BetMGM", "williamhill_us": "Caesars", "caesars": "Caesars", "betrivers": "BetRivers",
              "espnbet": "ESPN BET", "thescore": "theScore", "fanatics": "Fanatics", "hardrockbet": "Hard Rock",
              "ballybet": "Bally", "betparx": "betPARX", "unibet_us": "Unibet", "superbook": "SuperBook",
              "bovada": "Bovada", "betonlineag": "BetOnline", "mybookieag": "MyBookie", "betus": "BetUS"}
ORDER = {"🟢 Strong": 0, "🟡 Marginal": 1, "🔴 Skip": 2}


# ---------- data ----------
def dollars(m, key):
    d = m.get(f"{key}_dollars")
    if d not in (None, ""):
        return float(d)
    c = m.get(key)
    return c / 100 if c else None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_kalshi(series):
    out, cursor = [], None
    while True:
        params = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{KALSHI}/markets", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        out += data.get("markets", [])
        cursor = data.get("cursor")
        if not cursor:
            return out


@st.cache_data(ttl=30, show_spinner=False)
def fetch_depth(ticker, side, ask):
    """Contracts you can buy at <= ask+1c. Buying YES hits NO bids (and vice versa). None if unknown."""
    try:
        r = requests.get(f"{KALSHI}/markets/{ticker}/orderbook", timeout=10)
        r.raise_for_status()
        data = r.json()
        ob = data.get("orderbook") or {}
        fp = data.get("orderbook_fp") or {}
        want = "no" if side == "YES" else "yes"
        levels = ob.get(want) or fp.get(f"{want}_dollars") or ob.get(f"{want}_dollars") or []
        total = 0.0
        for lvl in levels:
            c = float(lvl[0])
            c = c if c > 1 else c * 100              # cents either way
            if 100 - c <= round(ask * 100) + 1:      # implied ask for our side
                total += float(lvl[1])
        return total
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)  # 5 min cache protects API credits
def fetch_consensus(sport_key, api_key, regions):
    r = requests.get(f"{ODDS}/sports/{sport_key}/odds", timeout=20, params={
        "apiKey": api_key, "regions": regions, "markets": "h2h", "oddsFormat": "decimal"})
    r.raise_for_status()
    remaining = r.headers.get("x-requests-remaining", "?")
    now, events = datetime.now(timezone.utc), []
    for ev in r.json():
        if datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")) <= now:
            continue                                  # already started: prices are live, odds are stale
        acc, wsum, books = defaultdict(float), 0.0, {}
        for bk in ev["bookmakers"]:
            w = BOOK_WEIGHT.get(bk["key"])
            mk = next((m for m in bk["markets"] if m["key"] == "h2h"), None)
            if not w or not mk:
                continue
            fair = devig_power({o["name"]: o["price"] for o in mk["outcomes"]})
            books[bk["key"]] = fair
            for name, p in fair.items():
                acc[name] += w * p
            wsum += w
        if wsum:
            events.append({"home": ev["home_team"], "away": ev["away_team"], "start": ev["commence_time"],
                           "fair": {k: v / wsum for k, v in acc.items()}, "books": books})
    return events, remaining


def et(start):
    t = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
    return t.strftime("%a %b %d, %I:%M %p ET")


def scan(markets, events, min_ev, max_spread, max_gap, bankroll, kelly_frac):
    sib, cands, matched, suspicious = build_siblings(markets), [], 0, 0
    for m in markets:
        hit, _ = match_market(m, events, sib)
        if not hit:
            continue
        matched += 1
        ev, team = hit
        fair_yes = ev["fair"].get(team)
        yes_ask, no_ask, yes_bid = dollars(m, "yes_ask"), dollars(m, "no_ask"), dollars(m, "yes_bid")
        if fair_yes is None or not yes_ask:
            continue
        if yes_bid and yes_ask - yes_bid > max_spread:
            continue
        for side, price, p in (("YES", yes_ask, fair_yes), ("NO", no_ask, 1 - fair_yes)):
            if not price or not 0.02 < price < 0.98:
                continue
            if abs(p - price) > max_gap:
                suspicious += 1
                continue
            if p - price - kalshi_fee(price, 100) / 100 >= min_ev:
                used = [k for k, b in ev["books"].items() if team in b]
                bp = [ev["books"][k][team] if side == "YES" else 1 - ev["books"][k][team] for k in used]
                cands.append((p - price, m, ev, team, side, price, p, bp, used))
    cands.sort(key=lambda c: -c[0])
    seen, unique = set(), []          # "Team A YES" and "Team B NO" are the same bet: keep the better-priced one
    for c in cands:
        _, m, ev, team, side, *_ = c
        backed = team if side == "YES" else next((t for t in (ev["home"], ev["away"]) if t != team), team)
        key = (ev["home"], ev["start"], backed) if len(ev["fair"]) == 2 else c[1]["ticker"] + side
        if key not in seen:
            seen.add(key)
            unique.append(c)
    cands, rows = unique, []
    for _, m, ev, team, side, price, p, bp, used in cands[:20]:   # depth lookups only for the best 20
        depth = fetch_depth(m["ticker"], side, price)
        a = assess(p, bp, price, bankroll, kelly_frac, depth, min_ev)
        rows.append({"Verdict": a["verdict"], "Game": f"{ev['away']} @ {ev['home']}", "Bet": f"{team} {side}",
                     "Kalshi price": price, "Fair prob": p, "Books agree range": f"{a['p_low']:.0%} to {a['p_high']:.0%}",
                     "# Books": a["n_books"], "Books used": ", ".join(sorted({BOOK_NAMES.get(k, k) for k in used})), "EV / contract": a["ev"], "Buy (contracts)": a["contracts"],
                     "Cost ($)": a["cost"], "Expected profit ($)": a["exp_profit"], "Why": a["why"],
                     "Start": et(ev["start"]), "Ticker": m["ticker"]})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Verdict", "EV / contract"], key=lambda c: c.map(ORDER) if c.name == "Verdict" else -c)
        df = df.reset_index(drop=True)
    return df, matched, suspicious


# ---------- UI ----------
st.set_page_config(page_title="Kalshi +EV Scanner", page_icon="📈", layout="wide")
st.title("📈 Kalshi Sports +EV Scanner")
st.caption("Compares Kalshi prices to the devigged sportsbook consensus, net of Kalshi fees, then grades each edge.")

with st.sidebar:
    st.header("Settings")
    sport = st.selectbox("Sport", list(SPORTS))
    bankroll = st.number_input("Bankroll ($)", 5, 1_000_000, 100, 5, help="Only used to size bets.")
    kelly_frac = st.slider("Kelly fraction", 0.05, 1.0, 0.25, 0.05)
    min_ev = st.slider("Min EV per $1 contract", 0.0, 0.10, 0.02, 0.005, format="%.3f")
    max_spread = st.slider("Max bid/ask spread ($)", 0.01, 0.20, 0.04, 0.01)
    max_gap = st.slider("Max price vs. fair gap", 0.05, 0.50, 0.15, 0.01,
                        help="Edges bigger than this are hidden as likely bad matches or stale lines.")
    more_books = st.checkbox("Include extra books (us2 region)", value=True,
                             help="Adds ESPN BET, Fanatics, Hard Rock, Bally etc. Costs 1 extra Odds API credit per refresh.")
    show_skips = st.checkbox("Show 🔴 Skip rows", value=False)
    api_key = st.secrets.get("ODDS_API_KEY", "") or st.text_input(
        "Odds API key", type="password", help="Free key at the-odds-api.com")
    if st.button("🔄 Refresh data", width="stretch"):
        st.cache_data.clear()

if not api_key:
    st.info("Add your Odds API key in the sidebar (or in Streamlit secrets as `ODDS_API_KEY`).")
    st.stop()

series, sport_key = SPORTS[sport]
try:
    with st.spinner("Fetching Kalshi and sportsbook data..."):
        markets = fetch_kalshi(series)
        events, remaining = fetch_consensus(sport_key, api_key, "us,us2,eu" if more_books else "us,eu")
        df, matched, suspicious = scan(markets, events, min_ev, max_spread, max_gap, bankroll, kelly_frac)
except requests.HTTPError as e:
    st.error(f"API error: {e}")
    st.stop()

n_strong = int((df["Verdict"] == "🟢 Strong").sum()) if not df.empty else 0
n_marg = int((df["Verdict"] == "🟡 Marginal").sum()) if not df.empty else 0
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🟢 Strong", n_strong)
c2.metric("🟡 Marginal", n_marg)
c3.metric("Matched markets", f"{matched}/{len(markets)}")
c4.metric("Upcoming games (books)", len(events))
c5.metric("Odds API credits", remaining)

with st.expander("How to read this / how to decide", expanded=n_strong + n_marg == 0):
    st.markdown("""
**🟢 Strong**: 3+ books agree, the edge survives even if the *lowest* book is right, the order book has depth,
and the price isn't extreme. Still not a guarantee, since even good bets lose often.

**🟡 Marginal**: there's an edge on paper, but at least one warning (see the **Why** column): a longshot or heavy favorite,
only 2 books, books disagreeing, or a thin order book. Use a smaller size, or pass.

**🔴 Skip**: one book only, too small to be worth the fees at your bankroll, no contracts available, or the lowest book shows no edge.

**Before any trade:** confirm the game and side on Kalshi (the **Ticker** column), check the live sportsbook line, and only buy
the number of contracts shown (sized off a haircut probability, not the optimistic one). *Expected profit* is an average over many
bets, and a single bet is mostly luck. Not financial advice.
""")

if suspicious:
    st.caption(f"⚠️ Hid {suspicious} edge(s) larger than the max gap as likely mismatches or stale lines.")

view = df if (show_skips or df.empty) else df[df["Verdict"] != "🔴 Skip"]
if view.empty:
    st.warning("No actionable edges right now. That's normal: real +EV spots are rare. "
               "Tick 'Show 🔴 Skip rows' to see what was filtered and why.")
else:
    st.dataframe(view, width="stretch", hide_index=True, column_config={
        "Kalshi price": st.column_config.NumberColumn(format="$%.2f"),
        "Fair prob": st.column_config.NumberColumn(format="percent"),
        "EV / contract": st.column_config.NumberColumn(format="$%.3f"),
        "Cost ($)": st.column_config.NumberColumn(format="$%.2f"),
        "Expected profit ($)": st.column_config.NumberColumn(format="$%.2f"),
        "Why": st.column_config.TextColumn(width="large"),
    })

with st.expander("Matching check: Kalshi markets vs. sportsbook games"):
    rows, sib = [], build_siblings(markets)
    for m in markets:
        hit, reason = match_market(m, events, sib)
        rows.append({"Kalshi market": f"{m.get('title','')} | YES = {m.get('yes_sub_title','')}",
                     "Ticker": m["ticker"],
                     "Matched to": f"{hit[0]['away']} @ {hit[0]['home']} (YES = {hit[1]})" if hit else "—",
                     "Status": reason})
    mdf = pd.DataFrame(rows)
    if not mdf.empty:
        mdf = mdf.sort_values("Status", key=lambda c: c != "ok")
    st.dataframe(mdf, width="stretch", hide_index=True)

st.caption("Not financial advice. Verify matches and live prices before trading. "
           "Stale sportsbook lines can look like edges.")
