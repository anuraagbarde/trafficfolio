<div align="center">

# Trafficfolio

### Fork this repository and get your own GitHub analytics dashboard.

One GitHub Action tracks your repository views, visitors, clones, stars, forks, referrers, release downloads, and trending projects. The dashboard updates inside your README every day.

**No server. No database. No subscription.**

[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-automated-2088FF?logo=github-actions&logoColor=white)](./.github/workflows/update-dashboard.yml)
[![Cost](https://img.shields.io/badge/cost-$0-2ea44f)](#make-it-yours)
[![License: MIT](https://img.shields.io/badge/license-MIT-f2cc60)](./LICENSE)

**Fork. Add one secret. Run once.**

</div>

<!-- TRAFFICFOLIO:START -->
<p align="center"><img src="./assets/dashboard.svg?v=2026-09-06T00%3A56%3A43Z" alt="Trafficfolio dashboard" width="100%"></p>
<!-- TRAFFICFOLIO:END -->

## Make it yours

### 1. Fork and enable

Fork this repository, open its **Actions** tab, and enable workflows.

### 2. Add one secret

[Create a fine-grained token](https://github.com/settings/personal-access-tokens/new) with:

- **Repository access:** All repositories
- **Administration:** Read-only
- **Contents:** No access needed for public repositories

In your fork, open **Settings > Secrets and variables > Actions** and add it as `TRAFFIC_TOKEN`.

### 3. Run once

Under **Settings > Actions > General**, set **Workflow permissions** to **Read and write**.

Then open **Actions > Update Trafficfolio > Run workflow**. Your fork replaces this dashboard with your data and updates it automatically every day.

**That is it.**

## Safe by default

- Your token stays in GitHub's encrypted Actions secrets and is never committed.
- Private repositories are excluded unless explicitly enabled in a private fork.
- GitHub provides aggregate traffic only; visitor identities are never available.
- GitHub-owned Actions are pinned to immutable releases.

Trafficfolio saves daily snapshots because GitHub exposes traffic for only 14 days. Your history stays in [`data/dashboard.json`](./data/dashboard.json), in your own repository.

[How it works](./scripts/trafficfolio.py) · [Security](./SECURITY.md) · [Contributing](./CONTRIBUTING.md) · [MIT License](./LICENSE)

If Trafficfolio helps, **star it and share your fork**.
