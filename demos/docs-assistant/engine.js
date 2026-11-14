// Docs assistant retrieval engine.
// One file, used by the build script (Node) and by the page (browser), so the
// index is built and queried with exactly the same text processing.
//
// Keyword side: BM25 over chunks (document title + section heading + text).
// Meaning side: latent semantic analysis (LSA). At build time a truncated SVD of
// the chunk-term TF-IDF matrix gives a k-dimensional space; a chunk is its
// projection A·V_k, and a query is projected the same way (q·V_k) in the browser.
// Hybrid: weighted sum of the two scores, each scaled by its best value for the query.
// Answers are extractive: sentences taken from the top passages, each with its citation.

export const DEFAULT_PARAMS = {
  k1: 1.2,
  b: 0.75,
  alpha: 0.5,          // hybrid weight of the keyword score (1 - alpha for the meaning score)
  refuseKeyword: 0.35,  // keyword mode: refuse when the top passage covers less of the query than this
  refuseVector: 0.35,  // meaning mode: refuse when the top cosine is below this
  refuseHybrid: 0.31,  // hybrid mode: refuse when the combined confidence is below this
  answerRelative: 0.6,  // passages used for the answer must score at least this share of the top passage
  followUpWeight: 0.6,  // weight of the previous question's terms in a follow-up
};

const STOP = new Set((
  'a an and are as at be been being but by can could did do does doing done for from had has have having he her ' +
  'here hers him his how i if in into is it its itself just me more most my no nor not of off on once only or ' +
  'other our ours out over own same she should so some such than that the their theirs them then there these they ' +
  'this those through to too under until up very was we were what when where which while who whom why will with ' +
  'would you your yours yourself about after again against all am any because before below between both down during ' +
  'each few further let lets need needs want wants get gets got also may might must shall s t much many please tell ' +
  'know way ways thing things anything something use using used one ones us able happen happens hey hi hello ' +
  'cannot cant dont doesnt didnt isnt arent wasnt wont im ive id youre whats thats theres hows'
).split(/\s+/));

const FOLLOW_UP_RE = /^(and|also|what about|how about|then|so)\b|\b(it|its|that|this|they|them|those|these|there|same|one)\b/i;

/** Light suffix stemmer: enough to join plan/plans, refund/refunded/refunds, integrate/integration. */
export function stem(w) {
  if (w.length <= 3 || /^\d/.test(w)) return w;
  if (w.endsWith('ies') && w.length > 4) w = w.slice(0, -3) + 'y';
  else if (w.endsWith('sses')) w = w.slice(0, -2);
  else if (w.endsWith('s') && !/(ss|us|is)$/.test(w)) w = w.slice(0, -1);
  const rules = [
    ['ational', 'ate'], ['ization', 'ize'], ['isation', 'ize'], ['ation', 'ate'], ['ition', 'ite'],
    ['ments', ''], ['ment', ''], ['ingly', ''], ['ing', ''], ['edly', ''], ['ed', ''], ['ly', ''],
    ['ness', ''], ['ful', ''], ['ible', ''], ['able', ''],
  ];
  for (const [suf, rep] of rules) {
    if (w.endsWith(suf) && w.length - suf.length >= 3) {
      w = w.slice(0, -suf.length) + rep;
      if ((suf === 'ing' || suf === 'ed') && /([b-df-hj-np-tv-z])\1$/.test(w) && !/(ll|ss|zz)$/.test(w)) w = w.slice(0, -1);
      break;
    }
  }
  if (w.endsWith('e') && w.length > 4) w = w.slice(0, -1);
  if (w.endsWith('ll') && w.length >= 6) w = w.slice(0, -1); // cancelling, cancelled -> cancel
  if (w.endsWith('y') && w.length > 4) w = w.slice(0, -1) + 'i';
  return w;
}

/** Text -> list of stemmed content terms (stop words removed). */
export function tokenize(text) {
  const out = [];
  const words = String(text).toLowerCase().replace(/[’']/g, '').match(/[a-z0-9]+(?:\.[0-9]+)?/g) || [];
  for (const w of words) {
    if (STOP.has(w)) continue;
    if (w.length === 1 && !/\d/.test(w)) continue;
    out.push(stem(w));
  }
  return out;
}

export function slugify(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

export function splitSentences(text) {
  return String(text).replace(/\s+/g, ' ').trim().split(/(?<=[.!?])\s+(?=[A-Z0-9])/).filter(Boolean);
}

// ---------------------------------------------------------------- index helpers

function decodeF32(b64) {
  let bytes;
  if (typeof atob === 'function') {
    const bin = atob(b64);
    bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  } else {
    bytes = new Uint8Array(Buffer.from(b64, 'base64'));
  }
  return new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
}

/** Wraps the shipped keyword index (and the meaning index once it is loaded). */
export class Engine {
  constructor(keywordIndex, params = {}) {
    this.kw = keywordIndex;
    this.params = { ...DEFAULT_PARAMS, ...params };
    this.chunks = keywordIndex.chunks;
    this.N = this.chunks.length;
    this.idf = {};
    for (const [t, df] of Object.entries(keywordIndex.bm25.df)) {
      this.idf[t] = Math.log(1 + (this.N - df + 0.5) / (df + 0.5));
    }
    this.maxIdf = Math.log(1 + (this.N + 0.5) / 0.5); // a term that appears nowhere
    this.vec = null;
  }

  attachVectorIndex(v) {
    const termVecs = decodeF32(v.termVecs);
    const chunkVecs = decodeF32(v.chunkVecs);
    const termRow = new Map(v.vocab.map((t, i) => [t, i]));
    const chunkNorm = new Float32Array(this.N);
    for (let i = 0; i < this.N; i++) {
      let s = 0;
      for (let d = 0; d < v.k; d++) s += chunkVecs[i * v.k + d] ** 2;
      chunkNorm[i] = Math.sqrt(s) || 1;
    }
    this.vec = { k: v.k, termVecs, chunkVecs, termRow, chunkNorm, idf: v.idf };
  }

  get vectorReady() { return this.vec !== null; }

  /** Query terms with weights; a follow-up adds the previous question's terms at a lower weight. */
  queryTerms(query, context) {
    const w = new Map();
    // "how much" is a price question, but both words are stop words: keep its meaning.
    const q = /how much/i.test(query) ? `${query} cost price` : query;
    for (const t of tokenize(q)) w.set(t, (w.get(t) || 0) + 1);
    if (context) {
      for (const t of tokenize(context)) {
        if (!w.has(t)) w.set(t, this.params.followUpWeight);
      }
    }
    return w;
  }

  bm25Scores(terms) {
    const { k1, b } = this.params;
    const { tf, len, avgdl } = this.kw.bm25;
    const scores = new Float64Array(this.N);
    for (const [t, qw] of terms) {
      const idf = this.idf[t];
      if (idf === undefined) continue;
      for (let i = 0; i < this.N; i++) {
        const f = tf[i][t];
        if (!f) continue;
        scores[i] += qw * idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * len[i] / avgdl));
      }
    }
    return scores;
  }

  /** Projects the query into the meaning space and returns the cosine with every chunk. */
  vectorScores(terms) {
    const V = this.vec;
    const scores = new Float64Array(this.N);
    if (!V) return scores;
    const q = new Float64Array(V.k);
    let any = false;
    for (const [t, qw] of terms) {
      const row = V.termRow.get(t);
      if (row === undefined) continue;
      any = true;
      const wgt = qw * V.idf[row];
      for (let d = 0; d < V.k; d++) q[d] += wgt * V.termVecs[row * V.k + d];
    }
    if (!any) return scores;
    let qn = 0;
    for (let d = 0; d < V.k; d++) qn += q[d] * q[d];
    qn = Math.sqrt(qn) || 1;
    for (let i = 0; i < this.N; i++) {
      let s = 0;
      for (let d = 0; d < V.k; d++) s += q[d] * V.chunkVecs[i * V.k + d];
      scores[i] = s / (qn * V.chunkNorm[i]);
    }
    return scores;
  }

  /** Share of the query (by term weight x idf) made of words the document set contains at all. */
  knownShare(terms) {
    let have = 0, total = 0;
    for (const [t, qw] of terms) {
      const idf = (this.idf[t] ?? this.maxIdf) * qw;
      total += idf;
      if (this.idf[t] !== undefined) have += idf;
    }
    return total ? have / total : 0;
  }

  /** Share of the query (by term weight x idf) that appears in a chunk. */
  coverage(terms, chunkIndex) {
    const tf = this.kw.bm25.tf[chunkIndex];
    let have = 0, total = 0;
    for (const [t, qw] of terms) {
      const idf = (this.idf[t] ?? this.maxIdf) * qw;
      total += idf;
      if (tf[t]) have += idf;
    }
    return total ? have / total : 0;
  }

  /**
   * Ranked search. mode: 'keyword' | 'vector' | 'hybrid'. If the meaning index is not loaded,
   * 'vector' and 'hybrid' fall back to keyword ranking and say so in `usedMode`.
   */
  search(query, { mode = 'hybrid', context = null, topK = 5 } = {}) {
    const terms = this.queryTerms(query, context);
    let usedMode = mode;
    if (mode !== 'keyword' && !this.vec) usedMode = 'keyword';
    const kw = this.bm25Scores(terms);
    const vs = usedMode === 'keyword' ? null : this.vectorScores(terms);
    const kwMax = Math.max(1e-9, ...kw);
    const vsMax = vs ? Math.max(1e-9, ...vs) : 1;
    const combined = new Float64Array(this.N);
    for (let i = 0; i < this.N; i++) {
      if (usedMode === 'keyword') combined[i] = kw[i];
      else if (usedMode === 'vector') combined[i] = vs[i];
      else combined[i] = this.params.alpha * (kw[i] / kwMax) + (1 - this.params.alpha) * Math.max(0, vs[i]) / vsMax;
    }
    const order = Array.from(combined.keys()).sort((a, b) => combined[b] - combined[a] || a - b);
    const results = order.slice(0, topK).map((i) => ({
      index: i,
      chunk: this.chunks[i],
      score: combined[i],
      keyword: kw[i],
      vector: vs ? vs[i] : null,
      coverage: this.coverage(terms, i),
    }));
    const top = results[0];
    const knownTerms = [...terms.keys()].filter((t) => this.idf[t] !== undefined);
    // The meaning side only sees words it knows; a query made mostly of unknown words
    // (a product we do not mention, say) must not look confident because of one known word.
    const known = this.knownShare(terms);
    let confidence;
    let threshold;
    if (usedMode === 'keyword') {
      confidence = top && top.keyword > 0 ? top.coverage : 0;
      threshold = this.params.refuseKeyword;
    } else if (usedMode === 'vector') {
      confidence = top ? Math.max(0, top.vector) * known : 0;
      threshold = this.params.refuseVector;
    } else {
      confidence = top ? 0.5 * top.coverage + 0.5 * Math.max(0, top.vector) * known : 0;
      threshold = this.params.refuseHybrid;
    }
    const refused = !top || knownTerms.length === 0 || confidence < threshold;
    return { query, terms, usedMode, results, confidence, threshold, refused };
  }

  /** Detects a follow-up question that leans on the previous turn. */
  isFollowUp(query, previousQuery) {
    if (!previousQuery) return false;
    const n = tokenize(query).length;
    return FOLLOW_UP_RE.test(query.trim()) || n <= 1;
  }

  /**
   * Builds an extractive answer from the top passages: sentences are copied from the
   * documents as written and each carries the number of the passage it came from.
   */
  answer(search) {
    if (search.refused) return { refused: true, sentences: [], citations: [] };
    const terms = search.terms;
    const top = search.results[0];
    const used = search.results.filter((r, i) => i === 0 || (r.score >= this.params.answerRelative * top.score)).slice(0, 3);
    const candidates = [];
    used.forEach((r, rank) => {
      r.chunk.sentences.forEach((s, si) => {
        const toks = new Set(tokenize(s));
        let have = 0, total = 0;
        for (const [t, qw] of terms) {
          const idf = (this.idf[t] ?? this.maxIdf) * qw;
          total += idf;
          if (toks.has(t)) have += idf;
        }
        // Sentence score: share of the question it covers, scaled by how well its passage ranked.
        const rel = top.score > 0 ? r.score / top.score : 0;
        const score = (total ? have / total : 0) * (0.5 + 0.5 * rel) + (rank === 0 ? 0.05 : 0) - si * 0.01;
        candidates.push({ rank, si, text: s, score, chunk: r.chunk });
      });
    });
    candidates.sort((a, b) => b.score - a.score);
    const best = candidates.find((c) => c.rank === 0) || candidates[0];
    const chosen = [best];
    for (const c of candidates) {
      if (chosen.length >= 3) break;
      if (chosen.includes(c) || c.score < Math.max(0.3, 0.75 * best.score)) continue;
      if (chosen.filter((x) => x.rank === c.rank).length >= 2) continue;
      chosen.push(c);
    }
    // Citation numbers follow passage rank; identical sentences from two passages share one line.
    const citations = [];
    const citeFor = (chunk) => {
      let c = citations.find((x) => x.chunk.id === chunk.id);
      if (!c) { c = { n: citations.length + 1, chunk, sentences: [] }; citations.push(c); }
      return c;
    };
    chosen.sort((a, b) => a.rank - b.rank || a.si - b.si);
    const sentences = [];
    for (const c of chosen) {
      const cite = citeFor(c.chunk);
      cite.sentences.push(c.si);
      const twin = sentences.find((s) => s.text === c.text);
      if (twin) { twin.cites.push(cite.n); continue; }
      sentences.push({ text: c.text, cites: [cite.n] });
    }
    // A passage whose text matches the top one sentence for sentence (for example the
    // iPhone and Android sync pages) is listed as a further source.
    for (const r of used) {
      if (!citations.some((c) => c.chunk.id === r.chunk.id)) {
        const shared = sentences.filter((s) => r.chunk.sentences.includes(s.text));
        if (shared.length) {
          const cite = citeFor(r.chunk);
          for (const s of shared) { s.cites.push(cite.n); cite.sentences.push(r.chunk.sentences.indexOf(s.text)); }
        }
      }
    }
    return { refused: false, sentences, citations };
  }
}

// ---------------------------------------------------------------- build side (Node only)

/** Parses one markdown document with a small front-matter block. */
export function parseDocument(raw) {
  const m = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!m) throw new Error('missing front matter');
  const meta = {};
  for (const line of m[1].split('\n')) {
    const i = line.indexOf(':');
    if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  const sections = [];
  let current = null;
  for (const line of m[2].split('\n')) {
    if (line.startsWith('# ')) continue;
    if (line.startsWith('## ')) {
      current = { heading: line.slice(3).trim(), body: [] };
      sections.push(current);
    } else {
      if (!current) { current = { heading: 'Overview', body: [] }; sections.push(current); }
      current.body.push(line);
    }
  }
  return {
    ...meta,
    sections: sections
      .map((s) => ({ heading: s.heading, slug: slugify(s.heading), text: s.body.join('\n').replace(/\n{2,}/g, '\n\n').trim() }))
      .filter((s) => s.text),
  };
}

/** Chunks a section: whole if short, else windows of sentences with one sentence of overlap. */
export function chunkSection(doc, section, maxWords = 120) {
  const sentences = splitSentences(section.text);
  const words = (s) => s.split(/\s+/).length;
  const total = sentences.reduce((n, s) => n + words(s), 0);
  const groups = [];
  if (total <= maxWords) groups.push(sentences);
  else {
    let cur = [];
    let n = 0;
    for (const s of sentences) {
      if (n + words(s) > maxWords && cur.length) {
        groups.push(cur);
        cur = [cur[cur.length - 1]];
        n = words(cur[0]);
      }
      cur.push(s);
      n += words(s);
    }
    if (cur.length) groups.push(cur);
  }
  return groups.map((g, i) => ({
    id: `${doc.id}#${section.slug}${groups.length > 1 ? '-' + (i + 1) : ''}`,
    doc: doc.id,
    docTitle: doc.title,
    category: doc.category,
    section: section.slug,
    heading: section.heading,
    sentences: g,
    text: g.join(' '),
  }));
}

/** Text that is indexed for a chunk: the headings are kept as context. */
export function indexText(chunk) {
  // The section heading is repeated once so that it weighs a little more than body text.
  return `${chunk.docTitle}. ${chunk.heading}. ${chunk.heading}. ${chunk.text}`;
}
