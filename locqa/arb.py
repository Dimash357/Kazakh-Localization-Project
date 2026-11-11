"""Reading and writing Flutter ARB files without losing key order or metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ArbFile:
    path: str
    locale: str | None
    data: dict  # full ordered JSON object, including @@ and @key entries
    duplicates: list[str] = field(default_factory=list)
    raw: dict | None = None

    @property
    def messages(self) -> dict[str, str]:
        return {k: v for k, v in self.data.items() if not k.startswith("@") and isinstance(v, str)}

    def meta(self, key: str) -> dict:
        m = self.data.get(f"@{key}")
        return m if isinstance(m, dict) else {}

    def description(self, key: str) -> str:
        return str(self.meta(key).get("description") or "")

    def keys(self) -> list[str]:
        return list(self.messages.keys())


_LOCALE_FROM_NAME = re.compile(r"_([a-z]{2,3}(?:_[A-Za-z]{2,4})?)\.arb$")


def guess_locale(path: str, data: dict) -> str | None:
    loc = data.get("@@locale")
    if isinstance(loc, str) and loc:
        return loc
    m = _LOCALE_FROM_NAME.search(Path(path).name)
    return m.group(1) if m else None


def base_lang(locale: str | None) -> str:
    return (locale or "").split("_")[0].split("-")[0].lower()


def load_arb(path: str | Path) -> ArbFile:
    path = str(path)
    dupes: list[str] = []

    class PairObject(dict):
        def __init__(self, pairs):
            super().__init__(pairs)
            self.pairs = pairs

    def hook(pairs):
        seen: dict = {}
        for k, v in pairs:
            if k in seen:
                dupes.append(k)
            seen[k] = v
        return PairObject(pairs)

    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f, object_pairs_hook=hook)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: ARB должен быть JSON-объектом")
    return ArbFile(path=path, locale=guess_locale(path, data), data=data, duplicates=dupes, raw=data)


def dump_arb(data: dict, path: str | Path) -> None:
    """Serialize retained pairs, preserving unmodified duplicate entries."""
    def encode(value, level=0):
        if isinstance(value, dict):
            pairs = getattr(value, "pairs", list(value.items()))
            pad = "  " * (level + 1)
            return "{\n" + ",\n".join(pad + json.dumps(k, ensure_ascii=False) + ": " + encode(v, level + 1) for k, v in pairs) + "\n" + "  " * level + "}"
        return json.dumps(value, ensure_ascii=False)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(encode(data) + "\n", encoding="utf-8")


class PreservedDict(dict):
    """Mapping view with the original serialization sequence."""
    def __init__(self, pairs):
        super().__init__(pairs)
        self.pairs = pairs


def preserve_pairs(original, updated, changed_keys):
    """Replace changed keys only; keep all other original occurrences."""
    pairs = []
    seen = set()
    for key, value in getattr(original, "pairs", original.items()):
        if key not in updated:
            pairs.append((key, value))
            seen.add(key)
            continue
        if key in changed_keys:
            if key in seen:
                continue
            value = updated[key]
        pairs.append((key, value))
        seen.add(key)
    pairs.extend((k, v) for k, v in updated.items() if k not in seen)
    return PreservedDict(pairs)


def mutable_arb_data(data):
    """Copy JSON into mutable plain containers; never choose conflicting pairs."""
    if isinstance(data, dict):
        result = {}
        for key, value in getattr(data, "pairs", data.items()):
            value = mutable_arb_data(value)
            if key != "@@comment" and key in result and result[key] != value:
                raise ValueError(f"конфликтующие дубли: {key}; сначала нормализуйте ARB")
            result[key] = value
        return result
    if isinstance(data, list):
        return [mutable_arb_data(value) for value in data]
    return data
