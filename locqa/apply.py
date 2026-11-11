from __future__ import annotations

import json
import os
import tempfile
import re
from pathlib import Path
from collections import defaultdict

from . import icu
from .arb import ArbFile, preserve_pairs, dump_arb, load_arb

REVIEW_FLAG = "x-reviewed_by_human"
_RESOURCE_NAME = re.compile(r"[a-z][A-Za-z0-9_]*\Z")
_DART_KEYWORDS = set("assert break case catch class const continue default do else enum extends false final finally for if in is new null rethrow return super switch this throw true try var void while with".split())



def validate(arb: ArbFile, template: ArbFile | None = None) -> list[str]:
    errors: list[str] = []
    if template is not None:
        errors.extend("шаблон: " + error for error in validate(template))
    pairs = getattr(arb.raw or arb.data, "pairs", list(arb.data.items()))
    values = defaultdict(list)
    for key, value in pairs:
        if key != "@@comment":
            values[key].append(value)
    duplicate_keys = {k for k, vs in values.items() if len(vs) > 1 and any(v != vs[0] for v in vs)}
    if duplicate_keys:
        errors.append(f"конфликтующие дубли ключей: {', '.join(sorted(duplicate_keys))}")
    tmsg = template.messages if template else {}
    for k, v in arb.data.items():
        if k.startswith("@@"):
            continue
        if k.startswith("@"):
            if not isinstance(v, dict):
                errors.append(f"{k}: метаданные должны быть объектом")
            elif "placeholders" in v and not isinstance(v["placeholders"], dict):
                errors.append(f"{k}: placeholders должны быть объектом")
            continue
        if not _RESOURCE_NAME.fullmatch(k) or k in _DART_KEYWORDS:
            errors.append(f"{k}: недопустимое имя ресурса Dart; ожидается имя с маленькой латинской буквы")
        if not isinstance(v, str):
            errors.append(f"{k}: значение должно быть строкой")
            continue
        try:
            nodes = icu.parse(v)
        except icu.IcuError as e:
            errors.append(f"{k}: {e}")
            continue
        errors.extend(f"{k}: {e}" for e in icu.semantic_errors(nodes))
        if template and k in tmsg:
            try:
                want = icu.placeholder_names(icu.parse(tmsg[k]))
            except icu.IcuError:
                continue  # Template error is already included above.
            errors.extend(f"{k}: {e}" for e in icu.compatibility_errors(tmsg[k], v))
            source_args = {a.name: a for a in icu.walk_args(icu.parse(tmsg[k]))}
            target_args = {a.name: a for a in icu.walk_args(nodes)}
            for name, arg in source_args.items():
                other = target_args.get(name)
                if other and arg.type in icu.COMPLEX_TYPES and other.type != arg.type:
                    errors.append(f"{k}: изменён тип ICU аргумента {name}")
            missing = want - icu.placeholder_names(nodes)
            if missing:
                errors.append(f"{k}: отсутствуют плейсхолдеры {sorted(missing)}")
            extra = icu.placeholder_names(nodes) - want
            if extra:
                errors.append(f"{k}: плейсхолдеры {sorted(extra)} не объявлены в шаблоне")
    return errors


def load_decisions(path: str | list[str]) -> list[dict]:
    paths = [path] if isinstance(path, str) else list(path)
    merged = []
    seen = set()
    allowed = {"accept", "edit", "reject", "pending", "code"}

    for filename in paths:
        with open(filename, encoding="utf-8-sig") as f:
            data = json.load(f)

        rows = data.get("decisions") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ValueError(f"{filename}: ожидается массив решений")

        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError(
                    f"{filename}: запись {index} должна быть объектом"
                )

            if not isinstance(row.get("key"), str) or not row["key"]:
                raise ValueError(f"{filename}: запись {index} без ключа")

            action = row.get("decision")
            if not isinstance(action, str) or action not in allowed:
                raise ValueError(
                    f"{filename}: неизвестный статус в записи {index}"
                )

            for field in ("issue_type", "original_source"):
                if not isinstance(row.get(field), str):
                    raise ValueError(
                        f"{filename}: запись {index}, неверное поле {field}"
                    )

            if "original_target" not in row or (
                row["original_target"] is not None
                and not isinstance(row["original_target"], str)
            ):
                raise ValueError(
                    f"{filename}: запись {index}, неверный original_target"
                )

            if action in {"accept", "edit"}:
                if not isinstance(row.get("final_text"), str):
                    raise ValueError(
                        f"{filename}: запись {index} без текста правки"
                    )
            elif row.get("final_text") is not None:
                raise ValueError(
                    f"{filename}: запись {index}, "
                    "статус без правки содержит текст"
                )

            if row.get("id") is not None and not isinstance(row["id"], str):
                raise ValueError(f"{filename}: запись {index}, неверный id")
            if row.get("comment") is not None and not isinstance(row["comment"], str):
                raise ValueError(f"{filename}: запись {index}, неверный комментарий")
            reviewer = row.get("reviewer")
            if reviewer is not None and not isinstance(reviewer, str):
                raise ValueError(
                    f"{filename}: запись {index}, неверный reviewer"
                )

            signature = json.dumps(
                row, ensure_ascii=False, sort_keys=True
            )
            if signature not in seen:
                seen.add(signature)
                merged.append(row)

    return merged


def apply_decisions(
    source: ArbFile,
    target: ArbFile,
    decisions: list[dict],
    auto_findings: list[dict] | None = None,
) -> tuple[dict, dict]:
    changes: dict[str, dict] = {}
    stats = defaultdict(int)
    problems: list[str] = []
    by_key: dict[str, list[dict]] = defaultdict(list)
    for d in decisions:
        key = d.get("key")
        if key not in source.messages:
            problems.append(f"{key}: неизвестный ключ, решение отклонено")
            continue
        if "original_target" not in d or d["original_target"] != target.messages.get(key) or d.get("original_source") != source.messages.get(key):
            problems.append(f"{key}: устаревшее решение или старый формат; экспортируйте из нового отчёта")
            continue
        by_key[key].append(d)

    raw_pairs = getattr(target.raw or target.data, "pairs", list(target.data.items()))
    for key, ds in by_key.items():
        values = [v for k, v in raw_pairs if k == key]
        if len(values) > 1 and any(v != values[0] for v in values):
            problems.append(f"{key}: конфликтующие дубли; сначала разрешите их в исходном ARB")
            continue
        by_issue = defaultdict(set)

        for d in ds:
            action = (
                "fix"
                if d["decision"] in {"accept", "edit"}
                else d["decision"]
            )
            by_issue[d.get("issue_type", "")].add(
                (action, d.get("final_text"))
            )

        if any(len(variants) > 1 for variants in by_issue.values()):
            problems.append(
                f"{key}: проверяющие расходятся по одной находке; "
                "согласуйте решение"
            )
            continue
        stats["decisions"] += len(ds)
        stats["rejected"] += sum(d["decision"] == "reject" for d in ds)
        code = [d for d in ds if d["decision"] == "code"]
        texts = [d for d in ds if d["decision"] in ("accept", "edit") and d.get("final_text") is not None]
        if code and not texts:
            changes[key] = {"text": None, "reviewed": True, "reviewer": code[-1].get("reviewer"), "issues": ["suffix_harmony"], "code": True}
            continue
        if not texts:
            continue
        final = texts[-1]["final_text"]
        if len({d["final_text"] for d in texts}) > 1:
            problems.append(f"{key}: конфликт правок; выберите один итоговый текст")
            continue
        changes[key] = {
            "text": final,
            "reviewed": True,
            "reviewer": texts[-1].get("reviewer"),
            "issues": sorted({d.get("issue_type", "") for d in ds if d["decision"] != "reject"}),
            "code": bool(code),
        }

    for f in auto_findings or []:
        # Deterministic, low-risk fixes only; marked as NOT reviewed.
        if f["key"] in by_key or f["key"] in changes or not f.get("suggestion"):
            continue
        if (f["issue_type"] == "orthography" and "двойники" in f["evidence"]) or f["issue_type"] == "placeholder_mismatch":
            changes[f["key"]] = {"text": f["suggestion"], "reviewed": False, "reviewer": None, "issues": [f["issue_type"]], "code": False}

    smsg = source.messages
    for key, ch in list(changes.items()):
        if ch["text"] is None:
            continue
        contract = icu.compatibility_errors(smsg.get(key, ""), ch["text"])
        if contract:
            problems.append(f"{key}: правка отклонена: {'; '.join(contract)}")
            del changes[key]
            continue
        try:
            nodes = icu.parse(ch["text"])
            semantic = icu.semantic_errors(nodes)
            if semantic:
                raise icu.IcuError("; ".join(semantic), 0)
            got = icu.placeholder_names(nodes)
            want = icu.placeholder_names(icu.parse(smsg.get(key, "")))
        except icu.IcuError as e:
            problems.append(f"{key}: правка отклонена, ICU не парсится: {e}")
            del changes[key]
            continue
        if got != want:
            problems.append(f"{key}: правка отклонена, плейсхолдеры {sorted(got)} ≠ {sorted(want)}")
            del changes[key]

    old = target.data
    out: dict = {}
    for k, v in old.items():
        if k.startswith("@@"):
            out[k] = v
    keys = list(smsg) + [k for k in target.messages if k not in smsg]
    for k in keys:
        ch = changes.get(k)
        if k not in old and not (ch and ch["text"] is not None):
            continue
        value = ch["text"] if ch and ch["text"] is not None else old.get(k)
        out[k] = value
        meta = dict(old.get(f"@{k}", {})) if isinstance(old.get(f"@{k}"), dict) else {}
        if ch:
            if ch["text"] is not None and value != old.get(k):
                meta["x-original"] = old.get(k)
                stats["changed"] += 1
                stats["changed_reviewed" if ch["reviewed"] else "changed_unreviewed"] += 1
            previous_meta = old.get(f"@{k}", {})
            if not isinstance(previous_meta, dict):
                previous_meta = {}

            if "x-original" in previous_meta:
                meta["x-original"] = previous_meta["x-original"]

            previous_history = meta.get("x-review-history", [])
            history = (
                list(previous_history)
                if isinstance(previous_history, list)
                else []
            )

            history.append({
                "before": old.get(k),
                "after": value,
                "reviewed_by_human": ch["reviewed"],
                "decisions": [
                    dict(d) for d in by_key.get(k, [])
                ],
            })

            meta["x-review-history"] = history
            meta[REVIEW_FLAG] = ch["reviewed"]
            if ch["reviewer"]:
                meta["x-reviewer"] = ch["reviewer"]
            if ch["issues"]:
                meta["x-issues"] = sorted(
                    set(meta.get("x-issues", [])) | set(ch["issues"])
                )
            if ch["code"]:
                meta["x-needs-code-suffix"] = True
                stats["needs_code"] += 1
        if meta:
            out[f"@{k}"] = meta
    stats_out = dict(stats)
    stats_out["problems"] = problems
    changed_keys = set(changes) | {"@" + k for k in changes}
    return preserve_pairs(target.raw or target.data, out, changed_keys), stats_out


def check_output_path(path, protected_paths):
    """Reject aliases of inputs, including existing symbolic and hard links."""
    destination = Path(path).resolve()
    for item in protected_paths:
        if not item:
            continue
        original = Path(item).resolve()
        if destination == original or (
            destination.exists() and original.exists()
            and os.path.samefile(destination, original)
        ):
            raise ValueError("--out совпадает с входным файлом; выберите отдельный путь")
    return destination


def save_validated_result(data, source, path, protected_paths=()):
    """Validate staged bytes before atomically replacing the destination.

    Returns validation errors without publishing an invalid result. Existing
    output survives validation, serialization and replacement failures.
    This runs local validation, not Flutter itself.
    """
    destination = check_output_path(path, protected_paths)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".locqa-", suffix=".arb", dir=destination.parent)
    os.close(fd)
    try:
        dump_arb(data, temporary)
        errors = validate(load_arb(temporary), source)
        if errors:
            return errors
        with open(temporary, "r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        # Repeat immediately before publication in case input aliases changed.
        check_output_path(path, protected_paths)
        os.replace(temporary, destination)
        return []
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
