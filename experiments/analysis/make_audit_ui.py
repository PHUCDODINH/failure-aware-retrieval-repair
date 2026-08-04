"""Generate a self-contained HTML annotation UI for the blind relevance audit.

Embeds experiments/manual_audit_blind_worksheet.json into a single HTML page.
The annotator picks an ID (ann1/ann2), judges each candidate Relevant/Not,
progress autosaves to localStorage, and Export downloads worksheet_<id>.json
in exactly the format score_blind_audit.py expects.

Run: python experiments/analysis/make_audit_ui.py
Then open experiments/audit_annotation_ui.html in a browser.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSHEET = ROOT / "experiments" / "manual_audit_blind_worksheet.json"
OUT = ROOT / "experiments" / "audit_annotation_ui.html"

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Blind Relevance Audit</title>
<style>
  :root { --bg:#fff; --fg:#1a1a1a; --muted:#666; --card:#f6f7f9; --border:#d8dce1;
          --accent:#2563eb; --yes:#16803c; --no:#b91c1c; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#111417; --fg:#e6e6e6; --muted:#9aa4af; --card:#1b2026;
            --border:#333a42; --accent:#60a5fa; --yes:#4ade80; --no:#f87171; }
  }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 -apple-system,system-ui,sans-serif; background:var(--bg); color:var(--fg); }
  header { position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--border);
           padding:10px 20px; display:flex; align-items:center; gap:16px; z-index:5; flex-wrap:wrap; }
  header h1 { font-size:16px; margin:0; }
  .progress { color:var(--muted); font-size:13px; }
  main { max-width:1100px; margin:0 auto; padding:20px; }
  .instructions { background:var(--card); border:1px solid var(--border); border-radius:8px;
                  padding:12px 16px; font-size:13.5px; color:var(--muted); margin-bottom:16px; }
  .target { border:2px solid var(--accent); border-radius:8px; padding:14px 16px; margin-bottom:18px; }
  .target h2 { margin:0 0 8px; font-size:15px; }
  pre { background:var(--card); border:1px solid var(--border); border-radius:6px; padding:10px;
        overflow-x:auto; font-size:12.5px; line-height:1.45; white-space:pre; margin:6px 0; }
  .sig { color:var(--no); }
  .cand { border:1px solid var(--border); border-radius:8px; padding:12px 16px; margin-bottom:14px; }
  .cand.judged-1 { border-color:var(--yes); }
  .cand.judged-0 { border-color:var(--no); }
  .cand h3 { margin:0 0 6px; font-size:14px; display:flex; align-items:center; gap:10px; }
  .pair { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  @media (max-width:800px) { .pair { grid-template-columns:1fr; } }
  .pair .lbl { font-size:12px; color:var(--muted); margin-bottom:2px; }
  .btns { margin-top:8px; display:flex; gap:8px; }
  button { font:inherit; padding:6px 14px; border-radius:6px; border:1px solid var(--border);
           background:var(--card); color:var(--fg); cursor:pointer; }
  button.sel-1 { background:var(--yes); color:#fff; border-color:var(--yes); }
  button.sel-0 { background:var(--no); color:#fff; border-color:var(--no); }
  nav { display:flex; gap:10px; margin:20px 0; align-items:center; flex-wrap:wrap; }
  nav .spacer { flex:1; }
  .taskmap { display:flex; gap:4px; flex-wrap:wrap; }
  .taskmap a { width:22px; height:22px; border-radius:4px; border:1px solid var(--border);
               display:flex; align-items:center; justify-content:center; font-size:11px;
               text-decoration:none; color:var(--fg); cursor:pointer; }
  .taskmap a.done { background:var(--yes); color:#fff; border-color:var(--yes); }
  .taskmap a.cur { outline:2px solid var(--accent); }
  select, .export { font:inherit; padding:5px 8px; border-radius:6px; border:1px solid var(--border);
                    background:var(--card); color:var(--fg); }
  .export:disabled { opacity:.5; cursor:not-allowed; }
</style>
</head>
<body>
<header>
  <h1>Blind relevance audit</h1>
  <label>Annotator:
    <select id="annot">
      <option value="">— choose —</option>
      <option value="ann1">ann1</option>
      <option value="ann2">ann2</option>
    </select>
  </label>
  <span class="progress" id="prog"></span>
  <button class="export" id="exportBtn" disabled>Export JSON</button>
</header>
<main>
  <div class="instructions">
    For each candidate (A–D), mark <b>Relevant</b> if its buggy&rarr;fixed change would
    plausibly guide fixing the <b>target bug</b>, else <b>Not relevant</b>. Judge the repair
    <i>pattern</i>, not surface similarity. Do not open the key file. Progress autosaves
    in this browser; use Export when all 80 judgments are done.
  </div>
  <div id="app"></div>
  <nav>
    <button id="prev">&larr; Prev</button>
    <button id="next">Next &rarr;</button>
    <span class="spacer"></span>
    <div class="taskmap" id="map"></div>
  </nav>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const WS = JSON.parse(document.getElementById('data').textContent);
const TASKS = WS.tasks, LABELS = ['A','B','C','D'];
let cur = 0, annot = localStorage.getItem('audit_annot') || '';

const store = () => 'audit_judgments_' + annot;
function loadJ() { try { return JSON.parse(localStorage.getItem(store())) || {}; } catch(e) { return {}; } }
function saveJ(j) { localStorage.setItem(store(), JSON.stringify(j)); }

const annotSel = document.getElementById('annot');
annotSel.value = annot;
annotSel.onchange = () => { annot = annotSel.value; localStorage.setItem('audit_annot', annot); render(); };

function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
function key(i,l) { return TASKS[i].problem + '|' + l; }

function count(j) { let n=0; for (let i=0;i<TASKS.length;i++) for (const l of LABELS) if (key(i,l) in j) n++; return n; }
function taskDone(j,i) { return LABELS.every(l => key(i,l) in j); }

function render() {
  const app = document.getElementById('app');
  if (!annot) { app.innerHTML = '<p>Select your annotator ID above to begin. Each annotator must judge independently — no discussion until both exports are done.</p>'; update(); return; }
  const t = TASKS[cur], j = loadJ();
  let h = `<div class="target"><h2>Task ${cur+1}/${TASKS.length} — target bug: <code>${esc(t.problem)}</code> (${t.benchmark})</h2>
    <div class="lbl">Buggy code (focused diff region):</div><pre>${esc(t.target_buggy_snippet)}</pre>
    <div class="lbl">Failure signal:</div><pre class="sig">${esc(t.target_failure_signal || '(none)')}</pre></div>`;
  for (const l of LABELS) {
    const c = t.candidates[l], v = j[key(cur,l)];
    h += `<div class="cand ${v===1?'judged-1':v===0?'judged-0':''}" id="cand${l}">
      <h3>Candidate ${l}</h3>
      <div class="pair">
        <div><div class="lbl">buggy</div><pre>${esc(c.buggy_snippet || '(empty)')}</pre></div>
        <div><div class="lbl">fixed</div><pre>${esc(c.fixed_snippet || '(empty)')}</pre></div>
      </div>
      <div class="btns">
        <button class="${v===1?'sel-1':''}" onclick="judge('${l}',1)">Relevant (1)</button>
        <button class="${v===0?'sel-0':''}" onclick="judge('${l}',0)">Not relevant (0)</button>
      </div></div>`;
  }
  app.innerHTML = h;
  update();
}

function judge(l, v) {
  const j = loadJ(); j[key(cur,l)] = v; saveJ(j);
  const t = TASKS[cur];
  if (taskDone(j,cur) && cur < TASKS.length-1) setTimeout(() => { cur++; render(); window.scrollTo(0,0); }, 250);
  else render();
}

function update() {
  const j = annot ? loadJ() : {};
  const n = annot ? count(j) : 0, total = TASKS.length*4;
  document.getElementById('prog').textContent = annot ? `${annot}: ${n}/${total} judgments` : '';
  document.getElementById('exportBtn').disabled = !annot || n < total;
  const map = document.getElementById('map');
  map.innerHTML = TASKS.map((t,i) =>
    `<a class="${annot && taskDone(j,i)?'done':''} ${i===cur?'cur':''}" onclick="cur=${i};render();window.scrollTo(0,0)">${i+1}</a>`).join('');
}

document.getElementById('prev').onclick = () => { if (cur>0) { cur--; render(); window.scrollTo(0,0); } };
document.getElementById('next').onclick = () => { if (cur<TASKS.length-1) { cur++; render(); window.scrollTo(0,0); } };

document.getElementById('exportBtn').onclick = () => {
  const j = loadJ();
  const out = JSON.parse(JSON.stringify(WS));
  out.tasks.forEach((t,i) => { for (const l of LABELS) t.candidates[l].relevant = j[key(i,l)] ?? null; });
  out._annotator = annot;
  const blob = new Blob([JSON.stringify(out, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'worksheet_' + annot + '.json';
  a.click();
};

render();
</script>
</body>
</html>
"""


def main():
    ws = json.loads(WORKSHEET.read_text())
    # embed safely inside a <script type="application/json"> block
    data = json.dumps(ws).replace("</", "<\\/")
    OUT.write_text(TEMPLATE.replace("__DATA__", data))
    n = len(ws["tasks"])
    print(f"UI with {n} tasks ({n*4} judgments) -> {OUT}")


if __name__ == "__main__":
    main()
