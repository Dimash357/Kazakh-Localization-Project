"""Regression tests for v0.1.1 fixes (glossary locale, plural repeat, CLI errors, noise tiers)."""
import json
import tempfile
import unittest
from pathlib import Path

from locqa.arb import load_arb
from locqa.checks import Context, Options, run_checks
from locqa.cli import main
from locqa.glossary import load_glossary

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


def _arb(d: Path, name: str, data: dict) -> str:
    p = d / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


class GlossaryLocale(unittest.TestCase):
    def test_english_target_gets_no_kazakh_glossary_findings(self):
        ctx = Context(load_arb(str(EX / "intl_ru.arb")), load_arb(str(EX / "intl_en.arb")),
                      load_glossary(str(ROOT / "glossary.csv")), Options())
        self.assertEqual([f for f in run_checks(ctx) if f.issue_type == "glossary_violation"], [])

    def test_kazakh_glossary_still_works(self):
        ctx = Context(load_arb(str(EX / "intl_ru.arb")), load_arb(str(EX / "intl_kk.arb")),
                      load_glossary(str(ROOT / "glossary.csv")), Options())
        self.assertTrue([f for f in run_checks(ctx) if f.issue_type == "glossary_violation"])
        # `reference` terms stay in the file but are not enforced
        import csv, io
        with tempfile.TemporaryDirectory() as t:
            g = Path(t) / "g.csv"
            g.write_text("ru,kk,en,note,status\nфракция,фракция,faction,,approved\nполиция,полиция,police,,reference\n", encoding="utf-8")
            self.assertEqual([x.ru for x in load_glossary(str(g))], ["фракция"])
            self.assertEqual(len(load_glossary(str(g), include_reference=True)), 2)


class PluralRepeat(unittest.TestCase):
    def test_same_word_in_two_plural_branches_is_not_a_repeat(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            src = _arb(d, "ru.arb", {"@@locale": "ru", "b": "{n, plural, one{{n} предмет} other{{n} предметов}}"})
            tgt = _arb(d, "kk.arb", {"@@locale": "kk", "b": "{n, plural, one{{n} зат} other{{n} зат}}"})
            ctx = Context(load_arb(src), load_arb(tgt), [], Options())
            self.assertFalse([f for f in run_checks(ctx) if "повтор слова" in f.evidence])

    def test_real_doubled_word_is_still_reported(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            src = _arb(d, "ru.arb", {"@@locale": "ru", "b": "Нажмите кнопку"})
            tgt = _arb(d, "kk.arb", {"@@locale": "kk", "b": "Түймені түймені басыңыз"})
            ctx = Context(load_arb(src), load_arb(tgt), [], Options())
            self.assertTrue([f for f in run_checks(ctx) if "повтор слова" in f.evidence])


class CliErrors(unittest.TestCase):
    def test_bad_json_gives_exit_code_2_not_traceback(self):
        with tempfile.TemporaryDirectory() as t:
            bad = Path(t) / "bad.arb"
            bad.write_text("{bad", encoding="utf-8")
            rc = main(["check", "--source", str(EX / "intl_ru.arb"), "--target", str(bad), "--out", str(Path(t) / "o.json")])
            self.assertEqual(rc, 2)

    def test_missing_file_gives_exit_code_2(self):
        with tempfile.TemporaryDirectory() as t:
            rc = main(["check", "--source", str(EX / "intl_ru.arb"), "--target", str(Path(t) / "nope.arb"), "--out", str(Path(t) / "o.json")])
            self.assertEqual(rc, 2)


class NoiseTiers(unittest.TestCase):
    def _run(self, *extra):
        t = tempfile.mkdtemp()
        out = str(Path(t) / "r.json")
        main(["check", "--source", str(EX / "intl_ru.arb"), "--target", str(EX / "intl_kk.arb"),
              "--glossary", str(ROOT / "glossary.csv"), "--out", out, *extra])
        return json.loads(Path(out).read_text(encoding="utf-8")), Path(t)

    def test_default_report_hides_low_confidence_and_saves_candidates(self):
        main_report, d = self._run()
        self.assertTrue(all(f["confidence"] >= 0.5 for f in main_report))
        cands = json.loads((d / "r.candidates.json").read_text(encoding="utf-8"))
        self.assertTrue(cands and all(f["confidence"] < 0.5 for f in cands))

    def test_min_confidence_zero_keeps_everything(self):
        full, d = self._run("--min-confidence", "0")
        self.assertFalse((d / "r.candidates.json").exists())
        default, d2 = self._run()
        cands = json.loads((d2 / "r.candidates.json").read_text(encoding="utf-8"))
        self.assertEqual(len(full), len(default) + len(cands))

    def test_native_russian_word_stays_in_main_report(self):
        main_report, _ = self._run()
        self.assertIn("support_title", {f["key"] for f in main_report})

    def test_default_report_is_plain_list_per_task_schema(self):
        main_report, _ = self._run()
        self.assertIsInstance(main_report, list)
        for f in main_report:
            for k in ("key", "issue_type", "severity", "source", "target", "evidence", "suggestion", "confidence", "reviewed_by_human"):
                self.assertIn(k, f)


if __name__ == "__main__":
    unittest.main()
