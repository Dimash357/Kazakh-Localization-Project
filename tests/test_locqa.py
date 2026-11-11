"""Run: python3 -m unittest discover -s tests -v"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from locqa import icu  # noqa: E402
from locqa.apply import apply_decisions, validate  # noqa: E402
from locqa.arb import ArbFile, load_arb  # noqa: E402
from locqa.checks import Context, Options, run_checks  # noqa: E402
from locqa.evaluate import evaluate  # noqa: E402
from locqa.glossary import load_glossary  # noqa: E402
from locqa.seed import seed_errors  # noqa: E402
from locqa.textutil import detect_lang, poss_case  # noqa: E402
from locqa.translit import transliterate_message  # noqa: E402

EX = ROOT / "examples"
GLOSSARY = load_glossary(str(ROOT / "glossary.csv"))

# A tiny but realistic background corpus so that corpus statistics have something to work with.
BASE_RU = {
    "a1": "Ваши деньги", "a2": "Купить дом", "a3": "Недостаточно денег", "a4": "Сохранить",
    "a5": "Закрыть", "a6": "Закрыть", "a7": "Закрыть", "a8": "Подключение к серверу",
    "a9": "Вы перевели деньги", "a10": "Пароль неверный", "a11": "Пароль изменён", "a12": "Новый пароль",
}
BASE_KK = {
    "a1": "Сіздің ақшаңыз", "a2": "Үй сатып алу", "a3": "Ақша жеткіліксіз", "a4": "Сақтау",
    "a5": "Жабу", "a6": "Жабу", "a7": "Жабу", "a8": "Серверге қосылу",
    "a9": "Сіз ақша аудардыңыз", "a10": "Құпиясөз қате", "a11": "Құпиясөз өзгертілді", "a12": "Жаңа құпиясөз",
}


def run(src: dict, tgt: dict, lang="kk", src_meta=None, refs=None):
    sd = {"@@locale": "ru", **src, **(src_meta or {})}
    td = {"@@locale": lang, **tgt}
    ctx = Context(ArbFile("ru.arb", "ru", sd), ArbFile(f"{lang}.arb", lang, td), GLOSSARY, Options(), refs)
    return run_checks(ctx)


def types_for(findings, key):
    return {f.issue_type for f in findings if f.key == key}


class IcuTest(unittest.TestCase):
    def test_simple_and_plural(self):
        nodes = icu.parse("У вас {count, plural, one{{count} предмет} other{{count} предметов}} от {name}")
        self.assertEqual(icu.placeholder_names(nodes), {"count", "name"})

    def test_errors(self):
        for bad in ["{name", "name}", "{count, plural, one{x}", "{count, plural, }"]:
            with self.assertRaises(icu.IcuError, msg=bad):
                icu.parse(bad)


class ChecksTest(unittest.TestCase):
    def check(self, key, ru, kk, expected, **kw):
        f = run({**BASE_RU, key: ru}, {**BASE_KK, **({key: kk} if kk is not None else {})}, **kw)
        self.assertIn(expected, types_for(f, key), [x.to_dict() for x in f if x.key == key])
        return [x for x in f if x.key == key and x.issue_type == expected][0]

    def test_untranslated(self):
        self.check("k", "Играть", None, "untranslated")
        self.check("k", "Играть", "", "untranslated")

    def test_same_as_source(self):
        self.check("k", "Сервер переполнен, попробуйте позже", "Сервер переполнен, попробуйте позже", "same_as_source")

    def test_same_as_source_loanword_ok(self):
        en = ArbFile("en.arb", "en", {"k": "Taxi"})
        f = run({**BASE_RU, "k": "Такси"}, {**BASE_KK, "k": "Такси"}, refs=[en])
        self.assertNotIn("same_as_source", types_for(f, "k"))

    def test_brand_ok(self):
        f = run({**BASE_RU, "k": "Grand Mobile"}, {**BASE_KK, "k": "Grand Mobile"})
        self.assertEqual(types_for(f, "k"), set())

    def test_placeholder(self):
        f = self.check("k", "Игрок {name} перевёл вам {amount}$", "{аты} сізге {amount}$ аударды", "placeholder_mismatch")
        self.assertEqual(f.suggestion, "{name} сізге {amount}$ аударды")
        self.check("k", "Уровень: {level}", "Деңгей: {level", "placeholder_mismatch")

    def test_plural(self):
        src = "{count, plural, one{{count} предмет} few{{count} предмета} many{{count} предметов} other{{count} предмета}}"
        self.check("k", src, "{count, plural, one{{count} зат}}", "plural_mismatch")
        self.check("k", src, "{count} зат", "plural_mismatch")
        f = run({**BASE_RU, "k": src}, {**BASE_KK, "k": "{count, plural, other{{count} зат}}"})
        self.assertNotIn("plural_mismatch", types_for(f, "k"))

    def test_glossary(self):
        f = self.check("family_tab", "Семья", "Жанұя", "glossary_violation")
        self.assertEqual(f.severity, "high")
        self.assertEqual(f.suggestion, "Отбасы")
        ok = run({**BASE_RU, "k": "Семь дней"}, {**BASE_KK, "k": "Жеті күн"})
        self.assertNotIn("glossary_violation", types_for(ok, "k"), "«семь» (7) is not «семья»")

    def test_length(self):
        f = self.check("garage_rent_button", "Арендовать", "Жалға алу үшін басыңыз", "length_overflow")
        self.assertEqual(f.severity, "high")
        ok = run({**BASE_RU, "garage_rent_button": "Арендовать"}, {**BASE_KK, "garage_rent_button": "Жалға алу"})
        self.assertNotIn("length_overflow", types_for(ok, "garage_rent_button"))

    def test_mt_suspect(self):
        self.check("k", "Награда: {amount}$ и опыт", "Сыйлық: {amount}$ и тәжірибе", "machine_translation_suspect")
        self.check("k", "Откройте телефон, чтобы посмотреть задания", "Үшін тапсырмаларды көру телефонды ашыңыз", "machine_translation_suspect")

    def test_inconsistent(self):
        f = self.check("a7", "Закрыть", "Жабық", "inconsistent_term")
        self.assertIsNone(f.suggestion)

    def test_suffix_harmony(self):
        f = self.check("k", "Вы перевели {amount}$ игроку {name}", "Сіз {name}-ға {amount}$ аудардыңыз", "suffix_harmony")
        self.assertEqual(f.suggestion, "Сіз {name} ойыншысына {amount}$ аудардыңыз")
        f = self.check("k", "Решение {admin}", "{admin}-нің шешімі", "suffix_harmony")
        self.assertEqual(f.suggestion, "{admin} әкімшісінің шешімі")
        f = self.check("k", "Осталось {count} мин.", "{count}-ға дейін", "suffix_harmony")
        self.assertEqual(f.severity, "medium")
        self.assertIsNone(f.suggestion)

    def test_orthography(self):
        f = self.check("k", "Недостаточно денег", "Акша жеткіліксіз", "orthography")
        self.assertEqual(f.suggestion, "Ақша жеткіліксіз")
        f = self.check("k", "Лотерея", "Лотерeя ойыны", "orthography")  # Latin e
        self.assertEqual(f.severity, "high")

    def test_wrong_language(self):
        self.check("k", "Вы хотите уволиться?", "Haqiqatan ham ishdan boʻshamoqchimisiz?", "wrong_language")
        self.check("k", "Событие начнётся", "Тадбир тез орада сўнг бошланади", "wrong_language")
        self.check("k", "Введите сообщение", "Введите текст сообщения", "wrong_language")

    def test_clean_strings_have_no_findings(self):
        f = run(BASE_RU, BASE_KK)
        self.assertEqual([x.to_dict() for x in f], [])

    def test_finding_schema(self):
        f = run({**BASE_RU, "k": "Играть"}, BASE_KK)[0].to_dict()
        for field in ["key", "issue_type", "severity", "source", "target", "evidence", "suggestion", "confidence", "reviewed_by_human"]:
            self.assertIn(field, f)
        self.assertIn(f["severity"], {"high", "medium", "low"})


class UzbekTest(unittest.TestCase):
    def test_kazakh_in_uzbek_file(self):
        ru = {"a": "Играть", "b": "Настройки", "c": "Выход", "k": "Задание выполнено!"}
        uz = {"a": "Oʻynash", "b": "Sozlamalar", "c": "Chiqish", "k": "Тапсырма орындалды!"}
        f = run(ru, uz, lang="uz")
        self.assertIn("wrong_language", types_for(f, "k"))

    def test_apostrophe(self):
        f = run({"k": "Игрок", "j": "Игроки"}, {"k": "O'yinchi", "j": "Oʻyinchilar"}, lang="uz")
        self.assertIn("orthography", types_for(f, "k"))


class MorphologyTest(unittest.TestCase):
    def test_poss_case(self):
        self.assertEqual(poss_case("ойыншы", "dat"), "ойыншысына")
        self.assertEqual(poss_case("ойыншы", "gen"), "ойыншысының")
        self.assertEqual(poss_case("отбасы", "dat"), "отбасына")
        self.assertEqual(poss_case("үй", "dat"), "үйіне")

    def test_detect(self):
        self.assertEqual(detect_lang("Сіз ойынға қосылдыңыз және сыйлық алдыңыз")[0], "kk")
        self.assertEqual(detect_lang("Вы вступили в семью и получили награду")[0], "ru")
        self.assertEqual(detect_lang("Siz oʻyinga qoʻshildingiz va mukofot oldingiz")[0], "uz")


class ApplyTest(unittest.TestCase):
    def test_apply_marks_review_and_keeps_icu_valid(self):
        src = ArbFile("ru.arb", "ru", {"@@locale": "ru", "a": "Привет, {name}", "b": "Пока"})
        tgt = ArbFile("kk.arb", "kk", {"@@locale": "kk", "a": "Сәлем {name}-ға", "b": "Пока"})
        decisions = [
            {"id": "1", "key": "a", "issue_type": "suffix_harmony", "decision": "edit", "final_text": "Сәлем, {name}!", "reviewer": "Айгерім"},
            {"id": "2", "key": "b", "issue_type": "same_as_source", "decision": "accept", "final_text": "Сау болыңыз {bad}", "reviewer": "Айгерім"},
        ]
        for d in decisions:
            d["original_source"] = src.messages[d["key"]]
            d["original_target"] = tgt.messages[d["key"]]
        data, stats = apply_decisions(src, tgt, decisions)
        self.assertEqual(data["a"], "Сәлем, {name}!")
        self.assertTrue(data["@a"]["x-reviewed_by_human"])
        self.assertEqual(data["@a"]["x-original"], "Сәлем {name}-ға")
        self.assertEqual(data["b"], "Пока", "edit with a foreign placeholder must be rejected")
        self.assertEqual(stats["changed_reviewed"], 1)
        self.assertEqual(validate(ArbFile("x", "kk", data), src), [])

    def test_validate_catches_broken_icu(self):
        errs = validate(ArbFile("x", "kk", {"a": "{count, plural, one{x}"}))
        self.assertTrue(errs)


class TranslitTest(unittest.TestCase):
    def test_translit(self):
        self.assertEqual(transliterate_message("Қазақстан"), "Qazaqstan")
        self.assertEqual(transliterate_message("Сіз {name} ойыншысына"), "Sız {name} oiynşysyna")
        out = transliterate_message("{count, plural, other{{count} зат}}")
        self.assertEqual(out, "{count, plural, other{{count} zat}}")


class EndToEndTest(unittest.TestCase):
    """Regression gate on the demo data. Numbers are optimistic: the demo set is small and hand-made."""

    def test_handmade_errors_recall(self):
        src, tgt = load_arb(EX / "intl_ru.arb"), load_arb(EX / "intl_kk.arb")
        refs = [load_arb(EX / "intl_en.arb"), load_arb(EX / "intl_uz.arb")]
        f = [x.to_dict() for x in run_checks(Context(src, tgt, GLOSSARY, Options(), refs))]
        res = evaluate(f, json.loads((EX / "expected_kk.json").read_text(encoding="utf-8")))
        self.assertGreaterEqual(res["recall_typed"], 0.95, res["missed"])

    def test_seeded_errors_recall(self):
        src, tgt, uz = load_arb(EX / "intl_ru.arb"), load_arb(EX / "intl_kk.arb"), load_arb(EX / "intl_uz.arb")
        refs = [load_arb(EX / "intl_en.arb"), uz]
        recalls = []
        for seed in (1, 2, 3):
            data, answer = seed_errors(src, tgt, n=33, rnd_seed=seed, other=uz, glossary=GLOSSARY)
            ctx = Context(src, ArbFile("seeded.arb", "kk", data), GLOSSARY, Options(), refs)
            res = evaluate([x.to_dict() for x in run_checks(ctx)], answer)
            recalls.append(res["recall_typed"])
        self.assertGreaterEqual(sum(recalls) / len(recalls), 0.9, recalls)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "report.json"
            r = subprocess.run(
                [sys.executable, "-m", "locqa", "check", "--source", str(EX / "intl_ru.arb"), "--target", str(EX / "intl_kk.arb"),
                 "--glossary", str(ROOT / "glossary.csv"), "--out", str(out), "--fail-on", "high"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 1, r.stderr)  # the demo file has high-severity issues
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIsInstance(data, list)
            self.assertTrue(out.with_suffix(".html").exists())


if __name__ == "__main__":
    unittest.main()
