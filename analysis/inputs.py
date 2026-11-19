"""Shared file handling for analysis commands; missing reviews are never success."""

from pathlib import Path

from crawler.app_releases import load_releases
from crawler.appstore_reviews import load_reviews


def add_input_arguments(parser) -> None:
    parser.add_argument("--reviews", type=Path, default=Path("data/appstore_reviews.jsonl"))
    parser.add_argument("--releases", type=Path,
                        help="official releases; otherwise use data/app_releases.jsonl if present")


def release_path(path: Path | None) -> Path | None:
    default = Path("data/app_releases.jsonl")
    return path if path is not None else default if default.exists() else None


def load_inputs(reviews_path: Path, releases_path: Path | None) -> tuple[list[dict], list[dict]]:
    reviews = list(load_reviews(reviews_path).values())
    if not reviews:
        raise ValueError("review collection is empty; cannot assess release impact")
    resolved = release_path(releases_path)
    return reviews, load_releases(resolved) if resolved is not None else []
