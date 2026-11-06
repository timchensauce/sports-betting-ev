"""Pure betting math: devig, fees, sizing, and the Bet / Marginal / Skip verdict."""
import math


def kalshi_fee(price, contracts):
    """Kalshi taker fee in dollars for the whole order: ceil(0.07*C*P*(1-P)) to the cent."""
    return math.ceil(0.07 * contracts * price * (1 - price) * 100 - 1e-9) / 100


def kelly(p, price):
    return max(0.0, (p - price) / (1 - price)) if 0 < price < 1 else 0.0


def devig_power(decimal_odds):
    """Power devig {outcome: decimal odds} -> fair probs. Unlike proportional scaling, it takes
    more vig off longshots (books shade them more), so longshot probabilities aren't overstated."""
    q = {k: 1 / v for k, v in decimal_odds.items()}
    if sum(q.values()) <= 1:
        t = sum(q.values())
        return {k: v / t for k, v in q.items()}
    lo, hi = 1.0, 10.0
    for _ in range(60):
        k = (lo + hi) / 2
        lo, hi = (k, hi) if sum(v ** k for v in q.values()) > 1 else (lo, k)
    k = (lo + hi) / 2
    f = {n: v ** k for n, v in q.items()}
    t = sum(f.values())
    return {n: v / t for n, v in f.items()}


def assess(p, book_probs, price, bankroll, kelly_frac, depth=None, min_ev=0.02):
    """Size and grade one Kalshi contract.
    p: consensus fair prob; book_probs: each book's fair prob for this bet; price: Kalshi ask ($);
    depth: contracts available at <= ask+1c (None = unknown)."""
    n_books = len(book_probs)
    p_low = min(book_probs) if n_books >= 2 else p - 0.03       # pessimistic estimate
    p_high = max(book_probs) if book_probs else p
    p_size = (p + p_low) / 2                                     # size off a haircut probability
    wanted = int(bankroll * kelly_frac * kelly(p_size, price) / price)
    contracts = wanted if depth is None else min(wanted, int(depth))

    n = max(contracts, 1)
    fee_pc = kalshi_fee(price, n) / n
    ev = p - price - fee_pc
    cons_ev = p_low - price - fee_pc

    why, flags, skip = [], 0, False
    if n_books < 2:
        skip = True
        why.append("Only 1 book prices this game, so there's no cross-check")
    else:
        why.append(f"{n_books} books priced it ({p_low:.0%} to {p_high:.0%})")
        if n_books == 2:
            flags += 1
            why.append("only 2 books")
    if wanted < 1:
        skip = True
        why.append("Kelly size is under 1 contract (edge too small for your bankroll)")
    elif contracts < 1:
        skip = True
        why.append("no contracts available near this price")
    elif depth is not None and depth < wanted:
        flags += 1
        why.append(f"thin order book: only {int(depth)} contracts near this price")
    if depth is None:
        why.append("order book depth unknown, check before trading")
    if ev < min_ev and not skip:
        skip = True
        why.append("fees at your size shrink the edge below your minimum")
    if cons_ev < 0 and not skip:
        if ev < 0.02:
            skip = True
            why.append("lowest book shows no edge")
        else:
            flags += 1
            why.append("books disagree: the lowest one shows no edge")
    elif 0 <= cons_ev < 0.015 and not skip:
        flags += 1
        why.append("edge is thin if the lowest book is right")
    if (price < 0.15 or price > 0.90) and not skip:
        flags += 1
        why.append("extreme price: high variance and vig-bias risk")

    verdict = "🔴 Skip" if skip else ("🟢 Strong" if flags == 0 else "🟡 Marginal")
    return {"verdict": verdict, "contracts": contracts if not skip else 0, "ev": ev, "cons_ev": cons_ev,
            "p_low": p_low, "p_high": p_high, "n_books": n_books,
            "cost": contracts * price + kalshi_fee(price, n) if contracts else 0.0,
            "exp_profit": contracts * ev if contracts else 0.0, "why": " · ".join(why)}
