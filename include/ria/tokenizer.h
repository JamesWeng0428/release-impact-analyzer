#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace ria {

// Splits text into search terms.
//
// Rules:
//   - ASCII letters and digits form tokens; ASCII letters are lowercased.
//   - Every other ASCII character separates tokens, except a '.' between two
//     digits, which stays inside the token so firmware versions such as
//     "31.20" remain one term instead of "31" and "20".
//   - Non-ASCII bytes (UTF-8) are kept inside tokens unchanged, so words like
//     "café" are not split apart.
std::vector<std::string> tokenize(std::string_view text);

}  // namespace ria
