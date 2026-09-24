"""Record Garmin Connect releases from Apple's public Lookup API.

The Lookup API only describes the version currently in the App Store, so each
run appends that version to a JSONL file if it is new. Running this regularly
(alongside the review fetcher) builds up an official release history.

    python -m crawler.app_releases --out data/app_releases.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from crawler.appstore_reviews import GARMIN_CONNECT_APP_ID, fetch_json

LOOKUP_URL = "https://itunes.apple.com/lookup?id={app_id}&country={country}"


def parse_lookup(payload: dict) -> dict | None:
    """Extracts the current release from a Lookup API response."""
    results = payload.get("results", [])
    if not results:
        return None
    app = results[0]
    return {
        "version": app["version"],
        "release_date": app["currentVersionReleaseDate"],
        "notes": app.get("releaseNotes", ""),
    }


def load_releases(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def record_release(path: Path, release: dict) -> bool:
    """Appends `release` unless its version is already recorded."""
    if any(r["version"] == release["version"] for r in load_releases(path)):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(release, ensure_ascii=False) + "\n")
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("data/app_releases.jsonl"))
    parser.add_argument("--app-id", default=GARMIN_CONNECT_APP_ID)
    parser.add_argument("--country", default="us")
    args = parser.parse_args(argv)

    url = LOOKUP_URL.format(app_id=args.app_id, country=args.country)
    release = parse_lookup(fetch_json(url))
    if release is None:
        sys.exit(f"no app found for id {args.app_id}")
    added = record_release(args.out, release)
    status = "recorded" if added else "already recorded"
    print(f"{release['version']} ({release['release_date'][:10]}): {status}", file=sys.stderr)


if __name__ == "__main__":
    main()
