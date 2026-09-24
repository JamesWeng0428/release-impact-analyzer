#include "ria/tokenizer.h"

namespace ria {
namespace {

bool is_digit(char c) { return c >= '0' && c <= '9'; }

bool is_upper(char c) { return c >= 'A' && c <= 'Z'; }

bool is_token_char(char c) {
  return is_digit(c) || is_upper(c) || (c >= 'a' && c <= 'z') ||
         static_cast<unsigned char>(c) >= 0x80;
}

char to_lower(char c) {
  return is_upper(c) ? static_cast<char>(c - 'A' + 'a') : c;
}

}  // namespace

std::vector<std::string> tokenize(std::string_view text) {
  std::vector<std::string> tokens;
  std::string current;

  for (std::size_t i = 0; i < text.size(); ++i) {
    const char c = text[i];
    // `current` is non-empty only when i > 0, so text[i - 1] is safe here.
    const bool version_dot = c == '.' && !current.empty() &&
                             is_digit(text[i - 1]) && i + 1 < text.size() &&
                             is_digit(text[i + 1]);

    if (is_token_char(c) || version_dot) {
      current.push_back(to_lower(c));
    } else if (!current.empty()) {
      tokens.push_back(std::move(current));
      current.clear();
    }
  }
  if (!current.empty()) {
    tokens.push_back(std::move(current));
  }
  return tokens;
}

}  // namespace ria
