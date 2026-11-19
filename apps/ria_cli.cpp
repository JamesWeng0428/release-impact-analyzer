// Command-line search over a corpus with one document per line.
//
//   ./build/ria examples/sample_posts.txt 3
//   > edge 1050 sync failed
//
// Each line typed on stdin is a query; the top-k documents are printed.

#include <cstddef>
#include <charconv>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

#include "ria/bm25.h"
#include "ria/inverted_index.h"

int main(int argc, char** argv) {
  if (argc < 2 || argc > 3) {
    std::cerr << "usage: " << argv[0] << " <corpus.txt> [k]\n";
    return 2;
  }
  std::ifstream corpus(argv[1]);
  if (!corpus) {
    std::cerr << "cannot open " << argv[1] << '\n';
    return 1;
  }
  std::size_t k = 5;
  if (argc == 3) {
    const std::string value(argv[2]);
    const auto parsed = std::from_chars(value.data(), value.data() + value.size(), k);
    if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) {
      std::cerr << "k must be a nonnegative integer within size_t range\n";
      return 2;
    }
  }

  ria::InvertedIndex index;
  std::vector<std::string> texts;  // doc id -> original line, for display
  std::string line;
  while (std::getline(corpus, line)) {
    index.add_document(line);
    texts.push_back(line);
  }
  std::cerr << "indexed " << index.num_documents() << " documents, "
            << index.num_terms() << " terms\n";

  while (std::getline(std::cin, line)) {
    const auto results = ria::bm25_search(index, line, k);
    if (results.empty()) {
      std::cout << "  (no match)\n";
    }
    for (std::size_t i = 0; i < results.size(); ++i) {
      std::cout << "  " << i + 1 << ". [" << std::fixed << std::setprecision(3)
                << results[i].score << "] " << texts[results[i].doc] << '\n';
    }
  }
  return 0;
}
