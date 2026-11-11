"""Synthetic recall by type at the CLI threshold and without filtering. No API."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from locqa import __version__
from locqa.arb import load_arb, ArbFile, mutable_arb_data
from locqa.checks import Context, Options, run_checks
from locqa.glossary import load_glossary
from locqa.seed import seed_errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'target', 'other', 'glossary', 'out'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--seeds', type=int, default=5)
    parser.add_argument('--min-confidence', type=float, default=0.5)
    args = parser.parse_args()
    if args.seeds < 1 or not 0 <= args.min_confidence <= 1:
        parser.error('seeds must be positive and confidence must be in [0, 1]')
    from locqa.cli import protect_outputs
    protect_outputs([args.out], [args.source, args.target, args.other, args.glossary])
    src, tgt, other = map(load_arb, [args.source, args.target, args.other])
    tgt = ArbFile(tgt.path, tgt.locale, mutable_arb_data(tgt.data))
    other = ArbFile(other.path, other.locale, mutable_arb_data(other.data))
    glossary = load_glossary(args.glossary)
    base = {(f.key, f.issue_type) for f in run_checks(Context(src, tgt, glossary, Options()))}
    totals = defaultdict(Counter)
    runs = []
    for seed in range(args.seeds):
        data, answer = seed_errors(src, tgt, n=110, rnd_seed=seed, other=other, glossary=glossary)
        effective, noops = [], []
        for row in answer:
            key = row['key']
            (effective if data.get(key) != tgt.data.get(key) or (key in data) != (key in tgt.data) else noops).append(row)
        findings = run_checks(Context(src, ArbFile('', tgt.locale, data), glossary, Options()))
        raw = {(f.key, f.issue_type) for f in findings}
        main = {(f.key, f.issue_type) for f in findings if f.confidence >= args.min_confidence}
        missed = []
        for row in effective:
            pair = row['key'], row['issue_type']
            count = totals[row['issue_type']]
            count['injected'] += 1
            count['found_typed'] += pair in main
            count['found_typed_all_confidences'] += pair in raw
            count['already_flagged_before_injection'] += pair in base
            count['novel_injections'] += pair not in base
            count['novel_found_typed'] += pair not in base and pair in main
            if pair not in main:
                missed.append({**row, 'found_in_candidates': pair in raw})
        runs.append({'seed': seed, 'effective_injections': len(effective), 'no_op_injections': noops, 'missed': missed})
    by_type = {}
    for name, count in sorted(totals.items()):
        by_type[name] = {**count,
            'recall_typed': round(count['found_typed'] / count['injected'], 4),
            'recall_typed_all_confidences': round(count['found_typed_all_confidences'] / count['injected'], 4),
            'recall_novel_typed': round(count['novel_found_typed'] / count['novel_injections'], 4) if count['novel_injections'] else None}
    n = sum(c['injected'] for c in totals.values())
    hits = sum(c['found_typed'] for c in totals.values())
    raw_hits = sum(c['found_typed_all_confidences'] for c in totals.values())
    novel = sum(c['novel_injections'] for c in totals.values())
    novel_hits = sum(c['novel_found_typed'] for c in totals.values())
    result = {
        'tool': 'locqa ' + __version__, 'synthetic_only': True, 'seeds': args.seeds,
        'min_confidence': args.min_confidence,
        'input_sha256': {name: hashlib.sha256(Path(getattr(args, name)).read_bytes()).hexdigest() for name in ('source', 'target', 'other', 'glossary')},
        'injected': n, 'found_typed': hits, 'found_typed_all_confidences': raw_hits,
        'recall_typed': round(hits / n, 4) if n else None,
        'recall_typed_all_confidences': round(raw_hits / n, 4) if n else None,
        'novel_injections': novel, 'novel_found_typed': novel_hits,
        'recall_novel_typed': round(novel_hits / novel, 4) if novel else None,
        'by_type': by_type, 'runs': runs,
        'limitations': 'Synthetic generator and detector share assumptions; repeated keys across seeds are correlated. Existing findings are excluded only from the novel metric. Missing types are unmeasured. Not hidden-test recall or independent precision.'}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'runs'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
