"""Compare releases after a detected regression with the spike and its baseline.

Later releases are candidates, not assumed hotfixes. Exact binomial intervals
are widened for every eligible version and every possible pooled baseline
before selecting regression episodes. Differences of their endpoints give
conservative simultaneous bounds, even when groups overlap.

    python -m analysis.fix_verification
    python -m analysis.fix_verification --recovery-margin 0.05 --json
"""

from __future__ import annotations

import argparse
import json
import math
from functools import lru_cache

from analysis.regression import detect_changes, validate_analysis
from analysis.release_timeline import build_timeline
from analysis.inputs import add_input_arguments, load_inputs


@lru_cache(maxsize=128)
def _log_binomial_coefficients(n: int) -> tuple[float, ...]:
    return tuple(
        math.lgamma(n + 1) - math.lgamma(x + 1) - math.lgamma(n - x + 1)
        for x in range(n + 1)
    )


def _binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k); sum in log space to avoid overflowing combinations."""
    if p == 0:
        return 1.0
    if p == 1:
        return float(k == n)
    log_p, log_q = math.log(p), math.log1p(-p)
    terms = [
        coefficient + x * log_p + (n - x) * log_q
        for x, coefficient in enumerate(_log_binomial_coefficients(n)[: k + 1])
    ]
    largest = max(terms)
    return min(1.0, math.exp(largest) * math.fsum(math.exp(t - largest) for t in terms))


def _upper_limit(k: int, n: int, tail: float) -> float:
    if k == n:
        return 1.0
    if k == 0:
        return -math.expm1(math.log(tail) / n)
    lo, hi = k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _binomial_cdf(k, n, mid) > tail:
            lo = mid
        else:
            hi = mid
    return hi


def exact_interval(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Clopper-Pearson interval, computed by binomial-tail inversion.

    With no observations the interval is [0, 1]. See NIST:
    https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm
    """
    if not isinstance(k, int) or not isinstance(n, int) or not 0 <= k <= n:
        raise ValueError("counts must be integers satisfying 0 <= complaints <= reviews")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    if n == 0:
        return 0.0, 1.0
    tail = alpha / 2
    return 1 - _upper_limit(n - k, n, tail), _upper_limit(k, n, tail)


def _difference_interval(
    first: tuple[float, float], second: tuple[float, float]
) -> tuple[float, float]:
    return first[0] - second[1], first[1] - second[0]


def verify_fixes(
    rows: list[dict],
    window: int = 3,
    min_reviews: int = 10,
    min_delta: float = 0.10,
    alpha: float = 0.05,
    recovery_margin: float = 0.10,
) -> dict:
    """Analyze every later release up to (excluding) the next regression.

    Rows must have unique versions in release order, as in build_timeline().
    Low-sample rows remain visible but do not enter tests or pooled baselines.
    The baseline is frozen at the versions preceding each regression.
    """
    validate_analysis(rows, window, min_reviews, min_delta, alpha)
    if type(recovery_margin) not in (int, float) or not 0 <= recovery_margin <= 1:
        raise ValueError("recovery_margin must be between 0 and 1")

    eligible = [r for r in rows if r["reviews"] >= min_reviews]
    regressions = [
        t for t in detect_changes(rows, window, min_reviews, min_delta, alpha)
        if t["verdict"] == "regression"
    ]
    # Count the whole possible family BEFORE selecting flagged regressions.
    # Bonferroni does not require independent intervals. Each group has two
    # endpoints; alpha / groups is the total error budget for that interval.
    groups = len(eligible) + max(0, len(eligible) - window)
    report = {
        "parameters": {
            "window": window, "min_reviews": min_reviews, "min_delta": min_delta,
            "alpha": alpha, "recovery_margin": recovery_margin,
        },
        "confidence_groups": groups,
        "regressions": regressions,
        "comparisons": [],
    }
    if not regressions:
        return report

    intervals = {
        r["version"]: exact_interval(r["complaints"], r["reviews"], alpha / groups)
        for r in eligible
    }
    by_version = {r["version"]: r for r in rows}
    positions = {r["version"]: i for i, r in enumerate(rows)}
    for index, regression in enumerate(regressions):
        version = regression["version"]
        baseline = [by_version[v] for v in regression["baseline_versions"]]
        bk = sum(r["complaints"] for r in baseline)
        bn = sum(r["reviews"] for r in baseline)
        baseline_ci = exact_interval(bk, bn, alpha / groups)
        stop = (
            positions[regressions[index + 1]["version"]]
            if index + 1 < len(regressions) else len(rows)
        )
        for row in rows[positions[version] + 1 : stop]:
            n, k = row["reviews"], row["complaints"]
            rate = k / n if n else None
            comparison = {
                "regression_version": version,
                "version": row["version"],
                "release_date": row["release_date"],
                "reviews": n, "complaints": k, "rate": rate,
                "regression_reviews": regression["reviews"],
                "regression_complaints": regression["complaints"],
                "regression_rate": regression["rate"],
                "baseline_versions": regression["baseline_versions"],
                "baseline_reviews": bn, "baseline_complaints": bk,
                "baseline_rate": bk / bn,
                "drop": regression["rate"] - rate if rate is not None else None,
                "baseline_delta": rate - bk / bn if rate is not None else None,
                "drop_ci": None, "baseline_delta_ci": None,
                "improvement_supported": False,
                "baseline_status": "insufficient_data",
                "verdict": "insufficient_data",
            }
            if n >= min_reviews:
                candidate_ci = intervals[row["version"]]
                drop_ci = _difference_interval(intervals[version], candidate_ci)
                baseline_delta_ci = _difference_interval(candidate_ci, baseline_ci)
                improved = drop_ci[0] > 0 and comparison["drop"] >= min_delta
                recovered = baseline_delta_ci[1] <= recovery_margin
                elevated = (
                    baseline_delta_ci[0] > 0
                    and comparison["baseline_delta"] >= min_delta
                )
                # The margin is an explicit tolerance: evidence of a smaller
                # excess is not evidence of exact equality or of a causal fix.
                status = (
                    "within_margin" if recovered else "elevated" if elevated else "uncertain"
                )
                if improved and recovered:
                    verdict = "recovery_supported"
                elif improved and elevated:
                    verdict = "partial_recovery"
                elif improved:
                    verdict = "improved_recovery_uncertain"
                else:
                    verdict = "no_clear_improvement"
                comparison.update(
                    drop_ci=drop_ci, baseline_delta_ci=baseline_delta_ci,
                    improvement_supported=improved, baseline_status=status, verdict=verdict,
                )
            report["comparisons"].append(comparison)
    return report


def format_report(report: dict) -> str:
    parameters = report["parameters"]
    confidence = 100 * (1 - parameters["alpha"])
    margin = 100 * parameters["recovery_margin"]
    lines = [
        "Garmin Connect connectivity complaint recovery",
        f"Recovery tolerance: +{margin:g} percentage points above the pre-regression baseline.",
        f"Conservative {confidence:g}% simultaneous bounds across "
        f"{report['confidence_groups']} possible rate groups; changes are in percentage points.",
    ]
    if not report["regressions"]:
        lines.append("\nNo regressions detected; there are no fix candidates to compare.")

    def change(value: float | None, bounds: tuple[float, float] | None) -> str:
        if value is None:
            return "-"
        if bounds is None:
            return f"{100 * value:+.1f} [insufficient]"
        return f"{100 * value:+.1f} [{100 * bounds[0]:+.1f},{100 * bounds[1]:+.1f}]"

    for regression in report["regressions"]:
        comparisons = [
            c for c in report["comparisons"]
            if c["regression_version"] == regression["version"]
        ]
        lines.extend([
            f"\nRegression {regression['version']}: "
            f"{regression['complaints']}/{regression['reviews']} complaints "
            f"({100 * regression['rate']:.1f}%).",
            f"Frozen baseline: {', '.join(regression['baseline_versions'])} "
            f"({100 * regression['baseline_rate']:.1f}%).",
        ])
        if not comparisons:
            lines.append("No later releases observed before the next regression.")
            continue
        lines.append(
            f"{'version':<10} {'released':<11} {'n':>5} {'rate':>6} "
            f"{'drop vs regression [CI]':<25} {'excess vs baseline [CI]':<25} "
            f"{'baseline':<14} verdict"
        )
        for c in comparisons:
            rate = "-" if c["rate"] is None else f"{100 * c['rate']:.1f}%"
            lines.append(
                f"{c['version']:<10} {c['release_date']:<11} {c['reviews']:>5} {rate:>6} "
                f"{change(c['drop'], c['drop_ci']):<25} "
                f"{change(c['baseline_delta'], c['baseline_delta_ci']):<25} "
                f"{c['baseline_status']:<14} {c['verdict']}"
            )
    lines.append(
        "\nA lower observed rate or an inconclusive baseline comparison does not establish recovery. "
        "Results describe keyword-labeled App Store reviews, not a proven firmware or causal fix."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_input_arguments(parser)
    parser.add_argument("--window", type=int, default=3, help="previous eligible versions pooled as baseline")
    parser.add_argument("--min-reviews", type=int, default=10)
    parser.add_argument("--min-delta", type=float, default=0.10, help="minimum observed change in rate")
    parser.add_argument("--alpha", type=float, default=0.05, help="error budget for detection and recovery bounds")
    parser.add_argument("--recovery-margin", type=float, default=0.10,
                        help="maximum tolerated excess over baseline, e.g. 0.10 = 10 percentage points")
    parser.add_argument("--json", action="store_true", help="emit the full structured report")
    args = parser.parse_args(argv)
    try:
        rows = build_timeline(*load_inputs(args.reviews, args.releases))
        report = verify_fixes(
            rows, args.window, args.min_reviews, args.min_delta,
            args.alpha, args.recovery_margin,
        )
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, allow_nan=False) if args.json else format_report(report))


if __name__ == "__main__":
    main()
