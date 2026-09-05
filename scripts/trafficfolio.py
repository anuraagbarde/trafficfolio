#!/usr/bin/env python3
"""Collect GitHub repository analytics and render a README dashboard."""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
START_MARKER = "<!-- TRAFFICFOLIO:START -->"
END_MARKER = "<!-- TRAFFICFOLIO:END -->"
DATA_VERSION = 1
DEFAULT_DAYS = 30


class GitHubAPIError(RuntimeError):
    """An actionable GitHub API failure."""


class GitHubClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{API_ROOT}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "trafficfolio",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(detail).get("message", detail)
            except json.JSONDecodeError:
                message = detail
            raise GitHubAPIError(
                f"GitHub API returned {error.code} for {path}: {message}"
            ) from error
        except urllib.error.URLError as error:
            raise GitHubAPIError(f"Could not reach GitHub for {path}: {error.reason}") from error

    def get_paginated(self, path: str) -> list[dict[str, Any]]:
        separator = "&" if "?" in path else "?"
        page = 1
        items: list[dict[str, Any]] = []
        while True:
            batch = self.get(f"{path}{separator}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise GitHubAPIError(f"Expected a list from GitHub API endpoint {path}")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1


def empty_data(owner: str) -> dict[str, Any]:
    return {
        "version": DATA_VERSION,
        "owner": owner,
        "updated_at": None,
        "repositories": {},
    }


def load_data(path: Path, owner: str) -> dict[str, Any]:
    if not path.exists():
        return empty_data(owner)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read dashboard data at {path}: {error}") from error
    if data.get("version") != DATA_VERSION:
        raise RuntimeError(
            f"Unsupported data version {data.get('version')!r}; expected {DATA_VERSION}"
        )
    if data.get("owner") == "OWNER" and not data.get("repositories"):
        return empty_data(owner)
    if data.get("owner", "").casefold() != owner.casefold():
        raise RuntimeError(
            f"Data belongs to {data.get('owner')!r}, not {owner!r}. "
            "Delete the data file after forking to initialize a new owner."
        )
    return data


def utc_day(timestamp: str) -> str:
    return timestamp[:10]


def collect_repository(client: GitHubClient, repository: dict[str, Any]) -> dict[str, Any]:
    full_name = repository["full_name"]
    encoded_name = "/".join(urllib.parse.quote(part, safe="") for part in full_name.split("/"))
    details = client.get(f"/repos/{encoded_name}")
    views = client.get(f"/repos/{encoded_name}/traffic/views?per=day")
    clones = client.get(f"/repos/{encoded_name}/traffic/clones?per=day")
    referrers = client.get(f"/repos/{encoded_name}/traffic/popular/referrers")
    paths = client.get(f"/repos/{encoded_name}/traffic/popular/paths")
    releases = client.get_paginated(f"/repos/{encoded_name}/releases")
    release_downloads = sum(
        int(asset.get("download_count", 0))
        for release in releases
        for asset in release.get("assets", [])
    )
    return {
        "metadata": {
            "name": details["name"],
            "full_name": full_name,
            "url": details["html_url"],
            "description": details.get("description") or "",
            "language": details.get("language"),
            "private": bool(details.get("private")),
            "fork": bool(details.get("fork")),
            "archived": bool(details.get("archived")),
            "stars": int(details.get("stargazers_count", 0)),
            "forks": int(details.get("forks_count", 0)),
            "subscribers": int(details.get("subscribers_count", 0)),
            "open_issues": int(details.get("open_issues_count", 0)),
            "release_downloads": release_downloads,
        },
        "views": {
            utc_day(item["timestamp"]): {
                "count": int(item["count"]),
                "uniques": int(item["uniques"]),
            }
            for item in views.get("views", [])
        },
        "clones": {
            utc_day(item["timestamp"]): {
                "count": int(item["count"]),
                "uniques": int(item["uniques"]),
            }
            for item in clones.get("clones", [])
        },
        "referrers": referrers,
        "popular_paths": paths,
    }


def merge_snapshot(
    data: dict[str, Any],
    repositories: list[dict[str, Any]],
    collected: dict[str, dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    day = now.date().isoformat()
    known = data.setdefault("repositories", {})
    visible_names = {repository["full_name"] for repository in repositories}

    for repository in repositories:
        full_name = repository["full_name"]
        snapshot = collected[full_name]
        existing = known.setdefault(
            full_name,
            {
                "metadata": {},
                "traffic": {},
                "counters": {},
                "referrer_snapshots": {},
                "path_snapshots": {},
            },
        )
        existing["metadata"] = snapshot["metadata"]
        traffic = existing.setdefault("traffic", {})
        all_days = set(snapshot["views"]) | set(snapshot["clones"])
        for traffic_day in all_days:
            view = snapshot["views"].get(traffic_day, {})
            clone = snapshot["clones"].get(traffic_day, {})
            traffic[traffic_day] = {
                "views": int(view.get("count", 0)),
                "unique_views": int(view.get("uniques", 0)),
                "clones": int(clone.get("count", 0)),
                "unique_clones": int(clone.get("uniques", 0)),
            }
        metadata = snapshot["metadata"]
        existing.setdefault("counters", {})[day] = {
            "stars": metadata["stars"],
            "forks": metadata["forks"],
            "subscribers": metadata["subscribers"],
            "open_issues": metadata["open_issues"],
            "release_downloads": metadata["release_downloads"],
        }
        existing.setdefault("referrer_snapshots", {})[day] = snapshot["referrers"]
        existing.setdefault("path_snapshots", {})[day] = snapshot["popular_paths"]

    for full_name, repository_data in known.items():
        repository_data["active"] = full_name in visible_names

    data["updated_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return data


def date_window(days: int, end: date | None = None) -> list[str]:
    end = end or datetime.now(UTC).date()
    return [(end - timedelta(days=offset)).isoformat() for offset in reversed(range(days))]


def sum_traffic(repository: dict[str, Any], days: list[str]) -> dict[str, int]:
    totals = {"views": 0, "unique_views": 0, "clones": 0, "unique_clones": 0}
    for day in days:
        point = repository.get("traffic", {}).get(day, {})
        for key in totals:
            totals[key] += int(point.get(key, 0))
    return totals


def counter_delta(repository: dict[str, Any], key: str, days: list[str]) -> int:
    counters = repository.get("counters", {})
    values = [int(counters[day].get(key, 0)) for day in days if day in counters]
    return max(0, values[-1] - values[0]) if len(values) >= 2 else 0


def trend_score(repository: dict[str, Any], days: list[str]) -> float:
    current_days = days[-7:]
    previous_days = days[-14:-7]
    current = sum_traffic(repository, current_days)
    previous = sum_traffic(repository, previous_days)
    traffic_growth = (current["unique_views"] + 1) / (previous["unique_views"] + 1)
    stars = counter_delta(repository, "stars", current_days)
    forks = counter_delta(repository, "forks", current_days)
    return round(traffic_growth * math.log2(current["views"] + 2) + stars * 2 + forks * 3, 2)


def active_repositories(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (name, repository)
        for name, repository in data.get("repositories", {}).items()
        if repository.get("active", True) and not repository.get("metadata", {}).get("archived")
    ]


def public_repositories(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (name, repository)
        for name, repository in active_repositories(data)
        if not repository.get("metadata", {}).get("private")
    ]


def archived_repositories(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (name, repository)
        for name, repository in data.get("repositories", {}).items()
        if repository.get("active", True) and repository.get("metadata", {}).get("archived")
    ]


def private_repositories(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (name, repository)
        for name, repository in active_repositories(data)
        if repository.get("metadata", {}).get("private")
    ]


def owned_repositories(
    repositories: list[dict[str, Any]], owner: str, include_private: bool
) -> list[dict[str, Any]]:
    return [
        repository
        for repository in repositories
        if repository.get("owner", {}).get("login", "").casefold() == owner.casefold()
        and (include_private or not repository.get("private"))
    ]


def format_number(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def ellipsize(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 3]}..."


def aggregate_series(
    repositories: list[tuple[str, dict[str, Any]]], days: list[str], key: str
) -> list[int]:
    return [
        sum(int(repository.get("traffic", {}).get(day, {}).get(key, 0)) for _, repository in repositories)
        for day in days
    ]


def portfolio_totals(
    repositories: list[tuple[str, dict[str, Any]]], days: list[str]
) -> dict[str, int]:
    traffic = {
        key: sum(sum_traffic(repository, days)[key] for _, repository in repositories)
        for key in ("views", "unique_views", "clones", "unique_clones")
    }
    return {
        **traffic,
        "stars": sum(
            int(repository.get("metadata", {}).get("stars", 0))
            for _, repository in repositories
        ),
        "forks": sum(
            int(repository.get("metadata", {}).get("forks", 0))
            for _, repository in repositories
        ),
        "subscribers": sum(
            int(repository.get("metadata", {}).get("subscribers", 0))
            for _, repository in repositories
        ),
        "open_issues": sum(
            int(repository.get("metadata", {}).get("open_issues", 0))
            for _, repository in repositories
        ),
        "release_downloads": sum(
            int(repository.get("metadata", {}).get("release_downloads", 0))
            for _, repository in repositories
        ),
    }


def svg_polyline(values: list[int], x: int, y: int, width: int, height: int) -> str:
    maximum = max(values, default=0) or 1
    denominator = max(1, len(values) - 1)
    points = [
        f"{x + index * width / denominator:.1f},{y + height - value * height / maximum:.1f}"
        for index, value in enumerate(values)
    ]
    return " ".join(points)


def render_svg(data: dict[str, Any], days: list[str]) -> str:
    public = public_repositories(data)
    archived = archived_repositories(data)
    views = aggregate_series(public, days, "views")
    clones = aggregate_series(public, days, "clones")
    totals = portfolio_totals(public, days)
    cards = [
        ("VIEWS", totals["views"], "#58a6ff"),
        ("VISITORS", totals["unique_views"], "#a371f7"),
        ("CLONES", totals["clones"], "#3fb950"),
        ("STARS", totals["stars"], "#f2cc60"),
        ("FORKS", totals["forks"], "#f778ba"),
    ]
    card_markup = []
    for index, (label, value, color) in enumerate(cards):
        x = 38 + index * 222
        card_markup.append(
            f'<rect x="{x}" y="100" width="202" height="105" rx="14" fill="#161b22" '
            f'stroke="#30363d"/><circle cx="{x + 24}" cy="129" r="5" fill="{color}"/>'
            f'<text x="{x + 38}" y="134" class="label">{label}</text>'
            f'<text x="{x + 20}" y="181" class="metric">{format_number(value)}</text>'
        )

    top_public = sorted(
        public,
        key=lambda item: (
            trend_score(item[1], days),
            sum_traffic(item[1], days)["views"],
        ),
        reverse=True,
    )[:4]
    top_archived = sorted(
        archived,
        key=lambda item: (
            sum_traffic(item[1], days)["views"],
            int(item[1].get("metadata", {}).get("stars", 0)),
        ),
        reverse=True,
    )[:4]
    maximum_public_views = max(
        (sum_traffic(repository, days)["views"] for _, repository in top_public),
        default=1,
    ) or 1
    maximum_archived_views = max(
        (sum_traffic(repository, days)["views"] for _, repository in top_archived),
        default=1,
    ) or 1
    public_rows = []
    for index, (name, repository) in enumerate(top_public):
        y = 574 + index * 55
        view_count = sum_traffic(repository, days)["views"]
        bar_width = int(185 * view_count / maximum_public_views)
        public_rows.append(
            f'<text x="62" y="{y + 17}" class="repo">'
            f'{html.escape(ellipsize(name.split("/", 1)[-1], 34))}</text>'
            f'<rect x="332" y="{y}" width="185" height="22" rx="6" fill="#21262d"/>'
            f'<rect x="332" y="{y}" width="{bar_width}" height="22" rx="6" fill="url(#bar)"/>'
            f'<text x="535" y="{y + 17}" class="value">{format_number(view_count)} views</text>'
            f'<text x="663" y="{y + 17}" text-anchor="end" class="trend">{trend_score(repository, days):.1f}</text>'
        )
    archived_rows = []
    for index, (name, repository) in enumerate(top_archived):
        y = 574 + index * 55
        view_count = sum_traffic(repository, days)["views"]
        bar_width = int(145 * view_count / maximum_archived_views)
        archived_rows.append(
            f'<text x="720" y="{y + 17}" class="repo">'
            f'{html.escape(ellipsize(name.split("/", 1)[-1], 30))}</text>'
            f'<rect x="955" y="{y}" width="145" height="22" rx="6" fill="#21262d"/>'
            f'<rect x="955" y="{y}" width="{bar_width}" height="22" rx="6" fill="url(#archiveBar)"/>'
            f'<text x="1120" y="{y + 17}" class="archive">{format_number(view_count)} views</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="860" viewBox="0 0 1200 860" role="img" aria-label="Trafficfolio GitHub analytics dashboard">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#080b13"/><stop offset=".55" stop-color="#10182b"/><stop offset="1" stop-color="#0b1020"/></linearGradient>
  <linearGradient id="line" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#58a6ff"/><stop offset="1" stop-color="#a371f7"/></linearGradient>
  <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#238636"/><stop offset="1" stop-color="#3fb950"/></linearGradient>
  <linearGradient id="archiveBar" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#9e6a03"/><stop offset="1" stop-color="#f2cc60"/></linearGradient>
  <radialGradient id="ambient"><stop stop-color="#58a6ff" stop-opacity=".16"/><stop offset="1" stop-color="#58a6ff" stop-opacity="0"/></radialGradient>
  <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#ffffff" stroke-opacity=".025"/></pattern>
  <filter id="glow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <style>
    .title{{font:750 30px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#f0f6fc}}
    .subtitle{{font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#8b949e}}
    .label{{font:600 12px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#8b949e;letter-spacing:1px}}
    .metric{{font:700 31px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#f0f6fc}}
    .section{{font:600 17px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#c9d1d9}}
    .repo,.value,.trend,.archive{{font:13px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#c9d1d9}}
    .value{{fill:#8b949e}} .trend{{fill:#3fb950;font-weight:600}} .archive{{fill:#d29922}}
    .pill{{font:600 12px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:.7px}}
  </style>
</defs>
<rect width="1200" height="860" rx="22" fill="url(#bg)"/>
<rect width="1200" height="860" rx="22" fill="url(#grid)"/>
<circle cx="1060" cy="20" r="280" fill="url(#ambient)"/>
<rect x="1" y="1" width="1198" height="858" rx="21" fill="none" stroke="#30363d"/>
<circle cx="51" cy="52" r="14" fill="url(#bar)"/><path d="M45 52h12M51 46v12" stroke="#fff" stroke-width="2"/>
<text x="78" y="60" class="title">Trafficfolio</text>
<rect x="846" y="34" width="116" height="34" rx="17" fill="#238636" fill-opacity=".16" stroke="#3fb950" stroke-opacity=".45"/>
<text x="904" y="56" text-anchor="middle" class="pill" fill="#56d364">{len(public)} PUBLIC</text>
<rect x="976" y="34" width="150" height="34" rx="17" fill="#9e6a03" fill-opacity=".14" stroke="#d29922" stroke-opacity=".45"/>
<text x="1051" y="56" text-anchor="middle" class="pill" fill="#f2cc60">{len(archived)} ARCHIVED</text>
{''.join(card_markup)}
<text x="40" y="256" class="section">Repository traffic</text>
<text x="1138" y="256" text-anchor="end" class="subtitle">public portfolio / {len(days)} days / views blue / clones green</text>
<rect x="38" y="274" width="1090" height="168" rx="14" fill="#0d1117" fill-opacity=".62" stroke="#30363d"/>
<line x1="52" y1="420" x2="1114" y2="420" stroke="#21262d"/>
<line x1="52" y1="350" x2="1114" y2="350" stroke="#21262d"/>
<line x1="52" y1="280" x2="1114" y2="280" stroke="#21262d"/>
<polyline points="{svg_polyline(views, 52, 275, 1096, 135)}" fill="none" stroke="url(#line)" stroke-width="4" stroke-linejoin="round" filter="url(#glow)"/>
<polyline points="{svg_polyline(clones, 52, 320, 1096, 90)}" fill="none" stroke="#3fb950" stroke-width="3" stroke-linejoin="round"/>
<rect x="38" y="478" width="642" height="310" rx="16" fill="#161b22" fill-opacity=".82" stroke="#30363d"/>
<circle cx="62" cy="512" r="5" fill="#3fb950"/><text x="76" y="518" class="section">Trending public repositories</text>
<text x="658" y="518" text-anchor="end" class="subtitle">views / momentum</text>
{''.join(public_rows)}
<rect x="700" y="478" width="428" height="310" rx="16" fill="#161b22" fill-opacity=".82" stroke="#30363d"/>
<circle cx="724" cy="512" r="5" fill="#d29922"/><text x="738" y="518" class="section">Archived repository traffic</text>
<text x="1104" y="518" text-anchor="end" class="subtitle">30-day views</text>
{''.join(archived_rows)}
<text x="40" y="826" class="subtitle">Updated {html.escape(str(data.get("updated_at") or "not yet"))} / durable data from the GitHub API</text>
</svg>
"""


def markdown_escape(value: str) -> str:
    normalized = " ".join(value.splitlines())
    escaped_html = html.escape(normalized, quote=False)
    return re.sub(r"([\\`*_[\]{}()#+\-.!|])", r"\\\1", escaped_html)


def popular_path_url(repository_name: str, path: str, repository_url: str) -> str:
    expected_prefix = f"/{repository_name}"
    if path != expected_prefix and not path.startswith(f"{expected_prefix}/"):
        return repository_url
    return f"https://github.com{urllib.parse.quote(path, safe='/%:@-._~')}"


def latest_snapshot(repository: dict[str, Any], key: str) -> list[dict[str, Any]]:
    snapshots = repository.get(key, {})
    if not snapshots:
        return []
    return snapshots[max(snapshots)]


def render_markdown(data: dict[str, Any], days: list[str]) -> str:
    public = public_repositories(data)
    archived = archived_repositories(data)
    private = private_repositories(data)
    included_repositories = [
        repository
        for repository in data.get("repositories", {}).values()
        if repository.get("active", True)
    ]
    ranked_public = sorted(
        public,
        key=lambda item: (
            trend_score(item[1], days),
            sum_traffic(item[1], days)["views"],
        ),
        reverse=True,
    )
    ranked_archived = sorted(
        archived,
        key=lambda item: (
            sum_traffic(item[1], days)["views"],
            int(item[1].get("metadata", {}).get("stars", 0)),
        ),
        reverse=True,
    )
    public_totals = portfolio_totals(public, days)
    archived_totals = portfolio_totals(archived, days)
    lines = [
        f"> Last updated **{data.get('updated_at', 'not yet')}** | "
        f"Showing **{len(public)} public** and **{len(archived)} archived** repositories | "
        f"Dataset: **{len(included_repositories)}** owned repositories "
        f"(private excluded by default) | "
        f"Window: **{len(days)} days**",
        "",
        f'<p align="center"><img src="./assets/dashboard.svg?v='
        f'{urllib.parse.quote(str(data.get("updated_at") or "pending"), safe="")}" '
        f'alt="Trafficfolio dashboard" width="100%"></p>',
        "",
        "### Public portfolio",
        "",
        "| Views | Unique visitors | Clones | Unique cloners | Stars | Forks | Subscribers | Open issues/PRs | Downloads |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| **{public_totals['views']:,}** | **{public_totals['unique_views']:,}** | "
        f"**{public_totals['clones']:,}** | **{public_totals['unique_clones']:,}** | "
        f"**{public_totals['stars']:,}** | **{public_totals['forks']:,}** | "
        f"**{public_totals['subscribers']:,}** | **{public_totals['open_issues']:,}** | "
        f"**{public_totals['release_downloads']:,}** |",
        "",
        "#### Public repositories",
        "",
        "| # | Repository | Views | Visitors | Clones | Stars (+30d) | Forks (+30d) | Downloads | Momentum |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, (name, repository) in enumerate(ranked_public, start=1):
        metadata = repository["metadata"]
        traffic = sum_traffic(repository, days)
        lines.append(
            f"| {index} | [{markdown_escape(name)}]({metadata['url']}) | "
            f"{traffic['views']:,} | {traffic['unique_views']:,} | {traffic['clones']:,} | "
            f"{metadata['stars']:,} (+{counter_delta(repository, 'stars', days):,}) | "
            f"{metadata['forks']:,} (+{counter_delta(repository, 'forks', days):,}) | "
            f"{metadata['release_downloads']:,} | {trend_score(repository, days):.1f} |"
        )

    lines.extend(
        [
            "",
            "### Archived portfolio",
            "",
            "| Views | Unique visitors | Clones | Unique cloners | Stars | Forks | Subscribers | Open issues/PRs | Downloads |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            f"| **{archived_totals['views']:,}** | **{archived_totals['unique_views']:,}** | "
            f"**{archived_totals['clones']:,}** | **{archived_totals['unique_clones']:,}** | "
            f"**{archived_totals['stars']:,}** | **{archived_totals['forks']:,}** | "
            f"**{archived_totals['subscribers']:,}** | **{archived_totals['open_issues']:,}** | "
            f"**{archived_totals['release_downloads']:,}** |",
            "",
            "#### Archived repositories",
            "",
            "| Repository | Views | Visitors | Clones | Stars | Forks | Downloads |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, repository in ranked_archived:
        metadata = repository["metadata"]
        traffic = sum_traffic(repository, days)
        lines.append(
            f"| [{markdown_escape(name)}]({metadata['url']}) | "
            f"{traffic['views']:,} | {traffic['unique_views']:,} | {traffic['clones']:,} | "
            f"{metadata['stars']:,} | {metadata['forks']:,} | "
            f"{metadata['release_downloads']:,} |"
        )
    if not ranked_archived:
        lines.append("| No archived repositories tracked | 0 | 0 | 0 | 0 | 0 | 0 |")

    if private:
        private_totals = portfolio_totals(private, days)
        lines.extend(
            [
                "",
                "<details>",
                f"<summary><strong>Private repositories ({len(private)})</strong></summary>",
                "",
                "Private repository reporting is opt-in and should only be used when this "
                "dashboard repository is also private.",
                "",
                "| Repositories | Views | Visitors | Clones | Stars | Forks |",
                "|---:|---:|---:|---:|---:|---:|",
                f"| **{len(private)}** | **{private_totals['views']:,}** | "
                f"**{private_totals['unique_views']:,}** | **{private_totals['clones']:,}** | "
                f"**{private_totals['stars']:,}** | **{private_totals['forks']:,}** |",
                "",
                "</details>",
            ]
        )

    referrers: dict[str, dict[str, int]] = {}
    popular_paths: list[tuple[int, str, str, str]] = []
    for name, repository in [*public, *archived, *private]:
        for item in latest_snapshot(repository, "referrer_snapshots"):
            current = referrers.setdefault(item["referrer"], {"count": 0, "uniques": 0})
            current["count"] += int(item.get("count", 0))
            current["uniques"] += int(item.get("uniques", 0))
        for item in latest_snapshot(repository, "path_snapshots"):
            popular_paths.append(
                (
                    int(item.get("count", 0)),
                    name,
                    str(item.get("path", "")),
                    str(item.get("title", "")),
                )
            )

    lines.extend(
        [
            "",
            "<details>",
            "<summary><strong>Top referrers and popular content</strong></summary>",
            "",
            "#### Referrers",
            "",
            "| Source | Views | Unique visitors |",
            "|---|---:|---:|",
        ]
    )
    for source, values in sorted(
        referrers.items(), key=lambda item: item[1]["count"], reverse=True
    )[:10]:
        lines.append(
            f"| {markdown_escape(source)} | {values['count']:,} | {values['uniques']:,} |"
        )
    if not referrers:
        lines.append("| No referrer data yet | 0 | 0 |")

    lines.extend(
        [
            "",
            "#### Popular content",
            "",
            "| Repository | Path | Views |",
            "|---|---|---:|",
        ]
    )
    for count, name, path, title in sorted(popular_paths, reverse=True)[:10]:
        label = markdown_escape(title or path)
        repository_url = data["repositories"][name]["metadata"]["url"]
        target = popular_path_url(
            name,
            path,
            repository_url,
        )
        lines.append(
            f"| {markdown_escape(name)} | [{label}]({target}) | {count:,} |"
        )
    if not popular_paths:
        lines.append("| No popular-path data yet | - | 0 |")
    lines.extend(
        [
            "",
            "</details>",
            "",
            "<sub>Traffic is reported by GitHub in UTC and is available only to repository owners. "
            "Unique counts are daily values and must not be interpreted as unique people across the entire period. "
            "Momentum combines recent traffic growth, stars, forks, and volume.</sub>",
        ]
    )
    return "\n".join(lines)


def replace_dashboard(readme: str, dashboard: str) -> str:
    if readme.count(START_MARKER) != 1 or readme.count(END_MARKER) != 1:
        raise RuntimeError(
            f"README must contain exactly one {START_MARKER} and one {END_MARKER}"
        )
    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}", re.DOTALL
    )
    return pattern.sub(f"{START_MARKER}\n{dashboard}\n{END_MARKER}", readme)


def write_outputs(data: dict[str, Any], data_path: Path, readme_path: Path, assets_dir: Path) -> None:
    days = date_window(DEFAULT_DAYS)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (assets_dir / "dashboard.svg").write_text(render_svg(data, days), encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    readme_path.write_text(
        replace_dashboard(readme, render_markdown(data, days)).rstrip() + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("update", "render"))
    parser.add_argument("--owner", default=os.getenv("DASHBOARD_OWNER"))
    parser.add_argument("--data", type=Path, default=Path("data/dashboard.json"))
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--assets-dir", type=Path, default=Path("assets"))
    return parser.parse_args()


def enabled(value: str | None) -> bool:
    return bool(value and value.casefold() in {"1", "true", "yes", "on"})


def main() -> int:
    args = parse_args()
    owner = args.owner
    if not owner:
        print("error: set DASHBOARD_OWNER or pass --owner", file=sys.stderr)
        return 2

    try:
        data = load_data(args.data, owner)
        if args.command == "update":
            token = os.getenv("TRAFFIC_TOKEN")
            if not token:
                raise RuntimeError(
                    "TRAFFIC_TOKEN is missing. Add it under Settings > Secrets and variables "
                    "> Actions, then run the workflow again."
                )
            client = GitHubClient(token)
            repositories = owned_repositories(
                client.get_paginated(
                    "/user/repos?affiliation=owner&sort=full_name&direction=asc"
                ),
                owner,
                enabled(os.getenv("INCLUDE_PRIVATE")),
            )
            if not repositories:
                raise RuntimeError(
                    f"No repositories owned by {owner!r} were visible to TRAFFIC_TOKEN. "
                    "Check the token's repository access."
                )
            collected: dict[str, dict[str, Any]] = {}
            for repository in repositories:
                print(f"Collecting {repository['full_name']}...")
                collected[repository["full_name"]] = collect_repository(client, repository)
            data = merge_snapshot(data, repositories, collected, datetime.now(UTC))
        write_outputs(data, args.data, args.readme, args.assets_dir)
    except (GitHubAPIError, RuntimeError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Trafficfolio dashboard rendered for {owner}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
