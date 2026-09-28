import pytest

from analysis import regression as rg


def test_wilson_interval_known_values():
    assert rg.wilson_interval(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert rg.wilson_interval(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-4)
    assert rg.wilson_interval(0, 0) == (0.0, 1.0)


def test_fisher_one_sided_matches_lady_tasting_tea():
    # 3 of 4 vs 1 of 4: P(X >= 3) = (16 + 1) / 70.
    assert rg.fisher_one_sided(3, 4, 1, 4, "greater") == pytest.approx(17 / 70)
    assert rg.fisher_one_sided(1, 4, 3, 4, "less") == pytest.approx(17 / 70)
    # Identical groups give no evidence either way.
    assert rg.fisher_one_sided(2, 4, 2, 4, "greater") > 0.5


def test_benjamini_hochberg_hand_computed():
    q = rg.benjamini_hochberg([0.01, 0.04, 0.03, 0.2])
    assert q == pytest.approx([0.04, 0.16 / 3, 0.16 / 3, 0.2])
    assert rg.benjamini_hochberg([]) == []


def row(version, complaints, reviews):
    return {"version": version, "release_date": "2026-01-01",
            "complaints": complaints, "reviews": reviews}


def test_detect_changes_flags_regression_then_fix():
    rows = [
        row("5.1", 1, 30),
        row("5.2", 2, 30),
        row("5.3", 1, 30),
        row("5.3.1", 0, 3),    # too few reviews: skipped, not used as baseline
        row("5.4", 20, 30),    # spike
        row("5.4.1", 1, 30),   # hotfix
        row("5.5", 3, 30),     # back to normal: small change, not flagged
    ]
    tests = rg.detect_changes(rows, window=1, min_reviews=10)
    verdicts = {t["version"]: t["verdict"] for t in tests}
    assert verdicts == {"5.2": "", "5.3": "", "5.4": "regression", "5.4.1": "improvement", "5.5": ""}
    spike = next(t for t in tests if t["version"] == "5.4")
    assert spike["baseline_versions"] == ["5.3"]
    assert spike["ci"][0] > spike["baseline_rate"]


def test_significant_but_small_change_is_not_flagged():
    rows = [row("5.1", 500, 5000), row("5.2", 600, 5000)]  # 10% -> 12%
    [t] = rg.detect_changes(rows, window=1, min_reviews=10, min_delta=0.10)
    assert t["q_regression"] < 0.05
    assert t["verdict"] == ""
