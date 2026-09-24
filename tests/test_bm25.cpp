#include "ria/bm25.h"

#include <gtest/gtest.h>

#include <cmath>
#include <initializer_list>
#include <ostream>
#include <string_view>
#include <vector>

namespace ria {
void PrintTo(const SearchResult& r, std::ostream* os) {
  *os << "{doc=" << r.doc << ", score=" << r.score << "}";
}
}  // namespace ria

namespace {

using ria::bm25_idf;
using ria::bm25_search;
using ria::DocId;
using ria::InvertedIndex;

InvertedIndex make_index(std::initializer_list<std::string_view> docs) {
  InvertedIndex index;
  for (const std::string_view doc : docs) {
    index.add_document(doc);
  }
  return index;
}

std::vector<DocId> ranked_docs(const InvertedIndex& index,
                               std::string_view query, std::size_t k = 10) {
  std::vector<DocId> docs;
  for (const auto& r : bm25_search(index, query, k)) {
    docs.push_back(r.doc);
  }
  return docs;
}

TEST(Bm25Idf, RarerTermsGetHigherIdf) {
  EXPECT_NEAR(bm25_idf(10, 1), std::log(1.0 + 9.5 / 1.5), 1e-12);
  EXPECT_GT(bm25_idf(10, 1), bm25_idf(10, 5));
  EXPECT_GT(bm25_idf(10, 10), 0.0);  // still positive when every doc has it
}

TEST(Bm25Search, ScoreMatchesHandComputedValue) {
  // N = 2, df("sync") = 1, |d0| = avgdl = 2, tf = 1.
  // idf = ln(1 + 1.5 / 1.5) = ln 2, and the tf part is
  // 1 * (k1 + 1) / (1 + k1) = 1, so the score is exactly ln 2.
  const auto index = make_index({"sync failed", "bluetooth dropped"});
  const auto results = bm25_search(index, "sync", 10);
  ASSERT_EQ(results.size(), 1u);
  EXPECT_EQ(results[0].doc, 0u);
  EXPECT_NEAR(results[0].score, std::log(2.0), 1e-12);
}

TEST(Bm25Search, HigherTermFrequencyRanksFirst) {
  const auto index = make_index({"sync failed", "sync sync"});
  EXPECT_EQ(ranked_docs(index, "sync"), (std::vector<DocId>{1, 0}));
}

TEST(Bm25Search, ShorterDocumentRanksFirstForSameTermFrequency) {
  const auto index =
      make_index({"sync issue after the latest firmware update", "sync"});
  EXPECT_EQ(ranked_docs(index, "sync"), (std::vector<DocId>{1, 0}));
}

TEST(Bm25Search, RareTermOutweighsCommonTerm) {
  const auto index = make_index({"sync x", "sync y", "bluetooth z"});
  EXPECT_EQ(ranked_docs(index, "sync bluetooth").front(), 2u);
}

TEST(Bm25Search, RepeatedQueryTermCountsTwice) {
  const auto index = make_index({"sync failed", "bluetooth dropped"});
  const double once = bm25_search(index, "sync", 1)[0].score;
  const double twice = bm25_search(index, "sync SYNC", 1)[0].score;
  EXPECT_NEAR(twice, 2.0 * once, 1e-12);
}

TEST(Bm25Search, ReturnsAtMostKAndBreaksTiesByDocId) {
  const auto index =
      make_index({"sync failed", "sync failed", "sync failed", "unrelated"});
  EXPECT_EQ(ranked_docs(index, "sync", 2), (std::vector<DocId>{0, 1}));
}

TEST(Bm25Search, MatchesFirmwareVersions) {
  const auto index =
      make_index({"sensor dropouts fixed in 31.20", "released 20 new faces"});
  EXPECT_EQ(ranked_docs(index, "31.20"), (std::vector<DocId>{0}));
}

TEST(Bm25Search, EmptyCases) {
  const auto index = make_index({"sync failed"});
  EXPECT_TRUE(bm25_search(index, "pairing", 10).empty());  // no match
  EXPECT_TRUE(bm25_search(index, "", 10).empty());         // empty query
  EXPECT_TRUE(bm25_search(index, "sync", 0).empty());      // k = 0
  EXPECT_TRUE(bm25_search(InvertedIndex{}, "sync", 10).empty());
}

}  // namespace
