from __future__ import annotations

import html
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone

from .checks import ISSUE_TYPES, Finding

ISSUE_LABELS = {
    "untranslated": "Нет перевода",
    "same_as_source": "Совпадает с русским",
    "placeholder_mismatch": "Плейсхолдеры",
    "plural_mismatch": "ICU plural",
    "glossary_violation": "Глоссарий",
    "length_overflow": "Длина",
    "machine_translation_suspect": "Машинный перевод?",
    "inconsistent_term": "Несогласованные термины",
    "suffix_harmony": "Окончание после плейсхолдера",
    "orthography": "Орфография",
    "wrong_language": "Чужой язык",
}


def summary(findings: list[Finding], meta: dict) -> dict:
    return {
        **meta,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(findings),
        "keys_with_findings": len({f.key for f in findings}),
        "by_type": dict(Counter(f.issue_type for f in findings)),
        "by_severity": dict(Counter(f.severity for f in findings)),
    }


def write_json(findings: list[Finding], path: str, meta: dict | None = None) -> None:
    data = [f.to_dict() for f in findings]
    if meta is not None:
        data = {"summary": summary(findings, meta), "findings": data}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def read_findings(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    rows = data.get("findings") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("отчёт должен быть массивом находок или объектом с findings")
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) for key in ("key", "issue_type", "source")):
            raise ValueError(f"находка {index}: неверные ключ, тип или исходный текст")
        if "target" not in row or (row["target"] is not None and not isinstance(row["target"], str)):
            raise ValueError(f"находка {index}: неверный перевод")
        if row.get("id") is not None and not isinstance(row["id"], str):
            raise ValueError(f"находка {index}: неверный id")
    return rows


def write_html(findings: list[Finding], path: str, meta: dict) -> None:
    payload = {
        "summary": summary(findings, meta),
        "labels": ISSUE_LABELS,
        "types": ISSUE_TYPES,
        "findings": [f.to_dict() for f in findings],
    }
    payload["fingerprint"] = hashlib.sha256(json.dumps(payload["findings"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(f"locqa: {meta.get('target', '')}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_TEMPLATE.replace("{{TITLE}}", title).replace("{{DATA}}", blob))


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{TITLE}}</title>
  <style>:root {
  --bg: #121212;
  --panel: #1c1c22;
  --panel-2: #24242c;
  --line: #34343e;
  --text: #e8e8ee;
  --muted: #9a9aa8;
  --high: #ff2e4d;
  --medium: #ffb020;
  --low: #2fd6a3;
  --action: #3d9bff;
  --mono: "JetBrains Mono", "Cascadia Mono", "SF Mono", Consolas, "Liberation Mono", monospace;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
* { box-sizing: border-box; }
html { color-scheme: dark; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.5 var(--sans); }
.mono { font-family: var(--mono); }
.muted { color: var(--muted); }
h1 { margin: 0; font-size: 20px; font-weight: 600; }
h1 .muted { font-weight: 400; }

.topbar { position: sticky; top: 0; z-index: 10; display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; padding: 12px 24px; background: rgba(18,18,18,.92); backdrop-filter: blur(6px); border-bottom: 1px solid var(--line); }
.topbar-actions { display: flex; align-items: center; gap: 14px; }
main { max-width: 1280px; margin: 0 auto; padding: 24px; }

.btn { font: 600 13px var(--sans); color: var(--text); background: var(--panel-2); border: 1px solid var(--line); border-radius: 4px; padding: 8px 14px; cursor: pointer; }
.btn:hover { border-color: var(--action); }
.btn-primary { background: var(--action); border-color: var(--action); color: #04121f; }
.btn-primary:hover { filter: brightness(1.1); }
.btn-ok { color: var(--low); border-color: #1f6e58; }
.btn-warn { color: var(--medium); border-color: #7a5710; }
:focus-visible { outline: 2px solid var(--action); outline-offset: 2px; }

.kpis { display: grid; grid-template-columns: 1.4fr repeat(4, 1fr); gap: 12px; }
.kpi { background: var(--panel); border: 1px solid var(--line); border-top: 3px solid var(--muted); border-radius: 4px; padding: 16px 18px; }
.kpi-val { font-size: 44px; line-height: 1; font-weight: 700; }
.kpi-label { margin-top: 8px; color: var(--muted); font-size: 13px; }
.kpi-total { border-top-color: var(--action); }
.kpi-high { border-top-color: var(--high); } .kpi-high .kpi-val { color: var(--high); }
.kpi-medium { border-top-color: var(--medium); } .kpi-medium .kpi-val { color: var(--medium); }
.kpi-low { border-top-color: var(--low); } .kpi-low .kpi-val { color: var(--low); }

.dist { margin: 16px 0 24px; }
.dist-row {
  display: flex;
  align-items: center;
  gap: 20px;
}

.dist-bar {
  flex: 1;
  min-width: 0;
  display: flex;
  height: 12px;
  overflow: hidden;
  border-radius: 6px;
  background: var(--panel-2);
}

.dist-bar span {
  display: block;
  height: 100%;
}

.dist-pie {
  width: 80px;
  height: 80px;
  flex: 0 0 80px;
  border-radius: 50%;
  background: var(--panel-2);
}
.dist-legend { display: flex; justify-content: center; flex-wrap: wrap; gap: 20px; margin-top: 8px; font-size: 12px; color: var(--muted); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.bg-high { background: var(--high); } .bg-medium { background: var(--medium); } .bg-low { background: var(--low); }

.filters { background: var(--panel); border: 1px solid var(--line); border-radius: 4px; padding: 16px; margin-bottom: 20px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.chip { font: 12px var(--mono); color: var(--muted); background: transparent; border: 1px solid var(--line); border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.chip b { color: var(--text); margin-left: 6px; }
.chip:hover { border-color: var(--action); color: var(--text); }
.chip[aria-pressed="true"] { background: rgba(61,155,255,.15); border-color: var(--action); color: var(--action); }
.filter-row { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.filter-row input[type="search"] { flex: 1 1 240px; }
input[type="search"], select, textarea { background: var(--bg); color: var(--text); border: 1px solid var(--line); border-radius: 4px; padding: 8px 10px; font: 14px var(--sans); }
input[type="search"]:focus, select:focus, textarea:focus { outline: none; border-color: var(--action); }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.check { display: flex; align-items: center; gap: 8px; padding-bottom: 8px; cursor: pointer; }
.check input { accent-color: var(--action); width: 16px; height: 16px; }
#resultCount { margin-top: 12px; font-size: 12px; }

.cards { display: grid; gap: 14px; }
.card { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--muted); border-radius: 4px; padding: 16px 18px; }
.card.sev-high { border-left-color: var(--high); }
.card.sev-medium { border-left-color: var(--medium); }
.card.sev-low { border-left-color: var(--low); }
.card-head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 14px; }
.key { font: 600 14px var(--mono); color: var(--action); word-break: break-all; }
.badge { font: 700 11px var(--mono); padding: 2px 8px; border-radius: 3px; text-transform: uppercase; color: #101010; }
.badge.high { background: var(--high); box-shadow: 0 0 10px rgba(255,46,77,.45); }
.badge.medium { background: var(--medium); box-shadow: 0 0 10px rgba(255,176,32,.4); }
.badge.low { background: var(--low); }
.tag { font: 12px var(--mono); color: var(--muted); border: 1px solid var(--line); border-radius: 3px; padding: 1px 8px; }
.conf { margin-left: auto; font: 12px var(--mono); color: var(--muted); }
.verdict { font: 700 11px var(--mono); padding: 2px 8px; border-radius: 3px; border: 1px solid; }
.verdict.accepted, .verdict.edited { color: var(--low); border-color: var(--low); }
.verdict.false_positive { color: var(--muted); border-color: var(--muted); }

.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.cell { background: var(--panel-2); border-radius: 4px; padding: 10px 12px; min-width: 0; }
.cell h3 { margin: 0 0 6px; font-size: 12px; font-weight: 600; color: var(--muted); }
.cell p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.cell.src p, .cell.tgt p { font-family: var(--mono); font-size: 14px; }
.cell.sug { border: 1px dashed #2a5a8a; }

.review { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--line); }
.review[hidden] { display: none; }
.review textarea { width: 100%; min-height: 72px; resize: vertical; font-family: var(--mono); font-size: 14px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.card.false_positive { opacity: .6; }
.status { text-align: center; color: var(--muted); padding: 40px 0; }

@media (max-width: 860px) {
  .kpis { grid-template-columns: repeat(2, 1fr); }
  .kpi-total { grid-column: 1 / -1; }
  .grid { grid-template-columns: 1fr; }
  main { padding: 16px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }

.btn:disabled { opacity: .45; cursor: not-allowed; }
.field input { background: var(--bg); color: var(--text); border: 1px solid var(--line); padding: 8px 10px; border-radius: 4px; max-width: 100%; }
@media (max-width: 480px) { .topbar { padding: 12px; } .topbar-actions { flex-wrap: wrap; } .filter-row input[type="search"] { min-width: 0; width: 100%; } .dist-legend { flex-wrap: wrap; } }
</style>
</head>
<body>
  <header class="topbar">
    <h1>LocQA <span class="muted">/ отчёт по локализации</span></h1>
    <div class="topbar-actions">
      <span id="saveState" class="muted mono" aria-live="polite"></span>
      <button id="importBtn" class="btn" type="button" disabled>Загрузить решения</button>
      <input id="importFile" type="file" accept=".json,application/json" hidden>
      <button id="exportBtn" disabled class="btn btn-primary" type="button">Скачать decisions.json</button>
    </div>
  </header>

  <main>
    <p id="llm-status" class="status" hidden></p>
    <section class="kpis" aria-label="Статистика">
      <div class="kpi kpi-total"><div class="kpi-val mono" id="kpiTotal">0</div><div class="kpi-label">Всего проблем</div></div>
      <div class="kpi kpi-high"><div class="kpi-val mono" id="kpiHigh">0</div><div class="kpi-label">High</div></div>
      <div class="kpi kpi-medium"><div class="kpi-val mono" id="kpiMedium">0</div><div class="kpi-label">Medium</div></div>
      <div class="kpi kpi-low"><div class="kpi-val mono" id="kpiLow">0</div><div class="kpi-label">Low</div></div>
      <div class="kpi kpi-done"><div class="kpi-val mono" id="kpiReviewed">0</div><div class="kpi-label">Проверено</div></div>
    </section>

    <section class="dist" aria-label="Распределение критичности">
      <div class="dist-row">
        <div class="dist-bar" id="distBar"
         role="img" aria-label="Распределение критичности"></div>
        <div class="dist-pie" id="distPie" aria-hidden="true"></div>
        </div>
      <div class="dist-legend mono" id="distLegend"></div>
    </section>

    <section class="filters" aria-label="Фильтры">
      <div class="chips" id="typeChips" role="group" aria-label="Тип проблемы"></div>
      <div class="filter-row">
        <input type="search" id="search" placeholder="Поиск по key, тексту, причине…" aria-label="Поиск">
        <label class="field">Критичность
          <select id="severityFilter">
            <option value="">Все</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>
        <label class="field">Уверенность
          <select id="confidenceFilter"><option value="">Любая</option></select>
        </label>
        <label class="field">Проверяющий<input id="reviewer" type="text" placeholder="Имя (необязательно)"></label>
        <label class="check"><input type="checkbox" id="reviewMode"> Режим проверки носителем</label>
        <button id="resetFilters" class="btn" type="button">Сбросить фильтры</button>
      </div>
      <div class="muted mono" id="resultCount" aria-live="polite"></div>
    </section>

    <section id="cards" class="cards" aria-label="Список проблем"></section>
    <p id="status" class="status" role="status"></p>
  </main>

  <script id="report-data" type="application/json">{{DATA}}</script>
<script>(() => {
  'use strict';
  let LS_KEY;
  let reportSignature;
  const drafts = new Map();
  const commentDrafts = new Map();
  let labels = {};
  const typeLabel = value => labels[value] || String(value || "Без типа").replaceAll("_", " ");
  const SEV = ['high', 'medium', 'low'];
  const $ = (id) => document.getElementById(id);
  const state = { items: [], decisions: Object.create(null), types: new Set(), numericConf: true };

  function loadDecisions() {
    try {
      const saved = JSON.parse(localStorage.getItem(LS_KEY));
      if (saved?.signature !== reportSignature) return Object.create(null);
      return Object.assign(Object.create(null), Object.fromEntries(
        Object.entries(saved.decisions || {}).filter(([id, d]) =>
          state.items.some(i => String(i.id) === id) && d &&
          ['accepted', 'edited', 'false_positive', 'pending', 'code'].includes(d.status) &&
          (d.edit === null || typeof d.edit === 'string'))));
    } catch { return Object.create(null); }
  }
  function saveDecisions() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({ signature: reportSignature, decisions: state.decisions }));
      $('saveState').textContent = 'сохранено ' + new Date().toLocaleTimeString('ru-RU');
    } catch { $('saveState').textContent = 'не удалось сохранить в localStorage'; }
    $('kpiReviewed').textContent = Object.keys(state.decisions).filter((id) => state.items.some((i) => String(i.id) === id)).length;
  }
  const sev = (i) => String(i.severity || '').toLowerCase();
  const confNum = (i) => { const v = i.confidence; if (v == null || v === '') return null; const n = Number(v); return !Number.isFinite(n) || n < 0 || n > 100 ? null : (n > 1 ? n / 100 : n); };
  const confLabel = (i) => { const n = confNum(i); return n === null ? String(i.confidence ?? '—') : Math.round(n * 100) + '%'; };

  function renderLLM(llm) {
    if (!llm) return;
    const block = $('llm-status'); block.hidden = false;
    const statuses = {ok:'завершено',partial:'частично завершено',failed:'ошибка',skipped:'нет подходящих находок'};
    block.textContent = `Gemini ${llm.model || ''}: ${statuses[llm.status] || llm.status}. ` +
      `Выбрано: ${llm.selected ?? 0}; отправлено: ${llm.items ?? 0}; обработано: ${llm.processed ?? 0}; ` +
      `предложений: ${llm.suggestions_added ?? 0}; вероятных ложных: ${llm.false_positives ?? 0}; ` +
      `отклонено: ${llm.suggestions_rejected ?? 0}; без ответа: ${llm.missing ?? 0}. Языковое качество требует проверки человеком.`;
  }
  // ---------- загрузка ----------
  async function init() {
    try {
      const data = JSON.parse(document.getElementById('report-data').textContent);
      labels = data.labels || {};
      renderLLM(data.summary?.llm);
      const rows = Array.isArray(data) ? data : (data?.findings ?? data?.items ?? data?.issues);
      if (!Array.isArray(rows)) throw new Error('Ожидается массив находок или объект с findings');
      const ids = new Set();
      state.items = rows.map((row, index) => {
        if (!row || typeof row !== 'object' || typeof row.key !== 'string' ||
            typeof row.source !== 'string' || typeof row.issue_type !== 'string' ||
            !(row.target === null || typeof row.target === 'string'))
          throw new Error('Некорректная находка ' + (index + 1));
        const id = row.id == null ? 'row-' + index : String(row.id);
        if (ids.has(id)) throw new Error('Повторяющийся id: ' + id);
        ids.add(id);
        return { ...row, id };
      });
      reportSignature = JSON.stringify(state.items);
      LS_KEY = 'locqa.decisions.v2.' + data.fingerprint;
      state.decisions = loadDecisions();
    } catch (e) {
      $('status').textContent = 'Не удалось загрузить report.json (' + e.message + '). Попробуйте заново создать HTML-отчёт.';
      return;
    }
    state.numericConf = state.items.every((i) => confNum(i) !== null);
    renderStats();
    renderChips();
    renderConfidenceOptions();
    bind();
    render();
    $('kpiReviewed').textContent = Object.keys(state.decisions).length;
    $('exportBtn').disabled = false;
    $('importBtn').disabled = false;
  }

  // ---------- статистика ----------
  function renderStats() {
    const total = state.items.length;
    const count = s => state.items.filter(i => sev(i) === s).length;
    $('kpiTotal').textContent = total;
    $('kpiHigh').textContent = count('high');
    $('kpiMedium').textContent = count('medium');
    $('kpiLow').textContent = count('low');
    const high = total ? count('high') / total * 100 : 0;
    const medium = total ? count('medium') / total * 100 : 0;

    $('distBar').innerHTML = SEV.map(s =>
      `<span class="bg-${s}" style="width:${total ? count(s) / total * 100 : 0}%"></span>`
    ).join('');
    $('distBar').style.background = 'var(--panel-2)';
    $('distPie').style.background = total
      ? `conic-gradient(var(--high) 0% ${high}%, var(--medium) ${high}% ${high + medium}%, var(--low) ${high + medium}% 100%)`
      : 'var(--panel-2)';
    $('distBar').setAttribute('aria-label',
      `High: ${count('high')}, Medium: ${count('medium')}, Low: ${count('low')}`);
    $('distLegend').innerHTML = SEV.map(s =>
      `<span><i class="dot bg-${s}"></i>${s} ${total ? Math.round(count(s) / total * 100) : 0}%</span>`
    ).join('');
  }

  function renderChips() {
    const counts = Object.create(null);
    state.items.forEach((i) => { const t = i.issue_type || '—'; counts[t] = (counts[t] || 0) + 1; });
    $('typeChips').innerHTML = '';
    Object.entries(counts).sort((a, b) => b[1] - a[1]).forEach(([t, n]) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'chip'; b.dataset.type = t; b.setAttribute('aria-pressed', 'false');
      b.innerHTML = `${esc(typeLabel(t))}<b>${n}</b>`;
      b.addEventListener('click', () => {
        state.types.has(t) ? state.types.delete(t) : state.types.add(t);
        b.setAttribute('aria-pressed', state.types.has(t));
        render();
      });
      $('typeChips').appendChild(b);
    });
  }

  function renderConfidenceOptions() {
    const sel = $('confidenceFilter');
    const opts = state.numericConf
      ? [['ge90', '≥ 90%'], ['ge70', '≥ 70%'], ['lt70', '< 70%']]
      : [...new Set(state.items.map((i) => String(i.confidence ?? '—')))].map((v) => [v, v]);
    opts.forEach(([v, l]) => sel.insertAdjacentHTML('beforeend', `<option value="${esc(v)}">${esc(l)}</option>`));
  }

  // ---------- фильтрация ----------
  function matches(i) {
    if (state.types.size && !state.types.has(i.issue_type || '—')) return false;
    const s = $('severityFilter').value;
    if (s && sev(i) !== s) return false;
    const c = $('confidenceFilter').value;
    if (c) {
      if (state.numericConf) {
        const n = confNum(i);
        if (c === 'ge90' && !(n >= 0.9)) return false;
        if (c === 'ge70' && !(n >= 0.7)) return false;
        if (c === 'lt70' && !(n < 0.7)) return false;
      } else if (String(i.confidence ?? '—') !== c) return false;
    }
    const q = $('search').value.trim().toLowerCase();
    if (q) {
      const hay = [i.key, i.source, i.target, i.evidence, i.suggestion, i.issue_type, typeLabel(i.issue_type)].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }

  // ---------- карточки ----------
  function render() {
    const list = state.items.filter(matches);
    $('resultCount').textContent = `Показано ${list.length} из ${state.items.length}`;
    $('status').textContent = list.length ? '' : (state.items.length ? 'Ничего не найдено. Сбросьте фильтры.' : 'В отчёте нет находок.');
    $('cards').innerHTML = list.map(cardHTML).join('');
  }

  function cardHTML(i) {
    const id = String(i.id);
    const d = state.decisions[id];
    const s = sev(i);
    const review = $('reviewMode').checked;
    const verdict = d ? `<span class="verdict ${d.status}">${{ accepted: 'принято', edited: 'правка сохранена', false_positive: 'ложное срабатывание', pending: 'на рассмотрении', code: 'нужна обработка в коде' }[d.status]}</span>` : '';
    return `
<article class="card sev-${esc(s)} ${d ? d.status : ''}" data-id="${esc(id)}">
  <div class="card-head">
    <span class="key">${esc(i.key)}</span>
    <span class="badge ${esc(s)}">${esc(s || '—')}</span>
    <span class="tag">${esc(typeLabel(i.issue_type))}</span>
    ${verdict}
    <span class="conf" title="Уверенность">conf ${esc(confLabel(i))}</span>
  </div>
  <div class="grid">
    <div class="cell src"><h3>Исходник</h3><p>${esc(i.source)}</p></div>
    <div class="cell tgt"><h3>Перевод</h3><p>${esc(i.target)}</p></div>
    <div class="cell"><h3>Почему</h3><p>${esc(i.evidence)}</p></div>
    <div class="cell sug"><h3>Предложение</h3><p>${esc(i.suggestion)}</p></div>
  </div>
  <div class="review" ${review ? '' : 'hidden'}>
    <textarea aria-label="Правка для ${esc(i.key)}">${esc(drafts.get(id) ?? (d && d.edit != null ? d.edit : i.suggestion ?? i.target ?? ''))}</textarea>
    <label>Комментарий
      <textarea class="review-comment" aria-label="Комментарий для ${esc(i.key)}">${esc(commentDrafts.get(id) ?? d?.comment ?? '')}</textarea>
    </label>
    ${d?.reviewer ? `<p class="muted">Проверяющий: ${esc(d.reviewer)}</p>` : ''}
    <div class="actions">
      <button class="btn btn-ok" type="button" data-act="accept" ${typeof i.suggestion === 'string' && i.suggestion.length ? '' : 'disabled'}>Принять</button>
      <button class="btn btn-primary" type="button" data-act="edit">Сохранить правку</button>
      <button class="btn btn-warn" type="button" data-act="fp">Ложное срабатывание</button>
      <button class="btn" type="button" data-act="pending">На рассмотрении</button>
      <button class="btn" type="button" data-act="code" ${i.issue_type === "suffix_harmony" ? "" : "disabled"}>Нужна обработка в коде</button>
      <button class="btn" type="button" data-act="reset">Сбросить</button>
    </div>
  </div>
</article>`;
  }

  function onCardClick(e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const card = btn.closest('.card');
    const id = card.dataset.id;
    const item = state.items.find((i) => String(i.id) === id);
    const text = card.querySelector('textarea').value;
    const now = new Date().toISOString();
    const act = btn.dataset.act;
    if (act !== 'reset' && !$('reviewer').value.trim()) { $('status').textContent = 'Введите имя проверяющего.'; $('reviewer').focus(); return; }
    if (act === 'code' && item.issue_type !== 'suffix_harmony') return;
    if (act === 'accept' && !(typeof item.suggestion === 'string' && item.suggestion.length)) return;
    if ((act === 'edit' && !text.trim())) { $('status').textContent = 'Введите непустой текст правки.'; return; }
    if (act === 'accept' || act === 'edit') {
      const error = validateMessage(item.source, act === 'accept' ? item.suggestion : text);
      if (error) { $('status').textContent = error; return; }
    }
    if (act === 'accept') state.decisions[id] = { id: item.id, key: item.key, status: 'accepted', edit: item.suggestion ?? '', updated_at: now };
    if (act === 'edit') state.decisions[id] = { id: item.id, key: item.key, status: 'edited', edit: text, updated_at: now };
    if (act === 'fp') state.decisions[id] = { id: item.id, key: item.key, status: 'false_positive', edit: null, updated_at: now };
    if (act === 'pending' || act === 'code') state.decisions[id] = {id:item.id, key:item.key, status:act, edit:null, updated_at:now};
    if (act === 'reset') delete state.decisions[id];
    if (state.decisions[id]) {
      state.decisions[id].comment = card.querySelector('.review-comment').value;
      state.decisions[id].reviewer = $('reviewer').value.trim();
    }
    commentDrafts.delete(id);
    drafts.delete(id);
    saveDecisions();
    render();
  }

  // ---------- экспорт ----------
  function exportDecisions() {
    const blob = new Blob([JSON.stringify(state.items.filter(i => state.decisions[i.id]).map(i => {
      const d = state.decisions[i.id];
      return { id: i.id, key: i.key, issue_type: i.issue_type,
        decision: { accepted: 'accept', edited: 'edit', false_positive: 'reject', pending: 'pending', code: 'code' }[d.status],
        final_text: ['false_positive','pending','code'].includes(d.status) ? null : d.edit,
        original_source: i.source, original_target: i.target,
        reviewer: d.reviewer ?? ($('reviewer').value.trim() || null), comment: d.comment ?? '', updated_at: d.updated_at };
    }), null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'decisions.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function resetFilters() {
    state.types.clear();
    document.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', 'false'));
    $('search').value = ''; $('severityFilter').value = ''; $('confidenceFilter').value = '';
    render();
  }

  function bind() {
    $('search').addEventListener('input', render);
    $('severityFilter').addEventListener('change', render);
    $('confidenceFilter').addEventListener('change', render);
    $('reviewMode').addEventListener('change', () =>
      document.querySelectorAll('.review').forEach((r) => (r.hidden = !$('reviewMode').checked)));
    $('resetFilters').addEventListener('click', resetFilters);
    $('exportBtn').addEventListener('click', exportDecisions);
    $('importBtn').addEventListener('click', () => $('importFile').click());
    $('importFile').addEventListener('change', async e => {
      const file = e.target.files[0]; if (!file) return;
      try {
        if (file.size > 10 * 1024 * 1024) throw Error('Файл больше 10 МБ');
        const result = prepareImport(JSON.parse(await file.text()), state.items, state.decisions);
        if (drafts.size || commentDrafts.size) throw Error('Сначала сохраните или сбросьте несохранённые правки и комментарии');
        Object.assign(state.decisions, result.decisions);
        saveDecisions(); render();
        $('status').textContent = `Загружено: ${result.added}; уже были: ${result.unchanged}.`;
      } catch (error) { $('status').textContent = 'Импорт отменён: ' + error.message; }
      finally { e.target.value = ''; }
    });
    $('cards').addEventListener('click', onCardClick);
    $('cards').addEventListener('input', e => {
      if (e.target.matches('textarea')) {
        const id = e.target.closest('.card').dataset.id;
        if (e.target.matches('.review-comment')) commentDrafts.set(id, e.target.value);
        else drafts.set(id, e.target.value);
      }
    });
  }

  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

// Import is atomic: any stale, invalid or conflicting row cancels the whole file.
function prepareImport(data, items, current) {
  const rows = Array.isArray(data) ? data : data?.decisions;
  if (!Array.isArray(rows)) throw Error('Ожидается массив решений');
  const statuses = {accept:'accepted',edit:'edited',reject:'false_positive',pending:'pending',code:'code'};
  const output = Object.create(null);
  let added=0, unchanged=0;
  const signature = d => JSON.stringify([d.status,d.edit,d.comment ?? '',d.reviewer ?? null]);
  for (const [index,row] of rows.entries()) {
    const fail = text => {throw Error(`Запись ${index+1}: ${text}`);};
    if (!row || typeof row !== 'object' || Array.isArray(row)) fail('не объект');
    if (typeof row.key !== 'string' || typeof row.issue_type !== 'string' || typeof row.original_source !== 'string' ||
        !Object.hasOwn(row,'original_target') || !(row.original_target === null || typeof row.original_target === 'string')) fail('нет исходных текстов или типа');
    if (!Object.hasOwn(statuses,row.decision)) fail('неизвестное решение');
    if (row.comment != null && typeof row.comment !== 'string') fail('неверный комментарий');
    if (row.reviewer != null && typeof row.reviewer !== 'string') fail('неверный проверяющий');
    if (row.updated_at != null && typeof row.updated_at !== 'string') fail('неверная дата');
    let item = items.find(i => i.id === row.id);
    const matches = i => i.key===row.key && i.issue_type===row.issue_type && i.source===row.original_source && i.target===row.original_target;
    if (item && !matches(item)) fail('ID относится к другому тексту');
    if (!item) {
      const candidates=items.filter(matches);
      if (candidates.length!==1) fail('устаревшая, неизвестная или неоднозначная находка');
      item=candidates[0];
    }
    const fixes=['accept','edit'].includes(row.decision);
    if (fixes) {
      if (typeof row.final_text !== 'string' || !row.final_text.trim()) fail('пустая правка');
      const error=validateMessage(item.source,row.final_text);if(error)fail(error);
    } else if (row.final_text != null) fail('решение без правки содержит текст');
    if (row.decision==='code' && item.issue_type!=='suffix_harmony') fail('обработка в коде допустима только для suffix_harmony');
    const d={id:item.id,key:item.key,status:statuses[row.decision],edit:fixes?row.final_text:null,
      comment:row.comment ?? '',reviewer:row.reviewer ?? null,updated_at:row.updated_at ?? null};
    const previous=output[item.id] || current[item.id];
    if(previous) {
      if(signature(previous)!==signature(d))fail('конфликт решений; существующее решение сохранено');
      unchanged++;continue;
    }
    output[item.id]=d;added++;
  }
  return {decisions:output,added,unchanged};
}

function parseMessage(text){
  let i=0; const names=new Set(), args=[];
  const ws=()=>{while(/\s/.test(text[i]||'')&&i<text.length)i++;};
  const expect=c=>{ws();if(text[i++]!==c)throw Error('Ожидалось '+c);};
  function word(){ws();const m=/^[^\s{},#=]+/.exec(text.slice(i));if(!m)throw Error('Нет имени');i+=m[0].length;return m[0];}
  function message(depth){
    if(depth>50)throw Error('Слишком глубокая вложенность');
    while(i<text.length){
      if(text[i]==='}'){if(!depth)throw Error('Лишняя скобка');return;}
      if(text[i]!=='{'){i++;continue;}
      i++;const name=word();names.add(name);ws();
      const arg={name,type:null,selectors:[],offset:null};args.push(arg);
      if(text[i]==='}'){i++;continue;}
      expect(',');arg.type=word();ws();
      if(['plural','select','selectordinal'].includes(arg.type)){
        expect(',');
        while(i<text.length){
          ws();if(text[i]==='}')break;
          if(text.slice(i).startsWith('offset:')){
            if(arg.type==='select'||arg.offset!==null||arg.selectors.length)throw Error('Неверный offset');
            i+=7;ws();const m=/^\d+(?=\s|\})/.exec(text.slice(i));if(!m)throw Error('Неверный offset');arg.offset=Number(m[0]);i+=m[0].length;continue;
          }
          const m=/^[^\s{}]+/.exec(text.slice(i));if(!m)throw Error('Нет селектора');
          const sel=m[0];i+=sel.length;
          if(arg.selectors.includes(sel))throw Error('Повтор селектора');
          if(arg.type!=='select'&&!/^(zero|one|two|few|many|other|=\d+)$/.test(sel))throw Error('Неверный селектор');
          arg.selectors.push(sel);expect('{');message(depth+1);expect('}');
        }
        if(!arg.selectors.includes('other'))throw Error('Нет формы other');expect('}');
      }else{
        if(!['number','date','time'].includes(arg.type))throw Error('Неизвестный тип ICU');
        if(text[i]===','){i++;while(i<text.length&&text[i]!=='}'){if(text[i]==='{')throw Error('Неверный формат');i++;}}
        expect('}');
      }
    }
    if(depth)throw Error('Не закрыта скобка');
  }
  message(0);
  for(const name of names){if(new Set(args.filter(a=>a.name===name&&a.type).map(a=>a.type)).size>1)throw Error('Конфликт типов');}
  return {names:[...names].sort(),args};
}
function validateMessage(source,target){
  try{
    const a=parseMessage(source),b=parseMessage(target);
    if(JSON.stringify(a.names)!==JSON.stringify(b.names))return 'Плейсхолдеры должны совпадать';
    for(const arg of a.args){
      if(!arg.type)continue;
      const required=arg.type==='select'?arg.selectors:arg.selectors.filter(s=>s.startsWith('='));
      if(!b.args.some(t=>t.name===arg.name&&t.type===arg.type&&t.offset===arg.offset&&required.every(s=>t.selectors.includes(s))))return 'Изменён тип ICU, селекторы или offset: '+arg.name;
    }
    return null;
  }catch(e){return 'Не удалось сохранить: '+e.message;}
}

function save() { saveDecisions(); }

  init();
})();
</script>
</body>
</html>
"""
