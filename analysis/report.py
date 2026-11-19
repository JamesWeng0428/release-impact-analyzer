"""One command for release trends, regression tests, recovery and source evidence."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from analysis.fix_verification import format_report as format_recovery, verify_fixes
from analysis.inputs import add_input_arguments, load_inputs, release_path
from analysis.regression import detect_changes, format_tests
from analysis.release_timeline import build_timeline, format_table, is_connectivity_complaint

LIMITATIONS = [
    "Connectivity labels use a keyword heuristic, not human ground truth.",
    "App Store reviewers are a self-selected sample; rates are not population failure rates.",
    "Versions are ordered numerically; first-review dates are estimates, not official release dates.",
    "A decline in complaints does not prove a causal fix or device-firmware recovery.",
    "Evidence is a deterministic illustration (review ID order), not a representative sample.",
]


def generate_report(reviews_path: Path, releases_path: Path | None = None, *,
                    window=3, min_reviews=10, min_delta=0.10, alpha=0.05,
                    recovery_margin=0.10, evidence_per_kind=2) -> dict:
    if type(evidence_per_kind) is not int or evidence_per_kind < 0:
        raise ValueError("evidence-per-kind must be a nonnegative integer")
    resolved = release_path(releases_path)
    reviews, releases = load_inputs(reviews_path, resolved)
    rows = build_timeline(reviews, releases)
    recovery = verify_fixes(rows, window, min_reviews, min_delta, alpha, recovery_margin)
    tests = detect_changes(rows, window, min_reviews, min_delta, alpha)
    by_version = {}
    for review in sorted(reviews, key=lambda r: r["id"]):
        bucket = by_version.setdefault(review["app_version"], {"complaint": [], "other": []})
        kind = "complaint" if is_connectivity_complaint(review) else "other"
        if len(bucket[kind]) < evidence_per_kind:
            bucket[kind].append({"kind": kind, **review})
    timeline = []
    for row in rows:
        evidence = by_version.get(row["version"], {"complaint": [], "other": []})
        timeline.append({**row,
                         "sample_status": "eligible" if row["reviews"] >= min_reviews else "insufficient_data",
                         "evidence": evidence["complaint"] + evidence["other"]})

    def source(path):
        return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    return {
        "schema_version": 1,
        "status": "analyzed" if tests else "insufficient_comparable_versions",
        "sources": {"reviews": source(reviews_path),
                    "releases": source(resolved) if resolved is not None else None},
        "review_count": len(reviews), "version_count": len(rows),
        "tested_versions": len(tests),
        "parameters": {**recovery["parameters"], "evidence_per_kind": evidence_per_kind},
        "label_method": "connectivity_keyword_v1",
        "timeline": timeline, "changes": tests, "recovery": recovery,
        "limitations": LIMITATIONS,
    }


def markdown(report: dict) -> str:
    lines = ["# Garmin Connect release impact", "",
             f"Reviews: {report['review_count']} | Versions: {report['version_count']} | "
             f"Tested: {report['tested_versions']}", "",
             "Parameters: `" + json.dumps(report["parameters"], sort_keys=True) + "`", "",
             "Input fingerprints: `" + json.dumps(report["sources"], sort_keys=True) + "`", ""]
    if report["status"] != "analyzed":
        lines += ["Insufficient comparable versions: no regression test was possible.", ""]
    lines += ["## Version timeline", "", "```text", format_table(report["timeline"]), "```", "",
              "## Regression and improvement tests", "", "```text", format_tests(report["changes"]),
              "```", "", "## Recovery", "", "```text", format_recovery(report["recovery"]), "```", "",
              "## Review evidence", ""]
    for row in report["timeline"]:
        lines += [f"### App {row['version']} ({row['sample_status']})", ""]
        for review in row["evidence"]:
            # JSON quoting keeps source text visibly delimited; escape Markdown/HTML.
            text = " ".join(f"{review['title']}. {review['text']}".split())
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            for char in ("\\", "`", "*", "_", "[", "]"):
                text = text.replace(char, "\\" + char)
            lines += [f"- {review['kind']} | ID {json.dumps(review['id'])} | "
                      f"{review['rating']} stars | {review['date']}: {text}"]
        if not row["evidence"]:
            lines.append("No evidence displayed.")
        lines.append("")
    lines += ["## Interpretation limits", "", *[f"- {item}" for item in report["limitations"]]]
    return "\n".join(lines) + "\n"


def write_output(path: Path, text: str, protected=()) -> None:
    for source in protected:
        if source is not None and (path.resolve() == source.resolve() or
                                  (path.exists() and source.exists() and path.samefile(source))):
            raise ValueError("output must not overwrite an input file")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".ria-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_input_arguments(parser)
    parser.add_argument("--window", type=int, default=3)
    parser.add_argument("--min-reviews", type=int, default=10)
    parser.add_argument("--min-delta", type=float, default=0.10)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--recovery-margin", type=float, default=0.10)
    parser.add_argument("--evidence-per-kind", type=int, default=2)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = generate_report(args.reviews, args.releases, window=args.window,
                                 min_reviews=args.min_reviews, min_delta=args.min_delta,
                                 alpha=args.alpha, recovery_margin=args.recovery_margin,
                                 evidence_per_kind=args.evidence_per_kind)
        text = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
                if args.format == "json" else markdown(report))
        if args.output:
            write_output(args.output, text, (args.reviews, release_path(args.releases)))
        else:
            print(text, end="")
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
