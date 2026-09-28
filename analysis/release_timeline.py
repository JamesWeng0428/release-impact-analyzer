"""Per-version timeline of Garmin Connect releases and how reviewers reacted.

Release dates come from the official record (crawler.app_releases) when
available, otherwise from the earliest review of that version, which can be
later than the real release when few reviews survive for old versions.

Connectivity complaints are detected with a keyword baseline for now; the
retrieval and topic models will replace it and be compared against it.

    python -m analysis.release_timeline --min-reviews 5
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

from crawler.app_releases import load_releases
from crawler.appstore_reviews import load_reviews

# "Garmin Connect" is the app's name, not a connection problem.
_APP_NAME = re.compile(r"garmin\s+connect", re.IGNORECASE)
_CONNECTIVITY = re.compile(
    r"\b(sync\w*|disconnect\w*|bluetooth|re-?pair\w*|pair(?:ed|ing)?|"
    r"connect(?:ion|ing|ed|s)?)\b",
    re.IGNORECASE,
)


def version_key(version: str) -> tuple[int, ...]:
    """Sort key so that 5.9 < 5.10 < 5.27.3 < 5.28."""
    return tuple(int(part) for part in re.findall(r"\d+", version))


def is_connectivity_complaint(review: dict) -> bool:
    """Keyword baseline: a low rating that mentions syncing or connecting."""
    text = _APP_NAME.sub(" ", f"{review['title']} {review['text']}")
    return review["rating"] <= 2 and bool(_CONNECTIVITY.search(text))


def build_timeline(reviews: list[dict], releases: list[dict]) -> list[dict]:
    """One row per app version, oldest version first."""
    official = {r["version"]: r["release_date"] for r in releases}
    by_version: dict[str, list[dict]] = {}
    for review in reviews:
        by_version.setdefault(review["app_version"], []).append(review)

    rows = []
    for version in sorted(set(by_version) | set(official), key=version_key):
        group = by_version.get(version, [])
        if version in official:
            date, source = official[version], "official"
        else:
            first = min(group, key=lambda r: datetime.fromisoformat(r["date"]))
            date, source = first["date"], "first review"
        complaints = sum(map(is_connectivity_complaint, group))
        rows.append(
            {
                "version": version,
                "release_date": datetime.fromisoformat(date).date().isoformat(),
                "date_source": source,
                "reviews": len(group),
                "complaints": complaints,
                "avg_rating": sum(r["rating"] for r in group) / len(group) if group else None,
                "connectivity_share": complaints / len(group) if group else None,
            }
        )
    return rows


def format_table(rows: list[dict]) -> str:
    lines = [
        f"{'version':<10} {'released':<11} {'date from':<13} {'reviews':>7} "
        f"{'avg ★':>6} {'conn. %':>8} {'Δ prev':>7}"
    ]
    previous = None
    for row in rows:
        share = row["connectivity_share"]
        rating = "-" if row["avg_rating"] is None else f"{row['avg_rating']:.2f}"
        pct = "-" if share is None else f"{100 * share:.0f}%"
        delta = "" if share is None or previous is None else f"{100 * (share - previous):+.0f}"
        lines.append(
            f"{row['version']:<10} {row['release_date']:<11} {row['date_source']:<13} "
            f"{row['reviews']:>7} {rating:>6} {pct:>8} {delta:>7}"
        )
        if share is not None:
            previous = share
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reviews", type=Path, default=Path("data/appstore_reviews.jsonl"))
    parser.add_argument("--releases", type=Path, default=Path("data/app_releases.jsonl"))
    parser.add_argument("--min-reviews", type=int, default=5,
                        help="hide versions with fewer reviews (official releases always shown)")
    args = parser.parse_args(argv)

    rows = build_timeline(list(load_reviews(args.reviews).values()), load_releases(args.releases))
    shown = [r for r in rows if r["reviews"] >= args.min_reviews or r["date_source"] == "official"]
    print(format_table(shown))


if __name__ == "__main__":
    main()
