"""Language heuristics: tokenization, script/language detection, Kazakh morphology helpers."""

from __future__ import annotations

import re
import unicodedata

WORD_RE = re.compile(r"[^\W\d_]+(?:['ʻʼ’‘`][^\W\d_]+)*", re.UNICODE)

KK_SPECIFIC = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
# Russian look-alike typed instead of each Kazakh letter.
KK_TO_RU = {
    "ә": "а", "ғ": "г", "қ": "к", "ң": "н", "ө": "о", "ұ": "у", "ү": "у", "һ": "х", "і": "и",
    "Ә": "А", "Ғ": "Г", "Қ": "К", "Ң": "Н", "Ө": "О", "Ұ": "У", "Ү": "У", "Һ": "Х", "І": "И",
}
UZ_CYR_SPECIFIC = set("ўҳЎҲ")
# Latin letters that look like Cyrillic ones (and non-Kazakh look-alikes of Kazakh letters).
HOMOGLYPHS = {
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у", "i": "і", "k": "к",
    "A": "А", "B": "В", "E": "Е", "K": "К", "M": "М", "H": "Н", "O": "О", "P": "Р", "C": "С",
    "T": "Т", "X": "Х", "Y": "У", "I": "І",
    "ə": "ә", "Ə": "Ә", "ɵ": "ө", "Ɵ": "Ө", "h": "һ",
    "ӊ": "ң", "Ӊ": "Ң", "ӈ": "ң", "Ӈ": "Ң", "ҕ": "ғ", "Ҕ": "Ғ", "ҝ": "қ", "Ҝ": "Қ",
}
NON_KK_LOOKALIKES = set("əƏɵƟӊӉӈӇҕҔҝҜ")

RU_STOP = set(
    "и в во не на с со что как для по от из к ко у о об за это вы вас вам ваш ваша ваше ваши "
    "ты тебя тебе твой мы нас если или но уже еще ещё бы же только чтобы при без до после через "
    "нет все всё был была было были будет можно нужно нельзя этот эта эти который которая которые "
    "свой своё свою сейчас также тоже пожалуйста".split()
)
KK_STOP = set(
    "және мен бен пен үшін бұл осы сіз сіздің сізге сізде біз біздің ол оның жоқ бар емес да де "
    "деп қалай немесе әлі енді тағы барлық бір екі кейін дейін арқылы туралы бойынша ғана ма ме "
    "болады болды керек мүмкін қажет сәтті қате".split()
)
UZ_STOP = set(
    "va uchun bilan bu siz sizning biz yoki emas yoʻq yo'q bor qilish mumkin kerak hamma bir lekin "
    "ham endi qanday muvaffaqiyatli xato ва учун билан бу сиз сизнинг биз ёки эмас йўқ қилиш "
    "мумкин керак ҳамма лекин ҳам энди қандай".split()
)
EN_STOP = set(
    "the a an and or to of for in on with your you is are not be this that it from at by please "
    "can will has have was".split()
)
RU_MORPH = re.compile(
    r"(ться|тся|ешь|ете|ите|ого|ему|ыми|ими|ение|ения|ание|ания|ость|ости|ются|ется|ует|ая|ое|ый|ий|ть)$"
)
UZ_LATIN_MARK = re.compile(r"[oOgG][ʻ'‘’`]")


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def is_cyrillic(ch: str) -> bool:
    return "CYRILLIC" in unicodedata.name(ch, "")


def is_latin(ch: str) -> bool:
    return "LATIN" in unicodedata.name(ch, "")


def letters(text: str) -> list[str]:
    return [c for c in text if c.isalpha()]


def script_of(text: str) -> str:
    ls = letters(text)
    if not ls:
        return "none"
    cyr = sum(is_cyrillic(c) for c in ls)
    lat = sum(is_latin(c) for c in ls)
    if cyr >= 0.8 * len(ls):
        return "cyrl"
    if lat >= 0.8 * len(ls):
        return "latn"
    return "mixed"


def lang_scores(text: str) -> dict[str, float]:
    toks = [w.lower() for w in words(text)]
    s = {"kk": 0.0, "ru": 0.0, "uz": 0.0, "en": 0.0}
    for t in toks:
        latin = all(is_latin(c) or c in "ʻʼ’‘'`" for c in t)
        if t in KK_STOP:
            s["kk"] += 2
        if any(c in KK_SPECIFIC for c in t):
            s["kk"] += 1.5
        if t in RU_STOP and not latin:
            s["ru"] += 2
        elif not latin and len(t) >= 4 and RU_MORPH.search(t) and not any(c in KK_SPECIFIC for c in t):
            s["ru"] += 1
        if t in UZ_STOP:
            s["uz"] += 2
        if any(c in UZ_CYR_SPECIFIC for c in t) or (latin and UZ_LATIN_MARK.search(t)):
            s["uz"] += 3
        if latin and t in EN_STOP:
            s["en"] += 2
    # Uzbek Latin text without markers still looks like "latin non-English" words.
    if script_of(text) == "latn" and s["en"] == 0 and s["uz"] == 0 and len(toks) >= 3:
        if any(re.search(r"(sh|ch|q|lar|ni|ga|da)$", t) for t in toks):
            s["uz"] += 1
    return s


def detect_lang(text: str) -> tuple[str | None, dict[str, float]]:
    s = lang_scores(text)
    best = max(s, key=s.get)
    if s[best] <= 0:
        return None, s
    return best, s


def has_kk_letters(text: str) -> bool:
    return any(c in KK_SPECIFIC for c in text)


def kk_skeleton(word: str) -> str:
    """Map Kazakh-specific letters to their Russian look-alikes (lowercased)."""
    return "".join(KK_TO_RU.get(c, c) for c in word.lower())


def fix_homoglyphs(word: str) -> str:
    """Replace Latin/foreign look-alikes inside a Cyrillic word."""
    return "".join(HOMOGLYPHS.get(c, c) for c in word)


def mixed_script_word(word: str) -> bool:
    has_cyr = any(is_cyrillic(c) for c in word)
    has_lat = any(is_latin(c) for c in word if c not in NON_KK_LOOKALIKES)
    has_foreign = any(c in NON_KK_LOOKALIKES for c in word)
    return (has_cyr and has_lat) or (has_foreign and (has_cyr or len(word) > 1))


# --- Kazakh morphology (enough for suffix-harmony analysis and rewording) -----------------

BACK_VOWELS = set("аоұыяёю")
FRONT_VOWELS = set("әөүіеэи")
VOICELESS = set("кқпстфхцчшщ")


def is_back(word: str) -> bool:
    for c in reversed(word.lower()):
        if c in BACK_VOWELS:
            return True
        if c in FRONT_VOWELS:
            return False
    return True


def ends_with_vowel(word: str) -> bool:
    return word[-1:].lower() in BACK_VOWELS | FRONT_VOWELS | {"у"}


# Case suffixes as they would be (wrongly) hard-coded after a placeholder.
CASE_SUFFIXES = {
    "dat": ["ға", "ге", "қа", "ке", "на", "не", "а", "е"],
    "gen": ["ның", "нің", "дың", "дің", "тың", "тің"],
    "acc": ["ны", "ні", "ды", "ді", "ты", "ті"],
    "loc": ["нда", "нде", "да", "де", "та", "те"],
    "abl": ["нан", "нен", "дан", "ден", "тан", "тен"],
    "ins": ["мен", "бен", "пен"],
    "plr": ["лар", "лер", "дар", "дер", "тар", "тер"],
}
SUFFIX_TO_CASE = {suf: case for case, sufs in CASE_SUFFIXES.items() for suf in sufs}
CASE_NAMES = {
    "dat": "барыс септік", "gen": "ілік септік", "acc": "табыс септік", "loc": "жатыс септік",
    "abl": "шығыс септік", "ins": "көмектес септік", "plr": "көптік жалғау",
}
_SUFFIX_ALT = "|".join(sorted(SUFFIX_TO_CASE, key=len, reverse=True))
PLACEHOLDER_SUFFIX_RE = re.compile(r"\{(\w+)\}([-‐'’ʼ]?)(" + _SUFFIX_ALT + r")(?![^\W\d_])", re.UNICODE)


def possessive3(noun: str) -> str:
    if noun in ALREADY_POSSESSIVE:
        return noun
    if ends_with_vowel(noun):
        return noun + ("сы" if is_back(noun) else "сі")
    return noun + ("ы" if is_back(noun) else "і")


def poss_case(noun: str, case: str) -> str | None:
    """noun + 3rd person possessive + case: ойыншы -> ойыншысына (dat)."""
    p = possessive3(noun)
    back = is_back(p)
    return {
        "dat": p + ("на" if back else "не"),
        "gen": p + ("ның" if back else "нің"),
        "acc": p + "н",
        "loc": p + ("нда" if back else "нде"),
        "abl": p + ("нан" if back else "нен"),
        "ins": p + "мен",
    }.get(case)


ALREADY_POSSESSIVE = {"отбасы"}

# Placeholder name pattern -> anchor noun used to carry the suffix.
ANCHOR_NOUNS = [
    (re.compile(r"(admin|moder)", re.I), "әкімші"),
    (re.compile(r"(nick|name|player|user|sender|receiver|recipient|target|owner|leader|killer|victim)", re.I), "ойыншы"),
    (re.compile(r"famil", re.I), "отбасы"),
    (re.compile(r"(faction|org|gang|clan)", re.I), "фракция"),
    (re.compile(r"(amount|price|sum|money|cost|balance|reward)", re.I), "сома"),
    (re.compile(r"(car|vehicle|auto)", re.I), "көлік"),
    (re.compile(r"(house|home)", re.I), "үй"),
    (re.compile(r"business", re.I), "бизнес"),
    (re.compile(r"(item|thing|product)", re.I), "зат"),
    (re.compile(r"city", re.I), "қала"),
]
NUMERIC_PLACEHOLDER = re.compile(r"(^n$|count|num|qty|quantity|level|lvl|days?|hours?|minutes?|seconds?)$", re.I)


def anchor_for(placeholder: str) -> str | None:
    for rx, noun in ANCHOR_NOUNS:
        if rx.search(placeholder):
            return noun
    return None
