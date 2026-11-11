"""Kazakh Cyrillic -> Latin (2021 official alphabet draft) with length checks for UI strings.

Letters absent from the 31-letter alphabet (ц, ч, щ, ё, ю, я, э, ъ, ь) follow the
accompanying orthography rules for loanwords; the table is a single dict so it can be adjusted.
"""

from __future__ import annotations

import re

from . import icu

KK_LATIN = {
    "а": "a", "ә": "ä", "б": "b", "в": "v", "г": "g", "ғ": "ğ", "д": "d", "е": "e", "ё": "io",
    "ж": "j", "з": "z", "и": "i", "й": "i", "к": "k", "қ": "q", "л": "l", "м": "m", "н": "n",
    "ң": "ñ", "о": "o", "ө": "ö", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ұ": "ū",
    "ү": "ü", "ф": "f", "х": "h", "һ": "h", "ц": "ts", "ч": "ç", "ш": "ş", "щ": "şş", "ъ": "",
    "ы": "y", "і": "ı", "ь": "", "э": "e", "ю": "iu", "я": "ia",
}
_UPPER_SPECIAL = {"и": "İ", "й": "İ", "і": "I"}


def _char(c: str) -> str:
    low = c.lower()
    if low not in KK_LATIN:
        return c
    if c == low:
        return KK_LATIN[low]
    if low in _UPPER_SPECIAL:
        return _UPPER_SPECIAL[low]
    out = KK_LATIN[low]
    return out[:1].upper() + out[1:]


def transliterate_text(text: str) -> str:
    return "".join(_char(c) for c in text)


_ARG = re.compile(r"\{\s*[^\s{},]+\s*(?:,\s*(?:plural|select|selectordinal)\s*,)?")


def transliterate_message(msg: str) -> str:
    """Transliterate literal text only; placeholder names and ICU keywords stay intact."""
    out, i = [], 0
    for m in _ARG.finditer(msg):
        out.append(transliterate_text(msg[i : m.start()]))
        out.append(m.group(0))
        i = m.end()
    out.append(transliterate_text(msg[i:]))
    res = "".join(out)
    # Plural selectors like `one{` / `other{` must not be touched: they are ASCII already.
    icu.parse(res)  # raises if we broke the message
    return res
