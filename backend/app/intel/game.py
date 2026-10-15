"""Stackelberg security games for patrol allocation: pure, deterministic numerics.

Model (Kiekintveld et al., AAMAS 2009; Korzhyk et al., JAIR 2011): n targets,
m homogeneous resources, each covering one target per period, so the defender
mixed strategy is a coverage vector c with 0 <= c_i <= 1 and sum(c) <= m.
For target i the attacker gets U_a^c(i) if it is covered, U_a^u(i) otherwise
(U_a^u >= U_a^c); the defender gets U_d^c(i) >= U_d^u(i).

* ``strong_stackelberg`` is exact for games without scheduling constraints:
  the ORIGAMI attack set at the minimal feasible attacker utility, with the
  attacker breaking ties in the defender's favour. The level is found by
  solving the piecewise-linear resource curve exactly (no LP solver).
* ``quantal_response`` optimises against a boundedly rational attacker
  (McKelvey & Palfrey 1995; Yang et al., AAMAS 2012, as used in PROTECT) by
  projected gradient ascent with Armijo backtracking from several
  deterministic starts, including the SSE strategy.
* ``comb_sample`` turns marginals into exactly m distinct targets, each with
  probability exactly c_i (systematic/comb sampling), after a random order.

All utilities are plain floats; callers own scaling and explainability.
"""
from dataclasses import dataclass
import math

EPS = 1e-12


@dataclass(frozen=True)
class Target:
    id: str
    attacker_covered: float
    attacker_uncovered: float
    defender_covered: float
    defender_uncovered: float

    @property
    def attacker_range(self):
        return self.attacker_uncovered - self.attacker_covered

    def attacker_utility(self, coverage):
        return coverage * self.attacker_covered + (1 - coverage) * self.attacker_uncovered

    def defender_utility(self, coverage):
        return coverage * self.defender_covered + (1 - coverage) * self.defender_uncovered


def validate(targets, resources):
    if resources < 0 or not math.isfinite(resources):
        raise ValueError("resources must be a finite non-negative number")
    seen = set()
    for t in targets:
        values = (t.attacker_covered, t.attacker_uncovered, t.defender_covered, t.defender_uncovered)
        if not all(math.isfinite(v) for v in values):
            raise ValueError(f"non-finite payoff for {t.id}")
        if t.attacker_uncovered < t.attacker_covered - EPS or t.defender_covered < t.defender_uncovered - EPS:
            raise ValueError(f"coverage must not help the attacker or hurt the defender at {t.id}")
        if t.id in seen:
            raise ValueError(f"duplicate target {t.id}")
        seen.add(t.id)


def required_coverage(target, level):
    """Least coverage that keeps the attacker's utility at target <= level."""
    if target.attacker_uncovered <= level:
        return 0.0
    if target.attacker_range <= EPS:
        return math.inf
    return (target.attacker_uncovered - level) / target.attacker_range


def resource_curve(targets, level):
    total = 0.0
    for t in targets:
        need = required_coverage(t, level)
        if need > 1:
            return math.inf
        total += need
    return total


def minimal_attacker_level(targets, resources):
    """Exact minimum u with resource_curve(u) <= resources (piecewise linear, decreasing)."""
    floor = max(t.attacker_covered for t in targets)
    top = max(t.attacker_uncovered for t in targets)
    if resource_curve(targets, floor) <= resources + EPS:
        return floor
    points = sorted({floor, top, *(t.attacker_uncovered for t in targets if floor < t.attacker_uncovered < top)})
    low = floor
    for high in points:
        if high <= low:
            continue
        if resource_curve(targets, high) <= resources + EPS:
            # resource_curve is linear on (low, high]: interpolate exactly.
            r_high = resource_curve(targets, high)
            slope = sum(1 / t.attacker_range for t in targets
                        if t.attacker_uncovered >= high and t.attacker_range > EPS)
            return max(low, high - (resources - r_high) / slope) if slope > 0 else high
        low = high
    return top


def strong_stackelberg(targets, resources):
    """Exact SSE for singleton schedules. Returns (coverage dict, attacked target id, level)."""
    validate(targets, resources)
    if not targets:
        return {}, None, None
    if resources >= len(targets) - EPS:
        coverage = {t.id: 1.0 for t in targets}
        best = max(targets, key=lambda t: (t.attacker_covered, t.defender_covered))
        return coverage, best.id, best.attacker_covered
    level = minimal_attacker_level(targets, resources)
    coverage = {t.id: min(1.0, required_coverage(t, level)) for t in targets}
    attack_set = [t for t in targets if t.attacker_utility(coverage[t.id]) >= level - 1e-9]
    # Defender-favourable tie breaking: the attacker picks the defender's preferred target.
    attacked = max(attack_set, key=lambda t: (t.defender_utility(coverage[t.id]), t.id))
    fill(targets, coverage, resources, protect=attacked.id)
    return coverage, attacked.id, level


def fill(targets, coverage, resources, protect=None, order=None):
    """Spend leftover resources without making any target more attractive to attack.

    Extra coverage only lowers attacker utility. The SSE target is filled last
    so the induced best response is unchanged whenever that is possible.
    """
    spare = resources - sum(coverage.values())
    ranked = order or sorted(targets, key=lambda t: (t.defender_covered - t.defender_uncovered, t.id), reverse=True)
    for t in [t for t in ranked if t.id != protect] + [t for t in ranked if t.id == protect]:
        if spare <= EPS:
            break
        add = min(1 - coverage[t.id], spare)
        coverage[t.id] += add
        spare -= add
    return coverage


def attacker_response(targets, coverage, model="stackelberg", rationality=0.0):
    """Attack probabilities under a perfectly rational (SSE tie-breaking) or quantal attacker."""
    utilities = {t.id: t.attacker_utility(coverage[t.id]) for t in targets}
    if model == "quantal":
        top = max(utilities.values())
        weights = {k: math.exp(rationality * (u - top)) for k, u in utilities.items()}
        total = sum(weights.values())
        return {k: w / total for k, w in weights.items()}
    best = max(utilities.values())
    candidates = [t for t in targets if utilities[t.id] >= best - 1e-9]
    choice = max(candidates, key=lambda t: (t.defender_utility(coverage[t.id]), t.id))
    return {t.id: float(t.id == choice.id) for t in targets}


def evaluate(targets, coverage, model="stackelberg", rationality=0.0):
    response = attacker_response(targets, coverage, model, rationality)
    by_id = {t.id: t for t in targets}
    defender = sum(p * by_id[k].defender_utility(coverage[k]) for k, p in response.items())
    attacker = sum(p * by_id[k].attacker_utility(coverage[k]) for k, p in response.items())
    return dict(defender_expected=defender, attacker_expected=attacker,
                attacker_max=max(t.attacker_utility(coverage[t.id]) for t in targets), response=response)


def project_capped_simplex(values, total):
    """Exact Euclidean projection onto {0 <= x_i <= 1, sum x <= total}.

    x_i = clip(v_i - tau, 0, 1) where f(tau) = sum x_i is continuous, non-increasing
    and linear between the breakpoints {v_i, v_i - 1}: binary search the breakpoints,
    then interpolate (O(n log n), no iteration tolerance).
    """
    def shifted(tau):
        return sum(min(1.0, max(0.0, v - tau)) for v in values)

    clipped = [min(1.0, max(0.0, v)) for v in values]
    if sum(clipped) <= total + EPS:
        return clipped
    points = sorted({*values, *(v - 1 for v in values)})
    low, high = 0, len(points) - 1
    # f(points[0]) = n > total >= 0 = f(points[-1]); keep f(points[low]) > total >= f(points[high]).
    while high - low > 1:
        mid = (low + high) // 2
        if shifted(points[mid]) > total:
            low = mid
        else:
            high = mid
    a, b = points[low], points[high]
    fa, fb = shifted(a), shifted(b)
    tau = b if fa - fb <= EPS else a + (fa - total) / (fa - fb) * (b - a)
    return [min(1.0, max(0.0, v - tau)) for v in values]


def quantal_response(targets, resources, rationality, iterations=400):
    """Defender optimum against a quantal-response attacker (local, multi-start, deterministic)."""
    validate(targets, resources)
    if not targets:
        return {}
    n = len(targets)
    if resources >= n - EPS:
        return {t.id: 1.0 for t in targets}

    def objective(c):
        return evaluate(targets, dict(zip((t.id for t in targets), c)), "quantal", rationality)["defender_expected"]

    def gradient(c):
        u = [t.attacker_utility(x) for t, x in zip(targets, c)]
        d = [t.defender_utility(x) for t, x in zip(targets, c)]
        top = max(u)
        w = [math.exp(rationality * (x - top)) for x in u]
        z = sum(w)
        q = [x / z for x in w]
        mean = sum(qi * di for qi, di in zip(q, d))
        grad = []
        for t, qi, di in zip(targets, q, d):
            du = -t.attacker_range
            dd = t.defender_covered - t.defender_uncovered
            grad.append(qi * dd + qi * rationality * du * (di - mean))
        return grad

    sse, _, _ = strong_stackelberg(targets, resources)
    starts = [[sse[t.id] for t in targets], [resources / n] * n]
    weights = [max(t.attacker_uncovered - t.attacker_covered, EPS) for t in targets]
    starts.append(project_capped_simplex([resources * w / sum(weights) for w in weights], resources))
    best, best_value = None, -math.inf
    for start in starts:
        c, value = project_capped_simplex(start, resources), None
        value = objective(c)
        step = 1.0
        for _ in range(iterations):
            g = gradient(c)
            gain = 0.0
            while step > 1e-9:
                candidate = project_capped_simplex([x + step * gi for x, gi in zip(c, g)], resources)
                moved = sum((a - b) * gi for a, b, gi in zip(candidate, c, g))
                new = objective(candidate)
                if new >= value + 1e-4 * moved and new > value:
                    c, value, gain = candidate, new, new - value
                    step *= 1.5
                    break
                step /= 2
            if gain <= 1e-12:
                break
        if value > best_value:
            best, best_value = c, value
    coverage = {t.id: x for t, x in zip(targets, best)}
    return fill(targets, coverage, resources)


def proportional(targets, resources, weights):
    """Water-filling coverage proportional to weights, capped at 1 (the legacy heuristic's marginals)."""
    coverage = {t.id: 0.0 for t in targets}
    remaining, free = float(min(resources, len(targets))), list(targets)
    while remaining > EPS and free:
        share = {t.id: max(weights.get(t.id, 0.0), 0.0) for t in free}
        total = sum(share.values())
        if total <= EPS:
            share, total = {k: 1.0 for k in share}, float(len(share))
        share = {k: remaining * v / total for k, v in share.items()}
        capped = [t for t in free if share[t.id] >= 1 - EPS]
        if not capped:
            for t in free:
                coverage[t.id] = share[t.id]
            break
        for t in capped:
            coverage[t.id] = 1.0
            remaining -= 1.0
        free = [t for t in free if t not in capped]
    return coverage


def comb_sample(coverage, count, rng):
    """Exactly ``count`` distinct ids; id i is drawn with probability exactly coverage[i].

    Requires sum(coverage) == count and each value in [0, 1]. A random order of
    the targets decorrelates which targets appear together.
    """
    ids = list(coverage)
    if abs(sum(coverage.values()) - count) > 1e-6 or any(not -EPS <= v <= 1 + EPS for v in coverage.values()):
        raise ValueError("comb sampling needs marginals in [0, 1] summing to the sample size")
    for i in range(len(ids) - 1, 0, -1):
        j = int(rng.random() * (i + 1))
        ids[i], ids[j] = ids[j], ids[i]
    offset = rng.random()
    chosen, cumulative, tooth = [], 0.0, 0
    for id in ids:
        start, cumulative = cumulative, cumulative + coverage[id]
        while tooth < count and start - 1e-12 <= offset + tooth < cumulative - 1e-12:
            chosen.append(id)
            tooth += 1
    while len(chosen) < count:
        # Floating-point remainder at the very end of the comb.
        chosen.append(next(id for id in reversed(ids) if id not in chosen))
    return chosen


def normalized_entropy(coverage):
    """Shannon entropy of the coverage distribution relative to its maximum (1 = least predictable)."""
    total = sum(coverage.values())
    if total <= EPS or len(coverage) < 2:
        return 0.0
    probabilities = [v / total for v in coverage.values() if v > EPS]
    return -sum(p * math.log(p) for p in probabilities) / math.log(len(coverage))
