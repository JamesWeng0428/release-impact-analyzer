import json
from pathlib import Path
import subprocess
import sys

import pytest

from analysis.report import generate_report, main, markdown
from analysis.regression import detect_changes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scenario(tmp_path):
    reviews = []
    # Large enough to demonstrate recovery with the simultaneous bounds.
    for version, complaints in (("5.1", 0), ("5.2", 0), ("5.3", 0), ("5.4", 180), ("5.5", 0)):
        for i in range(200):
            reviews.append({"id": f"{version}-{i:03}", "app_version": version,
                            "date": "2026-01-01T00:00:00Z", "country": "us",
                            "title": "Sync failed" if i < complaints else "Works well",
                            "text": "Cannot sync my watch" if i < complaints else "Sync works perfectly",
                            "rating": 1 if i < complaints else 5})
    reviews.append({**reviews[0], "id": "small", "app_version": "5.4.1"})
    corpus = tmp_path / "reviews.jsonl"
    corpus.write_text("\n".join(json.dumps(r) for r in reviews))
    releases = tmp_path / "releases.jsonl"
    releases.write_text(json.dumps({"version": "5.6", "release_date": "2026-02-01T00:00:00Z"}))
    return corpus, releases


def test_complete_report_detects_spike_recovery_and_preserves_denominators(scenario):
    report = generate_report(*scenario)
    assert report["status"] == "analyzed"
    assert report["review_count"] == 1001
    assert report["version_count"] == 7
    assert [r["version"] for r in report["recovery"]["regressions"]] == ["5.4"]
    candidates = {r["version"]: r for r in report["recovery"]["comparisons"]}
    assert candidates["5.5"]["verdict"] == "recovery_supported"
    assert candidates["5.4.1"]["verdict"] == candidates["5.6"]["verdict"] == "insufficient_data"
    rows = {r["version"]: r for r in report["timeline"]}
    assert rows["5.4"]["reviews"] == 200 and rows["5.4"]["complaints"] == 180
    assert len(rows["5.4"]["evidence"]) == 4
    assert rows["5.6"]["date_source"] == "official"
    assert rows["5.6"]["evidence"] == []
    source = {r["id"]: r for r in map(json.loads, scenario[0].read_text().splitlines())}
    for row in report["timeline"]:
        for evidence in row["evidence"]:
            assert {k: v for k, v in evidence.items() if k != "kind"} == source[evidence["id"]]
    assert "recovery_supported" in markdown(report)


def test_cli_end_to_end_offline(scenario, tmp_path):
    output = tmp_path / "output" / "report.json"
    # Run with cwd=root like a clean checkout user, not an imported in-process CLI.
    result = subprocess.run([sys.executable, "-m", "analysis.report", "--reviews", str(scenario[0]),
                             "--releases", str(scenario[1]), "--format", "json", "--output", str(output)],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["tested_versions"] == 2
    assert report["review_count"] == 1001


@pytest.mark.parametrize("module", ["analysis.report", "analysis.regression",
                                    "analysis.release_timeline", "analysis.fix_verification"])
@pytest.mark.parametrize("content", [None, "", "{bad json", "[]", '{"id":"bad"}'])
def test_analysis_commands_reject_missing_empty_or_invalid_reviews(tmp_path, module, content):
    path = tmp_path / "bad.jsonl"
    if content is not None:
        path.write_text(content)
    result = subprocess.run([sys.executable, "-m", module, "--reviews", str(path)],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2
    assert "error:" in result.stderr and "Traceback" not in result.stderr
    assert not result.stdout


@pytest.mark.parametrize("kwargs", [{"window": 0}, {"window": True}, {"min_reviews": 0},
                                    {"alpha": float("nan")}, {"alpha": 1},
                                    {"min_delta": float("inf")}, {"min_delta": -0.1}])
def test_regression_rejects_invalid_parameters_even_with_no_rows(kwargs):
    with pytest.raises(ValueError):
        detect_changes([], **kwargs)


@pytest.mark.parametrize("rows", [
    [{"version": "1", "reviews": -1, "complaints": 0}],
    [{"version": "1", "reviews": 2, "complaints": 3}],
    [{"version": "1", "reviews": 2, "complaints": True}],
    [{"version": "bad", "reviews": 2, "complaints": 1}],
    [{"version": v, "reviews": 2, "complaints": 1} for v in ("2", "1")],
    [{"version": "1", "reviews": 2, "complaints": 1}] * 2,
])
def test_regression_rejects_bad_rows_before_sample_filtering(rows):
    with pytest.raises(ValueError):
        detect_changes(rows)


def test_output_cannot_destroy_input_even_through_a_hardlink(scenario, tmp_path):
    path, releases = scenario
    original = path.read_bytes()
    alias = tmp_path / "alias.jsonl"
    alias.hardlink_to(path)
    for target in (path, alias, releases):
        with pytest.raises(SystemExit) as error:
            main(["--reviews", str(path), "--releases", str(releases), "--output", str(target)])
        assert error.value.code == 2
    assert path.read_bytes() == original


def test_absent_official_dates_and_low_samples_are_explicit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = generate_report(ROOT / "examples/retrieval_reviews.jsonl")
    assert report["sources"]["releases"] is None
    assert report["status"] == "insufficient_comparable_versions"
    assert "Insufficient comparable versions" in markdown(report)
    with pytest.raises(FileNotFoundError):
        generate_report(ROOT / "examples/retrieval_reviews.jsonl", tmp_path / "missing.jsonl")
