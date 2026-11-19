"""Flag app versions whose connectivity-complaint rate changed significantly.

Each version is compared with the pooled reviews of the versions just before
it. A version is flagged when

  - a one-sided Fisher exact test finds its rate higher ("regression") or
    lower ("improvement") than that baseline,
  - the p-value survives Benjamini-Hochberg correction across all tests, and
  - the rate moved by at least `min_delta` (so tiny changes are ignored).

    python -m analysis.regression            # flagged versions only
    python -m analysis.regression --all      # every tested version
"""

from __future__ import annotations

import argparse
import math
from analysis.release_timeline import build_timeline, version_key
from analysis.inputs import add_input_arguments, load_inputs


def validate_analysis(rows, window, min_reviews, min_delta, alpha) -> None:
    """Validate before filtering so bad counts cannot disappear as low samples."""
    for name, value in (("window", window), ("min_reviews", min_reviews)):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    for name, value in (("min_delta", min_delta), ("alpha", alpha)):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if not 0 <= min_delta <= 1:
        raise ValueError("min_delta must be between 0 and 1")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    versions = [r["version"] for r in rows]
    if len(set(versions)) != len(versions):
        raise ValueError("versions must be unique")
    if versions != sorted(versions, key=version_key):
        raise ValueError("rows must be in release order")
    for row in rows:
        k, n = row["complaints"], row["reviews"]
        if type(k) is not int or type(n) is not int or not 0 <= k <= n:
            raise ValueError("counts must be integers satisfying 0 <= complaints <= reviews")


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes out of n (95% by default)."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def fisher_one_sided(k1: int, n1: int, k2: int, n2: int, alternative: str = "greater") -> float:
    """P-value that group 1's rate (k1/n1) is greater (or less) than group 2's.

    Conditioning on the total number of successes, k1 follows a
    hypergeometric distribution; the p-value sums its tail.
    """
    total, successes = n1 + n2, k1 + k2
    lo, hi = max(0, n1 - (total - successes)), min(n1, successes)
    tail = range(k1, hi + 1) if alternative == "greater" else range(lo, k1 + 1)
    denom = math.comb(total, n1)
    p = sum(math.comb(successes, x) * math.comb(total - successes, n1 - x) for x in tail)
    return min(1.0, p / denom)


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """BH-adjusted q-values, returned in the same order as `p_values`."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    q = [0.0] * m
    running_min = 1.0
    # Walk from the largest p-value down so q-values stay monotone.
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running_min = min(running_min, p_values[i] * m / rank)
        q[i] = running_min
    return q


def detect_changes(
    rows: list[dict],
    window: int = 3,
    min_reviews: int = 10,
    min_delta: float = 0.10,
    alpha: float = 0.05,
) -> list[dict]:
    """Tests every version with enough reviews against its baseline.

    `rows` come from build_timeline() and must be in release order.
    """
    validate_analysis(rows, window, min_reviews, min_delta, alpha)
    rows = [r for r in rows if r["reviews"] >= min_reviews]
    tests = []
    for i in range(window, len(rows)):
        row, baseline = rows[i], rows[i - window : i]
        k, n = row["complaints"], row["reviews"]
        bk = sum(b["complaints"] for b in baseline)
        bn = sum(b["reviews"] for b in baseline)
        tests.append(
            {
                "version": row["version"],
                "release_date": row["release_date"],
                "reviews": n,
                "complaints": k,
                "rate": k / n,
                "ci": wilson_interval(k, n),
                "baseline_versions": [b["version"] for b in baseline],
                "baseline_rate": bk / bn,
                "delta": k / n - bk / bn,
                "p_regression": fisher_one_sided(k, n, bk, bn, "greater"),
                "p_improvement": fisher_one_sided(k, n, bk, bn, "less"),
            }
        )

    # Both directions for every version form one family of tests.
    q = benjamini_hochberg([t["p_regression"] for t in tests] + [t["p_improvement"] for t in tests])
    for t, q_reg, q_imp in zip(tests, q[: len(tests)], q[len(tests) :]):
        t["q_regression"], t["q_improvement"] = q_reg, q_imp
        if q_reg < alpha and t["delta"] >= min_delta:
            t["verdict"] = "regression"
        elif q_imp < alpha and t["delta"] <= -min_delta:
            t["verdict"] = "improvement"
        else:
            t["verdict"] = ""
    return tests


def format_tests(tests: list[dict]) -> str:
    lines = [
        f"{'version':<9} {'released':<11} {'n':>4} {'rate [95% CI]':<17} "
        f"{'baseline':>8} {'Δ':>5} {'q':>7}  verdict"
    ]
    for t in tests:
        lo, hi = t["ci"]
        q = min(t["q_regression"], t["q_improvement"])
        lines.append(
            f"{t['version']:<9} {t['release_date']:<11} {t['reviews']:>4} "
            f"{100 * t['rate']:>3.0f}% [{100 * lo:>2.0f}-{100 * hi:>3.0f}%]  "
            f"{100 * t['baseline_rate']:>7.0f}% {100 * t['delta']:>+5.0f} {q:>7.4f}  {t['verdict']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_input_arguments(parser)
    parser.add_argument("--window", type=int, default=3, help="previous versions pooled as baseline")
    parser.add_argument("--min-reviews", type=int, default=10)
    parser.add_argument("--min-delta", type=float, default=0.10, help="minimum rate change, e.g. 0.10")
    parser.add_argument("--alpha", type=float, default=0.05, help="false discovery rate")
    parser.add_argument("--all", action="store_true", help="show every tested version")
    args = parser.parse_args(argv)

    try:
        rows = build_timeline(*load_inputs(args.reviews, args.releases))
        tests = detect_changes(rows, args.window, args.min_reviews, args.min_delta, args.alpha)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    shown = tests if args.all else [t for t in tests if t["verdict"]]
    print(format_tests(shown))
    print(f"\n{sum(bool(t['verdict']) for t in tests)} of {len(tests)} tested versions flagged")


if __name__ == "__main__":
    main()
