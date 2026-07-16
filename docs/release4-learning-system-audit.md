# Release 4 learning-system audit

## Release boundary

Release 4 is observational. It adds the Reece Edge Map, played-versus-passed segment evaluation, holdout validation, configuration proposals, and rule-violation analytics. It does not automatically modify trade scoring, provider weights, Kelly sizing, execution rules, risk caps, or Model Tracker eligibility. No later release work is included.

## Authoritative inputs

- `candidate_ledger` supplies all candidates and their immutable decision/version context.
- `candidate_monitoring` supplies settled outcomes and hypothetical played-versus-passed P&L.
- `dual_clv_measurements` supplies exchange and composite CLV only when genuinely available.
- `trade_quality_snapshots`, `liquidity_quality_snapshots`, and `execution_plan_snapshots` supply versioned segment attributes.
- Model and Personal Tracker storage remains separate. Edge Map uses the global Candidate Ledger and never exposes user-owned Personal Tracker records.

`learning_system.py` is the authoritative calculation layer. `database.py` and `durable_user_store.py` persist the same contracts for SQLite and PostgreSQL. `app.py` exposes the read-only Edge Map, user-scoped violation recording, and protected administration workflow.

## Safeguards

- Fewer than 25 candidates is always `INSUFFICIENT_SAMPLE`.
- 25–99 candidates remains `DISCOVERY` regardless of apparent performance.
- `VALIDATED` requires at least 250 candidates, at least 100 settled observations, positive composite CLV, and positive ROI.
- Strong negative evidence can become `WEAK` or `SUSPENDED`; missing CLV never becomes positive evidence.
- Holdouts must be later and non-overlapping, meet their own minimum sample, and have positive composite CLV.
- An admin cannot approve a proposal before its holdout passes.
- Approval records proposed old/new configuration versions but does not apply the change; `applied_at` stays empty.
- Users must explicitly confirm a recognized warning before a violation is stored.
- User submissions cannot supply their own P&L or CLV. Those fields remain unavailable until an authorized settlement update.

## Migration risk

Migration `004_release4_learning_system` is additive and idempotent in SQLite and PostgreSQL. It creates five new tables and indexes without altering historical recommendations. Existing records are read for analysis but never rewritten or recalculated in place.

## Data availability

The Edge Map uses existing real Candidate Ledger and Polymarket-derived observations. No provider price, result, liquidity, fee, CLV, or P&L is fabricated. When closing observations are absent, ROI and CLV display `Unavailable`, and statistical reliability remains low.

## Before/after validation

Before Release 4, measurements were stored candidate-by-candidate but could not identify repeatable segments or enforce a holdout approval workflow. After Release 4, the same immutable measurements can be grouped across 15 segment dimensions, compared between played and passed decisions, versioned as Edge Map snapshots, and used to create non-production configuration proposals.

Automated tests cover sample thresholds, all meaningful segment states, played-versus-passed counts, CLV/ROI aggregation, holdout safeguards, proposal approval ordering, migration/persistence, rule-violation confirmation and privacy, admin authorization, and the honest unavailable state. Browser QA verified the Edge Map, its dimension filter, responsive table, navigation state, and console.
