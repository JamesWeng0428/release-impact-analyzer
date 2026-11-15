import json
import math

import pytest

from analysis import fix_verification as fv


def row(version, complaints, reviews):
    return {"version": version, "release_date": "2026-01-01",
            "complaints": complaints, "reviews": reviews}


def baseline_and_spike():
    return [row("5.0", 10, 200), row("5.1", 10, 200), row("5.2", 10, 200),
            row("5.3", 120, 200)]


def test_exact_interval_matches_nist_example():
    # NIST's published 90% interval for 4 defects out of 20.
    assert fv.exact_interval(4, 20, alpha=0.10) == pytest.approx(
        (0.071354, 0.401029), abs=1e-6
    )


def test_exact_interval_boundaries_symmetry_and_large_counts():
    assert fv.exact_interval(0, 0) == (0, 1)
    assert fv.exact_interval(0, 10) == pytest.approx((0, 1 - 0.025 ** 0.1))
    assert fv.exact_interval(10, 10) == pytest.approx((0.025 ** 0.1, 1))
    lo, hi = fv.exact_interval(1200, 3000)
    mirrored = fv.exact_interval(1800, 3000)
    assert 0 < lo < 0.4 < hi < 1
    assert mirrored == pytest.approx((1 - hi, 1 - lo))


def test_exact_interval_has_nominal_binomial_coverage():
    # Enumerate all outcomes independently instead of mirroring inversion code.
    for n in (1, 4, 8):
        bounds = [fv.exact_interval(k, n, alpha=0.10) for k in range(n + 1)]
        for p in (0.01, 0.10, 0.35, 0.50, 0.90, 0.99):
            coverage = sum(
                math.comb(n, k) * p ** k * (1 - p) ** (n - k)
                for k, (lo, hi) in enumerate(bounds) if lo <= p <= hi
            )
            assert coverage >= 0.90 - 1e-12


def test_recovery_supported_against_spike_and_frozen_baseline():
    rows = baseline_and_spike() + [row("5.4", 10, 200), row("5.5", 8, 200)]
    report = fv.verify_fixes(rows)
    assert [r["version"] for r in report["regressions"]] == ["5.3"]
    assert report["confidence_groups"] == 6 + 3
    for candidate in report["comparisons"]:
        assert candidate["verdict"] == "recovery_supported"
        assert candidate["drop_ci"][0] > 0
        assert candidate["baseline_delta_ci"][1] <= 0.10
        assert candidate["baseline_versions"] == ["5.0", "5.1", "5.2"]
        assert candidate["baseline_reviews"] == 600
        assert candidate["baseline_complaints"] == 30


def test_partial_recovery_stays_elevated_above_baseline():
    report = fv.verify_fixes(baseline_and_spike() + [row("5.4", 60, 200)])
    [candidate] = report["comparisons"]
    assert candidate["verdict"] == "partial_recovery"
    assert candidate["baseline_status"] == "elevated"
    assert candidate["improvement_supported"]
    assert candidate["baseline_delta_ci"][0] > 0


def test_low_rate_with_small_sample_is_not_proof_of_recovery():
    report = fv.verify_fixes(baseline_and_spike() + [row("5.4", 0, 10)])
    [candidate] = report["comparisons"]
    assert candidate["improvement_supported"]
    assert candidate["baseline_delta_ci"][1] > 0.10
    assert candidate["baseline_status"] == "uncertain"
    assert candidate["verdict"] == "improved_recovery_uncertain"


def test_small_observed_change_is_not_supported_as_a_fix():
    report = fv.verify_fixes(
        baseline_and_spike() + [row("5.4", 119, 200), row("5.5", 180, 200)]
    )
    assert all(c["verdict"] == "no_clear_improvement" for c in report["comparisons"])
    assert all(not c["improvement_supported"] for c in report["comparisons"])


def test_low_sample_and_zero_review_releases_remain_visible():
    rows = baseline_and_spike() + [row("5.3.1", 0, 0), row("5.3.2", 0, 3),
                                  row("5.4", 10, 200)]
    report = fv.verify_fixes(rows)
    assert report["confidence_groups"] == 5 + 2  # no low-sample rate groups
    empty, small, recovered = report["comparisons"]
    assert empty["rate"] is None and empty["drop"] is None
    for candidate in (empty, small):
        assert candidate["verdict"] == "insufficient_data"
        assert candidate["drop_ci"] is None
        assert candidate["baseline_delta_ci"] is None
    assert recovered["verdict"] == "recovery_supported"
    assert recovered["baseline_versions"] == ["5.0", "5.1", "5.2"]


def test_next_regression_starts_a_new_episode():
    rows = baseline_and_spike() + [
        row("5.4", 10, 200), row("5.5", 10, 200), row("5.6", 10, 200),
        row("5.7", 150, 200), row("5.8", 10, 200),
    ]
    report = fv.verify_fixes(rows)
    assert [r["version"] for r in report["regressions"]] == ["5.3", "5.7"]
    first = [c for c in report["comparisons"] if c["regression_version"] == "5.3"]
    second = [c for c in report["comparisons"] if c["regression_version"] == "5.7"]
    assert [c["version"] for c in first] == ["5.4", "5.5", "5.6"]
    assert [c["version"] for c in second] == ["5.8"]
    assert second[0]["baseline_versions"] == ["5.4", "5.5", "5.6"]


def test_tolerance_is_explicit_and_can_be_tightened():
    rows = baseline_and_spike() + [row("5.4", 10, 200)]
    [loose] = fv.verify_fixes(rows)["comparisons"]
    [strict] = fv.verify_fixes(rows, recovery_margin=0)["comparisons"]
    assert loose["verdict"] == "recovery_supported"
    assert strict["verdict"] == "improved_recovery_uncertain"


def test_no_regressions_and_no_later_candidates_are_explained():
    empty = fv.verify_fixes([])
    assert empty["comparisons"] == [] and empty["regressions"] == []
    assert "No regressions detected" in fv.format_report(empty)
    report = fv.verify_fixes(baseline_and_spike())
    assert len(report["regressions"]) == 1 and report["comparisons"] == []
    assert "No later releases observed" in fv.format_report(report)


@pytest.mark.parametrize("kwargs", [
    {"window": 0}, {"min_reviews": 0}, {"alpha": 0}, {"alpha": 1},
    {"min_delta": -0.1}, {"min_delta": 1.1},
    {"recovery_margin": -0.1}, {"recovery_margin": 1.1},
])
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        fv.verify_fixes([], **kwargs)


@pytest.mark.parametrize("rows", [
    [row("5.1", 2, 1)], [row("5.1", -1, 10)], [row("5.1", 1, -10)],
    [row("5.1", 1, 10), row("5.1", 0, 10)],
    [row("5.2", 1, 10), row("5.1", 0, 10)],
])
def test_invalid_counts_duplicates_and_order_are_rejected(rows):
    with pytest.raises(ValueError):
        fv.verify_fixes(rows)


def test_cli_reads_review_files_and_emits_json_and_uncertainty(tmp_path, capsys):
    review_path = tmp_path / "reviews.jsonl"
    release_path = tmp_path / "releases.jsonl"
    reviews = []
    for source in baseline_and_spike() + [row("5.4", 0, 3)]:
        for i in range(source["reviews"]):
            complaint = i < source["complaints"]
            reviews.append({
                "id": f"{source['version']}-{i}", "app_version": source["version"],
                "date": "2026-01-01T00:00:00Z", "rating": 1 if complaint else 5,
                "title": "Sync failed" if complaint else "Works well", "text": "",
            })
    review_path.write_text("".join(json.dumps(r) + "\n" for r in reviews), encoding="utf-8")
    release_path.write_text(
        json.dumps({"version": "5.5", "release_date": "2026-02-01T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    args = ["--reviews", str(review_path), "--releases", str(release_path)]
    fv.main(args + ["--json"])
    report = json.loads(capsys.readouterr().out)
    assert [c["version"] for c in report["comparisons"]] == ["5.4", "5.5"]
    assert all(c["verdict"] == "insufficient_data" for c in report["comparisons"])
    fv.main(args)
    output = capsys.readouterr().out
    assert "Regression 5.3" in output and "insufficient_data" in output
    assert "not a proven firmware or causal fix" in output
    with pytest.raises(SystemExit) as error:
        fv.main(args + ["--window", "0"])
    assert error.value.code == 2
