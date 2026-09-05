# Contributing to Trafficfolio

Thank you for helping improve Trafficfolio.

## Development

Trafficfolio supports Python 3.12 and uses only the standard library.

```bash
python -m unittest discover -s tests -v
DASHBOARD_OWNER=OWNER python scripts/trafficfolio.py render
```

Do not use a real personal access token in tests. API behavior should be represented by small deterministic fixtures or fake clients.

## Pull requests

1. Keep collection runs idempotent. Reprocessing GitHub's rolling 14-day traffic window must never inflate totals.
2. Preserve historical data that has fallen out of the API window.
3. Treat referrers and popular paths as rolling snapshots, not additive daily values.
4. Keep secrets out of generated output, logs, fixtures, and commits.
5. Update tests and user-facing setup instructions when behavior changes.

Open an issue before a large architectural change. Focused fixes and dashboard themes can go directly to a pull request.

