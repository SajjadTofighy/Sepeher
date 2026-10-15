"""Patrol security game: exact numerics, Bayesian evidence, organisation parameters and governance."""

from copy import deepcopy
from datetime import date, datetime, timezone
import itertools
import math
import random
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import sim, store, tour_schedule
from app.intel import bayes, game, patrol, patrol_game, risk
from app.main import app
from app.models import PatrolGameSettings, PatrolPlan, PatrolPlanInput, PatrolStrategy
from app.seed import seed


def poisson_cdf_complement(a, x):
    """Independent closed form for integer a: P(a, x) = 1 - sum_{k<a} e^-x x^k / k!."""
    return 1 - sum(math.exp(-x + k * math.log(x) - math.lgamma(k + 1)) for k in range(a))


def random_game(rng, n):
    targets = []
    for i in range(n):
        uncovered = rng.uniform(0.1, 1)
        loss = -rng.uniform(0.1, 1)
        targets.append(game.Target(f"T{i}", rng.uniform(-1, uncovered), uncovered, rng.uniform(loss, 0), loss))
    return targets


class FixedRng:
    """Shuffle draws first, then the comb offset: enumerates offsets deterministically."""
    def __init__(self, values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0)


def headers(token_factory, *roles):
    return {"Authorization": "Bearer " + token_factory(sub="user-" + "-".join(roles), roles=list(roles))}


@pytest.fixture
def plan_case(monkeypatch):
    clock = SimpleNamespace(t=datetime(2099, 1, 1, 9, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(sim.time, "time", lambda: clock.t)
    monkeypatch.setattr(store, "now", lambda: sim.iso(clock.t))
    store.state.update(policies=[], incidents=[], missions=[], segments=[])
    base = deepcopy(store.state["facilities"][0])
    facilities = []
    for index, unmanned in enumerate((True, False, True, False)):
        facility = deepcopy(base)
        facility.update(id=f"FAC-G{index}", name=f"تأسیسات شماتیک {index}", lon=base["lon"] + index * 0.01, unmanned=unmanned)
        facilities.append(facility)
    store.state["facilities"] = facilities
    # Every target recently visited: no overdue mandatory stop, the game alone chooses.
    store.state["intel"]["coverage"] = dict(cursors={}, visits={f["id"]: dict(last_visit=sim.iso(clock.t - 600), last_asset_id="AST-001")
                                                               for f in facilities})
    asset = store.state["assets"][0]
    asset.update(speed=0, synthetic=True, track=[], patrol_base=[base["lon"], base["lat"]])
    return clock, facilities


def plan_request(clock, stops=2):
    return PatrolPlanInput(shift_start=sim.iso(clock.t + 3600), shift_end=sim.iso(clock.t + 9 * 3600),
                           asset_ids=["AST-001"], stops_per_patrol=stops)


def test_incomplete_gamma_and_quantiles_match_closed_forms():
    for a, x in [(1, 0.3), (3, 2.0), (7, 12.5), (50, 50.0), (200, 180.0)]:
        assert bayes.regularized_lower_gamma(a, x) == pytest.approx(poisson_cdf_complement(a, x), abs=1e-12)
    assert bayes.regularized_lower_gamma(0.5, 1.0) == pytest.approx(math.erf(1.0), abs=1e-13)
    assert bayes.gamma_quantile(1, 1, 0.5) == pytest.approx(math.log(2), rel=1e-10)
    # Chi-square table values: chi2_k = Gamma(k/2, rate 1/2).
    assert bayes.gamma_quantile(1, 0.5, 0.95) == pytest.approx(5.991464547107979, rel=1e-9)
    assert bayes.gamma_quantile(5, 0.5, 0.9) == pytest.approx(15.987179172105263, rel=1e-9)
    with pytest.raises(ValueError):
        bayes.gamma_quantile(1, 1, 1.0)


def test_posterior_decay_exposure_and_attempt_probability_arithmetic():
    estimate = bayes.posterior(2.0, 1.0, 3.0, 0.5, quantile=0.5, credible=0.9)
    assert (estimate["shape"], estimate["rate"]) == (5.0, 1.5) and estimate["mean"] == pytest.approx(10 / 3)
    assert estimate["lower"] < estimate["planning_rate"] < estimate["mean"] < estimate["upper"]
    assert bayes.regularized_lower_gamma(5, estimate["upper"] * 1.5) == pytest.approx(0.95, abs=1e-9)
    assert bayes.decay(365, 365) == 0.5 and bayes.decay(-3, 365) == 1.0
    assert bayes.discounted_exposure_years(bayes.YEAR_DAYS, bayes.YEAR_DAYS) == pytest.approx(0.5 / math.log(2))
    assert bayes.discounted_exposure_years(0, 365) == 0
    assert bayes.attempt_probability(1.0, 24 * bayes.YEAR_DAYS) == pytest.approx(1 - math.exp(-1))


def test_strong_stackelberg_is_optimal_against_exhaustive_coverage_grid():
    rng = random.Random(20991)
    grid = [i / 40 for i in range(41)]
    for _ in range(40):
        targets = random_game(rng, 3)
        resources = rng.choice([0.5, 1.0, 1.7])
        coverage, attacked, level = game.strong_stackelberg(targets, resources)
        assert sum(coverage.values()) == pytest.approx(resources) and all(0 <= c <= 1 for c in coverage.values())
        value = game.evaluate(targets, coverage)["defender_expected"]
        for point in itertools.product(grid, repeat=3):
            if sum(point) <= resources + 1e-12:
                other = dict(zip((t.id for t in targets), point))
                assert game.evaluate(targets, other)["defender_expected"] <= value + 1e-9
        assert game.evaluate(targets, coverage)["response"][attacked] == 1


def test_zero_sum_origami_equalizes_the_attack_set_at_the_minimax_level():
    rng = random.Random(5)
    for _ in range(25):
        targets = []
        for i in range(6):
            gain, caught = rng.uniform(0.2, 1), rng.uniform(-0.5, 0.1)
            targets.append(game.Target(f"Z{i}", caught, gain, -caught, -gain))
        coverage, _, level = game.strong_stackelberg(targets, 2)
        utilities = [t.attacker_utility(coverage[t.id]) for t in targets]
        assert max(utilities) == pytest.approx(level, abs=1e-9)
        attacked = [t for t, u in zip(targets, utilities) if u >= level - 1e-9]
        assert all(coverage[t.id] < 1 or t.attacker_covered == pytest.approx(level) for t in attacked)
        uniform = {t.id: 2 / 6 for t in targets}
        assert game.evaluate(targets, uniform)["attacker_max"] >= level - 1e-9


def test_projection_is_exact_and_quantal_response_is_a_local_optimum():
    rng = random.Random(9)
    for _ in range(100):
        values = [rng.uniform(-1, 2) for _ in range(7)]
        total = rng.uniform(0.5, 5)
        x = game.project_capped_simplex(values, total)
        assert all(0 <= v <= 1 for v in x) and sum(x) <= total + 1e-9
        for _ in range(20):
            y = [rng.random() for _ in values]
            scale = min(1.0, total / sum(y))
            y = [v * scale for v in y]
            assert sum((a - b) ** 2 for a, b in zip(values, x)) <= sum((a - b) ** 2 for a, b in zip(values, y)) + 1e-9
    targets = [game.Target(f"Q{i}", -0.2 * i, 0.5 + 0.1 * i, -0.1, -0.5 - 0.1 * i) for i in range(8)]
    coverage = game.quantal_response(targets, 3, 4.0)
    value = game.evaluate(targets, coverage, "quantal", 4.0)["defender_expected"]
    assert sum(coverage.values()) == pytest.approx(3)
    weights = {t.id: t.attacker_uncovered for t in targets}
    for start in ({t.id: 3 / 8 for t in targets}, game.strong_stackelberg(targets, 3)[0], game.proportional(targets, 3, weights)):
        assert value >= game.evaluate(targets, start, "quantal", 4.0)["defender_expected"] - 1e-9
    ids = [t.id for t in targets]
    for _ in range(40):
        direction = [rng.uniform(-1, 1) for _ in ids]
        moved = game.project_capped_simplex([coverage[i] + 1e-3 * d for i, d in zip(ids, direction)], 3)
        assert game.evaluate(targets, dict(zip(ids, moved)), "quantal", 4.0)["defender_expected"] <= value + 1e-7


def test_comb_sampling_reproduces_marginals_exactly_and_never_repeats():
    coverage = {"a": 0.9, "b": 0.6, "c": 0.3, "d": 0.2}
    counts, offsets = dict.fromkeys(coverage, 0), 1000
    for shuffle in ([0.0, 0.0, 0.0], [0.99, 0.5, 0.1]):
        for k in range(offsets):
            chosen = game.comb_sample(coverage, 2, FixedRng([*shuffle, (k + 0.5) / offsets]))
            assert len(chosen) == len(set(chosen)) == 2
            for id in chosen:
                counts[id] += 1
    assert all(counts[id] / (2 * offsets) == pytest.approx(c, abs=1e-3) for id, c in coverage.items())
    with pytest.raises(ValueError):
        game.comb_sample({"a": 0.5, "b": 0.6}, 2, random.Random(1))
    assert game.normalized_entropy({"a": 0.5, "b": 0.5}) == pytest.approx(1)
    assert game.normalized_entropy({"a": 1.0, "b": 0.0}) == 0


def test_vehicle_plan_samples_the_strategy_and_reports_its_arithmetic(plan_case):
    clock, facilities = plan_case
    plan = patrol.create(plan_request(clock), random.Random(3))
    strategy = PatrolStrategy.model_validate(plan["strategy"])
    PatrolPlan.model_validate(plan)
    assert strategy.model == "stackelberg" and strategy.can_execute is False and plan["can_execute"] is False
    assert sum(t.coverage for t in strategy.targets) == pytest.approx(2)
    assert {s["target_id"] for s in plan["patrols"][0]["stops"]} == {t.id for t in strategy.targets if t.selected}
    assert strategy.outcome.defender_expected >= strategy.baselines["uniform"].defender_expected - 1e-12
    assert strategy.outcome.defender_expected >= strategy.baselines["proportional"].defender_expected - 1e-12
    assert strategy.parameters_approved is False
    assert any("تأیید مدیر حراست" in w for w in plan["warnings"])
    finding = store.lookup("findings", plan["finding_id"])
    assert "استکلبرگ" in finding["evidence"]["rule"] and finding["evidence"]["thresholds"]["patrol_game"]["model"] == "stackelberg"
    assert store.state["commands"] == [] and store.state["missions"] == []
    row = risk.snapshot()["items"][0]
    assert row["bayes"]["prior_rate"] > 0 and row["target_class"] in ("facility_unmanned", "facility_manned")


def test_organisation_values_and_always_visit_drive_the_plan(plan_case):
    clock, facilities = plan_case
    params = store.state["settings"]["patrol_game"]
    params.update(threat_profile=1.0)
    params["overrides"] = [dict(target_id=facilities[1]["id"], value=100, prior_rate_per_year=None, always_visit=False, note="مخزن اصلی")]
    preview = patrol.preview(1, 8)
    covered = {t["id"]: t["coverage"] for t in preview["targets"]}
    assert max(covered, key=covered.get) == facilities[1]["id"]
    # Even full coverage leaves the 100-value target the best attack: a pure strategy, reported as such.
    assert covered[facilities[1]["id"]] == 1 and any("قطعی" in w for w in preview["warnings"])
    params["overrides"].append(dict(target_id=facilities[3]["id"], value=None, prior_rate_per_year=None, always_visit=True, note="بازدید الزامی"))
    plan = patrol.create(plan_request(clock), random.Random(1))
    stops = plan["patrols"][0]["stops"]
    assert any(s["target_id"] == facilities[3]["id"] and s["mandatory"] for s in stops)
    assert next(t for t in plan["strategy"]["targets"] if t["id"] == facilities[3]["id"])["coverage"] == 1
    params["overrides"].append(dict(target_id=facilities[0]["id"], value=None, prior_rate_per_year=None, always_visit=True, note="بازدید الزامی"))
    params["overrides"].append(dict(target_id=facilities[2]["id"], value=None, prior_rate_per_year=None, always_visit=True, note="بازدید الزامی"))
    with pytest.raises(Exception) as exc:
        patrol.create(plan_request(clock), random.Random(1))
    assert getattr(exc.value, "status_code", None) == 422


@pytest.mark.parametrize("model", ["quantal", "weighted"])
def test_alternative_models_stay_explainable(plan_case, model):
    clock, _ = plan_case
    store.state["settings"]["patrol_game"]["model"] = model
    plan = patrol.create(plan_request(clock), random.Random(2))
    strategy = plan["strategy"]
    assert strategy["model"] == model and "stackelberg" in strategy["baselines"]
    assert {s["target_id"] for s in plan["patrols"][0]["stops"]} == {t["id"] for t in strategy["targets"] if t["selected"]}
    if model == "quantal":
        assert sum(t["attack_probability"] for t in strategy["targets"]) == pytest.approx(1)
    else:
        assert any("وزن‌دار" in w for w in strategy["warnings"])


def test_parameters_need_herasat_and_any_change_voids_the_approval(plan_case, token_factory):
    with TestClient(app) as client:
        supervisor = headers(token_factory, "shift_supervisor")
        settings = client.get("/api/v1/settings").json()
        settings["patrol_game"]["threat_profile"] = 0.8
        assert client.put("/api/v1/settings", json=settings, headers=supervisor).status_code == 403
        assert client.post("/api/v1/intel/patrol-game/approve", headers=supervisor).status_code == 403
        bad = deepcopy(settings)
        bad["patrol_game"]["overrides"] = [dict(target_id="NOPE", value=5, note="آزمون")]
        assert client.put("/api/v1/settings", json=bad).status_code == 422
        bad["patrol_game"]["classes"] = [c for c in bad["patrol_game"]["classes"] if c["key"] != "pipeline_segment"]
        assert client.put("/api/v1/settings", json=bad).status_code == 422
        assert client.put("/api/v1/settings", json=settings, headers=headers(token_factory, "security_manager")).status_code == 200
        approved = client.post("/api/v1/intel/patrol-game/approve", headers=headers(token_factory, "security_manager")).json()
        assert approved["approved"] and approved["approved_by"] == "user-security_manager"
        assert client.get("/api/v1/intel/patrol-strategy", params=dict(stops=2, horizon_hours=8)).json()["parameters_approved"]
        settings["patrol_game"]["classes"][0]["value"] = 9
        assert client.put("/api/v1/settings", json=settings).status_code == 200
        assert client.get("/api/v1/intel/patrol-game/approval").json()["approved"] is False
    persisted = store.field.get("settings", "tour_phase_two")["patrol_game"]
    store.state["settings"]["patrol_game"] = PatrolGameSettings().model_dump()
    store.restore_field_state()
    assert store.state["settings"]["patrol_game"] == persisted and persisted["threat_profile"] == 0.8


def test_event_ledger_is_append_only_idempotent_and_moves_the_posterior(plan_case, token_factory):
    clock, facilities = plan_case
    target = facilities[0]
    before = {r["id"]: r["bayes"] for r in risk.snapshot()["items"]}
    event = dict(time=sim.iso(clock.t - 30 * 86400), category="theft", lon=target["lon"], lat=target["lat"],
                 description="سرقت شماتیک از تأسیسات", source_ref="HIST-0001")
    with TestClient(app) as client:
        assert client.post("/api/v1/intel/risk/events", json=dict(events=[event]), headers=headers(token_factory, "shift_supervisor")).status_code == 403
        first = client.post("/api/v1/intel/risk/events", json=dict(events=[event])).json()
        assert first["created"] == 1 and first["unchanged"] == 0
        again = client.post("/api/v1/intel/risk/events", json=dict(events=[event])).json()
        assert again["created"] == 0 and again["unchanged"] == 1
        assert client.post("/api/v1/intel/risk/events", json=dict(events=[{**event, "weight": 2}])).status_code == 409
        future = {**event, "time": sim.iso(clock.t + 60), "source_ref": "HIST-FUTURE"}
        assert client.post("/api/v1/intel/risk/events", json=dict(events=[future])).status_code == 422
        unknown = {**event, "lon": None, "lat": None, "target_id": "NOPE", "source_ref": "HIST-NOPE"}
        assert client.post("/api/v1/intel/risk/events", json=dict(events=[unknown])).status_code == 422
        assert any(e["source_ref"] == "HIST-0001" for e in client.get("/api/v1/intel/risk/events").json())
    after = {r["id"]: r["bayes"] for r in risk.snapshot()["items"]}
    assert after[target["id"]]["weighted_events"] > 0 and after[target["id"]]["mean"] > before[target["id"]]["mean"]
    far = facilities[3]  # 3 km away: outside three kernel bandwidths.
    assert after[far["id"]]["weighted_events"] == 0 and after[target["id"]]["exposure_years"] == 0
    assert any("آغاز مشاهده" in w for w in patrol.preview(1, 8)["warnings"])
    store.state["settings"]["patrol_game"]["history_start"] = "2098-01-01"
    declared = {r["id"]: r["bayes"] for r in risk.snapshot()["items"]}
    observed = (clock.t - datetime(2098, 1, 1, tzinfo=timezone.utc).timestamp()) / 86400
    assert declared[target["id"]]["exposure_years"] == pytest.approx(bayes.discounted_exposure_years(observed, 365))
    assert declared[target["id"]]["mean"] < after[target["id"]]["mean"]
    assert not any("آغاز مشاهده" in w for w in patrol.preview(1, 8)["warnings"])
    incident = store.create_incident("رخداد شماتیک", "low", "آزمایش", store.state["assets"][0], "نمونه", "ثبت")
    store.state["incidents"] = []
    assert any(e["source_ref"] == incident["id"] for e in bayes.events(store.now()))


def test_conformity_compares_observed_selection_with_planned_marginals():
    def plan(selected):
        return dict(status="approved", strategy=dict(model="stackelberg", targets=[
            dict(id="a", coverage=0.5, mandatory=False, selected=selected),
            dict(id="b", coverage=0.5, mandatory=False, selected=not selected)]))
    assert patrol_game.conformity([plan(True)] * 4) is None
    result = patrol_game.conformity([plan(True)] * 6)
    # Each target: mean 3, variance 1.5, observed 6 and 0.
    assert result["plans"] == 6 and result["chi_square"] == pytest.approx(2 * 9 / 1.5)
    assert result["max_standardized_deviation"] == pytest.approx(3 / math.sqrt(1.5))
    balanced = patrol_game.conformity([plan(True)] * 3 + [plan(False)] * 3)
    assert balanced["chi_square"] == pytest.approx(0)


@pytest.fixture
def route_case(monkeypatch):
    monkeypatch.setattr(store, "now", lambda: "2026-10-10T06:00:00+00:00")
    store.field.save("guards", dict(id="G1", keycloak_sub="guard-1", zone_id="Z1", contractor_id="SCHEMATIC"))
    labels = ["حیاتی", "حساس", "مهم", "قابل حفاظت", "مهم", "حساس"]
    ids = list("ABCDEF")
    for index, (id, label) in enumerate(zip(ids, labels)):
        store.field.save("stations", dict(id=id, name=f"ایستگاه {id}", lon=49.0 + index * 0.002, lat=30.0, sensitivity=label,
                                          zone_id="Z1", contractor_id="SCHEMATIC", min_dwell_seconds=60))
    route = dict(id="R1", name="مسیر شماتیک", guard_id="G1", station_ids=ids, order_mode="randomized", fixed_first="A", fixed_last=None,
                 must_precede=[["B", "C"]], zone_id="Z1", contractor_id="SCHEMATIC", coverage_mode="optimized",
                 stations_per_tour=3, subset_mode="shadow", created_at="2026-10-01T00:00:00+00:00")
    store.field.save("routes", route)
    return route


def schedule(id):
    return dict(id=id, status="approved", first_date="2026-10-10", last_date="2026-10-11", pattern_id="DEFAULT",
                route_id="R1", tours_per_shift=1, zone_id="Z1", contractor_id="SCHEMATIC")


def test_walking_subset_is_shadow_until_herasat_allows_approves_and_activates(route_case):
    rows = tour_schedule.materialize(schedule("S1"), date(2026, 10, 10), rng_factory=lambda seed: random.Random(4))
    assert rows and all(sorted(r["station_ids"]) == list("ABCDEF") and r["selection_mode"] == "all" for r in rows)
    assert all(len(r["proposed_station_ids"]) == 3 and "A" in r["proposed_station_ids"] for r in rows)
    finding = store.lookup("findings", rows[0]["selection_finding_id"])
    assert finding["kind"] == "tour_subset" and finding["mode"] == "shadow" and finding["can_execute"] is False
    blocked = finding["evidence"]["values"]["blocked"]
    assert finding["evidence"]["values"]["applied"] is False and len(blocked) == 3 and set(blocked) <= set(rows[0]["warnings"])
    store.state["settings"]["patrol_game"]["allow_subset_tours"] = True
    with TestClient(app) as client:
        assert client.post("/api/v1/intel/patrol-game/approve").json()["approved"]
    store.field.save("routes", {**route_case, "subset_mode": "active"})
    rows = tour_schedule.materialize(schedule("S2"), date(2026, 10, 10), rng_factory=lambda seed: random.Random(4))
    for row in rows:
        assert row["selection_mode"] == "optimized" and len(row["station_ids"]) == 3 and row["station_ids"][0] == "A"
        assert set(row["station_ids"]) == set(row["proposed_station_ids"])
        if {"B", "C"} <= set(row["station_ids"]):
            assert row["station_ids"].index("B") < row["station_ids"].index("C")
    again = tour_schedule.materialize(schedule("S3"), date(2026, 10, 10), rng_factory=lambda seed: random.Random(4))
    assert [r["station_ids"] for r in again] == [r["station_ids"] for r in rows]
    store.state["settings"]["shadow_mode"] = True
    shadowed = tour_schedule.materialize(schedule("S4"), date(2026, 10, 10), rng_factory=lambda seed: random.Random(4))
    assert all(len(r["station_ids"]) == 6 for r in shadowed)
    store.state["settings"]["shadow_mode"] = False
    store.state["settings"]["patrol_game"]["threat_profile"] = 0.9  # Unapproved change.
    unapproved = tour_schedule.materialize(schedule("S5"), date(2026, 10, 10), rng_factory=lambda seed: random.Random(4))
    assert all(len(r["station_ids"]) == 6 and any("تأیید نشده" in w for w in r["warnings"]) for r in unapproved)
    guard = SimpleNamespace(roles=["guard"])
    assert all(r["proposed_station_ids"] == [] and r["selection_finding_id"] is None
               for r in tour_schedule.queue_rows(guard, unapproved))


def test_route_decision_api_roles_bounds_and_preview(route_case, token_factory):
    path = "/api/v1/tour/routes/R1"
    with TestClient(app) as client:
        decision = dict(coverage_mode="optimized", stations_per_tour=4, subset_mode="active")
        assert client.put(path + "/coverage", json=decision, headers=headers(token_factory, "shift_supervisor")).status_code == 403
        assert client.put(path + "/coverage", json={**decision, "stations_per_tour": 6}).status_code == 422
        assert client.put(path + "/coverage", json=dict(coverage_mode="all", stations_per_tour=2)).status_code == 422
        saved = client.put(path + "/coverage", json=decision).json()
        assert (saved["coverage_mode"], saved["stations_per_tour"], saved["subset_mode"]) == ("optimized", 4, "active")
        store.state["settings"]["patrol_game"]["overrides"] = [
            dict(target_id=id, value=None, prior_rate_per_year=None, always_visit=True, note="الزامی") for id in "BCDE"]
        assert client.put(path + "/coverage", json=decision).status_code == 422
        store.state["settings"]["patrol_game"]["overrides"] = []
        preview = client.get(path + "/strategy", params=dict(stations_per_tour=3, horizon_hours=8)).json()
        assert preview["can_execute"] is False and len(preview["targets"]) == 6
        first = next(t for t in preview["targets"] if t["id"] == "A")
        assert first["mandatory"] and first["coverage"] == 1
        assert sum(t["coverage"] for t in preview["targets"] if not t["mandatory"]) == pytest.approx(2)
        assert client.put(path + "/coverage", json=dict(coverage_mode="all")).json()["coverage_mode"] == "all"
