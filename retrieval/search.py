"""Search the same frozen review collection with three transparent methods."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import ria
except ImportError as error:
    raise ImportError(
        "Build the C++ Python module first; see README. "
        "Run with PYTHONPATH=build-py."
    ) from error

SYSTEMS = ("keyword", "bm25", "bm25_expanded")
# Fixed domain vocabulary, not learned from relevance judgments. Expansion can
# hurt precision; its value must be measured, not assumed. Original terms retain
# their frequency; each additional term is appended only once.
EXPANSIONS = {
    "sync": ("syncs", "syncing", "synced", "synchronization", "synchronisation"),
    "pair": ("pairing", "paired", "unpaired"),
    "disconnect": ("disconnects", "disconnected", "disconnecting", "dropout"),
    "crash": ("crashes", "crashing", "crashed"),
    "freeze": ("freezes", "freezing", "frozen"),
    "notification": ("notifications", "alerts"),
    "battery": ("drain", "draining"),
    "login": ("signin", "sign", "log"),
}
FIELDS = ("id", "title", "text", "app_version", "date", "country", "rating")


def expand_query(query: str) -> str:
    terms = ria.tokenize(query)
    seen = set(terms)
    added = []
    for term in terms:
        for extra in EXPANSIONS.get(term, ()):
            if extra not in seen:
                seen.add(extra)
                added.append(extra)
    return " ".join(terms + added)


def load_documents(path: Path) -> list[dict]:
    # A missing corpus is an error, not a successful search over zero reviews.
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


class ReviewSearch:
    def __init__(self, reviews: list[dict]):
        self.documents = []
        seen = set()
        for review in reviews:
            if any(field not in review for field in FIELDS):
                raise ValueError(f"review must contain {', '.join(FIELDS)}")
            if any(not isinstance(review[f], str) for f in FIELDS if f != "rating"):
                raise ValueError("review IDs and text metadata must be strings")
            if not review["id"] or review["id"] in seen:
                raise ValueError("review IDs must be nonempty and unique")
            if type(review["rating"]) is not int or not 1 <= review["rating"] <= 5:
                raise ValueError("review rating must be an integer from 1 to 5")
            seen.add(review["id"])
            self.documents.append({field: review[field] for field in FIELDS})
        # Stable IDs, not JSONL line numbers, define tie-breaking and joins.
        self.documents.sort(key=lambda review: review["id"])
        self.index = ria.InvertedIndex()
        self.term_sets = []
        for review in self.documents:
            text = f"{review['title']}. {review['text']}"
            self.index.add_document(text)
            self.term_sets.append(set(ria.tokenize(text)))

    def search(
        self, query: str, k: int = 10, system: str = "bm25", *,
        version: str | None = None, country: str | None = None,
    ) -> list[dict]:
        if system not in SYSTEMS:
            raise ValueError(f"unknown system: {system}")
        if type(k) is not int or k < 0:
            raise ValueError("k must be a nonnegative integer")
        if k == 0:
            return []
        if system == "keyword":
            terms = set(ria.tokenize(query))
            ranked = [(doc, float(len(terms & tokens)))
                      for doc, tokens in enumerate(self.term_sets) if terms & tokens]
            ranked.sort(key=lambda hit: (-hit[1], hit[0]))
        else:
            effective = expand_query(query) if system == "bm25_expanded" else query
            # Filter AFTER global scoring, BEFORE truncation. Thus a version
            # filter cannot lose matching results just outside the global top k.
            limit = len(self.documents) if version is not None or country is not None else k
            ranked = [(hit.doc, hit.score) for hit in ria.bm25_search(self.index, effective, limit)]
        hits = []
        for doc, score in ranked:
            review = self.documents[doc]
            if version is not None and review["app_version"] != version:
                continue
            if country is not None and review["country"] != country:
                continue
            hits.append({**review, "score": score})
            if len(hits) == k:
                break
        return hits


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Search reviews and retain source metadata.")
    parser.add_argument("query")
    parser.add_argument("--reviews", type=Path, default=Path("data/appstore_reviews.jsonl"))
    parser.add_argument("--system", choices=SYSTEMS, default="bm25")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--version")
    parser.add_argument("--country")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        engine = ReviewSearch(load_documents(args.reviews))
        hits = engine.search(args.query, args.top_k, args.system,
                             version=args.version, country=args.country)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps({"query": args.query, "system": args.system, "results": hits},
                         ensure_ascii=False, indent=2))
    elif not hits:
        print("No matching reviews.")
    else:
        for rank, hit in enumerate(hits, 1):
            print(f"{rank}. [{hit['score']:.3f}] {hit['title']}")
            print(f"   id={hit['id']} | app={hit['app_version']} | "
                  f"{hit['date']} | {hit['country']} | {hit['rating']} stars")
            print("   " + " ".join(hit["text"].split()))


if __name__ == "__main__":
    main()
