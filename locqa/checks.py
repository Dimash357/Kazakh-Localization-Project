from __future__ import annotations

import difflib
import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from . import icu
from .arb import ArbFile, base_lang
from .glossary import Term
from .textutil import (
    KK_SPECIFIC,
    KK_STOP,
    KK_TO_RU,
    NUMERIC_PLACEHOLDER,
    PLACEHOLDER_SUFFIX_RE,
    RU_MORPH,
    SUFFIX_TO_CASE,
    CASE_NAMES,
    anchor_for,
    detect_lang,
    fix_homoglyphs,
    has_kk_letters,
    is_back,
    is_cyrillic,
    kk_skeleton,
    mixed_script_word,
    poss_case,
    script_of,
    words,
)
from .lexicon import KK_SEED_WORDS

ISSUE_TYPES = [
    "untranslated",
    "same_as_source",
    "placeholder_mismatch",
    "plural_mismatch",
    "glossary_violation",
    "length_overflow",
    "machine_translation_suspect",
    "inconsistent_term",
    "suffix_harmony",
    "orthography",
    "wrong_language",
]
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Finding:
    key: str
    issue_type: str
    severity: str
    source: str
    target: str | None
    evidence: str
    suggestion: str | None = None
    confidence: float = 0.5
    reviewed_by_human: bool = False
    id: str = field(default="")

    def __post_init__(self):
        self.confidence = round(max(0.0, min(1.0, self.confidence)), 2)
        if not self.id:
            self.id = hashlib.sha256(json.dumps([self.key, self.issue_type, self.source, self.target, self.evidence], ensure_ascii=False).encode()).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Options:
    length_ratio: float | None = None
    min_confidence: float = 0.0
    disabled: set[str] = field(default_factory=set)


_SHORT_UI_TOKENS = {
    "btn", "button", "tab", "title", "header", "heading", "label", "menu", "action", "cta", "ok",
    "cancel", "confirm", "close", "back", "next", "save", "apply", "caption", "chip", "badge",
    "toggle", "nav", "tooltip", "hint", "placeholder",
}
_SHORT_UI_DESC = re.compile(r"кнопк|button|вкладк|\btab\b|заголов|title|header|меню|menu|label|надпис", re.I)
_RU_STRICT = set(
    "и в во на с со что для по от из к у об за это вы ваш ваша ваши если или но уже чтобы при без "
    "после через нет пожалуйста который которая".split()
)
_POSTPOSITIONS = {"үшін", "туралы", "арқылы", "бойынша", "кейін", "дейін", "бері", "сияқты", "қарай", "жөнінде", "қарамастан"}
_CALQUES = {"болып табылады": "калька с «является»", "болып табылмайды": "калька с «не является»"}
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_BRANDS = {"grand", "mobile", "coins", "vip", "ok", "id", "gps", "discord", "telegram", "google", "apple", "ios", "android", "youtube", "tiktok", "instagram"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[.!?:…]+$", "", s.strip())).lower()


def key_tokens(key: str) -> set[str]:
    k = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower()
    return set(t for t in re.split(r"[_\-.\s]+", k) if t)


class Context:
    def __init__(self, src: ArbFile, tgt: ArbFile, glossary: list[Term], options: Options | None = None, refs: list[ArbFile] | None = None):
        self.refs = refs or []
        self.src = src
        self.tgt = tgt
        self.glossary = glossary
        self.opt = options or Options()
        self.lang = base_lang(tgt.locale) or "kk"
        self.src_lang = base_lang(src.locale) or "ru"
        self.smsg = src.messages
        self.tmsg = tgt.messages
        self.keys = [k for k in self.smsg]
        self._parsed: dict[tuple[str, str], object] = {}
        self.tplain = {k: icu.plain_text(v) for k, v in self.tmsg.items()}
        self.splain = {k: icu.plain_text(v) for k, v in self.smsg.items()}
        self.translated = [k for k in self.keys if self.tmsg.get(k, "").strip() and self.tmsg[k].strip() != self.smsg[k].strip()]
        self._build_corpus_stats()

    def parsed(self, which: str, key: str):
        ck = (which, key)
        if ck not in self._parsed:
            text = (self.smsg if which == "src" else self.tmsg).get(key, "")
            try:
                self._parsed[ck] = icu.parse(text)
            except icu.IcuError as e:
                self._parsed[ck] = e
        return self._parsed[ck]

    def _build_corpus_stats(self):
        self.vocab: Counter = Counter()
        self.context_words: Counter = Counter()
        self.context_prefixes: Counter = Counter()
        for k in self.translated:
            toks = [w.lower() for w in words(self.tplain[k])]
            self.vocab.update(toks)
            if self.lang == "kk":
                is_target = has_kk_letters(self.tplain[k]) or any(t in KK_STOP or t in KK_SEED_WORDS for t in toks)
            else:
                lang, _ = detect_lang(self.tplain[k])
                is_target = lang == self.lang
            if is_target:
                self.context_words.update(set(toks))
                self.context_prefixes.update({t[:n] for t in toks if len(t) >= 4 for n in range(4, len(t) + 1)})
        self.tm: dict[str, Counter] = defaultdict(Counter)
        for k in self.translated:
            self.tm[_norm(self.smsg[k])][self.tmsg[k].strip()] += 1
        ratios = [
            len(self.tmsg[k]) / len(self.smsg[k])
            for k in self.translated
            if len(self.smsg[k]) >= 15
        ]
        self.length_baseline = statistics.median(ratios) if len(ratios) >= 10 else 1.15
        scripts = Counter(script_of(self.tplain[k]) for k in self.translated)
        self.target_script = scripts.most_common(1)[0][0] if scripts else "none"
        self.glossary_target_words = {
            w.lower() for t in self.glossary for v in t.target_terms(self.lang) for w in words(v)
        }

    def tm_suggestion(self, key: str) -> str | None:
        c = self.tm.get(_norm(self.smsg.get(key, "")))
        if not c:
            return None
        cur = (self.tmsg.get(key) or "").strip()
        for text, _ in c.most_common():
            if text != cur:
                return text
        return None

    def is_short_ui(self, key: str) -> bool:
        return bool(key_tokens(key) & _SHORT_UI_TOKENS) or bool(_SHORT_UI_DESC.search(self.src.description(key)))


def F(ctx: Context, key: str, issue: str, severity: str, evidence: str, conf: float, suggestion=None) -> Finding:
    return Finding(
        key=key,
        issue_type=issue,
        severity=severity,
        source=ctx.smsg.get(key, ""),
        target=ctx.tmsg.get(key),
        evidence=evidence,
        suggestion=suggestion,
        confidence=conf,
    )


# ---------------------------------------------------------------------------------------------
## TODO ПРОВЕРКИ
# ---------------------------------------------------------------------------------------------


def check_untranslated(ctx: Context):
    for k in ctx.keys:
        if k not in ctx.tmsg:
            yield F(ctx, k, "untranslated", "high", "Ключ есть в исходнике, но отсутствует в целевом файле", 0.99, ctx.tm_suggestion(k))
        elif not ctx.tmsg[k].strip() and ctx.smsg[k].strip():
            yield F(ctx, k, "untranslated", "high", "Перевод пустой, исходник непустой", 0.98, ctx.tm_suggestion(k))


def _is_shared_word(ctx: Context, w: str) -> bool:
    w = w.lower()
    if w in ctx.glossary_target_words or w in _BRANDS or ctx.context_words.get(w, 0) >= 1:
        return True
    return len(w) >= 4 and ctx.context_prefixes.get(w, 0) >= 1


_RU_LAT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", ["a","b","v","g","d","e","e","zh","z","i","y","k","l","m","n","o","p","r","s","t","u","f","h","ts","ch","sh","sch","","y","","e","yu","ya"]))


def _latinize(w: str) -> str:
    return "".join(_RU_LAT.get(c, c) for c in w.lower())


def _lat_norm(w: str) -> str:
    w = w.lower().replace("x", "ks").replace("ph", "f").replace("w", "v").replace("q", "k")
    return re.sub(r"c(?=[aou]|$)", "k", w).replace("y", "i").replace("j", "y")


def _international(ctx: Context, key: str, word: str) -> bool:
    lat = _lat_norm(_latinize(word))
    for ref in ctx.refs:
        for rw in words(ref.messages.get(key, "")):
            rw = _lat_norm(_latinize(rw) if any(is_cyrillic(c) for c in rw) else rw)
            if difflib.SequenceMatcher(None, lat, rw).ratio() >= 0.7:
                return True
    return False


_NATIVE_RU_SUFFIX = re.compile(r"(?:ка|ние|ость|тель|ство|ник|чик|щик)$")


def check_same_as_source(ctx: Context):
    for k in ctx.keys:
        t = ctx.tmsg.get(k)
        s = ctx.smsg[k]
        if not t or t.strip() != s.strip():
            continue
        plain = ctx.splain[k]
        if sum(is_cyrillic(c) for c in plain) < 2:
            continue
        ws = words(plain)
        cyr_words = [w for w in ws if any(is_cyrillic(c) for c in w)]
        not_shared = [w for w in cyr_words if not _is_shared_word(ctx, w)]
        if not not_shared:
            continue
        ru_markers = [w for w in cyr_words if w.lower() in _RU_STRICT or (len(w) >= 4 and RU_MORPH.search(w.lower()))]
        if len(cyr_words) >= 2:
            sev, conf = "high", 0.95 if ru_markers else 0.85
            ev = f"Строка из {len(cyr_words)} слов идентична русской"
        elif _international(ctx, k, cyr_words[0]):
            continue
        else:
            w0 = cyr_words[0].lower()
            # Native Russian derivation (Поддержка, Управление, Помощник) is not
            # an international loanword that Kazakh may legitimately share.
            native_ru = len(w0) >= 6 and bool(_NATIVE_RU_SUFFIX.search(w0))
            if ru_markers or ctx.refs:
                sev, conf = "medium", 0.75
            elif native_ru:
                sev, conf = "medium", 0.55
            else:
                sev, conf = "low", 0.45
            ev = f"Слово «{cyr_words[0]}» идентично русскому и не встречается в других строках перевода"
        if ru_markers:
            ev += f"; русские признаки: {', '.join(ru_markers[:4])}"
        yield F(ctx, k, "same_as_source", sev, ev, conf, ctx.tm_suggestion(k))


def check_placeholders(ctx: Context):
    for k in ctx.keys:
        t = ctx.tmsg.get(k)
        if not t:
            continue
        sp, tp = ctx.parsed("src", k), ctx.parsed("tgt", k)
        if isinstance(sp, icu.IcuError):
            continue  # broken source is not a translation issue
        src_has_plural = any(a.type in ("plural", "selectordinal") for a in icu.walk_args(sp))
        if isinstance(tp, icu.IcuError):
            issue = "plural_mismatch" if src_has_plural or "plural" in t else "placeholder_mismatch"
            yield F(ctx, k, issue, "high", f"ICU-синтаксис сломан: {tp}. Файл не скомпилируется в flutter gen-l10n", 0.97)
            continue
        snames, tnames = icu.placeholder_names(sp), icu.placeholder_names(tp)
        missing, extra = sorted(snames - tnames), sorted(tnames - snames)
        if missing or extra:
            parts = []
            if missing:
                parts.append("нет " + ", ".join(f"{{{n}}}" for n in missing))
            if extra:
                parts.append("лишние " + ", ".join(f"{{{n}}}" for n in extra))
            if any(any(is_cyrillic(c) for c in n) for n in extra):
                parts.append("имя плейсхолдера переведено — его нельзя переводить")
            sugg = None
            if len(missing) == 1 and len(extra) == 1:
                sugg = re.sub(r"\{\s*" + re.escape(extra[0]) + r"(?=\s*[,}])", lambda m: "{" + missing[0], t)
            if not extra and missing and not any(a.type for a in icu.walk_args(sp)) and not any(a.type for a in icu.walk_args(tp)):
                candidate = t
                safe = True
                for name in missing:
                    rx = re.compile(r"(?<![\w{}])" + re.escape(name) + r"(?![\w{}])")
                    matches = list(rx.finditer(candidate))
                    if len(matches) != 1:
                        safe = False
                        break
                    candidate = rx.sub(lambda m: "{" + name + "}", candidate)
                if safe:
                    sugg = candidate
            if sugg:
                try:
                    nodes = icu.parse(sugg)
                    if icu.placeholder_names(nodes) != snames or icu.semantic_errors(nodes):
                        sugg = None
                except icu.IcuError:
                    sugg = None
            yield F(ctx, k, "placeholder_mismatch", "high", "; ".join(parts), 0.95, sugg)
        yield from _plural_checks(ctx, k, sp, tp)


def _plural_checks(ctx: Context, k: str, sp, tp):
    s_args = {a.name: a for a in icu.walk_args(sp) if a.type in icu.COMPLEX_TYPES}
    t_args = {a.name: a for a in icu.walk_args(tp) if a.type in icu.COMPLEX_TYPES}
    problems = [(error, "high") for error in icu.compatibility_errors(ctx.smsg[k], ctx.tmsg[k])
                if error != "placeholder_mismatch"]
    if not s_args and not t_args:
        if problems:
            yield F(ctx, k, "placeholder_mismatch", "high", "; ".join(p[0] for p in problems), 0.97)
        return
    for name, sa in s_args.items():
        ta = t_args.get(name)
        if ta is None:
            problems.append((f"в исходнике {{{name}, {sa.type}}}, в переводе форм нет — перевод не согласуется с числом", "high"))
            continue
        if ta.type != sa.type:
            problems.append((f"тип {{{name}}} изменён: {sa.type} → {ta.type}", "high"))
    for name, ta in t_args.items():
        sels = set(ta.options)
        if "other" not in sels:
            problems.append((f"в {{{name}, {ta.type}}} нет обязательной формы other", "high"))
        if ta.type in ("plural", "selectordinal"):
            bad = [s for s in sels if not s.startswith("=") and s not in icu.ALL_PLURAL_KEYWORDS]
            if bad:
                problems.append((f"неизвестные формы plural: {', '.join(bad)}", "high"))
            allowed = icu.PLURAL_CATEGORIES.get(ctx.lang)
            if allowed:
                odd = sorted(s for s in sels if s in icu.ALL_PLURAL_KEYWORDS and s not in allowed)
                if odd:
                    problems.append(
                        (f"формы {', '.join(odd)} не используются в языке «{ctx.lang}» (CLDR: {', '.join(sorted(allowed))}) — скопированы из исходника?", "low")
                    )
        empty = [s for s, body in ta.options.items() if not "".join(icu.text_segments(body)).strip() and not list(icu.walk_args(body))]
        if empty:
            problems.append((f"пустые формы: {', '.join(empty)}", "medium"))
        sa = s_args.get(name)
        if sa and ta.type == "select":
            missing = set(sa.options) - sels
            if missing:
                problems.append((f"в select нет вариантов: {', '.join(sorted(missing))}", "medium"))
    if problems:
        sev = min((p[1] for p in problems), key=lambda s: SEVERITY_ORDER[s])
        conf = 0.95 if sev == "high" else 0.6
        yield F(ctx, k, "plural_mismatch", sev, "; ".join(p[0] for p in problems), conf)


def _skip_semantic(ctx: Context, k: str) -> bool:
    t = ctx.tmsg.get(k)
    return not t or t.strip() == ctx.smsg[k].strip()


def check_glossary(ctx: Context):
    if not ctx.glossary:
        return
    for k in ctx.keys:
        if _skip_semantic(ctx, k):
            continue
        s, t = ctx.splain[k], ctx.tplain[k]
        for term in ctx.glossary:
            if not term.ru_rx.search(s):
                continue
            trx = term.target_rx(ctx.lang)
            if trx is None:
                continue
            preferred = term.target_terms(ctx.lang)[0]
            if ctx.lang != "uz" and term.forbidden_rx is not None:
                m = term.forbidden_rx.search(t)
                if m:
                    raw = ctx.tmsg[k]
                    i = raw.find(m.group(0))
                    fixed = raw[:i] + _match_case(m.group(0), preferred) + raw[i + len(m.group(0)) :] if i >= 0 else None
                    yield F(
                        ctx, k, "glossary_violation", "high",
                        f"«{term.ru}» переведено как «{m.group(0)}», по глоссарию — «{preferred}». {term.note} "
                        "Предложение — автозамена основы, окончание проверить.".strip(),
                        0.9, fixed,
                    )
                    break
            if not trx.search(t):
                f = F(
                    ctx, k, "glossary_violation", "medium",
                    f"В исходнике термин «{term.ru}», в переводе нет «{' / '.join(term.target_terms(ctx.lang))}». {term.note}".strip(),
                    0.6,
                )
                f._missing_rx = trx
                yield f
                break


def check_length(ctx: Context):
    thr = ctx.opt.length_ratio or max(1.5, ctx.length_baseline * 1.35)
    for k in ctx.keys:
        t = ctx.tmsg.get(k)
        s = ctx.smsg[k]
        if not t or not s.strip() or t.strip() == s.strip():
            continue
        sl, tl = len(s), len(t)
        ratio = tl / max(sl, 1)
        ui = ctx.is_short_ui(k)
        if ui and sl <= 25 and ratio >= thr and tl - sl >= 5:
            sev = "high" if ratio >= 2.0 else "medium"
            conf = min(0.95, 0.65 + (ratio - thr) * 0.4)
            why = "имя ключа/описание указывает на кнопку, вкладку или заголовок"
        elif sl <= 12 and ratio >= max(2.2, thr * 1.5) and tl - sl >= 8:
            sev, conf, why = "medium", 0.55, "короткая строка, вероятно элемент интерфейса"
        else:
            continue
        sugg = None
        alt = ctx.tm.get(_norm(s))
        if alt:
            fits = [x for x in alt if len(x) / max(sl, 1) < thr]
            sugg = min(fits, key=len) if fits else None
        yield F(
            ctx, k, "length_overflow", sev,
            f"{tl} символов против {sl} в исходнике (×{ratio:.1f}; порог ×{thr:.2f}, медиана по файлу ×{ctx.length_baseline:.2f}); {why}",
            conf, sugg,
        )


def check_wrong_language(ctx: Context):
    for k in ctx.keys:
        if _skip_semantic(ctx, k):
            continue
        t = ctx.tplain[k]
        if len(words(t)) == 0:
            continue
        lang, sc = detect_lang(t)
        src_script, t_script = script_of(ctx.splain[k]), script_of(t)
        found = None
        if ctx.lang == "kk":
            if sc["uz"] >= 3 and sc["uz"] > sc["kk"]:
                found = ("uz", 0.88)
            elif sc["kk"] == 0 and (sc["ru"] >= 3 or (sc["ru"] >= 2 and len(words(t)) >= 2)):
                found = ("ru", 0.85 if sc["ru"] >= 3 else 0.7)
            elif t_script == "latn" and src_script == "cyrl" and sc["en"] >= 2 and sc["en"] >= sc["uz"]:
                found = ("en", 0.8)
            elif t_script == "latn" and src_script == "cyrl" and not set(w.lower() for w in words(t)) <= _BRANDS and not t.strip().isupper():
                found = ("латиница", 0.6 if len(words(t)) >= 2 else 0.5)
        elif ctx.lang == "uz":
            if t_script == "cyrl" and has_kk_letters(t):
                found = ("kk", 0.9)
            elif t_script == "cyrl" and ctx.target_script == "latn":
                guess = "kk" if sc["kk"] > max(sc["ru"], sc["uz"]) else "ru" if sc["ru"] > sc["uz"] else "uz (кириллица)"
                found = (guess, 0.8)
            elif sc["ru"] >= 3 and sc["uz"] == 0:
                found = ("ru", 0.85)
            elif t_script == "latn" and sc["en"] >= 3 and sc["uz"] == 0:
                found = ("en", 0.75)
        else:
            if lang and lang != ctx.lang and sc[lang] >= 3 and sc.get(ctx.lang, 0) == 0:
                found = (lang, 0.75)
        if found:
            other, conf = found
            yield F(
                ctx, k, "wrong_language", "high",
                f"Текст похож на язык «{other}», а не «{ctx.lang}» (оценки: " + ", ".join(f"{l}={v:g}" for l, v in sc.items() if v) + ")",
                conf, ctx.tm_suggestion(k),
            )


def check_mt_suspect(ctx: Context):
    if ctx.lang != "kk":
        return
    for k in ctx.keys:
        if _skip_semantic(ctx, k):
            continue
        t = ctx.tplain[k]
        toks = words(t)
        low = [w.lower() for w in toks]
        if not (has_kk_letters(t) or any(w in KK_STOP for w in low)):
            continue
        reasons, conf = [], 0.0
        ru_func = [w for w in low if w in _RU_STRICT]
        if ru_func:
            reasons.append(f"русские служебные слова в казахском тексте: {', '.join(sorted(set(ru_func)))}")
            conf = max(conf, 0.8)
        ru_words = [
            w for w in toks
            if len(w) >= 5 and not any(c in KK_SPECIFIC for c in w) and RU_MORPH.search(w.lower())
            and ctx.context_words.get(w.lower(), 0) < 3 and w.lower() not in ctx.glossary_target_words
            and w.lower() not in KK_SEED_WORDS
        ]
        if ru_words:
            reasons.append(f"слова с русскими окончаниями: {', '.join(ru_words[:4])}")
            conf = max(conf, 0.6)
        for sent in _SENT_SPLIT.split(t):
            sw = words(sent)
            if len(sw) >= 2 and sw[0].lower() in _POSTPOSITIONS:
                reasons.append(f"послелог «{sw[0]}» в начале фразы — порядок слов русского предлога («Для …», «О …»)")
                conf = max(conf, 0.75)
        for phrase, why in _CALQUES.items():
            if phrase in t.lower():
                reasons.append(f"«{phrase}» — {why}")
                conf = max(conf, 0.6)
        if reasons:
            sev = "high" if conf >= 0.8 else "medium"
            yield F(ctx, k, "machine_translation_suspect", sev, "; ".join(reasons), conf)


def check_inconsistent(ctx: Context):
    flagged: set[str] = set()
    groups: dict[str, list[str]] = defaultdict(list)
    for k in ctx.translated:
        s = ctx.smsg[k]
        if k.lower() in {"lang", "locale", "languagecode", "language_code", "currencysymbol"}:
            continue
        if 1 <= len(words(s)) <= 4:
            groups[_norm(s)].append(k)
    for src_norm, ks in groups.items():
        if len(ks) < 2:
            continue
        # Multiple explicitly permitted standalone renderings are not errors
        # merely because they occur in different screens.
        permitted = next((term for term in ctx.glossary
                          if _norm(term.ru) == src_norm
                          and "не смешивать" not in term.note.lower()
                          and all(_norm(ctx.tmsg[k]) in {_norm(v) for v in term.target_terms(ctx.lang)} for k in ks)), None)
        if permitted:
            continue
        variants = Counter(_norm(ctx.tmsg[k]) for k in ks)
        if len(variants) < 2:
            continue
        (top, top_n), (_, second_n) = variants.most_common(2)
        if top_n == second_n:
            shown = " / ".join(f"«{v}» ×{n}" for v, n in variants.most_common())
            for k in ks:
                flagged.add(k)
                yield F(ctx, k, "inconsistent_term", "low",
                        f"«{ctx.smsg[k]}» переводится по-разному без явного большинства: {shown}; сравнить контекст; различие само по себе не доказывает ошибку", 0.4)
            continue
        majority_text = next(ctx.tmsg[k] for k in ks if _norm(ctx.tmsg[k]) == top)
        share = top_n / len(ks)
        for k in ks:
            if _norm(ctx.tmsg[k]) != top:
                flagged.add(k)
                other = _norm(ctx.tmsg[k])
                # Confidence tiers: a clear majority is stronger evidence than a
                # 2-vs-1 split; forms of one stem (Жабу/Жабуға) are usually grammar.
                if len(top) >= 4 and other[:4] == top[:4]:
                    conf = 0.3
                elif top_n >= 3 and share >= 0.75:
                    conf = 0.65
                elif top_n >= 3:
                    conf = 0.5
                else:
                    conf = 0.4
                yield F(
                    ctx, k, "inconsistent_term", "medium",
                    f"«{ctx.smsg[k]}» в {top_n} из {len(ks)} ключей переведено как «{majority_text}», здесь — «{ctx.tmsg[k]}». Частотность не подтверждает правильность; проверить оба варианта и контекст",
                    conf, None,
                )
    for term in ctx.glossary:
        variants = term.target_terms(ctx.lang)
        if "не смешивать" not in term.note.lower():
            continue
        if len(variants) < 2:
            continue
        use: dict[str, list[str]] = defaultdict(list)
        for k in ctx.translated:
            if not term.ru_rx.search(ctx.splain[k]):
                continue
            low = ctx.tplain[k].lower()
            for v in variants:
                if v.lower()[: max(3, len(v) - 1)] in low:
                    use[v].append(k)
                    break
        if len(use) < 2:
            continue
        major = max(use, key=lambda v: len(use[v]))
        for v, ks in use.items():
            if v == major or len(ks) >= len(use[major]):
                continue
            for k in ks:
                if k in flagged:
                    continue
                flagged.add(k)
                yield F(
                    ctx, k, "inconsistent_term", "low",
                    f"«{term.ru}» здесь «{v}», а в {len(use[major])} других ключах — «{major}»", 0.5,
                )
    # Сопоставление по коротким основам отключено:
    # оно смешивает слова с разным смыслом.


def _stem(w: str, n: int = 5) -> str:
    w = w.lower()
    return w[:n] if len(w) > n else w


def _mined_term_inconsistency(ctx: Context, flagged: set[str]):
    df: Counter = Counter()
    co: dict[str, Counter] = defaultdict(Counter)
    tdf: Counter = Counter()
    per_key: dict[str, tuple[set, set]] = {}
    for k in ctx.translated:
        rs = {_stem(w) for w in words(ctx.splain[k]) if len(w) >= 4 and w.lower() not in _RU_STRICT}
        ts = {_stem(w) for w in words(ctx.tplain[k]) if len(w) >= 3}
        per_key[k] = (rs, ts)
        df.update(rs)
        tdf.update(ts)
        for r in rs:
            co[r].update(ts)
    for r, n in df.items():
        if n < 6:
            continue
        best, c = co[r].most_common(1)[0] if co[r] else (None, 0)
        if not best or c / n < 0.85 or c / tdf[best] < 0.3:
            continue
        misses = [k for k, (rs, ts) in per_key.items() if r in rs and best not in ts]
        if not misses or len(misses) > max(2, n * 0.15):
            continue
        for k in misses:
            if k in flagged or len(words(ctx.splain[k])) > 8:
                continue
            flagged.add(k)
            yield F(
                ctx, k, "inconsistent_term", "low",
                f"Русская основа «{r}…» в {c} из {n} строк переводится основой «{best}…», здесь её нет",
                0.4,
            )


def check_suffix_harmony(ctx: Context):
    if ctx.lang != "kk":
        return
    for k in ctx.keys:
        t = ctx.tmsg.get(k)
        if not t or t.strip() == ctx.smsg[k].strip():
            continue
        matches = list(PLACEHOLDER_SUFFIX_RE.finditer(t))
        if not matches:
            continue
        fixed, notes, numeric_only, can_fix = t, [], True, True
        for m in matches:
            ph, suf = m.group(1), m.group(3)
            case = SUFFIX_TO_CASE[suf]
            is_num = bool(NUMERIC_PLACEHOLDER.search(ph))
            numeric_only &= is_num
            if is_num:
                notes.append(f"«{m.group(0)}»: для числа аффикс зависит от последней цифры (1-ге, 3-ке, 6-ға, 10-ға) — выбирать в коде")
                can_fix = False
                continue
            anchor = anchor_for(ph)
            form = poss_case(anchor, case) if anchor else None
            notes.append(
                f"«{m.group(0)}»: аффикс {CASE_NAMES[case]} «-{suf}» жёстко прибит к плейсхолдеру; значение подставляется в игре, гармония гласных не гарантирована"
            )
            if form:
                fixed = fixed.replace(m.group(0), "{" + ph + "} " + form, 1)
            else:
                can_fix = False
        sev = "medium" if numeric_only else "high"
        sugg = fixed if can_fix and fixed != t else None
        if sugg:
            notes.append("предложена переформулировка через опорное слово, аффикс переносится на него")
        elif not numeric_only:
            notes.append("нужна обработка в коде (выбор аффикса по последней букве значения) или ручная переформулировка")
        yield F(ctx, k, "suffix_harmony", sev, "; ".join(notes), 0.9 if not numeric_only else 0.75, sugg)


def _replace_word(text: str, old: str, new: str) -> str:
    return re.sub(r"(?<![^\W\d_])" + re.escape(old) + r"(?![^\W\d_])", new, text)


def _match_case(src: str, repl: str) -> str:
    if src.isupper() and len(src) > 1:
        return repl.upper()
    if src[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def check_orthography(ctx: Context):
    if ctx.lang == "kk":
        yield from _ortho_kk(ctx)
    elif ctx.lang == "uz":
        yield from _ortho_uz(ctx)


_PREFIX = 5
_RU_SUFFIX_I = re.compile(r"(?<=[^\W\d_]{2})(лери|дери|тери|нери|си|ни|ди|ти)$")


def _aligned(bad: str, good: str) -> bool:
    """`good` differs from `bad` only where `bad` has the Russian look-alike of a Kazakh letter."""
    return len(bad) == len(good) and bad != good and all(a == b or KK_TO_RU.get(b) == a for a, b in zip(bad, good))


_LOAN_MARK = re.compile(r"[вфцчщёю]|дж")
_CONS = set("бвгғджзйклмнңпрстфхһцчшщқ")
_BACK_ONLY = set("аоұы")
_FRONT_ONLY = set("әөүіе")


def _harmony_at(w: str, i: int) -> str | None:
    for j in list(range(i + 1, len(w))) + list(range(i - 1, -1, -1)):
        if w[j] in _BACK_ONLY:
            return "back"
        if w[j] in _FRONT_ONLY:
            return "front"
    return None


def _phonotactic_fix(w: str) -> str | None:
    return None


def phon_reason(bad: str, good: str) -> str:
    return "нарушена гармония: в казахском слове с гласными заднего ряда пишутся қ/ғ, между согласными — і/ұ/ү"


def _segments(text: str) -> list[str]:
    """Literal text pieces of a message; plural/select branches are separate,
    so a word repeated in two branches is not reported as a doubled word."""
    try:
        return icu.text_segments(icu.parse(text))
    except Exception:
        return [re.sub(r"\{[^{}]*\}", " | ", text)]


def _ortho_kk(ctx: Context):
    vocab = Counter(ctx.vocab)
    for w in KK_SEED_WORDS:
        vocab[w] += 3
    index: dict[str, list[str]] = defaultdict(list)
    for w in vocab:
        index[kk_skeleton(w)].append(w)
    pcount: Counter = Counter()
    for w, n in vocab.items():
        if len(w) >= _PREFIX:
            pcount[w[:_PREFIX]] += n
    pindex: dict[str, list[str]] = defaultdict(list)
    for p in pcount:
        pindex[kk_skeleton(p)].append(p)

    for k in ctx.keys:
        if _skip_semantic(ctx, k):
            continue
        t = ctx.tmsg[k]
        plain = ctx.tplain[k]
        fixed, reasons, conf, sev = t, [], 0.0, "low"
        for w in dict.fromkeys(words(plain)):
            if mixed_script_word(w):
                good = fix_homoglyphs(w)
                if good != w:
                    fixed = _replace_word(fixed, w, good)
                reasons.append(f"«{w}» содержит латинские/чужие буквы-двойники")
                conf, sev = max(conf, 0.95), "high"
                continue
            lw = w.lower()
            if len(lw) < 3 or vocab[lw] - (3 if lw in KK_SEED_WORDS else 0) > 2 or lw in KK_SEED_WORDS:
                continue
            best, basis_n = None, 0
            for cand in index.get(kk_skeleton(lw), []):
                if _aligned(lw, cand) and vocab[cand] >= max(3, 3 * vocab[lw]) and vocab[cand] > basis_n:
                    best, basis_n = cand, vocab[cand]
            if not best and len(lw) >= _PREFIX:
                p = lw[:_PREFIX]
                cands = [c for c in pindex.get(kk_skeleton(p), []) if _aligned(p, c) and pcount[c] >= max(3, 3 * pcount[p])]
                if cands:
                    c = max(cands, key=lambda x: pcount[x])
                    best, basis_n = c + lw[_PREFIX:], pcount[c]
            if not best and vocab[lw] <= 2:
                m = _RU_SUFFIX_I.search(lw)
                if m and not is_back(lw[: m.start()]):
                    best = lw[:-1] + "і"
            phon = None
            if (not best and vocab[lw] <= 2 and lw not in ctx.glossary_target_words
                    and pcount[lw[:_PREFIX]] < 3 and not _LOAN_MARK.search(lw)):
                best = phon = _phonotactic_fix(lw)
            # Частотность не доказывает ошибку.
            # Не предлагаем замену н → ң без словарного подтверждения.
            if best and any(
                    old == "н" and new == "ң"
                    for old, new in zip(lw, best)
            ):
                best = None
            if best:
                fixed = _replace_word(fixed, w, _match_case(w, best))
                swaps = [f"{a}→{b}" for a, b in zip(lw, best) if a != b]
                basis = (f"основа встречается {basis_n} раз" if basis_n
                         else phon_reason(lw, best) if phon else "казахский аффикс пишется через «і»")
                reasons.append(f"«{w}» → «{_match_case(w, best)}» ({', '.join(swaps)}; {basis})")
                conf, sev = max(conf, 0.85 if basis_n >= 5 else 0.65), "medium" if sev == "low" else sev
                continue
            typo = None
            if typo:
                fixed = _replace_word(fixed, w, _match_case(w, typo))
                reasons.append(f"«{w}» — вероятная опечатка, частое слово «{typo}»")
                conf, sev = max(conf, 0.6), "medium" if sev == "low" else sev
        rep = None
        for seg in _segments(t):
            rep = re.search(r"(?<![^\W\d_])([^\W\d_]{2,})\s+\1(?![^\W\d_])", seg, re.I)
            if rep:
                break
        if rep:
            fixed = fixed.replace(rep.group(0), rep.group(1), 1)
            reasons.append(f"повтор слова «{rep.group(1)}»")
            conf = max(conf, 0.8)
        if reasons:
            yield F(ctx, k, "orthography", sev, "; ".join(reasons), conf, fixed if fixed != t else None)


def _typo_candidate(w: str, vocab: Counter) -> str | None:
    if len(w) < 5 or vocab[w] > 1:
        return None
    cands = set()
    for i in range(len(w) - 1):
        cands.add(w[:i] + w[i + 1] + w[i] + w[i + 2 :])
        if w[i] == w[i + 1]:
            cands.add(w[:i] + w[i + 1 :])
    best = max((c for c in cands if c != w and vocab[c] >= 3), key=lambda c: vocab[c], default=None)
    return best


_UZ_APOS = re.compile(r"([oOgG])([ʻ'‘’`ʼ])")


def _ortho_uz(ctx: Context):
    usage: Counter = Counter()
    for k in ctx.translated:
        usage.update(m.group(2) for m in _UZ_APOS.finditer(ctx.tmsg[k]))
    norm = "ʻ"
    for k in ctx.keys:
        if _skip_semantic(ctx, k):
            continue
        t = ctx.tmsg[k]
        reasons, fixed, conf, sev = [], t, 0.0, "low"
        bad = {m.group(2) for m in _UZ_APOS.finditer(t)} - {norm}
        if bad:
            fixed = _UZ_APOS.sub(lambda m: m.group(1) + norm, fixed)
            reasons.append(f"апостроф в oʻ/gʻ набран как {', '.join(repr(b) for b in sorted(bad))}, норма — «ʻ» (U+02BB)")
            conf = 0.7
        if script_of(ctx.tplain[k]) == "latn":
            mixed = [w for w in words(ctx.tplain[k]) if any(is_cyrillic(c) for c in w)]
            if mixed:
                reasons.append(f"кириллица в латинском тексте: {', '.join(mixed[:3])}")
                conf, sev = 0.9, "high"
        if reasons:
            yield F(ctx, k, "orthography", sev, "; ".join(reasons), conf, fixed if fixed != t else None)


CHECKS = {
    "untranslated": check_untranslated,
    "same_as_source": check_same_as_source,
    "placeholder_mismatch": check_placeholders,
    "glossary_violation": check_glossary,
    "length_overflow": check_length,
    "wrong_language": check_wrong_language,
    "machine_translation_suspect": check_mt_suspect,
    "inconsistent_term": check_inconsistent,
    "suffix_harmony": check_suffix_harmony,
    "orthography": check_orthography,
}


def run_checks(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for name, fn in CHECKS.items():
        if name in ctx.opt.disabled:
            continue
        findings.extend(fn(ctx))
    findings = [f for f in findings if f.issue_type not in ctx.opt.disabled and f.confidence >= ctx.opt.min_confidence]
    wrong = {f.key for f in findings if f.issue_type in ("wrong_language", "same_as_source", "untranslated")}
    findings = [
        f for f in findings
        if not (f.key in wrong and f.issue_type in ("glossary_violation", "machine_translation_suspect", "orthography", "inconsistent_term"))
    ]
    ortho = {f.key: f.suggestion for f in findings if f.issue_type == "orthography" and f.suggestion}
    findings = [
        f for f in findings
        if not (getattr(f, "_missing_rx", None) and f.key in ortho and f._missing_rx.search(icu.plain_text(ortho[f.key])))
    ]
    order = {k: i for i, k in enumerate(ctx.keys)}
    findings.sort(key=lambda f: (order.get(f.key, 1 << 30), SEVERITY_ORDER[f.severity], f.issue_type))
    # Identical emissions collapse; distinct evidence keeps a distinct identity.
    unique = {}
    for f in findings:
        previous = unique.get(f.id)
        if previous and previous.to_dict() != f.to_dict():
            raise ValueError("Conflicting finding identity")
        unique[f.id] = f
    return list(unique.values())
