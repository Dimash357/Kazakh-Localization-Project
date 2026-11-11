#!/usr/bin/env bash
# Recall/precision on the demo data: hand-made errors + randomly seeded errors over several seeds.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${OUT:-/tmp/locqa-bench}; mkdir -p "$OUT"
EX=examples; ARGS="--glossary glossary.csv --ref $EX/intl_en.arb $EX/intl_uz.arb"
python3 -m locqa check --source $EX/intl_ru.arb --target $EX/intl_kk.arb $ARGS --out "$OUT/base.json" 2>/dev/null
echo "== ручные ошибки (examples/expected_kk.json)"
python3 -m locqa eval --report "$OUT/base.json" --answer $EX/expected_kk.json | head -1
for s in ${SEEDS:-1 2 3 4 5}; do
  python3 -m locqa seed --source $EX/intl_ru.arb --target $EX/intl_kk.arb --other $EX/intl_uz.arb \
    --glossary glossary.csv --out "$OUT/seeded$s.arb" --answer "$OUT/answer$s.json" --n 33 --seed "$s" 2>/dev/null
  # Answer key = seeded errors + hand-made ones still present in the file.
  python3 - "$OUT/answer$s.json" $EX/expected_kk.json "$OUT/full$s.json" <<'PY'
import json, sys
seeded = json.load(open(sys.argv[1])); keys = {a["key"] for a in seeded}
json.dump(seeded + [a for a in json.load(open(sys.argv[2])) if a["key"] not in keys], open(sys.argv[3], "w"))
PY
  python3 -m locqa check --source $EX/intl_ru.arb --target "$OUT/seeded$s.arb" $ARGS --out "$OUT/r$s.json" 2>/dev/null
  echo "== seed $s"
  python3 -m locqa eval --report "$OUT/r$s.json" --answer "$OUT/answer$s.json" | head -1
  python3 -m locqa eval --report "$OUT/r$s.json" --answer "$OUT/full$s.json" | grep -E "Precision|^  -" || true
done
