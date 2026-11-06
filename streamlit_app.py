"""Kalshi Sports +EV Scanner (Streamlit)."""
import math
from collections import defaultdict
from difflib import SequenceMatcher

import pandas as pd
import requests
import streamlit as st

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
BOOK_WEIGHT = {"pinnacle": 2.0, "draftkings": 1.0, "fanduel": 1.0,
               "betmgm": 1.0, "caesars": 1.0, "betrivers": 1.0}


# ---------- math ----------
def kalshi_fee(price, contracts=100):
    return math.ceil(0.07 * contracts * price * (1 - price) * 100 - 1e-9) / 100


def ev_per_contract(p, price):
    return p - price - kalshi_fee(price) / 100


def kelly(p, price):
    return max(0.0, (p - price) / (1 - price)) if 0 < price < 1 else 0.0


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


@st.cache_data(ttl=300, show_spinner=False)  # 5 min cache protects API credits
def fetch_consensus(sport_key, api_key):
    r = requests.get(f"{ODDS}/sports/{sport_key}/odds", timeout=20, params={
        "apiKey": api_key, "regions": "us,eu", "markets": "h2h", "oddsFormat": "decimal"})
    r.raise_for_status()
    remaining = r.headers.get("x-requests-remaining", "?")
    events = []
    for ev in r.json():
        acc, wsum = defaultdict(float), 0.0
        for bk in ev["bookmakers"]:
            w = BOOK_WEIGHT.get(bk["key"])
            mk = next((m for m in bk["markets"] if m["key"] == "h2h"), None)
            if not w or not mk:
                continue
            inv = {o["name"]: 1 / o["price"] for o in mk["outcomes"]}
            tot = sum(inv.values())
            for name, v in inv.items():
                acc[name] += w * v / tot
            wsum += w
        if wsum:
            events.append({"home": ev["home_team"], "away": ev["away_team"],
                           "start": ev["commence_time"],
                           "fair": {k: v / wsum for k, v in acc.items()}})
    return events, remaining


# ---------- matching ----------
def norm(s):
    return "".join(c for c in s.lower() if c.isalnum() or c == " ")


def team_in_text(team, text):
    toks = [t for t in norm(team).split() if len(t) > 3]
    return bool(toks) and sum(t in text for t in toks) >= max(1, len(toks) // 2)


def match_market(m, events):
    text = norm(m.get("title", "") + " " + m.get("yes_sub_title", ""))
    sub = norm(m.get("yes_sub_title", ""))
    for ev in events:
        if team_in_text(ev["home"], text) and team_in_text(ev["away"], text):
            best = max((ev["home"], ev["away"]),
                       key=lambda t: SequenceMatcher(None, sub, norm(t)).ratio()
                       + (0.5 if team_in_text(t, sub) else 0))
            return ev, best
    return None


def scan(markets, events, min_ev, max_spread, bankroll, kelly_frac):
    rows, matched = [], 0
    for m in markets:
        hit = match_market(m, events)
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
            e = ev_per_contract(p, price)
            if e >= min_ev:
                rows.append({
                    "Game": f"{ev['away']} @ {ev['home']}",
                    "Bet": f"{team} {side}",
                    "Kalshi price": price,
                    "Fair prob": p,
                    "EV / contract": e,
                    "ROI": e / price,
                    "Kelly stake ($)": round(bankroll * kelly_frac * kelly(p, price), 2),
                    "Start (UTC)": ev["start"],
                    "Ticker": m["ticker"],
                })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("EV / contract", ascending=False).reset_index(drop=True)
    return df, matched


# ---------- UI ----------
st.set_page_config(page_title="Kalshi +EV Scanner", page_icon="📈", layout="wide")
st.title("📈 Kalshi Sports +EV Scanner")
st.caption("Compares Kalshi prices to the devigged sportsbook consensus, net of Kalshi fees.")

with st.sidebar:
    st.header("Settings")
    sport = st.selectbox("Sport", list(SPORTS))
    min_ev = st.slider("Min EV per $1 contract", 0.0, 0.10, 0.01, 0.005, format="%.3f")
    max_spread = st.slider("Max bid/ask spread ($)", 0.01, 0.20, 0.06, 0.01)
    bankroll = st.number_input("Bankroll ($)", 100, 1_000_000, 1000, 100)
    kelly_frac = st.slider("Kelly fraction", 0.05, 1.0, 0.25, 0.05)
    api_key = st.secrets.get("ODDS_API_KEY", "") or st.text_input(
        "Odds API key", type="password", help="Free key at the-odds-api.com")
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()

if not api_key:
    st.info("Add your Odds API key in the sidebar (or in Streamlit secrets as `ODDS_API_KEY`).")
    st.stop()

series, sport_key = SPORTS[sport]
try:
    with st.spinner("Fetching Kalshi and sportsbook data..."):
        markets = fetch_kalshi(series)
        events, remaining = fetch_consensus(sport_key, api_key)
except requests.HTTPError as e:
    st.error(f"API error: {e}")
    st.stop()

df, matched = scan(markets, events, min_ev, max_spread, bankroll, kelly_frac)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Kalshi markets", len(markets))
c2.metric("Sportsbook games", len(events))
c3.metric("Matched markets", matched)
c4.metric("Odds API credits left", remaining)

if df.empty:
    st.warning("No +EV edges above your threshold right now.")
else:
    st.subheader(f"{len(df)} edge(s) found")
    st.dataframe(df, use_container_width=True, hide_index=True, column_config={
        "Kalshi price": st.column_config.NumberColumn(format="$%.2f"),
        "Fair prob": st.column_config.NumberColumn(format="percent"),
        "EV / contract": st.column_config.NumberColumn(format="$%.3f"),
        "ROI": st.column_config.NumberColumn(format="percent"),
        "Kelly stake ($)": st.column_config.NumberColumn(format="$%.0f"),
    })

with st.expander("Matching check: Kalshi markets vs. sportsbook games"):
    rows = []
    for m in markets:
        hit = match_market(m, events)
        rows.append({"Kalshi": f"{m.get('title','')} | {m.get('yes_sub_title','')}",
                     "Matched to": f"{hit[0]['away']} @ {hit[0]['home']} → {hit[1]}" if hit else "—"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.caption("Not financial advice. Verify matches and live prices before trading. "
           "Stale sportsbook lines can look like edges.")
