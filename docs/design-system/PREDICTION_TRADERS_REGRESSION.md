# Prediction Traders visual regression baseline

## Frozen reference

- source: approved running production page with the five-trade visual fixture
- URL: `https://iconbets-polymarket-wallet-tracker.vercel.app/trades?selected=qa-trade-2&preview=trade`
- captured: 2026-08-19
- density: 1×

Baseline files:

- `baselines/prediction-traders-baseline-1920x1080.png`
- `baselines/prediction-traders-baseline-1440x900.png`
- `baselines/prediction-traders-baseline-390x844.png`
- `baselines/prediction-traders-computed-baseline.json`

Post-refactor files:

- `post-refactor/prediction-traders-post-1920x1080.png`
- `post-refactor/prediction-traders-post-1440x900.png`
- `post-refactor/prediction-traders-post-390x844.png`
- `post-refactor/prediction-traders-computed-post-refactor.json`

Side-by-side comparison files are stored under `comparisons/` for all three
viewports.

## Recorded geometry

| Measure | 1920 × 1080 | 1440 × 900 | 390 × 844 |
| --- | ---: | ---: | ---: |
| Sidebar | 232px | 232px | 60px tall mobile bar |
| Command header | 79px | 121–124px wrapped | 265–268px stacked |
| Detail panel | 460.8px | 420px | 375px sheet |
| First opportunity | 1171.2 × 112px | 732 × 112px | 354.1 × about 189px |
| Opportunity gap | 8px | 8px | 8px |
| Summary | desktop single row | desktop single row | 2 × 2, 142px tall |
| Control height | 44px | 44px | responsive compact variants preserved |

Approved computed color, typography, spacing, radius, border, and component
properties are serialized in the baseline JSON rather than rounded in this
document. The canonical tokens reproduce those computed values.

## Comparison result

The shell, header, KPI strip, filters, opportunity geometry, confidence,
selection hierarchy, executable quote, stake alignment, selected state, detail
width, provider table, evidence metrics, chart container, and responsive layout
remain visually equivalent at all three viewports.

Intentional cleanup differences:

- `DESIGN PREVIEW` badges were removed.
- the preview-only purple border and shadow that were applied to every fixture
  card were removed; normal cards use the approved subtle border and only the
  selected card receives the purple selection treatment.
- the client-only production visual fixture was removed. Local regression uses
  the deterministic five-trade QA server, so event times, quote values,
  liquidity, and chart points can differ while layout remains stable.
- the single-line `Bet Size` label is preserved and the duplicate pseudo-label
  is absent.

No subjective visual redesign was introduced, and no other page was opted into
the extracted system.
