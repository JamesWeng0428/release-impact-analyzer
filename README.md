# Garmin Firmware Release Impact Analyzer

CS410 (Fall 2026) final project by James Weng (zweng7).

Garmin users with sync and Bluetooth problems have to dig through forum threads,
support FAQs and firmware changelogs to find out whether their issue is a known
bug and whether a later release fixed it. This project:

1. **Searches** user reports (App Store reviews; forum posts later) with a C++
   retrieval engine (inverted index + BM25),
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
examples/      small made-up corpus for demos
python/        pybind11 bindings, used by the evaluation scripts
crawler/       data collection (Python, standard library only)
```

## Build and test

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure
```

Search a corpus (one document per line); each line typed on stdin is a query:

```bash
./build/ria examples/sample_posts.txt 3
```

`examples/sample_posts.txt` holds a few made-up example posts for demos.

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

## Data

Garmin Connect reviews come from Apple's public App Store review feed. Each
country serves only its most recent reviews, so the fetcher merges every run
into one JSONL file (keyed by review id); running it weekly builds up history
across app versions. Reviewer names are not stored, and `data/` is not
committed.

```bash
python3 -m crawler.appstore_reviews fetch                      # -> data/appstore_reviews.jsonl
python3 -m crawler.appstore_reviews export > data/corpus.txt   # one review per line
./build/ria data/corpus.txt 5
python3 -m pytest -q crawler                                   # offline unit tests
```

Garmin forum posts are on hold until it is clear that crawling them fits
Garmin's Terms of Use.

## Roadmap

- [x] Tokenizer (keeps firmware versions like `31.20` as one term)
- [x] Inverted index (postings with term frequencies, document lengths)
- [ ] Document store (external ids, title, device, date)
- [x] BM25 ranking + top-k retrieval
- [ ] Stemming / query expansion ("dropout" vs "drops out", "pair" vs "pairing")
- [ ] Field boosting (device model, firmware version)
- [x] App Store review fetcher (Garmin Connect, versioned reviews)
- [ ] Garmin forum posts (on hold: Terms of Use)
- [ ] Changelog parser
- [ ] Relevance labels + evaluation (NDCG@10 vs keyword baseline)
- [ ] Topic modeling + per-release issue trends
- [ ] CI regression gates on quality, latency and memory
