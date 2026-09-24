#include "ria/inverted_index.h"

#include <gtest/gtest.h>

#include <ostream>
#include <vector>

namespace ria {
// Lets GoogleTest print postings readably when an assertion fails.
void PrintTo(const Posting& p, std::ostream* os) {
  *os << "{doc=" << p.doc << ", tf=" << p.tf << "}";
}
}  // namespace ria

namespace {

using ria::InvertedIndex;
using ria::Posting;

std::vector<Posting> postings_of(const InvertedIndex& index,
                                 std::string_view term) {
  const auto span = index.postings(term);
  return {span.begin(), span.end()};
}

TEST(InvertedIndex, EmptyIndex) {
  const InvertedIndex index;
  EXPECT_EQ(index.num_documents(), 0u);
  EXPECT_EQ(index.num_terms(), 0u);
  EXPECT_EQ(index.average_doc_length(), 0.0);
  EXPECT_TRUE(index.postings("sync").empty());
}

TEST(InvertedIndex, AssignsDenseDocIdsInOrder) {
  InvertedIndex index;
  EXPECT_EQ(index.add_document("sync failed"), 0u);
  EXPECT_EQ(index.add_document("bluetooth dropped"), 1u);
  EXPECT_EQ(index.add_document("pairing"), 2u);
  EXPECT_EQ(index.num_documents(), 3u);
}

TEST(InvertedIndex, CountsTermFrequencyWithinADocument) {
  InvertedIndex index;
  index.add_document("Sync failed. Sync failed again.");
  EXPECT_EQ(postings_of(index, "sync"), (std::vector<Posting>{{0, 2}}));
  EXPECT_EQ(postings_of(index, "again"), (std::vector<Posting>{{0, 1}}));
}

TEST(InvertedIndex, PostingsAreSortedByDocAndGiveDocumentFrequency) {
  InvertedIndex index;
  index.add_document("sync failed");
  index.add_document("bluetooth dropped");
  index.add_document("sync sync");
  EXPECT_EQ(postings_of(index, "sync"),
            (std::vector<Posting>{{0, 1}, {2, 2}}));
  EXPECT_EQ(index.document_frequency("sync"), 2u);
  EXPECT_EQ(index.document_frequency("bluetooth"), 1u);
  EXPECT_EQ(index.document_frequency("missing"), 0u);
}

TEST(InvertedIndex, TracksDocumentLengths) {
  InvertedIndex index;
  index.add_document("edge 1050 sync failed");  // 4 tokens
  index.add_document("");                       // 0 tokens
  index.add_document("pairing");                // 1 token
  EXPECT_EQ(index.doc_length(0), 4u);
  EXPECT_EQ(index.doc_length(1), 0u);
  EXPECT_EQ(index.doc_length(2), 1u);
  EXPECT_DOUBLE_EQ(index.average_doc_length(), 5.0 / 3.0);
}

TEST(InvertedIndex, IndexesFirmwareVersionsAsOneTerm) {
  InvertedIndex index;
  index.add_document("Dropouts fixed in beta 31.20");
  EXPECT_EQ(index.document_frequency("31.20"), 1u);
  EXPECT_EQ(index.document_frequency("20"), 0u);
}

TEST(InvertedIndex, CountsDistinctTerms) {
  InvertedIndex index;
  index.add_document("sync failed");
  index.add_document("sync dropped");
  EXPECT_EQ(index.num_terms(), 3u);  // sync, failed, dropped
}

}  // namespace
