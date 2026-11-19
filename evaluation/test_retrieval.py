import csv
import json
import math

import pytest

from evaluation.retrieval import (
    ANNOTATION_FIELDS, format_report, main, ndcg_at, precision_at, prepare, score, write_jsonl,
)
from retrieval.test_search import review


@pytest.fixture
def snapshot(tmp_path):
    corpus = tmp_path / "reviews.jsonl"
    queries = tmp_path / "queries.jsonl"
    write_jsonl(corpus, [review("a", "sync failed"), review("b", "syncing failed"),
                        review("c", "sync is fine")])
    write_jsonl(queries, [
        {"id": "d1", "text": "battery", "information_need": "Battery drain", "split": "dev"},
        {"id": "t1", "text": "sync", "information_need": "Sync failure", "split": "test"},
    ])
    workspace = tmp_path / "workspace"
    prepare(corpus, queries, workspace)
    return workspace


def fill_judgments(workspace, *, source="synthetic"):
    path = workspace / "judgments.csv"
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row.update(relevance="2" if row["review_id"] in ("a", "b") else "0",
                   assessor="test-fixture", provenance=source)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=ANNOTATION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def test_metric_values_and_short_result_penalty():
    labels = {"a": 2, "b": 1, "c": 0}
    ideal = 3 + 1 / math.log2(3)
    actual = 1 + 3 / math.log2(3)
    assert ndcg_at(["b", "a", "c"], labels) == pytest.approx(actual / ideal)
    assert precision_at(["a", "b"], labels) == 2 / 5
    assert ndcg_at([], labels) == 0
    assert ndcg_at(["c"], {"c": 0}) == 0


def test_prepare_pools_union_without_rank_or_system_and_keeps_labels_blank(snapshot):
    manifest = json.loads((snapshot / "manifest.json").read_text())
    with (snapshot / "pool.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert {(r["query_id"], r["review_id"]) for r in rows} == {
        ("t1", "a"), ("t1", "b"), ("t1", "c")}
    assert all(not row["relevance"] for row in rows)
    assert "score" not in rows[0] and "system" not in rows[0]
    assert manifest["reviews"] == 3 and manifest["pooled_pairs"] == 3


def test_prepare_is_reproducible_and_refuses_to_overwrite(snapshot, tmp_path):
    second = tmp_path / "second"
    prepare(tmp_path / "reviews.jsonl", tmp_path / "queries.jsonl", second)
    for path in snapshot.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()
    with pytest.raises(ValueError, match="empty"):
        prepare(tmp_path / "reviews.jsonl", tmp_path / "queries.jsonl", snapshot)


def test_missing_labels_are_not_silently_nonrelevant(snapshot):
    with pytest.raises(ValueError, match="3 unjudged"):
        score(snapshot)


def test_score_distinguishes_synthetic_metrics_from_quality_evidence(snapshot):
    fill_judgments(snapshot)
    report = score(snapshot)
    assert report["query_count"] == 1
    assert report["aggregate"]["bm25"]["precision@5"] == 0.2
    assert report["aggregate"]["bm25_expanded"]["precision@5"] == 0.4
    assert any("Synthetic" in warning for warning in report["warnings"])
    assert report["judgment_provenance"] == {"synthetic": 3}
    assert "NDCG@10" in format_report(report)
    assert report["snapshot"]["hashes"]["corpus.jsonl"]


def test_test_scoring_does_not_require_unrelated_dev_judgments(snapshot):
    fill_judgments(snapshot)
    report = score(snapshot, split="dev")
    assert report["query_count"] == 1
    assert report["aggregate"]["bm25"]["ndcg@10"] == 0
    assert any("No judged relevant" in warning for warning in report["warnings"])


@pytest.mark.parametrize("filename", ["corpus.jsonl", "queries.jsonl", "runs.jsonl", "pool.csv"])
def test_changed_snapshot_is_rejected(snapshot, filename):
    with (snapshot / filename).open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="snapshot changed"):
        score(snapshot)


@pytest.mark.parametrize("field,value,message", [
    ("relevance", "3", "0, 1, or 2"),
    ("assessor", "", "assessor"),
    ("provenance", "unspecified", "provenance"),
    ("review_id", "missing-id", "unknown"),
    ("text", "edited source text", "text changed"),
])
def test_bad_judgments_are_rejected(snapshot, field, value, message):
    rows = fill_judgments(snapshot)
    rows[0][field] = value
    with (snapshot / "judgments.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=ANNOTATION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match=message):
        score(snapshot)


def test_duplicate_judgments_are_rejected(snapshot):
    rows = fill_judgments(snapshot)
    with (snapshot / "judgments.csv").open("a", newline="") as stream:
        csv.DictWriter(stream, fieldnames=ANNOTATION_FIELDS).writerow(rows[0])
    with pytest.raises(ValueError, match="duplicate"):
        score(snapshot)


def test_ai_judgments_are_explicitly_identified(snapshot):
    fill_judgments(snapshot, source="ai")
    assert "AI judgments" in format_report(score(snapshot))


def test_cli_saves_per_query_report_and_protects_snapshot(snapshot, capsys):
    fill_judgments(snapshot)
    output = snapshot / "report.json"
    main(["score", "--workspace", str(snapshot), "--report", str(output)])
    assert json.loads(output.read_text())["per_query"][0]["query_id"] == "t1"
    for name in ("corpus.jsonl", "judgments.csv", "manifest.json"):
        original = (snapshot / name).read_bytes()
        with pytest.raises(SystemExit):
            main(["score", "--workspace", str(snapshot), "--report", str(snapshot / name)])
        assert (snapshot / name).read_bytes() == original


def test_empty_corpus_and_shallow_pool_fail(tmp_path):
    queries = tmp_path / "queries.jsonl"
    corpus = tmp_path / "corpus.jsonl"
    write_jsonl(queries, [{"id": "t1", "text": "sync", "information_need": "Sync", "split": "test"}])
    write_jsonl(corpus, [])
    with pytest.raises(ValueError, match="empty"):
        prepare(corpus, queries, tmp_path / "out")
    with pytest.raises(ValueError, match="at least 10"):
        prepare(corpus, queries, tmp_path / "out", depth=5)
