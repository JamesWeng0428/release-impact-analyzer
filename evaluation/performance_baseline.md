# Local performance baseline

Measured November 19, 2026, with Python 3.12.4 on macOS arm64.

Command: `PYTHONPATH=build-py python -m evaluation.benchmark`.

1,435 reviews; 24 queries; top 10; two warmup passes and 20 measured passes (480 queries per method).

| Method | p50 (ms) | p95 (ms) | Max (ms) |
|---|---:|---:|---:|
| keyword | 0.1797 | 0.3690 | 0.3993 |
| bm25 | 0.0102 | 0.0128 | 0.0167 |
| bm25_expanded | 0.0117 | 0.0158 | 0.0327 |

Load/index time: 0.0249 seconds. Whole-process peak RSS: 37.11 MiB.

This is one local run, not a cross-machine performance guarantee. RSS includes the interpreter, native code, corpus and benchmark work; it is not the index size. Warm search latency excludes CLI startup, corpus loading and filtering. CI runs a smoke benchmark without unstable timing thresholds.

[Raw measurements](performance_baseline.json) include corpus/query hashes, implementation hashes and environment metadata. The corpus hash differs from the evaluation snapshot because file ordering/serialization differs; the evaluation uses a separately frozen input. Neither corpus is committed.
