"""Prepare blind relevance pools and score completed judgments offline.

    PYTHONPATH=build-py python -m evaluation.retrieval prepare
    python -m evaluation.retrieval score --workspace evaluation/workspace
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ANNOTATION_FIELDS = (
    "query_id", "query", "information_need", "review_id", "title", "text",
    "relevance", "assessor", "provenance",
)
PROVENANCE = {"human", "ai", "synthetic"}
METRIC_DEPTH = 10
SNAPSHOT_FILES = ("corpus.jsonl", "queries.jsonl", "runs.jsonl", "pool.csv")


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_queries(path: Path) -> list[dict]:
    queries = read_jsonl(path)
    seen = set()
    if not queries:
        raise ValueError("query collection is empty")
    for query in queries:
        for field in ("id", "text", "information_need", "split"):
            if not isinstance(query.get(field), str) or not query[field].strip():
                raise ValueError(f"query needs a nonempty {field}")
        if query["id"] in seen or query["split"] not in ("dev", "test"):
            raise ValueError("queries need unique IDs and a dev/test split")
        seen.add(query["id"])
    return queries


def prepare(reviews: Path, queries_path: Path, out: Path, depth: int = 10) -> dict:
    # Scoring an existing snapshot needs no native module; preparation does.
    from retrieval.search import EXPANSIONS, SYSTEMS, ReviewSearch, load_documents

    if type(depth) is not int or depth < METRIC_DEPTH:
        raise ValueError("pool depth must be at least 10 for NDCG@10")
    queries = load_queries(queries_path)
    engine = ReviewSearch(load_documents(reviews))
    if not engine.documents:
        raise ValueError("review collection is empty")
    runs = []
    pool = {}
    for query in queries:
        for system in SYSTEMS:
            hits = engine.search(query["text"], depth, system)
            runs.append({"query_id": query["id"], "system": system,
                         "results": [{"review_id": hit["id"], "score": hit["score"]} for hit in hits]})
            for hit in hits:
                pool[(query["id"], hit["id"])] = {
                    "query_id": query["id"], "query": query["text"],
                    "information_need": query["information_need"],
                    "review_id": hit["id"], "title": hit["title"], "text": hit["text"],
                    "relevance": "", "assessor": "", "provenance": "",
                }
    # A deterministic shuffle conceals which system retrieved each item and
    # where it was ranked. The assessor sees only the need and review text.
    pairs = sorted(pool, key=lambda pair: hashlib.sha256(
        json.dumps(pair).encode("utf-8")).hexdigest())
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("output directory must be empty; use a new directory to preserve judgments")
    write_jsonl(out / "corpus.jsonl", engine.documents)
    write_jsonl(out / "queries.jsonl", queries)
    write_jsonl(out / "runs.jsonl", runs)
    for name in ("pool.csv", "judgments.csv"):
        with (out / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=ANNOTATION_FIELDS)
            writer.writeheader()
            writer.writerows(pool[pair] for pair in pairs)
    manifest = {
        "schema_version": 1, "pool_depth": depth, "systems": list(SYSTEMS),
        "reviews": len(engine.documents), "queries": len(queries), "pooled_pairs": len(pool),
        "bm25": {"k1": 1.2, "b": 0.75}, "expansions": EXPANSIONS,
        "keyword": "count of distinct query terms present; OR matching",
        "tie_break": "ascending review ID (lexicographic)",
        "hashes": {name: digest(out / name) for name in SNAPSHOT_FILES},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def precision_at(ranked: list[str], labels: dict[str, int], k: int = 5) -> float:
    """Unfilled ranks count as nonrelevant; grades 1 and 2 count as relevant."""
    if k < 1:
        raise ValueError("k must be positive")
    return sum(labels[doc] > 0 for doc in ranked[:k]) / k


def ndcg_at(ranked: list[str], labels: dict[str, int], k: int = 10) -> float:
    """Exponential gain (2**grade - 1), normalized over the judged pool."""
    if k < 1:
        raise ValueError("k must be positive")

    def dcg(grades):
        return sum((2**grade - 1) / math.log2(rank + 2)
                   for rank, grade in enumerate(grades))

    ideal = dcg(sorted(labels.values(), reverse=True)[:k])
    return dcg([labels[doc] for doc in ranked[:k]]) / ideal if ideal else 0.0


def score(workspace: Path, judgments_path: Path | None = None, split: str = "test") -> dict:
    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported snapshot schema")
    for name in SNAPSHOT_FILES:
        if digest(workspace / name) != manifest["hashes"][name]:
            raise ValueError(f"snapshot changed: {name}; prepare a new workspace")
    if manifest["pool_depth"] < METRIC_DEPTH:
        raise ValueError("pool depth is too shallow for the metrics")
    queries = load_queries(workspace / "queries.jsonl")
    if split not in ("dev", "test", "all"):
        raise ValueError("split must be dev, test, or all")
    selected = [q for q in queries if split == "all" or q["split"] == split]
    if not selected:
        raise ValueError(f"no queries in split {split}")
    query_ids = {q["id"] for q in selected}
    with (workspace / "pool.csv").open(encoding="utf-8", newline="") as stream:
        pool_rows = {(row["query_id"], row["review_id"]): row for row in csv.DictReader(stream)}
    pool = set(pool_rows)
    judgments_path = judgments_path or workspace / "judgments.csv"
    labels = {}
    sources = Counter()
    seen = set()
    with judgments_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"query_id", "review_id", "relevance", "assessor", "provenance"} <= set(reader.fieldnames or []):
            raise ValueError("judgments need query_id, review_id, relevance, assessor, provenance")
        for row in reader:
            pair = row["query_id"], row["review_id"]
            if pair not in pool or pair in seen:
                raise ValueError(f"unknown or duplicate judgment pair: {pair}")
            seen.add(pair)
            for field in ("query", "information_need", "title", "text"):
                if field in row and row[field] != pool_rows[pair][field]:
                    raise ValueError(f"judgment text changed for {pair}: {field}")
            grade = (row["relevance"] or "").strip()
            if not grade:
                continue
            if grade not in ("0", "1", "2"):
                raise ValueError(f"relevance must be 0, 1, or 2: {pair}")
            source = (row["provenance"] or "").strip()
            if source not in PROVENANCE or not (row["assessor"] or "").strip():
                raise ValueError(f"judgment needs assessor and human/ai/synthetic provenance: {pair}")
            if pair[0] in query_ids:
                labels[pair] = int(grade)
                sources[source] += 1
    required = {pair for pair in pool if pair[0] in query_ids}
    missing = required - labels.keys()
    if missing:
        raise ValueError(f"{len(missing)} unjudged pool pairs in {split}; fill judgments.csv before scoring")
    runs = read_jsonl(workspace / "runs.jsonl")
    systems = manifest["systems"]
    if not systems or len(set(systems)) != len(systems):
        raise ValueError("invalid systems in snapshot")
    expected = {(q["id"], system) for q in queries for system in systems}
    run_keys = [(run["query_id"], run["system"]) for run in runs]
    if len(set(run_keys)) != len(run_keys) or set(run_keys) != expected:
        raise ValueError("runs must contain exactly one ranking per query and system")
    per_query = []
    for query in selected:
        judged = {doc: grade for (qid, doc), grade in labels.items() if qid == query["id"]}
        per_query.append({
            "query_id": query["id"], "text": query["text"],
            "judged_documents": len(judged), "relevant_documents": sum(g > 0 for g in judged.values()),
            "systems": {},
        })
        for run in runs:
            if run["query_id"] != query["id"]:
                continue
            ranked = [hit["review_id"] for hit in run["results"]]
            if len(set(ranked)) != len(ranked) or any(doc not in judged for doc in ranked):
                raise ValueError("rankings must contain unique, judged review IDs")
            per_query[-1]["systems"][run["system"]] = {
                "ndcg@10": ndcg_at(ranked, judged), "precision@5": precision_at(ranked, judged),
            }
    warnings = []
    if sources.get("ai"):
        warnings.append("AI judgments are a pilot, not independent human ground truth.")
    if sources.get("synthetic"):
        warnings.append("Synthetic judgments validate the pipeline, not real-world search quality.")
    zero = [q["query_id"] for q in per_query if not q["relevant_documents"]]
    if zero:
        warnings.append(f"No judged relevant documents for {', '.join(zero)}; NDCG is defined as 0.")
    warnings.append("Metrics are relative to this judged pool, not exhaustive corpus relevance.")
    return {
        "split": split, "query_count": len(selected), "judgment_provenance": dict(sources),
        "metric_definitions": {"ndcg@10": "gain=2^grade-1; log2(rank+1); pooled IDCG",
                               "precision@5": "grade>0; fixed denominator 5"},
        "snapshot": manifest, "judgments_sha256": digest(judgments_path),
        "warnings": warnings, "per_query": per_query,
        "aggregate": {
            system: {metric: sum(q["systems"][system][metric] for q in per_query) / len(per_query)
                     for metric in ("ndcg@10", "precision@5")}
            for system in systems
        },
    }


def format_report(report: dict) -> str:
    lines = [f"Split: {report['split']} | queries: {report['query_count']} | "
             f"judgments: {report['judgment_provenance']}",
             f"{'system':<18} {'NDCG@10':>9} {'P@5':>9}"]
    for system, metrics in report["aggregate"].items():
        lines.append(f"{system:<18} {metrics['ndcg@10']:>9.4f} {metrics['precision@5']:>9.4f}")
    lines.extend("Note: " + warning for warning in report["warnings"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="freeze corpus and rankings; create blind judgments.csv")
    prep.add_argument("--reviews", type=Path, default=Path("data/appstore_reviews.jsonl"))
    prep.add_argument("--queries", type=Path, default=Path("evaluation/queries.jsonl"))
    prep.add_argument("--out", type=Path, default=Path("evaluation/workspace"))
    prep.add_argument("--depth", type=int, default=10)
    scoring = commands.add_parser("score", help="score fully judged pools; no native module needed")
    scoring.add_argument("--workspace", type=Path, default=Path("evaluation/workspace"))
    scoring.add_argument("--judgments", type=Path)
    scoring.add_argument("--split", choices=("dev", "test", "all"), default="test")
    scoring.add_argument("--report", type=Path, help="also save full JSON with per-query metrics")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            manifest = prepare(args.reviews, args.queries, args.out, args.depth)
            print(f"Frozen {manifest['reviews']} reviews, {manifest['queries']} queries, "
                  f"{manifest['pooled_pairs']} query-review pairs in {args.out}.")
            print("Fill relevance, assessor and provenance in judgments.csv; no labels have been inferred.")
        else:
            report = score(args.workspace, args.judgments, args.split)
            if args.report:
                if args.report.resolve() in {
                    (args.workspace / name).resolve()
                    for name in (*SNAPSHOT_FILES, "manifest.json", "judgments.csv")
                } or (args.judgments and args.report.resolve() == args.judgments.resolve()):
                    raise ValueError("report path must not overwrite snapshot or judgments")
                args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                                       encoding="utf-8")
            print(format_report(report))
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
