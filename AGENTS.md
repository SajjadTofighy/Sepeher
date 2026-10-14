# Sepehr Command contributor rules

- Intelligence is rule-based or statistical: no LLM, ML training, external
  services, or new runtime dependencies.
- Every intelligence output is a Finding with evidence and can_execute=false.
  Never dispatch or send commands automatically; a human approves every action.
- New intelligence rules default to shadow mode. Apply global shadow_mode and
  maintenance_silence exactly through the shared engine routing decision.
- Import helpers; never copy logic. Geometry: app/intel/geo.py. Great-circle
  distance: sim.distance_km. Polygon/schedule checks: engine.point_in_polygon,
  in_schedule, valid_schedule. Patrol eligibility/ETA: routers/incidents.py
  (patrol_vehicle, dispatchable, eta_minutes). Observation gap: engine.observation_gap_seconds.
  Stop/silence helpers: engine.continuous_stop, connection_lost, connection_timeout_minutes.
  Backup suggestions: routers/incidents.nearby_patrols.
  Coverage items/threshold: intel.coverage.coverage_items, stale_hours.
  Mission progress/window: store.update_mission_progress, engine.checkpoint_window_minutes.
  Incident creation/audit/clock/lookup: store.py.
  Routing decision: engine.routing_decision. Move shared logic once and import it.
- All sample records belong in backend/app/seed.py and remain synthetic and
  labelled schematic. Never use real infrastructure coordinates.
- API contracts are Pydantic models in models.py, including RuntimeSettings.
  After any API change run `python scripts/export_openapi.py` and
  `npm run api:generate --prefix frontend`. Frontend DTOs are aliases in
  frontend/src/types.ts; never hand-write DTOs or edit schema.d.ts.
- Frontend features belong under frontend/src/features. Map sources/layers
  belong in features/command/OperationalMap.tsx. Use TanStack Query for server
  state, with no second global store. Use Persian UI strings, existing fa()
  formatting, and shared/ui components.
- Edit existing documentation in place only: docs/CAPABILITY-MATRIX.fa.md,
  docs/DESIGN-REVIEW.fa.md, docs/API.fa.md, and docs/ARCHITECTURE.fa.md (when layer
  boundaries change). Do not create markdown files, changelogs, phase reports,
  or summaries. This required AGENTS.md is the sole exception.
- Never edit design text in README.fa.md design sections, Main-Design.MD, or
  the Persian “طرح سامانه …” file. Rewrite/delete false statements instead of
  appending contradictory notes. Infrastructure does not implement §10 features.
- Tests use pytest in backend/tests and existing fixtures (track_database and
  injected clocks as in test_live_ops.py). At most one new file per capability:
  test_intel_<capability>.py. Keep tests deterministic: no sleep or wall clock.
- Protect shared state with store.locked_state; refresh_tracks and worker ticks
  share the same lock. Intelligence observations use store.observations_since.
- Done means `python -m pytest backend/tests -q`,
  `npm run typecheck --prefix frontend`, and `npm run build` all pass.
  Final reports state changed files, deviations, what was verified, and what
  was not. Keep diffs minimal; do not refactor or reformat unrelated code.
