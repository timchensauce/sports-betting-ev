"""Run: python test_matching.py  (regression tests from the bad export)"""
from matching import build_siblings, match_market

EVENTS = [
    {"home": "Michigan Wolverines", "away": "Michigan State Spartans", "start": "2026-11-08T00:30:00Z"},
    {"home": "East Carolina Pirates", "away": "South Florida Bulls", "start": "2026-11-07T00:30:00Z"},
    {"home": "Texas Tech Red Raiders", "away": "West Virginia Mountaineers", "start": "2026-11-08T02:30:00Z"},
    {"home": "South Carolina Gamecocks", "away": "Texas A&M Aggies", "start": "2026-11-07T20:00:00Z"},
]

def mk(ticker, title, sub):
    return {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "title": title, "yes_sub_title": sub}

# Markets that were WRONGLY matched before: must now be rejected
BAD = [
    mk("KXNCAAFGAME-26NOV14MICHORE-MICH", "Oregon at Michigan Winner?", "Michigan"),
    mk("KXNCAAFGAME-26NOV07SEMOTNST-SEMO", "Southeast Missouri at Tennessee State Winner?", "Southeast Missouri"),
    mk("KXNCAAFGAME-26NOV06VTSMU-VT", "Virginia Tech at SMU Winner?", "Virginia Tech"),
    mk("KXNCAAFGAME-26NOV07ALSTTXSO-TXSO", "Alabama State at Texas Southern Winner?", "Texas Southern"),
    mk("KXNCAAFGAME-26NOV07IWSELA-SELA", "Incarnate Word at SE Louisiana Winner?", "SE Louisiana"),
]
# Markets that SHOULD match, with the correct YES team
GOOD = [
    (mk("KXNCAAFGAME-26NOV07MSUMICH-MSU", "Michigan State at Michigan Winner?", "Michigan State"), "Michigan State Spartans"),
    (mk("KXNCAAFGAME-26NOV07MSUMICH-MICH", "Michigan State at Michigan Winner?", "Michigan"), "Michigan Wolverines"),
    (mk("KXNCAAFGAME-26NOV06USFECU-USF", "South Florida at East Carolina Winner?", "South Florida"), "South Florida Bulls"),
    (mk("KXNCAAFGAME-26NOV07WVUTTU-TTU", "West Virginia at Texas Tech Winner?", "Texas Tech"), "Texas Tech Red Raiders"),
    (mk("KXNCAAFGAME-26NOV07TXAMSCAR-TXAM", "Texas A&M at South Carolina Winner?", "Texas A&M"), "Texas A&M Aggies"),
]

def sib_for(*markets):
    return build_siblings(list(markets))

for m in BAD:
    hit, why = match_market(m, EVENTS)
    assert hit is None, f"false match: {m['ticker']} -> {hit}"
    print("rejected  ", m["ticker"], "-", why)
for m, want in GOOD:
    hit, why = match_market(m, EVENTS)
    assert hit and hit[1] == want, f"bad: {m['ticker']} -> {hit} ({why})"
    print("matched   ", m["ticker"], "->", hit[1])

# ---- NBA false matches from the 11/06 23:27 export ----
NBA = [
    {"home": "Memphis Grizzlies", "away": "Oklahoma City Thunder", "start": "2026-11-07T01:10:00Z"},  # Nov 6 local
    {"home": "Atlanta Hawks", "away": "Washington Wizards", "start": "2026-11-07T00:10:00Z"},          # Nov 6 local
]
wasokc = [mk("KXNBAGAME-26NOV07WASOKC-OKC", "Washington at Oklahoma City Winner?", "Oklahoma City"),
          mk("KXNBAGAME-26NOV07WASOKC-WAS", "Washington at Oklahoma City Winner?", "Washington")]
bknatl = [mk("KXNBAGAME-26NOV07BKNATL-ATL", "Brooklyn at Atlanta Winner?", "Atlanta"),
          mk("KXNBAGAME-26NOV07BKNATL-BKN", "Brooklyn at Atlanta Winner?", "Brooklyn")]
untitled = [mk("KXNBAGAME-26NOV07WASOKC-OKC", "Will the Thunder win?", "Oklahoma City")]  # title can't be parsed
allm = wasokc + bknatl
for m in allm:
    hit, why = match_market(m, NBA, build_siblings(allm))
    assert hit is None, f"false match: {m['ticker']} -> {hit}"
    print("rejected  ", m["ticker"], "-", why)

# date lines up (game is Nov 7 local) but opponent is wrong -> sibling check must still reject
NBA_SAMEDAY = [{"home": "Memphis Grizzlies", "away": "Oklahoma City Thunder", "start": "2026-11-08T00:10:00Z"}]
for m in wasokc:
    hit, why = match_market(m, NBA_SAMEDAY, build_siblings(wasokc))
    assert hit is None, f"opponent check failed: {m['ticker']} -> {hit}"
    print("rejected  ", m["ticker"], "- same date, wrong opponent:", why)

# unverifiable opponent (no siblings, unparseable title) -> reject
hit, why = match_market(untitled[0], NBA_SAMEDAY, build_siblings(untitled))
assert hit is None
print("rejected  ", untitled[0]["ticker"], "- unverifiable:", why)

# real game still matches
REAL = [{"home": "Oklahoma City Thunder", "away": "Washington Wizards", "start": "2026-11-08T00:10:00Z"}]
for m, want in ((wasokc[0], "Oklahoma City Thunder"), (wasokc[1], "Washington Wizards")):
    hit, why = match_market(m, REAL, build_siblings(wasokc))
    assert hit and hit[1] == want, (m["ticker"], hit, why)
    print("matched   ", m["ticker"], "->", hit[1])

print("\nall tests passed")
