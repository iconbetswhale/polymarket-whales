# Release 5 completion audit

## Scope

Release 5 closes the remaining product-specification gaps after Releases 1–4. It does not fabricate external sportsbook, composite probability, liquidity, or CLV observations. It adds a safe path for applying holdout-approved, risk-reducing segment policies and makes the existing measurement, execution, and learning systems inspectable in the product.

## Authoritative paths

- Candidate and measurement persistence: `database.py`, `durable_user_store.py`, `measurement_foundation.py`
- Candidate decisions: `decision_engine.py`, `position_tracker.py`
- Fair price and composite adapters: `fair_price_engine.py`, `composite_prices.py`
- Sizing, execution, and portfolio risk: `bet_sizing.py`, `execution_engine.py`, `risk_engine.py`
- Learning and holdouts: `learning_system.py`
- Applied policy and explainability: `completion_system.py`
- HTTP and admin control plane: `app.py`
- Product surfaces: `templates/intelligence.html`, `templates/tracker.html`, `static/app.js`, `static/style.css`

## Additive database changes

Migration `005_release5_completion` creates:

- `production_configuration_versions`
- `segment_policy_assignments`
- `post_change_monitoring_runs`

SQLite and PostgreSQL migrations are additive. Existing tracker, wallet, whiteboard, position, candidate, decision, price, execution, CLV, and learning records are neither rewritten nor deleted.

## Safety policy

- A proposal must complete the existing holdout workflow and be `APPROVED` before application.
- `stake_multiplier` is constrained to `0 <= multiplier <= 1`; the completion release cannot increase risk.
- Matching policies are included in the frozen recommendation and portfolio-risk evidence.
- Applying a replacement policy supersedes only the active assignment for the same segment.
- Each later Edge Map run records post-change metrics for active policies.
- Missing external evidence remains `UNAVAILABLE` with its machine-readable reason.

## Product completion

- Trades expose decision, price validation, fair price, edge, liquidity, context, execution method, maximum average price, correlation, Kelly/risk evidence, and Tracker evidence. Execution links are disabled above the approved maximum.
- Model Tracker exposes intended and actual weighted entries, grade/score, composite fair price, liquidity/execution, maximum price/correlation, exchange and composite CLV, execution loss, decision reason, advanced filters, and played-versus-passed segment analytics.
- Intelligence provides authorized Candidate Ledger, proposal, rule-violation, diagnostics, and 16-stage explainability views.
- Approved proposals can be applied from the control plane, and post-change monitoring is operational.

## External dependencies

Independent composite fair prices and composite CLV become available only when real provider credentials and mappings are configured. Until then the system intentionally returns unavailable states; no synthetic substitute is used.

## Release gate

- Python compilation and JavaScript syntax validation are required.
- Focused Release 5 tests cover migration, approval gating, risk limits, matching, monitoring, trace integrity, authorization, and unavailable evidence.
- The complete regression suite covers Trades, Model Tracker, Personal Tracker, Whiteboard, wallet sync, execution, live prices, Releases 1–4, and Release 5.
- Rendered QA covers the Intelligence workspace, explainability trace, responsive navigation, and Model Tracker evidence panel.
