import { Engine, tokenize, stem } from './engine.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const INSTANT = params.has('instant');

const SUGGESTED = [
  'Can I get a refund on a yearly plan?',
  'My iPhone entries are not syncing',
  'How much does the Team plan cost?',
  'Who can approve timesheets?',
  'What are the API rate limits?',
  'Do you offer a lifetime licence?',
];

const state = {
  engine: null,
  docs: [],
  previous: null,      // { query, context } of the last answered question
  busy: false,
  vectorStatus: 'loading',
};

// ------------------------------------------------------------------ theme
function applyTheme(t) {
  if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}
try { applyTheme(localStorage.getItem('pb-theme')); } catch { /* storage unavailable */ }
$('theme-toggle').addEventListener('click', () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  const next = dark ? 'light' : 'dark';
  applyTheme(next);
  try { localStorage.setItem('pb-theme', next); } catch { /* ignore */ }
});

// ------------------------------------------------------------------ helpers
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Wraps the words of `text` whose stem is one of the query terms in <mark>. */
function markTerms(text, terms) {
  return esc(text).replace(/[A-Za-z0-9]+(?:\.[0-9]+)?/g, (w) => {
    const t = tokenize(w)[0];
    return t && terms.has(t) ? `<mark>${w}</mark>` : w;
  });
}

function setStatus(kind, text, short) {
  const el = $('status');
  el.className = `status ${kind}`;
  $('status-text').textContent = text;
  $('status-short').textContent = short;
}

function scrollMessages() {
  const m = $('messages');
  m.scrollTop = m.scrollHeight;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ loading
async function loadJson(path) {
  const res = await fetch(path, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

const ready = (async () => {
  const [kw, docs] = await Promise.all([loadJson('data/index-keyword.json'), loadJson('data/documents.json')]);
  state.engine = new Engine(kw);
  state.docs = docs;
  renderDocList();
  setStatus('partial', 'Keyword search ready', 'Keywords');
  $('send').disabled = false;
  // The meaning index loads after the page is usable; until then answers use keyword ranking.
  const vectorReady = (async () => {
    try {
      if (params.has('novector')) throw new Error('meaning index switched off for this test');
      const v = await loadJson('data/index-vector.json');
      state.engine.attachVectorIndex(v);
      state.vectorStatus = 'ready';
      setStatus('ready', 'Meaning and keyword search ready', 'Ready');
    } catch (err) {
      state.vectorStatus = 'failed';
      setStatus('partial', 'Keyword search only', 'Keywords only');
      console.info('Meaning index not loaded; answering with keyword ranking.', err.message);
    }
  })();
  return { vectorReady };
})().catch((err) => {
  setStatus('error', 'Could not load the documents', 'Error');
  console.error(err);
  throw err;
});

// ------------------------------------------------------------------ documents panel
function renderDocList(filter = '') {
  const list = $('doc-list');
  const f = filter.trim().toLowerCase();
  const groups = new Map();
  for (const d of state.docs) {
    if (f && !(`${d.title} ${d.category}`.toLowerCase().includes(f))) continue;
    if (!groups.has(d.category)) groups.set(d.category, []);
    groups.get(d.category).push(d);
  }
  const order = ['Getting started', 'Product guide', 'Plans and billing', 'Policies', 'Troubleshooting', 'Developers', 'Release notes'];
  const cats = [...groups.keys()].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  list.innerHTML = cats.map((c) => `<div class="doc-group">${esc(c)}</div>` + groups.get(c)
    .sort((a, b) => a.title.localeCompare(b.title))
    .map((d) => `<button class="doc-item" data-doc="${esc(d.id)}">${esc(d.title)}</button>`).join('')).join('')
    || '<p class="doc-group">No matching documents</p>';
  $('doc-count').textContent = `(${state.docs.length})`;
}
$('doc-filter').addEventListener('input', (e) => renderDocList(e.target.value));
$('doc-list').addEventListener('click', (e) => {
  const b = e.target.closest('.doc-item');
  if (!b) return;
  openDocument(b.dataset.doc, null, new Set());
  closeSidebar();
});

function openSidebar() { $('sidebar').classList.add('open'); $('scrim').hidden = false; $('docs-toggle').setAttribute('aria-expanded', 'true'); }
function closeSidebar() { $('sidebar').classList.remove('open'); if ($('reader').hidden) $('scrim').hidden = true; $('docs-toggle').setAttribute('aria-expanded', 'false'); }
$('docs-toggle').addEventListener('click', () => ($('sidebar').classList.contains('open') ? closeSidebar() : openSidebar()));
$('scrim').addEventListener('click', () => { closeSidebar(); closeReader(); });

// ------------------------------------------------------------------ reader
function showReader() {
  $('reader').hidden = false;
  document.querySelector('.app').classList.add('reading');
  if (matchMedia('(max-width: 760px)').matches) $('scrim').hidden = false;
}
function closeReader() {
  $('reader').hidden = true;
  document.querySelector('.app').classList.remove('reading');
  document.querySelectorAll('.cite.active').forEach((c) => c.classList.remove('active'));
  document.querySelectorAll('.doc-item.active').forEach((c) => c.classList.remove('active'));
  if (!$('sidebar').classList.contains('open')) $('scrim').hidden = true;
}
$('reader-close').addEventListener('click', closeReader);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeReader(); closeSidebar(); } });

/** Shows one cited passage, with the sentences used in the answer and the query words highlighted. */
function openCitation(cite, terms) {
  const c = cite.chunk;
  $('reader-eyebrow').textContent = `Source [${cite.n}] · ${c.category}`;
  $('reader-title').textContent = c.docTitle;
  const used = new Set(cite.sentences);
  const body = c.sentences.map((s, i) => (used.has(i) ? `<span class="hl">${markTerms(s, terms)}</span>` : markTerms(s, terms))).join(' ');
  $('reader-body').innerHTML = `
    <div class="passage focus" data-passage="${esc(c.id)}">
      <p class="heading">${esc(c.heading)}</p>
      <p>${body}</p>
    </div>
    <p class="legend"><span class="hl">Highlighted</span> sentences are the ones used in the answer; <mark>marked</mark> words match your question.</p>
    <div class="reader-actions"><button class="text-btn" id="open-full" type="button">Show the whole document</button></div>`;
  $('open-full').addEventListener('click', () => openDocument(c.doc, c.section, terms, used));
  showReader();
  $('reader-body').scrollTop = 0;
}

/** Shows a whole document; when a section is given it is outlined and scrolled into view. */
function openDocument(docId, sectionSlug, terms, usedSentences = new Set()) {
  const d = state.docs.find((x) => x.id === docId);
  if (!d) return;
  document.querySelectorAll('.doc-item').forEach((b) => b.classList.toggle('active', b.dataset.doc === docId));
  $('reader-eyebrow').textContent = `${d.category} · updated ${d.updated}`;
  $('reader-title').textContent = d.title;
  $('reader-body').innerHTML = d.sections.map((s) => {
    const focus = s.slug === sectionSlug;
    const paras = s.text.split(/\n\n+/).map((p) => `<p>${terms.size ? markTerms(p, terms) : esc(p)}</p>`).join('');
    return `<section class="${focus ? 'passage focus' : ''}" id="sec-${esc(s.slug)}"><h3>${esc(s.heading)}</h3>${paras}</section>`;
  }).join('');
  showReader();
  const target = sectionSlug && document.getElementById(`sec-${sectionSlug}`);
  if (target) target.scrollIntoView({ block: 'start' });
  else $('reader-body').scrollTop = 0;
}

// ------------------------------------------------------------------ chat
function addUser(text) {
  $('welcome')?.remove();
  const el = document.createElement('div');
  el.className = 'msg user';
  el.innerHTML = `<div class="bubble">${esc(text)}</div>`;
  $('messages').append(el);
  scrollMessages();
}

function modeLabel(m) {
  return m === 'keyword' ? 'keywords' : m === 'vector' ? 'meaning' : 'meaning and keywords';
}

/** Runs one question end to end and returns what was shown (also used by the automated checks). */
async function ask(text) {
  const query = text.trim();
  if (!query || state.busy) return null;
  await ready;
  state.busy = true;
  $('send').disabled = true;
  addUser(query);
  const engine = state.engine;
  const mode = $('mode').value;
  const followUp = state.previous && engine.isFollowUp(query, state.previous.query);
  const context = followUp ? [state.previous.query, state.previous.context].filter(Boolean).join(' ') : null;
  const search = engine.search(query, { mode, context });
  const answer = engine.answer(search);

  const el = document.createElement('div');
  el.className = 'msg bot';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  el.append(bubble);
  $('messages').append(el);

  if (answer.refused) {
    const nearby = [...new Map(search.results.map((r) => [r.chunk.doc, r.chunk])).values()].slice(0, 2);
    bubble.innerHTML = `
      <div class="refusal"><strong>Not found in the documents.</strong> I could not find an answer to this in the Pellbrook Hours documents, so I will not guess. Try other words, or browse the documents list.</div>
      ${search.results.length && search.terms.size ? `<p class="nearby">Closest topics I checked: ${nearby.map((c) => `<button type="button" data-doc="${esc(c.doc)}" data-sec="${esc(c.section)}">${esc(c.docTitle)}</button>`).join(', ')}</p>` : ''}
      <p class="meta-line">Searched by ${modeLabel(search.usedMode)} · match ${(search.confidence * 100).toFixed(0)}%, below the ${(search.threshold * 100).toFixed(0)}% needed to answer</p>`;
    bubble.querySelectorAll('.nearby button').forEach((b) => b.addEventListener('click', () => openDocument(b.dataset.doc, b.dataset.sec, search.terms)));
    state.previous = null;
  } else {
    const ctxNote = followUp ? `<p class="followup-note">Read as a follow-up to: “${esc(state.previous.query)}”</p>` : '';
    bubble.innerHTML = `${ctxNote}<div class="answer"></div>`;
    const box = bubble.querySelector('.answer');
    const p = document.createElement('p');
    box.append(p);
    for (const s of answer.sentences) {
      const span = document.createElement('span');
      p.append(span, ' ');
      if (INSTANT) span.textContent = s.text;
      else {
        span.classList.add('typing');
        const words = s.text.split(' ');
        for (let i = 0; i < words.length; i++) {
          span.textContent = words.slice(0, i + 1).join(' ');
          if (i % 2 === 1) { scrollMessages(); await sleep(28); }
        }
        span.classList.remove('typing');
      }
      for (const n of s.cites) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'cite';
        b.textContent = n;
        b.dataset.cite = n;
        b.title = `Open source ${n}`;
        span.append(b);
      }
    }
    const src = document.createElement('div');
    src.className = 'sources';
    src.innerHTML = `<h3>Sources</h3>` + answer.citations.map((c) => `
      <button class="source" type="button" data-cite="${c.n}"><span class="num">[${c.n}]</span>
      <span><span class="src-title">${esc(c.chunk.docTitle)}</span> <span class="src-path">› ${esc(c.chunk.heading)}</span></span></button>`).join('')
      + `<p class="meta-line">Searched by ${modeLabel(search.usedMode)}${search.usedMode !== mode ? (state.vectorStatus === 'failed' ? ' (meaning index not available)' : ' (meaning index still loading)') : ''} · match ${(search.confidence * 100).toFixed(0)}%</p>`;
    bubble.append(src);
    bubble.addEventListener('click', (e) => {
      const b = e.target.closest('[data-cite]');
      if (!b) return;
      const cite = answer.citations.find((c) => c.n === Number(b.dataset.cite));
      document.querySelectorAll('.cite.active').forEach((x) => x.classList.remove('active'));
      bubble.querySelectorAll(`.cite[data-cite="${cite.n}"]`).forEach((x) => x.classList.add('active'));
      openCitation(cite, search.terms);
    });
    state.previous = { query, context };
  }
  scrollMessages();
  state.busy = false;
  $('send').disabled = false;
  return { query, followUp: !!followUp, search, answer };
}

$('composer').addEventListener('submit', (e) => {
  e.preventDefault();
  const q = $('question').value;
  $('question').value = '';
  ask(q);
});
$('new-chat').addEventListener('click', () => {
  state.previous = null;
  closeReader();
  $('messages').innerHTML = '<div class="welcome" id="welcome"><h2>How can I help?</h2><p>Ask a question in your own words. Every answer shows where it comes from.</p><div class="suggestions" id="suggestions"></div></div>';
  renderSuggestions();
});
function renderSuggestions() {
  $('suggestions').innerHTML = SUGGESTED.map((q) => `<button class="chip" type="button">${esc(q)}</button>`).join('');
  $('suggestions').querySelectorAll('.chip').forEach((b) => b.addEventListener('click', () => ask(b.textContent)));
}
renderSuggestions();
$('send').disabled = true;

// Hook for the automated test run: the evaluation drives this same engine in the browser.
window.__docsAssistant = {
  ready: ready.then((r) => r.vectorReady),
  get engine() { return state.engine; },
  get vectorStatus() { return state.vectorStatus; },
  ask,
  stem,
};
