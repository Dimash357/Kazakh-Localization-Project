"""Minimal ICU MessageFormat parser compatible with what `flutter gen-l10n` accepts.

Supports simple arguments `{name}`, typed arguments `{date, date, short}`,
`plural` / `select` / `selectordinal` with nested messages and `#`.
Escaping with apostrophes is gen-l10n opt-in (`use-escaping`), so it is off by default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NAME_RE = re.compile(r"[^\s{},#=]+")
_SELECTOR_RE = re.compile(r"=?[^\s{}]+")

COMPLEX_TYPES = {"plural", "select", "selectordinal"}


class IcuError(ValueError):
    def __init__(self, message: str, pos: int):
        super().__init__(f"{message} (позиция {pos})")
        self.pos = pos


@dataclass
class Arg:
    name: str
    type: str | None = None  # None for simple `{name}`
    style: str | None = None
    options: dict[str, list] = field(default_factory=dict)  # selector -> nodes
    pos: int = 0
    offset: int | None = None


Node = "str | Arg"


class _Parser:
    def __init__(self, text: str, escaping: bool = False):
        self.s = text
        self.i = 0
        self.escaping = escaping

    def parse(self) -> list:
        nodes = self.message(in_plural=False, depth=0)
        if self.i < len(self.s):
            raise IcuError("лишняя закрывающая скобка '}'", self.i)
        return nodes

    def message(self, in_plural: bool, depth: int) -> list:
        nodes: list = []
        buf: list[str] = []
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "{":
                if buf:
                    nodes.append("".join(buf))
                    buf = []
                nodes.append(self.argument(depth))
                continue
            elif c == "}":
                if depth == 0:
                    raise IcuError("лишняя закрывающая скобка '}'", self.i)
                break
            elif c == "'" and self.escaping and self.i + 1 < len(self.s):
                end = self.s.find("'", self.i + 1)
                if end == self.i + 1:
                    buf.append("'")
                    self.i += 2
                    continue
                if end == -1:
                    raise IcuError("незакрытая кавычка", self.i)
                buf.append(self.s[self.i + 1 : end])
                self.i = end + 1
                continue
            else:
                buf.append(c)
            self.i += 1
        if buf:
            nodes.append("".join(buf))
        return nodes

    def ws(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def expect(self, ch: str):
        if self.i >= len(self.s) or self.s[self.i] != ch:
            got = self.s[self.i] if self.i < len(self.s) else "конец строки"
            raise IcuError(f"ожидалось '{ch}', найдено '{got}'", self.i)
        self.i += 1

    def word(self, what: str) -> str:
        m = _NAME_RE.match(self.s, self.i)
        if not m:
            raise IcuError(f"ожидалось {what}", self.i)
        self.i = m.end()
        return m.group(0)

    def argument(self, depth: int) -> Arg:
        if depth > 50:
            raise IcuError("слишком глубокая вложенность ICU", self.i)
        start = self.i
        self.expect("{")
        self.ws()
        name = self.word("имя плейсхолдера")
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "}":
            self.i += 1
            return Arg(name=name, pos=start)
        self.expect(",")
        self.ws()
        typ = self.word("тип аргумента")
        self.ws()
        arg = Arg(name=name, type=typ, pos=start)
        if self.i < len(self.s) and self.s[self.i] == "}":
            self.i += 1
            return arg
        self.expect(",")
        if typ in COMPLEX_TYPES:
            self.options(arg, depth)
        else:
            end = self.s.find("}", self.i)
            if end == -1:
                raise IcuError("незакрытый аргумент", start)
            arg.style = self.s[self.i : end].strip()
            if "{" in arg.style:
                raise IcuError("скобка внутри формата аргумента", self.i)
            self.i = end
        self.ws()
        if self.i >= len(self.s):
            raise IcuError(f"незакрытый аргумент {{{name}}}", start)
        self.expect("}")
        return arg

    def options(self, arg: Arg, depth: int):
        while True:
            self.ws()
            if self.i >= len(self.s) or self.s[self.i] == "}":
                break
            if self.s.startswith("offset:", self.i):
                self.i += len("offset:")
                self.ws()
                if arg.type == "select" or arg.offset is not None or arg.options:
                    raise IcuError("недопустимый offset", self.i)
                value = self.word("значение offset")
                if not re.fullmatch(r"\d+", value):
                    raise IcuError("offset должен быть неотрицательным целым", self.i)
                arg.offset = int(value)
                continue
            m = _SELECTOR_RE.match(self.s, self.i)
            if not m:
                raise IcuError("ожидался селектор формы", self.i)
            sel = m.group(0)
            self.i = m.end()
            self.ws()
            self.expect("{")
            body = self.message(in_plural=arg.type != "select", depth=depth + 1)
            self.expect("}")
            if sel in arg.options:
                raise IcuError(f"повторяющаяся форма '{sel}'", self.i)
            arg.options[sel] = body
        if not arg.options:
            raise IcuError(f"у {arg.type} нет ни одной формы", arg.pos)


def parse(text: str, escaping: bool = False) -> list:
    return _Parser(text, escaping).parse()


def walk_args(nodes: list):
    for n in nodes:
        if isinstance(n, Arg):
            yield n
            for body in n.options.values():
                yield from walk_args(body)


def placeholder_names(nodes: list) -> set[str]:
    return {a.name for a in walk_args(nodes)}


def text_segments(nodes: list) -> list[str]:
    """All literal text pieces (including inside plural/select forms)."""
    out: list[str] = []
    for n in nodes:
        if isinstance(n, str):
            out.append(n)
        else:
            for body in n.options.values():
                out.extend(text_segments(body))
    return out


def plain_text(text: str) -> str:
    """Human text with placeholders replaced by spaces; falls back to regex on parse errors."""
    try:
        return " ".join(text_segments(parse(text)))
    except IcuError:
        return re.sub(r"\{[^{}]*\}", " ", text)


# CLDR plural categories that a translation must provide (besides explicit =N forms).
PLURAL_CATEGORIES = {
    "ru": {"one", "few", "many", "other"},
    "uk": {"one", "few", "many", "other"},
    "kk": {"one", "other"},
    "uz": {"one", "other"},
    "en": {"one", "other"},
    "es": {"one", "many", "other"},
    "pt": {"one", "many", "other"},
    "tr": {"one", "other"},
}
ALL_PLURAL_KEYWORDS = {"zero", "one", "two", "few", "many", "other"}


def semantic_errors(nodes):
    errors = []
    for arg in walk_args(nodes):
        if arg.type in COMPLEX_TYPES:
            if "other" not in arg.options:
                errors.append(f"{arg.name}: нет обязательной формы other")
            if arg.type != "select":
                for selector in arg.options:
                    if selector not in ALL_PLURAL_KEYWORDS and not re.fullmatch(r"=\d+", selector):
                        errors.append(f"{arg.name}: неверный селектор {selector}")
        elif arg.type not in (None, "number", "date", "time"):
            errors.append(f"{arg.name}: неизвестный тип {arg.type}")
    by_name = {}
    for arg in walk_args(nodes):
        typ = arg.type or "simple"
        by_name.setdefault(arg.name, set()).add(typ)
    for name, types in by_name.items():
        # A plural variable may also appear as a simple placeholder in its body.
        meaningful = types - {"simple"}
        if len(meaningful) > 1:
            errors.append(f"{name}: конфликтующие типы аргумента")
    return errors


def compatibility_errors(source: str, target: str) -> list[str]:
    """Shared structural contract for human and model changes (escaping off)."""
    try:
        src, tgt = parse(source), parse(target)
    except IcuError as exc:
        return [str(exc)]
    errors = semantic_errors(src) + semantic_errors(tgt)
    if placeholder_names(src) != placeholder_names(tgt):
        errors.append("placeholder_mismatch")
    for arg in walk_args(src):
        candidates = [a for a in walk_args(tgt) if a.name == arg.name and a.type == arg.type]
        if arg.type is None:
            continue
        if not candidates:
            errors.append(f"{arg.name}: icu_type_changed")
            continue
        if arg.type in COMPLEX_TYPES:
            required = set(arg.options) if arg.type == "select" else {s for s in arg.options if s.startswith("=")}
            if not any(required <= set(a.options) and a.offset == arg.offset for a in candidates):
                errors.append(f"{arg.name}: потеря селекторов или изменение offset")
    return errors
