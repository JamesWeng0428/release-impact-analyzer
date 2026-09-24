# Garmin Firmware Release Impact Analyzer

CS410 (Fall 2026) final project by James Weng (zweng7).

Garmin users with sync and Bluetooth problems have to dig through forum threads,
support FAQs and firmware changelogs to find out whether their issue is a known
bug and whether a later release fixed it. This project:

1. **Searches** forum posts with a C++ retrieval engine (inverted index + BM25),
   using a symptom or a changelog entry as the query.
2. **Mines** complaints with topic modeling and tracks each issue across
   firmware releases, to spot which release introduced a problem and whether a
   "fixed" item actually reduced complaints.

## Layout

```
include/ria/   public C++ headers
src/           C++ core library (ria_core)
apps/          command-line tool (ria)
tests/         GoogleTest unit tests
python/        pybind11 bindings, used by the evaluation scripts
```

## Build and test

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure
```

Try the tokenizer by hand:

```bash
echo "Edge 1050 won't sync after 31.20" | ./build/ria
```

Build the Python module (in its own build directory, without sanitizers):

```bash
cmake -S . -B build-py -G Ninja -DCMAKE_BUILD_TYPE=Release -DRIA_BUILD_TESTS=OFF -DRIA_BUILD_PYTHON=ON -DPython_EXECUTABLE="$(which python3)"
cmake --build build-py
PYTHONPATH=build-py python3 -c "import ria; print(ria.tokenize('Edge 1050 sync failed after 31.20'))"
```

Options (pass as `-DNAME=ON`):

| Option | Default | Purpose |
|---|---|---|
| `RIA_BUILD_TESTS` | ON | Build unit tests (downloads GoogleTest) |
| `RIA_BUILD_PYTHON` | OFF | Build the `ria` Python module (needs pybind11) |
| `RIA_WARNINGS_AS_ERRORS` | OFF | `-Werror`; CI turns it on |
| `RIA_SANITIZE` | OFF | AddressSanitizer + UBSan; CI turns it on |

## Roadmap

- [x] Tokenizer (keeps firmware versions like `31.20` as one term)
- [x] Inverted index (postings with term frequencies, document lengths)
- [ ] Document store (external ids, title, device, date)
- [ ] BM25 ranking + top-k retrieval
- [ ] Field boosting (device model, firmware version)
- [ ] Forum crawler (Python, rate-limited, follows robots.txt)
- [ ] Changelog parser
- [ ] Relevance labels + evaluation (NDCG@10 vs keyword baseline)
- [ ] Topic modeling + per-release issue trends
- [ ] CI regression gates on quality, latency and memory
