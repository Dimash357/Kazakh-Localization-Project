"""Glossary: CSV with columns ru, kk, en, note (+ optional match columns).

Required columns: ru, kk, en, note.
Optional columns (regular expressions, case-insensitive):
  ru_match      - how to find the term in the source (default: derived from `ru` stem)
  kk_match      - accepted target forms (default: derived from every `kk` variant)
  kk_forbidden  - known wrong renderings; finding them gives a high-severity violation
  uz            - Uzbek rendering (used when the target locale is uz)
  status        - `approved` (default) is enforced by `check`. `reference`, `pending`
                  or `draft` keep the term in the file as an approved or proposed
                  translation but do NOT enforce it: no findings are produced.
`kk` may list several accepted variants separated by `|`; the first one is preferred.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass

_VOWEL_TAIL = re.compile(r"[аеёиоуыэюяәөүұі]+$", re.I)
_B = r"(?<![^\W\d_])"  # left word boundary that works for Cyrillic


def _stem_regex(term: str) -> str:
    term = term.strip()
    if " " in term or not re.fullmatch(r"[^\W\d_]+", term):
        return _B + re.escape(term)
    stem = _VOWEL_TAIL.sub("", term) if len(term) > 4 else term
    if len(stem) < 3:
        stem = term
    return _B + re.escape(stem)


@dataclass
class Term:
    ru: str
    kk: list[str]
    en: str
    note: str
    ru_rx: re.Pattern
    kk_rx: re.Pattern
    forbidden_rx: re.Pattern | None
    forbidden_literals: list[str]
    uz: list[str]
    uz_rx: re.Pattern | None

    @property
    def preferred(self) -> str:
        return self.kk[0]


    # Glossary has columns only for these target languages. For any other
    # locale (en, es, ...) the glossary is not applicable: using the Kazakh
    # column against an English file produced dozens of false alarms.
    SUPPORTED_LANGS = ("kk", "uz")

    def target_rx(self, lang: str) -> re.Pattern | None:
        if lang not in self.SUPPORTED_LANGS:
            return None
        return self.uz_rx if lang == "uz" else self.kk_rx

    def target_terms(self, lang: str) -> list[str]:
        if lang not in self.SUPPORTED_LANGS:
            return []
        return self.uz if lang == "uz" else self.kk


def _compile(rx: str) -> re.Pattern:
    return re.compile(rx, re.I | re.UNICODE)


NOT_ENFORCED = {"reference", "pending", "draft", "справочный", "на согласовании"}


def load_glossary(path: str | None, include_reference: bool = False) -> list[Term]:
    if not path:
        return []
    terms: list[Term] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"ru", "kk", "en"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: нет колонок {', '.join(sorted(missing))}")
        for row in reader:
            ru = (row.get("ru") or "").strip()
            kk = [v.strip() for v in (row.get("kk") or "").split("|") if v.strip()]
            if not ru or not kk:
                continue
            if not include_reference and (row.get("status") or "approved").strip().lower() in NOT_ENFORCED:
                continue
            uz = [v.strip() for v in (row.get("uz") or "").split("|") if v.strip()]
            ru_rx = _B + "(?:" + row["ru_match"] + ")" if row.get("ru_match") else _stem_regex(ru)
            kk_rx = _B + "(?:" + row["kk_match"] + ")" if row.get("kk_match") else "|".join(f"(?:{_stem_regex(v)})" for v in kk)
            forb = (row.get("kk_forbidden") or "").strip()
            terms.append(
                Term(
                    ru=ru,
                    kk=kk,
                    en=(row.get("en") or "").strip(),
                    note=(row.get("note") or "").strip(),
                    ru_rx=_compile(ru_rx),
                    kk_rx=_compile(kk_rx),
                    forbidden_rx=_compile(_B + "(?:" + forb + ")") if forb else None,
                    forbidden_literals=[x for x in forb.split("|") if x] if forb else [],
                    uz=uz,
                    uz_rx=_compile("|".join(f"(?:{_stem_regex(v)})" for v in uz)) if uz else None,
                )
            )
    return terms
