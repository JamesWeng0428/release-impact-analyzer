#include "ria/tokenizer.h"

#include <gtest/gtest.h>

#include <string>
#include <vector>

using ria::tokenize;
using Tokens = std::vector<std::string>;

TEST(Tokenizer, SplitsOnWhitespaceAndPunctuation) {
  EXPECT_EQ(tokenize("Edge 1050: sync failed!"),
            (Tokens{"edge", "1050", "sync", "failed"}));
}

TEST(Tokenizer, LowercasesAscii) {
  EXPECT_EQ(tokenize("BLUETOOTH Pairing"), (Tokens{"bluetooth", "pairing"}));
}

TEST(Tokenizer, KeepsFirmwareVersionsAsOneToken) {
  EXPECT_EQ(tokenize("fixed in beta 31.20"),
            (Tokens{"fixed", "in", "beta", "31.20"}));
  EXPECT_EQ(tokenize("v31.20.1"), (Tokens{"v31.20.1"}));
}

TEST(Tokenizer, SplitsOnDotsNotBetweenDigits) {
  EXPECT_EQ(tokenize("Won't sync. Then 1050."),
            (Tokens{"won", "t", "sync", "then", "1050"}));
  EXPECT_EQ(tokenize("e.g. 31."), (Tokens{"e", "g", "31"}));
}

TEST(Tokenizer, KeepsNonAsciiBytesInsideTokens) {
  EXPECT_EQ(tokenize("café sync"), (Tokens{"café", "sync"}));
}

TEST(Tokenizer, EmptyAndSeparatorOnlyInputGiveNoTokens) {
  EXPECT_TRUE(tokenize("").empty());
  EXPECT_TRUE(tokenize("  ...!?  ").empty());
}
