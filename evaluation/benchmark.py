"""Measure local search latency and whole-process peak RSS; no quality claims."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import resource
from statistics import median
from time import perf_counter

from analysis.report import write_output
from evaluation.retrieval import load_queries
from retrieval.search import SYSTEMS, ReviewSearch, load_documents


def benchmark(reviews: Path, queries: Path, repetitions=20, warmup=2) -> dict:
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    if type(warmup) is not int or warmup < 0:
        raise ValueError("warmup must be a nonnegative integer")
    query_set = load_queries(queries)
    start = perf_counter()
    documents = load_documents(reviews)
    if not documents:
        raise ValueError("review collection is empty")
    engine = ReviewSearch(documents)
    index_seconds = perf_counter() - start
    timings = {}
    for system in SYSTEMS:
        for _ in range(warmup):
            for query in query_set:
                engine.search(query["text"], system=system)
        samples = []
        for _ in range(repetitions):
            for query in query_set:
                start = perf_counter()
                engine.search(query["text"], system=system)
                samples.append((perf_counter() - start) * 1000)
        samples.sort()
        timings[system] = {"queries_measured": len(samples), "p50_ms": median(samples),
                           "p95_ms": samples[math.ceil(0.95 * len(samples)) - 1],
                           "max_ms": max(samples)}
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = rss if platform.system() == "Darwin" else rss * 1024
    root = Path(__file__).resolve().parents[1]
    return {
        "schema_version": 1,
        "environment": {"python": platform.python_version(), "system": platform.system(),
                        "machine": platform.machine()},
        "reviews": len(documents), "queries": len(query_set),
        "repetitions": repetitions, "warmup": warmup, "top_k": 10,
        "reviews_sha256": hashlib.sha256(reviews.read_bytes()).hexdigest(),
        "queries_sha256": hashlib.sha256(queries.read_bytes()).hexdigest(),
        "implementation_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("src/bm25.cpp", "src/inverted_index.cpp", "src/tokenizer.cpp",
                         "python/bindings.cpp", "retrieval/search.py", "evaluation/benchmark.py")
        },
        "load_and_index_seconds": index_seconds,
        "process_peak_rss_mib": rss_bytes / 1024**2,
        "timings": timings,
        "limitations": ["Peak RSS includes Python, native code, inputs and all benchmark work; not index size.",
                        "Latency excludes loading/indexing and CLI startup; filters are not measured.",
                        "Results describe this machine and corpus; not a portable performance guarantee."],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", type=Path, default=Path("data/appstore_reviews.jsonl"))
    parser.add_argument("--queries", type=Path, default=Path("evaluation/queries.jsonl"))
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = benchmark(args.reviews, args.queries, args.repetitions, args.warmup)
        text = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            write_output(args.output, text, (args.reviews, args.queries))
        else:
            print(text, end="")
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
