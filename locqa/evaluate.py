"""Recall against an answer key and precision from reviewer decisions."""

from __future__ import annotations

from collections import Counter, defaultdict


def evaluate(findings: list[dict], answer: list[dict] | None, decisions: list[dict] | None = None) -> dict:
    answer_available = bool(answer)
    answer = answer or []
    found_typed = {(f["key"], f["issue_type"]) for f in findings}
    found_keys = {f["key"] for f in findings}
    per_type: dict[str, Counter] = defaultdict(Counter)
    missed = []
    for a in answer:
        c = per_type[a["issue_type"]]
        c["total"] += 1
        if (a["key"], a["issue_type"]) in found_typed:
            c["typed"] += 1
        elif a["key"] in found_keys:
            c["key_only"] += 1
            missed.append({**a, "found_as": sorted(f["issue_type"] for f in findings if f["key"] == a["key"])})
        else:
            missed.append({**a, "found_as": []})
    total = sum(c["total"] for c in per_type.values())
    typed = sum(c["typed"] for c in per_type.values())
    keyed = typed + sum(c["key_only"] for c in per_type.values())
    answer_keys = {(a["key"], a["issue_type"]) for a in answer}
    answer_key_set = {a["key"] for a in answer}
    res = {
        "answer_available": answer_available,
        "recall_typed": round(typed / total, 3) if total else None,
        "recall_key": round(keyed / total, 3) if total else None,
        "per_type": {t: dict(c) for t, c in sorted(per_type.items())},
        "missed": missed,
        "findings_total": len(findings),
        # Lower bound: findings on non-seeded keys may still be real errors of the original file.
        "precision_vs_answer_lower_bound": round(
            sum((f["key"], f["issue_type"]) in answer_keys for f in findings) / len(findings), 3
        ) if findings and answer_available else None,
        "findings_outside_answer": sum(f["key"] not in answer_key_set for f in findings),
    }
    if decisions is not None:
        # Report IDs distinguish multiple pieces of evidence on one key/type.
        by_id = defaultdict(list)
        by_pair = defaultdict(list)
        for index, f in enumerate(findings):
            if f.get("id"):
                by_id[f["id"]].append(index)
            by_pair[(f["key"], f["issue_type"])].append(index)
        unique, conflicts = {}, set()
        counts = Counter()
        for d in decisions:
            pair = (d.get("key"), d.get("issue_type"))
            candidates = by_id.get(d.get("id"), [])
            matches = lambda i: (
                (findings[i]["key"], findings[i]["issue_type"]) == pair
                and d.get("original_source") == findings[i].get("source")
                and d.get("original_target") == findings[i].get("target")
            )
            if candidates:
                if len(candidates) != 1:
                    counts["review_ambiguous"] += 1
                    continue
                if not matches(candidates[0]):
                    counts["review_stale"] += 1
                    continue
            else:
                candidates = [i for i in by_pair.get(pair, []) if matches(i)]
                if not candidates:
                    counts["review_stale" if pair in by_pair else "review_unmatched"] += 1
                    continue
                if len(candidates) != 1:
                    counts["review_ambiguous"] += 1
                    continue
            index = candidates[0]
            if d.get("decision") not in ("accept", "edit", "reject", "code"):
                counts["review_pending"] += 1
                continue
            action = "reject" if d["decision"] == "reject" else "fix"
            previous = unique.get(index)
            if previous:
                old_action = "reject" if previous["decision"] == "reject" else "fix"
                if action != old_action:
                    conflicts.add(index)
                else:
                    counts["review_duplicates"] += 1
            unique[index] = d
        judged = [(i, d) for i, d in unique.items() if i not in conflicts]
        res.update({key: counts[key] for key in ("review_ambiguous", "review_stale", "review_unmatched", "review_pending", "review_duplicates")})
        res["review_conflicts"] = len(conflicts)
        res["review_decisions_total"] = len(decisions)
        res["review_coverage"] = round(len(judged) / len(findings), 4) if findings else None
        by_type = defaultdict(Counter)
        for index, d in judged:
            group = by_type[findings[index]["issue_type"]]
            group["reviewed"] += 1
            group["confirmed"] += d["decision"] != "reject"
        res["review_by_type"] = {t: {**c, "precision": round(c["confirmed"] / c["reviewed"], 3)} for t, c in sorted(by_type.items())}
        if judged:
            ok = sum(d["decision"] != "reject" for _, d in judged)
            res["precision_reviewed"] = round(ok / len(judged), 3)
            res["reviewed"] = len(judged)
    return res


def format_eval(res: dict) -> str:
    lines = [f"Recall (ключ+тип): {res['recall_typed']}   Recall (только ключ): {res['recall_key']}"] if res.get("answer_available") else ["Ключ ответов не задан; recall и precision относительно ключа не рассчитываются."]
    lines.append(f"{'тип':32} {'найдено':>8} {'всего':>6} {'recall':>7}")
    for t, c in res["per_type"].items():
        tot = c.get("total", 0)
        lines.append(f"{t:32} {c.get('typed', 0):>8} {tot:>6} {c.get('typed', 0) / tot if tot else 0:>7.2f}")
    lines.append(f"Находок всего: {res['findings_total']}, вне ключа ответов: {res['findings_outside_answer']}")
    if res.get("precision_vs_answer_lower_bound") is not None:
        lines.append(f"Precision vs ключ ответов (нижняя граница): {res['precision_vs_answer_lower_bound']}")
    if "precision_reviewed" in res:
        lines.append(f"Precision по ручной проверке: {res['precision_reviewed']} ({res['reviewed']} находок)")
    if "review_decisions_total" in res:
        lines.append(f"Покрытие ручной проверкой: {res.get('reviewed', 0)}/{res['findings_total']}; "
                     f"устаревших: {res['review_stale']}, неизвестных: {res['review_unmatched']}, "
                     f"неоднозначных: {res['review_ambiguous']}, конфликтов: {res['review_conflicts']}, "
                     f"отложенных: {res['review_pending']}")
        if not res.get("reviewed"):
            lines.append("Нет подходящих завершённых решений для оценки precision.")
    if res["missed"]:
        lines.append("Пропущено:")
        for m in res["missed"]:
            extra = f" (найдено как {', '.join(m['found_as'])})" if m["found_as"] else ""
            lines.append(f"  - {m['key']} [{m['issue_type']}] {m.get('how', '')}{extra}")
    return "\n".join(lines)
