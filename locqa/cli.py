from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

from . import __version__
from .apply import apply_decisions, load_decisions, validate, check_output_path, save_validated_result
from .arb import ArbFile, base_lang, dump_arb, load_arb
from .checks import ISSUE_TYPES, SEVERITY_ORDER, Context, Finding, Options, key_tokens, run_checks
from .evaluate import evaluate, format_eval
from .glossary import load_glossary
from .report import ISSUE_LABELS, read_findings, write_html, write_json
from .seed import seed_errors
from .translit import transliterate_message


def _out(msg: str = ""):
    print(msg, file=sys.stderr)


def protect_outputs(outputs, inputs):
    """Validate every destination before any output is opened."""
    used = []
    for output in outputs:
        if output:
            check_output_path(output, [*inputs, *used])
            used.append(output)


def cmd_check(a) -> int:
    html_path = a.html or str(Path(a.out).with_suffix(".html"))
    cand_path = Path(a.out).with_name(Path(a.out).stem + ".candidates.json")
    protect_outputs([a.out, html_path, cand_path], [a.source, a.target, a.glossary, *(a.ref or [])])
    for value in (a.min_confidence, a.fail_confidence):
        if not 0 <= value <= 1:
            raise ValueError("confidence должен быть числом от 0 до 1")
    if a.sample_size is not None and a.sample_size < 1:
        raise ValueError("--sample-size должен быть положительным")
    src, tgt = load_arb(a.source), load_arb(a.target)
    if a.locale:
        tgt.locale = a.locale
    glossary = load_glossary(a.glossary)
    unknown = set(a.disable or []) - set(ISSUE_TYPES)
    if unknown:
        sys.exit(f"Неизвестные типы: {', '.join(sorted(unknown))}")
    refs = [load_arb(r) for r in (a.ref or [])]
    ctx = Context(src, tgt, glossary, Options(length_ratio=a.length_ratio, min_confidence=0.0, disabled=set(a.disable or [])), refs)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    raw_findings = run_checks(ctx)
    findings = raw_findings
    # Low-confidence findings are the main source of noise. They are kept out
    # of the main report and saved separately for optional review.
    candidates = [f for f in findings if f.confidence < a.min_confidence]
    findings = [f for f in findings if f.confidence >= a.min_confidence]
    meta = {
        "tool": f"locqa {__version__}",
        "source": Path(a.source).name,
        "target": Path(a.target).name,
        "target_lang": ctx.lang,
        "keys_checked": len(ctx.keys),
        "glossary_terms": len(glossary),
        "min_confidence": a.min_confidence,
        "low_confidence_candidates": len(candidates),
    }
    if ctx.glossary and ctx.lang not in ("kk", "uz"):
        _out(f"Внимание: в глоссарии нет колонки для языка «{ctx.lang}», проверки глоссария пропущены.")
    if a.llm:
        from .llm import llm_review

        try:
            usage = llm_review(ctx, findings, model=a.llm_model, max_items=a.llm_max, retries=a.llm_retries)
        except Exception as exc:
            usage = {"items": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": None, "error": type(exc).__name__}
            _out("LLM не завершён; сохраняем локальные результаты. " + type(exc).__name__)

        meta["llm"] = usage
        _out(
            f"LLM: статус={usage.get('status', 'failed')}; "
            f"отправлено={usage.get('items', 0)}, "
            f"обработано={usage.get('processed', 0)}, "
            f"предложений={usage.get('suggestions_added', 0)}, "
            f"отклонено={usage.get('suggestions_rejected', 0)}, "
            f"без ответа={usage.get('missing', 0)}"
        )

        _out(
            f"Токены: вход={usage.get('input_tokens', 0)}, "
            f"выход={usage.get('output_tokens', 0)}, "
            f"размышления={usage.get('thinking_tokens', 0)}"
        )

        _out("Стоимость не рассчитана; проверяйте расход в кабинете провайдера.")

        for problem in usage.get("errors", []):
            _out(
                f"  LLM: {problem['type']}; "
                f"ключи: {', '.join(problem['keys']) or '—'}"
            )
    # LLM mutates the initially eligible objects. Preserve that selection
    # scope, then apply the final threshold to all results after enrichment.
    candidates = [f for f in raw_findings if f.confidence < a.min_confidence]
    findings = [f for f in raw_findings if f.confidence >= a.min_confidence]
    meta["low_confidence_candidates"] = len(candidates)
    if candidates:
        write_json(candidates, str(cand_path), None)
    else:
        cand_path.unlink(missing_ok=True)
    all_findings = findings
    if a.sample_size is not None:
        if a.sample_size < 1:
            raise ValueError("--sample-size должен быть положительным")
        meta["population_size"] = len(findings)
        meta["sample_seed"] = a.sample_seed
        findings = random.Random(a.sample_seed).sample(findings, min(a.sample_size, len(findings)))
        meta["sample_size"] = len(findings)
    write_json(findings, a.out, meta if a.with_meta else None)
    write_html(findings, html_path, meta)
    by = Counter(f.issue_type for f in findings)
    _out(f"{meta['target']}: {len(ctx.keys)} ключей, {len(findings)} находок → {a.out}, {html_path}")
    if candidates:
        _out(f"  + {len(candidates)} находок с уверенностью < {a.min_confidence} вынесены в {cand_path.name}")
    for t in ISSUE_TYPES:
        if by.get(t):
            _out(f"  {t:30} {by[t]:>5}  {ISSUE_LABELS[t]}")
    if src.duplicates or tgt.duplicates:
        _out(f"Внимание: дубли ключей — {sorted(set(src.duplicates + tgt.duplicates))}")
    if a.fail_on != "never":
        limit = SEVERITY_ORDER[a.fail_on]
        bad = [f for f in all_findings if SEVERITY_ORDER[f.severity] <= limit and f.confidence >= a.fail_confidence]
        if bad:
            _out(f"FAIL: {len(bad)} находок уровня {a.fail_on} и выше")
            return 1
    return 0


def cmd_apply(a) -> int:
    decisions_paths = a.decisions or []
    if isinstance(decisions_paths, str):
        decisions_paths = [decisions_paths]
    protected = [a.source, a.target, *decisions_paths, a.report]
    try:
        check_output_path(a.out, protected)
        src, tgt = load_arb(a.source), load_arb(a.target)
        decisions = load_decisions(decisions_paths) if decisions_paths else []
        if a.auto_safe and not a.report:
            raise ValueError("--auto-safe требует --report")
        auto = read_findings(a.report) if a.auto_safe else None
        data, stats = apply_decisions(src, tgt, decisions, auto)
        problems = stats.pop("problems")
        for problem in problems:
            _out("  ! " + problem)
        _out(json.dumps(stats, ensure_ascii=False))
        if problems:
            _out("Результат не сохранён: есть отклонённые или конфликтующие решения. Согласуйте их и повторите команду.")
            return 1
        errors = save_validated_result(data, src, a.out, protected)
        if errors:
            _out("Результат не сохранён: локальная проверка ARB обнаружила ошибки:")
            for error in errors[:50]:
                _out("  - " + error)
            _out("Существующий выходной файл не изменён.")
            return 1
    except (ValueError, OSError) as exc:
        _out(f"Результат не сохранён: {exc}")
        return 1
    _out(f"OK: {a.out}. Локальная проверка пройдена; flutter gen-l10n запускается отдельно.")
    return 0


def cmd_validate(a) -> int:
    arb = load_arb(a.file)
    errors = validate(arb, load_arb(a.template) if a.template else None)
    for e in errors:
        print(e)
    _out("OK" if not errors else f"{len(errors)} ошибок")
    return 1 if errors else 0


def cmd_translit(a) -> int:
    protect_outputs([a.out, a.report], [a.source, a.target])
    src, tgt = load_arb(a.source), load_arb(a.target)
    ctx = Context(src, tgt, [], Options())
    out: dict = {}
    flags = []
    for k, v in tgt.data.items():
        if k.startswith("@@locale"):
            out[k] = "kk_Latn" if a.locale is None else a.locale
            continue
        if k.startswith("@") or not isinstance(v, str):
            out[k] = v
            continue
        lat = transliterate_message(v)
        out[k] = lat
        s = src.messages.get(k, "")
        if s and ctx.is_short_ui(k) and len(s) <= 25 and len(lat) / max(len(s), 1) >= a.max_ratio and len(lat) - len(s) >= 5:
            flags.append({"key": k, "issue_type": "length_overflow", "severity": "medium", "source": s, "target": lat,
                          "evidence": f"латиница {len(lat)} символов (кириллица {len(v)}), исходник {len(s)}; ключ похож на элемент интерфейса",
                          "suggestion": None, "confidence": 0.7, "reviewed_by_human": False})
        elif len(lat) > len(v) * 1.1 and len(lat) - len(v) >= 3:
            flags.append({"key": k, "issue_type": "length_overflow", "severity": "low", "source": s, "target": lat,
                          "evidence": f"после транслитерации строка выросла с {len(v)} до {len(lat)} символов (ц/ч/щ/ю/я)",
                          "suggestion": None, "confidence": 0.5, "reviewed_by_human": False})
    dump_arb(out, a.out)
    if a.report:
        Path(a.report).write_text(json.dumps(flags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _out(f"{a.out}: {len(tgt.messages)} строк, {len(flags)} предупреждений о длине")
    return 0


def cmd_seed(a) -> int:
    protect_outputs([a.out, a.answer], [a.source, a.target, a.other, a.glossary])
    if a.n < 1:
        raise ValueError("--n должен быть положительным")
    src, tgt = load_arb(a.source), load_arb(a.target)
    other = load_arb(a.other) if a.other else None
    data, answer = seed_errors(src, tgt, n=a.n, rnd_seed=a.seed, other=other, glossary=load_glossary(a.glossary))
    dump_arb(data, a.out)
    Path(a.answer).write_text(json.dumps(answer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _out(f"Подложено {len(answer)} ошибок: " + ", ".join(f"{t}={c}" for t, c in Counter(x['issue_type'] for x in answer).items()))
    return 0


def cmd_eval(a) -> int:
    findings = read_findings(a.report)
    if not a.answer and not a.decisions:
        raise ValueError("eval требует --answer или --decisions")
    protect_outputs([a.json], [a.report, a.answer, a.decisions])
    answer = json.loads(Path(a.answer).read_text(encoding="utf-8-sig")) if a.answer else None
    if answer is not None and (not isinstance(answer, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("key"), str)
        or not isinstance(row.get("issue_type"), str) for row in answer
    )):
        raise ValueError("ключ ответов должен быть массивом объектов с key и issue_type")
    decisions = load_decisions(a.decisions) if a.decisions else None
    res = evaluate(findings, answer, decisions)
    print(format_eval(res))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="locqa", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="проверить перевод и построить report.json + HTML")
    c.add_argument("--source", required=True)
    c.add_argument("--target", required=True)
    c.add_argument("--glossary")
    c.add_argument("--ref", nargs="*", metavar="ARB", help="переводы на другие языки (en, uz) — для распознавания заимствований")
    c.add_argument("--out", default="report.json")
    c.add_argument("--html", help="путь HTML-отчёта (по умолчанию рядом с --out)")
    c.add_argument("--locale", help="переопределить язык целевого файла (kk, uz, en …)")
    c.add_argument("--sample-size", type=int, help="случайная выборка находок для ручной оценки precision")
    c.add_argument("--sample-seed", type=int, default=42)
    c.add_argument("--with-meta", action="store_true", help="обернуть находки в {summary, findings}")
    c.add_argument("--min-confidence", type=float, default=0.5,
                   help="находки с меньшей уверенностью идут в <out>.candidates.json, а не в отчёт; 0 — всё в отчёт (по умолчанию 0.5)")
    c.add_argument("--length-ratio", type=float, help="порог длины (по умолчанию калибруется по файлу)")
    c.add_argument("--disable", nargs="*", metavar="TYPE", help="отключить типы проверок")
    c.add_argument("--fail-on", choices=["high", "medium", "low", "never"], default="never", help="код возврата 1 для CI")
    c.add_argument("--fail-confidence", type=float, default=0.8)
    c.add_argument("--llm",action="store_true",help="проверка через Gemini; нужен GEMINI_API_KEY",)
    c.add_argument("--llm-model", default="gemini-3.1-flash-lite")
    c.add_argument("--llm-max", type=int, default=300)
    c.add_argument("--llm-retries", type=int, choices=range(6), default=2, help="повторы временных ошибок API, 0–5")
    c.set_defaults(fn=cmd_check)

    ap = sub.add_parser("apply", help="собрать исправленный ARB из решений проверяющих")
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--decisions",nargs="+",help="один или несколько JSON-файлов решений",)
    ap.add_argument("--report", help="report.json (нужен для --auto-safe)")
    ap.add_argument("--auto-safe", action="store_true", help="применить детерминированные правки, помеченные reviewed=false")
    ap.add_argument("--out", required=True)
    ap.set_defaults(fn=cmd_apply)

    v = sub.add_parser("validate", help="локально проверить ARB и ICU; flutter gen-l10n запускается отдельно")
    v.add_argument("file")
    v.add_argument("--template")
    v.set_defaults(fn=cmd_validate)

    t = sub.add_parser("translit", help="казахский в латиницу (алфавит 2021) с проверкой длины")
    t.add_argument("--source", required=True)
    t.add_argument("--target", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--report")
    t.add_argument("--locale")
    t.add_argument("--max-ratio", type=float, default=1.6)
    t.set_defaults(fn=cmd_translit)

    s = sub.add_parser("seed", help="подложить синтетические ошибки для замера recall")
    s.add_argument("--source", required=True)
    s.add_argument("--target", required=True)
    s.add_argument("--other", help="ARB другого языка для wrong_language (например intl_uz.arb)")
    s.add_argument("--glossary")
    s.add_argument("--out", required=True)
    s.add_argument("--answer", required=True)
    s.add_argument("--n", type=int, default=100)
    s.add_argument("--seed", type=int, default=42)
    s.set_defaults(fn=cmd_seed)

    e = sub.add_parser("eval", help="recall/precision по ключу ответов")
    e.add_argument("--report", required=True)
    e.add_argument("--answer", help="ключ известных ошибок для recall; не нужен при --decisions")
    e.add_argument("--decisions")
    e.add_argument("--json")
    e.set_defaults(fn=cmd_eval)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except json.JSONDecodeError as exc:
        _out(f"Ошибка: файл не является корректным JSON/ARB (строка {exc.lineno}, столбец {exc.colno}): {exc.msg}")
        return 2
    except FileNotFoundError as exc:
        _out(f"Ошибка: файл не найден: {exc.filename}")
        return 2
    except (UnicodeDecodeError, ValueError, OSError) as exc:
        _out(f"Ошибка: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
