"""Verify published AI metrics from frozen rankings and labels, without review text.

This recomputes metrics, not retrieval rankings. Rerunning retrieval requires
the original local corpus; a newly downloaded feed is a different experiment.
"""

import argparse
import csv
import json
from pathlib import Path

from evaluation.retrieval import digest, ndcg_at, precision_at, read_jsonl

ROOT = Path(__file__).resolve().parent


def reproduce(root: Path = ROOT) -> dict:
    manifest = json.loads((root / "ai_annotation_manifest.json").read_text())
    for group in ("judgments_sha256", "reports_sha256"):
        for name, expected in manifest[group].items():
            if digest(root / name) != expected:
                raise ValueError(f"published artifact changed: {name}")
    rankings = root / "frozen" / "runs.jsonl"
    for path, name in ((rankings, "runs.jsonl"), (root / "frozen/queries.jsonl", "queries.jsonl")):
        if digest(path) != manifest["snapshot_hashes"][name]:
            raise ValueError(f"frozen input changed: {name}")
    runs = read_jsonl(rankings)
    queries = read_jsonl(root / "frozen/queries.jsonl")
    all_report = json.loads((root / "ai_all_report.json").read_text())
    systems = all_report["snapshot"]["systems"]
    expected = {(q["id"], s) for q in queries for s in systems}
    keys = [(r["query_id"], r["system"]) for r in runs]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("incomplete or duplicate frozen runs")
    pools = {q["id"]: set() for q in queries}
    ranked = {}
    for run in runs:
        ids = [h["review_id"] for h in run["results"]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate document in frozen ranking")
        pools[run["query_id"]].update(ids)
        ranked[run["query_id"], run["system"]] = ids
    results = {}
    for split in ("dev", "test", "all"):
        selected = [q for q in queries if split == "all" or q["split"] == split]
        with (root / f"relevance_ai_{split}.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        labels = {(r["query_id"], r["review_id"]): int(r["relevance"]) for r in rows}
        required = {(q["id"], doc) for q in selected for doc in pools[q["id"]]}
        if len(labels) != len(rows) or set(labels) != required:
            raise ValueError(f"incomplete or duplicate {split} labels")
        if any(r["provenance"] != "ai" or not r["assessor"] for r in rows):
            raise ValueError("published judgments must retain AI provenance")
        if any(grade not in (0, 1, 2) for grade in labels.values()):
            raise ValueError("invalid relevance grade")
        per_query = []
        for q in selected:
            judged = {doc: labels[q["id"], doc] for doc in pools[q["id"]]}
            per_query.append({"query_id": q["id"], "text": q["text"],
                              "judged_documents": len(judged),
                              "relevant_documents": sum(g > 0 for g in judged.values()),
                              "systems": {s: {
                                  "ndcg@10": ndcg_at(ranked[q["id"], s], judged),
                                  "precision@5": precision_at(ranked[q["id"], s], judged)
                              } for s in systems}})
        aggregate = {s: {metric: sum(q["systems"][s][metric] for q in per_query) / len(per_query)
                         for metric in ("ndcg@10", "precision@5")} for s in systems}
        published = json.loads((root / f"ai_{split}_report.json").read_text())
        if per_query != published["per_query"] or aggregate != published["aggregate"]:
            raise ValueError(f"{split} metrics differ from the published report")
        results[split] = aggregate
    return {"verified": True, "results": results,
            "limitations": ["AI labels are not independent human ground truth.",
                            "Recomputed from saved rankings; does not rerun retrieval."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        print(json.dumps(reproduce(), indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
