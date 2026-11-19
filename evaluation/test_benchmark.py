from pathlib import Path

import pytest

from evaluation.benchmark import benchmark

ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_reports_measurement_scope_without_quality_claims():
    report = benchmark(ROOT / "examples/retrieval_reviews.jsonl",
                       ROOT / "examples/retrieval_queries.jsonl", repetitions=2, warmup=0)
    assert report["reviews"] == 6 and report["queries"] == 2
    assert report["process_peak_rss_mib"] > 0
    for timing in report["timings"].values():
        assert timing["queries_measured"] == 4
        assert 0 <= timing["p50_ms"] <= timing["p95_ms"] <= timing["max_ms"]
    assert report["limitations"]


@pytest.mark.parametrize("kwargs", [{"repetitions": 0}, {"warmup": -1}])
def test_bad_benchmark_configuration_fails_before_loading(kwargs):
    with pytest.raises(ValueError):
        benchmark(Path("missing"), Path("missing"), **kwargs)
