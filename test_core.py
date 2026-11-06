"""Run: python test_core.py"""
from core import assess, devig_power, kalshi_fee

# devig: sums to 1, and shaves longshots more than proportional scaling would
odds = {"fav": 1.25, "dog": 4.6}
f = devig_power(odds)
assert abs(sum(f.values()) - 1) < 1e-9
raw = {k: 1 / v for k, v in odds.items()}
prop_dog = raw["dog"] / sum(raw.values())
assert f["dog"] < prop_dog, (f, prop_dog)
print(f"devig ok: dog {f['dog']:.3f} (power) vs {prop_dog:.3f} (proportional)")

# the Washington State longshot from the 11/06 export -> should NOT be a clean "Strong"
a = assess(0.1768, [0.15, 0.18, 0.19], 0.10, 1000, 0.25, depth=500)
assert a["verdict"].startswith("🟡"), a
print("WSU longshot:", a["verdict"], a["contracts"], "contracts |", a["why"])

# a clean favorite-range edge with deep book and 4 books agreeing -> Strong
a = assess(0.56, [0.545, 0.555, 0.565, 0.57], 0.50, 1000, 0.25, depth=400)
assert a["verdict"].startswith("🟢"), a
print("Clean edge:", a["verdict"], a["contracts"], "contracts")

# single-book consensus -> Skip
a = assess(0.30, [0.30], 0.22, 1000, 0.25, depth=400)
assert a["verdict"].startswith("🔴"), a
print("One book:", a["verdict"])

# lowest book shows no edge and consensus edge is small -> Skip
a = assess(0.53, [0.49, 0.53, 0.55], 0.50, 1000, 0.25, depth=400)
assert a["verdict"].startswith("🔴"), a
print("Books disagree:", a["verdict"])

# $10 bankroll: fees are computed on the real contract count, tiny stakes get skipped or sized honestly
a = assess(0.56, [0.55, 0.56, 0.57], 0.50, 10, 0.25)
print("$10 bankroll:", a["verdict"], a["contracts"], "contracts, EV/ct", round(a["ev"], 3))
assert a["contracts"] <= 2

# thin book caps size and flags
a = assess(0.56, [0.55, 0.56, 0.57], 0.50, 1000, 0.25, depth=3)
assert a["contracts"] == 3 and a["verdict"].startswith("🟡"), a
print("Thin book:", a["verdict"], a["contracts"], "contracts")

assert kalshi_fee(0.10, 100) == 0.63
print("\nall tests passed")
