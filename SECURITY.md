# Security policy

## Supported versions

Security fixes are applied to the latest version on the default branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature instead of opening a public issue. Include the affected workflow or code path, impact, reproduction steps, and any suggested remediation.

Do not include personal access tokens, workflow logs containing credentials, private repository names, or private traffic data in a report.

## Token model

Trafficfolio uses two separate credentials:

1. `TRAFFIC_TOKEN` reads traffic and metadata from repositories owned by the user. Store it only as a GitHub Actions secret.
2. The workflow's short-lived `GITHUB_TOKEN` has `contents: write` permission only in the dashboard repository and commits generated output.

Use a fine-grained personal access token rather than a classic token. For public repositories, grant only read-only Administration permission; source-code access is not required. Private repository collection is disabled by default and additionally requires read-only Contents permission. Rotate the token when it expires or immediately if exposure is suspected.

Third-party workflow code is limited to GitHub-owned Actions pinned to immutable release commit hashes. Dependabot checks those pins for updates weekly.

Forks do not inherit upstream Actions secrets. This is an intentional GitHub security boundary.
