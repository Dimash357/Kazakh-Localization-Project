"""Seed synthetic errors into a target ARB to measure recall per issue type.

The organisers keep the real answer key; this lets the team reproduce the evaluation
recipe on any ARB pair (and on the real files) and track recall while tuning checks.
"""

from __future__ import annotations

import random
import re

from . import icu
from .arb import ArbFile, mutable_arb_data
from .glossary import Term
from .textutil import KK_TO_RU, KK_SPECIFIC, words

SYNONYMS_KK = {
    "Жабу": "Жабық",
    "Сақтау": "Сақтап қою",
    "Растау": "Мақұлдау",
    "Жіберу": "Жолдау",
    "Бас тарту": "Болдырмау",
    "Алу": "Қабылдау",
}
VERBOSE_TAILS = [" үшін осында басыңыз", " батырмасын басыңыз", " әрекетін орындау"]
SEEDABLE = [
    "untranslated", "same_as_source", "placeholder_mismatch", "plural_mismatch", "glossary_violation",
    "length_overflow", "machine_translation_suspect", "inconsistent_term", "suffix_harmony",
    "orthography", "wrong_language",
]


def _ui_key(key: str) -> bool:
    return bool(re.search(r"(button|btn|tab|title|label|menu)", key, re.I))


def seed_errors(
    source: ArbFile,
    target: ArbFile,
    n: int = 100,
    rnd_seed: int = 42,
    other: ArbFile | None = None,
    glossary: list[Term] | None = None,
) -> tuple[dict, list[dict]]:
    rnd = random.Random(rnd_seed)
    data = mutable_arb_data(target.data)
    mutable_arb_data(source.data)  # Reject ambiguous originals too.
    smsg = source.messages
    used: set[str] = set()
    answer: list[dict] = []

    def tgt(k):
        return data.get(k)

    def pool(pred):
        ks = [k for k in smsg if k not in used and isinstance(tgt(k), str) and tgt(k).strip() and tgt(k) != smsg[k] and pred(k)]
        rnd.shuffle(ks)
        return ks

    def mark(k, typ, how):
        used.add(k)
        answer.append({"key": k, "issue_type": typ, "how": how})

    def s_untranslated(k):
        if rnd.random() < 0.5:
            del data[k]
            data.pop(f"@{k}", None)
            return "ключ удалён"
        data[k] = ""
        return "пустая строка"

    def s_same(k):
        data[k] = smsg[k]
        return "заменено русским оригиналом"

    def s_placeholder(k):
        names = sorted(icu.placeholder_names(icu.parse(smsg[k])))
        ph = rnd.choice(names)
        if rnd.random() < 0.5:
            data[k] = tgt(k).replace("{" + ph + "}", "", 1).replace("  ", " ").strip()
            return f"удалён {{{ph}}}"
        data[k] = tgt(k).replace("{" + ph + "}", "{" + ph + "_1}", 1)
        return f"переименован {{{ph}}}"

    def s_plural(k):
        data[k] = re.sub(r"\s*other\s*\{[^{}]*(\{[^{}]*\}[^{}]*)*\}", "", tgt(k), count=1)
        return "удалена форма other"

    def s_glossary(k):
        for term in glossary or []:
            bad = next((alt for alt in term.forbidden_literals if re.fullmatch(r"[^\W\d_]+(?: [^\W\d_]+)*", alt)), None)
            for v in term.kk:
                if bad and v in tgt(k):
                    data[k] = tgt(k).replace(v, bad, 1)
                    return f"«{v}» → «{bad}»"
        return None

    def s_length(k):
        data[k] = tgt(k) + rnd.choice(VERBOSE_TAILS)
        return "добавлен многословный хвост"

    def s_mt(k):
        t = tgt(k)
        if " және " in t:
            data[k] = t.replace(" және ", " и ", 1)
            return "«және» → «и»"
        ws = t.split(" ")
        if len(ws) >= 3:
            data[k] = "Үшін " + ws[0][:1].lower() + ws[0][1:] + " " + " ".join(ws[1:])
            return "послелог «үшін» вынесен в начало"
        return None

    groups: dict = {}
    for k in smsg:
        if isinstance(tgt(k), str):
            groups.setdefault((smsg[k].strip(), tgt(k).strip()), []).append(k)

    def s_inconsistent(k):
        orig = tgt(k).strip()
        alt = SYNONYMS_KK.get(orig)
        # Only meaningful when the same source is translated the same way in >= 2 other keys.
        if not alt or len([x for x in groups.get((smsg[k].strip(), orig), []) if x not in used]) < 3:
            return None
        data[k] = alt
        return f"синоним «{alt}» вместо «{orig}»"

    def s_suffix(k):
        m = re.search(r"\{(\w+)\} ", tgt(k))
        if not m:
            return None
        data[k] = tgt(k).replace(m.group(0), "{" + m.group(1) + "}-ға ", 1)
        return f"«{{{m.group(1)}}}-ға»"

    def s_ortho(k):
        t = tgt(k)
        cand = [w for w in words(icu.plain_text(t)) if any(c in KK_SPECIFIC for c in w)]
        if not cand:
            return None
        w = rnd.choice(cand)
        idx = [i for i, c in enumerate(w) if c in KK_SPECIFIC]
        i = rnd.choice(idx)
        bad = w[:i] + KK_TO_RU[w[i]] + w[i + 1 :]
        data[k] = t.replace(w, bad, 1)
        return f"«{w}» → «{bad}»"

    def s_wrong(k):
        if other and other.messages.get(k) and other.messages[k] != smsg[k]:
            data[k] = other.messages[k]
            return f"вставлен перевод из {other.locale}"
        return None

    plan = {
        "untranslated": (s_untranslated, lambda k: True),
        "same_as_source": (s_same, lambda k: len(words(smsg[k])) >= 2),
        "placeholder_mismatch": (s_placeholder, lambda k: "{" in smsg[k] and "plural" not in smsg[k]),
        "plural_mismatch": (s_plural, lambda k: "plural" in (tgt(k) or "")),
        "glossary_violation": (s_glossary, lambda k: True),
        "length_overflow": (s_length, lambda k: _ui_key(k) and len(smsg[k]) <= 20),
        "machine_translation_suspect": (s_mt, lambda k: len(words(tgt(k) or "")) >= 3),
        "inconsistent_term": (s_inconsistent, lambda k: (tgt(k) or "").strip() in SYNONYMS_KK),
        "suffix_harmony": (s_suffix, lambda k: bool(re.search(r"\{\w+\} ", tgt(k) or ""))),
        "orthography": (s_ortho, lambda k: any(c in KK_SPECIFIC for c in tgt(k) or "")),
        "wrong_language": (s_wrong, lambda k: other is not None),
    }
    per_type = max(1, n // len(plan))
    for typ in SEEDABLE:
        fn, pred = plan[typ]
        done = 0
        for k in pool(pred):
            if done >= per_type:
                break
            before = data.get(k)
            existed = k in data
            how = fn(k)
            if how and (data.get(k) != before or (k in data) != existed):
                mark(k, typ, how)
                done += 1
    return data, answer
