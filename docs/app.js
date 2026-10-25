/* Co-Register demo page: the negotiation as a short show.
 *
 * presets.json holds recorded runs of the real engine, so the page works at once; then the engine
 * itself loads into Pyodide (Python in WebAssembly) so every change, and every "no" the visitor
 * gives, re-runs the real negotiation in the browser. Nothing on this page makes a decision: it
 * only plays back what webapi.run() returns.
 *
 * The run's timeline becomes a list of "beats". The screen for beat i is always rebuilt from
 * beats 0..i (see world()), so Step, Skip and resuming after a re-run all land in the same state.
 */
(function () {
  'use strict';

  const $ = (sel, el) => (el || document).querySelector(sel);
  const $$ = (sel, el) => [...(el || document).querySelectorAll(sel)];
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
  const DAY_NAMES = { Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday', Thu: 'Thursday', Fri: 'Friday' };
  const START = 8 * 60, END = 21 * 60;
  const DEFAULTS = { ben_friday_priority: 1, maya_max_days: 3, ana_no_early: true, seats_left: 2, priya_willing: true, say_no_first: [], answers: [] };
  const COLOR = { ana: 'var(--ana)', ben: 'var(--ben)', maya: 'var(--maya)' };
  const PYODIDE_BASE = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';
  const STEPS = [
    { key: 'share', label: 'Share' }, { key: 'find', label: 'Find' }, { key: 'negotiate', label: 'Negotiate' },
    { key: 'seats', label: 'Seats' }, { key: 'confirm', label: 'Confirm' }, { key: 'privacy', label: 'Done' },
  ];

  const state = {
    presets: [], presetId: 'base', run: null, beats: [], pos: 0, playing: false, timer: null, speed: 1,
    peek: new Set(), waiting: false, engine: null, engineFailed: false, engineReady: null, who: 'ana', busy: false,
  };

  /* ---------- small helpers ---------- */
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const hm = (m) => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
  const clock = (m) => { const h = Math.floor(m / 60), mm = m % 60; return ((h + 11) % 12 + 1) + (mm ? ':' + String(mm).padStart(2, '0') : '') + (h < 12 ? ' AM' : ' PM'); };
  const colorOf = (id) => COLOR[id] || 'var(--holder)';
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const merge = (o) => Object.assign({}, DEFAULTS, o || {});
  const norm = (o) => { const m = merge(o); return JSON.stringify(Object.assign({}, m, { say_no_first: [...m.say_no_first].sort(), answers: [...m.answers] })); };
  const same = (a, b) => norm(a) === norm(b);
  const sameRules = (a, b) => norm(Object.assign({}, a, { answers: [] })) === norm(Object.assign({}, b, { answers: [] }));
  const student = (id) => state.run.students.find((s) => s.id === id);
  const nameOf = (id) => (names()[id] || id);
  function names() {
    const m = {};
    state.run.students.forEach((s) => (m[s.id] = s.name));
    state.run.seat_holders.forEach((h) => (m[h.id] = h.name));
    return m;
  }
  const idOfName = (nm) => Object.entries(names()).find(([, v]) => v === nm)?.[0] || nm;

  function meetingsText(sec) {
    const groups = new Map();
    sec.meetings.forEach((m) => {
      const k = m.start + '-' + m.end + '-' + m.label;
      if (!groups.has(k)) groups.set(k, { days: [], m });
      groups.get(k).days.push(m.day);
    });
    return [...groups.values()].map((g) => g.days.join('/') + ' ' + hm(g.m.start) + '–' + hm(g.m.end)
      + (g.m.label && g.m.label !== 'Lecture' ? ' ' + g.m.label.toLowerCase() : '')).join(', ');
  }
  const sectionText = (sid) => (state.run.sections[sid] ? meetingsText(state.run.sections[sid]) : '');

  function setStatus(kind, text) {
    const el = $('#engine-status');
    el.className = 'status' + (kind ? ' ' + kind : '');
    el.textContent = text;
  }

  /* ---------- timeline -> beats ---------- */
  const SECONDS = { share: 0.55, find: 3.4, miss: 2.6, propose: 1.6, reply: 1.25, relax: 4.6, recheck: 2.2, agree: 3, offer: 1.5, holder: 1.1, open: 2, swapdone: 3.6, verdict: 1.3, banner: 2.8, escalate: 1.6, end: 0 };

  function buildBeats(run) {
    const beats = [{ kind: 'intro', phase: 'intro' }];
    let phase = 'share', brief = null, afterRelax = false;
    const isStudent = (id) => !!COLOR[id];
    run.timeline.forEach((t) => {
      if (t.kind === 'phase') { phase = t.key; if (phase === 'privacy') beats.push({ kind: 'end', phase }); return; }
      if (t.kind === 'briefing') { brief = t.text; return; }
      if (t.kind === 'ask') { beats.push({ kind: 'ask', phase, who: t.student, answer: t.answer, index: t.index, brief }); brief = null; return; }
      if (t.kind === 'note') {
        const text = t.text.trim();
        if (/counts for everyone:/.test(text)) beats.push({ kind: 'find', phase, text, course: text.split(' ')[0], title: text.split(' counts for')[0].split(' ').slice(1).join(' '), uses: [...text.matchAll(/(\w+) as ([A-Z_/]+)/g)].map((m) => ({ id: idOfName(m[1]), cats: m[2] })) });
        else if (/^Also considered/.test(text)) beats.push({ kind: 'miss', phase, text, misses: [...text.matchAll(/(\w+) \(not (\w+)\)/g)].map((m) => ({ course: m[1], who: idOfName(m[2]) })) });
        else if (/^Agreement:/.test(text)) beats.push({ kind: 'agree', phase, text, sid: text.match(/Agreement: (\S+)/)[1] });
        else if (/take the open seats/.test(text)) beats.push({ kind: 'open', phase: 'seats', text, who: text.replace(' take the open seats.', '').split(/, | and /).map(idOfName) });
        else if (/gets in through a/.test(text)) beats.push({ kind: 'swapdone', phase: 'seats', text, friend: idOfName(text.split(' ')[0]), trades: [...text.matchAll(/(\w+) gives a (\S+) seat to (\w+)/g)].map((m) => ({ giver: idOfName(m[1]), section_id: m[2], receiver: idOfName(m[3]) })) });
        else if (/^\[to /.test(text)) { /* escalation text, covered by the ESCALATE beat */ }
        else beats.push({ kind: 'banner', phase, text, tone: /re-plan|Re-plan|No seat/.test(text) ? 'warn' : '' });
        return;
      }
      // a message on the bus
      const p = t.payload, base = { phase, msg: t };
      if (t.type === 'SHARE') beats.push(Object.assign(base, { kind: 'share', who: t.sender }));
      else if (t.type === 'PROPOSE' || t.type === 'COUNTER') { afterRelax = false; beats.push(Object.assign(base, { kind: 'propose', who: t.sender, sid: p.section_id })); }
      else if (t.type === 'RELAX') { afterRelax = true; beats.push(Object.assign(base, { kind: 'relax', who: t.sender, level: p.level, dropped: t.relaxed_private || {} })); }
      else if (t.type === 'SWAP_OFFER') beats.push(Object.assign(base, { kind: 'offer', who: t.sender, to: t.recipient, give: p.give_section, want: p.want_section }));
      else if (t.type === 'ESCALATE_TO_HUMAN') beats.push(Object.assign(base, { kind: 'escalate', who: t.sender, sid: p.section_id, options: p.options }));
      else if ((t.type === 'ACCEPT' || t.type === 'DECLINE') && t.recipient === 'all') beats.push(Object.assign(base, { kind: 'verdict', who: t.sender, yes: t.type === 'ACCEPT', sid: p.section_id }));
      else if (t.type === 'ACCEPT' || t.type === 'DECLINE') {
        if (!isStudent(t.sender)) beats.push(Object.assign(base, { kind: 'holder', who: t.sender, yes: t.type === 'ACCEPT', sid: p.section_id }));
        else beats.push(Object.assign(base, { kind: afterRelax ? 'recheck' : 'reply', who: t.sender, to: t.recipient, yes: t.type === 'ACCEPT', sid: p.section_id, thought: t.thought || '' }));
      }
    });
    // Swap offers learn the whole cycle from the "gets in through" note that follows them.
    beats.forEach((b, i) => {
      if (b.kind !== 'offer' && b.kind !== 'holder') return;
      const done = beats.slice(i).find((x) => x.kind === 'swapdone' || x.kind === 'ask' || x.kind === 'banner');
      if (done && done.kind === 'swapdone') { b.trades = done.trades; b.friend = done.friend; }
    });
    if (!beats.length || beats[beats.length - 1].kind !== 'end') beats.push({ kind: 'end', phase: 'privacy' });
    return beats;
  }

  /* ---------- world state after beat i ---------- */
  function world(upto) {
    const w = {
      phase: 'intro', said: {}, stamp: {}, thought: {}, shared: {}, windows: {}, find: null, misses: [],
      table: null, votes: {}, tried: {}, level: 0, dropped: {}, offers: [], holderYes: {}, open: [], swap: null,
      verdict: {}, attempt: 1, banner: null, ask: null, escalated: null, last: null, agreed: null, replans: [],
    };
    for (let i = 0; i <= upto && i < state.beats.length; i++) {
      const b = state.beats[i], now = i === upto;
      w.phase = b.phase;
      w.banner = null;
      if (b.msg) w.last = b.msg;
      switch (b.kind) {
        case 'share':
          if (b.msg.payload.open_categories) { w.shared[b.who] = b.msg.payload.open_categories; w.said[b.who] = { text: 'I still need ' + b.msg.payload.open_categories.join(', ') + '.' }; }
          else { w.windows[b.who] = b.msg.payload.free_windows.length; w.said[b.who] = { text: 'Free in ' + b.msg.payload.free_windows.length + ' time windows. (No reasons attached.)' }; }
          break;
        case 'find': w.find = b; w.said = {}; break;
        case 'miss': w.misses = b.misses; break;
        case 'propose':
          if (w.table && w.votes[w.table] && !w.tried[w.table]) w.tried[w.table] = 'no';
          w.table = b.sid; w.votes = { [b.sid]: { [b.who]: 'yes' } }; w.stamp = {}; w.thought = {};
          w.said = { [b.who]: { text: (b.msg.type === 'COUNTER' ? 'Counter-offer: ' : 'How about ') + b.sid + ', ' + sectionText(b.sid) + '?', tone: 'propose' } };
          w.stamp[b.who] = 'propose';
          break;
        case 'reply':
        case 'recheck':
          (w.votes[b.sid] = w.votes[b.sid] || {})[b.who] = b.yes ? 'yes' : 'no';
          w.stamp[b.who] = b.yes ? 'yes' : 'no';
          w.said[b.who] = { text: b.kind === 'recheck' ? 'Actually, ' + b.sid + ' works for me now.' : (b.yes ? 'Accept.' : 'Decline.'), tone: b.yes ? 'yes' : 'no', nudge: !b.yes && now };
          w.thought[b.who] = b.thought;
          if (b.kind === 'recheck') { w.table = b.sid; }
          if (!b.yes) w.tried[b.sid] = 'no';
          else if (w.tried[b.sid] === 'no' && b.kind === 'recheck') delete w.tried[b.sid];
          break;
        case 'relax':
          w.level = b.level; w.stamp = {}; w.said = { [b.who]: { text: 'We are stuck. Everyone, quietly drop your least important preferences (level ' + b.level + ').', tone: 'relax' } };
          Object.entries(b.dropped).forEach(([id, list]) => { w.dropped[id] = (w.dropped[id] || []).concat(list); if (list.length) w.thought[id] = 'I dropped ' + list.join(' and ') + '. Nobody else is told.'; else w.thought[id] = 'Nothing to drop at this level.'; });
          if (now) w.banner = { tone: 'relax', text: 'Stuck. Every agent quietly drops its least important preferences. Nobody says whose, or what.' };
          break;
        case 'agree':
          w.agreed = b.sid; w.table = b.sid; w.stamp = { ana: 'yes', ben: 'yes', maya: 'yes' };
          if (now) w.banner = { tone: 'good', text: b.text.replace('Agreement: ', 'Agreed: ') };
          break;
        case 'offer':
          w.offers.push(b); w.swap = { friend: b.friend, trades: b.trades };
          w.said = { [b.who]: { text: 'Offering ' + nameOf(b.to) + ' a trade: give ' + b.give + ', get ' + b.want + '.', tone: 'propose' } };
          break;
        case 'holder': w.holderYes[b.who] = b.yes; if (b.trades) w.swap = { friend: b.friend, trades: b.trades }; break;
        case 'open': w.open = b.who; b.who.forEach((id) => { w.said[id] = { text: 'I take one of the open seats.', tone: 'yes' }; }); break;
        case 'swapdone': w.swap = { friend: b.friend, trades: b.trades, done: true }; w.said[b.friend] = { text: 'I get in through a ' + b.trades.length + '-way swap.', tone: 'yes' }; break;
        case 'ask':
          w.ask = b; w.said = {}; w.stamp = Object.assign({}, w.verdict);
          Object.entries(w.verdict).forEach(([id, v]) => { w.said[id] = { text: v === 'yes' ? 'Confirmed ✓' : 'No. (No reason given.)', tone: v === 'yes' ? 'yes' : 'no' }; });
          break;
        case 'verdict':
          w.ask = null; w.verdict[b.who] = b.yes ? 'yes' : 'no'; w.stamp = Object.assign({}, w.verdict);
          w.said[b.who] = { text: b.yes ? 'Confirmed ✓' : 'No. (No reason given.)', tone: b.yes ? 'yes' : 'no' };
          if (!b.yes) w.replans.push({ sid: b.sid, who: b.who });
          break;
        case 'banner':
          if (/re-plan|No seat/i.test(b.text)) {
            if (/No seat/.test(b.text)) w.replans.push({ sid: (b.text.match(/No seat in (\S+)/) || [])[1], who: 'no seat' });
            w.attempt += 1; w.table = null; w.votes = {}; w.tried = {}; w.level = 0; w.dropped = {}; w.offers = []; w.holderYes = {}; w.open = []; w.swap = null; w.verdict = {}; w.agreed = null; w.stamp = {}; w.thought = {};
          }
          if (now) w.banner = { tone: b.tone, text: b.text };
          break;
        case 'escalate':
          w.escalated = b; w.said[b.who] = { text: 'Handing this back to ' + nameOf(b.who) + '.', tone: 'no' }; w.stamp[b.who] = 'human';
          break;
        case 'end': w.ended = true; break;
      }
    }
    return w;
  }

  /* ---------- rendering ---------- */
  function render(animate) {
    const w = world(state.pos);
    const beat = state.beats[state.pos];
    renderSteps(w);
    renderAgents(w, beat, animate);
    renderMinds(w);
    renderBanner(w);
    renderScene(w, beat, animate);
    renderWire(w, beat);
    renderTransport();
  }

  function renderSteps(w) {
    const idx = STEPS.findIndex((s) => s.key === w.phase);
    $('#steps').innerHTML = STEPS.map((s, i) => `<li class="${i < idx ? 'done' : i === idx ? 'now' : ''}"${i === idx ? ' aria-current="step"' : ''}><span>${i + 1}</span>${esc(s.label)}</li>`).join('');
    const p = state.presets.find((x) => x.id === state.presetId);
    const attempt = w.attempt > 1 ? ` · attempt ${w.attempt}` : '';
    $('#story').textContent = (p ? p.name : state.custom ? 'Your rules' : 'Your answers') + (state.run.live ? ' · computed live' : '') + attempt;
  }

  const STAMP = { yes: '✓', no: '✗', propose: '?', human: '↩' };
  function renderAgents(w, beat, animate) {
    const box = $('#agents');
    if (!box.children.length || box.dataset.run !== String(state.runId)) {
      box.dataset.run = String(state.runId);
      box.innerHTML = state.run.students.map((s) => `
        <article class="agent" data-id="${esc(s.id)}" style="--c:${colorOf(s.id)}">
          <header>
            <span class="avatar" aria-hidden="true">${esc(s.name[0])}</span>
            <div class="who"><h3>${esc(s.name)}<span class="agent-word">'s agent</span></h3><p>${esc(s.major)}</p></div>
            <span class="stamp" aria-hidden="true"></span>
          </header>
          <div class="bubble empty" aria-live="off"><p></p></div>
          <button type="button" class="peek" aria-pressed="false"><span class="eye" aria-hidden="true"></span><span class="peek-label">Peek inside</span></button>
        </article>`).join('');
      $$('.agent .peek', box).forEach((b) => b.addEventListener('click', () => togglePeek(b.closest('.agent').dataset.id)));
    }
    $$('.agent', box).forEach((card) => {
      const id = card.dataset.id, said = w.said[id], st = w.stamp[id];
      const speaking = beat && beat.who === id && beat.kind !== 'end';
      card.classList.toggle('speaking', !!speaking);
      card.classList.toggle('peeked', state.peek.has(id));
      card.dataset.stamp = st || '';
      $('.stamp', card).textContent = st ? STAMP[st] : '';
      const p = $('.bubble p', card);
      const html = said ? esc(said.text) + (said.nudge && !state.peek.has(id) ? ` <button type="button" class="why" data-id="${esc(id)}">Why? Peek inside</button>` : '') : '';
      if (p.innerHTML !== html) {
        p.innerHTML = html;
        const bubble = $('.bubble', card);
        bubble.dataset.tone = said ? said.tone || '' : '';
        bubble.classList.toggle('empty', !said);
        if (animate && speaking && !reduceMotion) { bubble.classList.remove('pop'); void bubble.offsetWidth; bubble.classList.add('pop'); }
        const why = $('.why', card);
        if (why) why.addEventListener('click', () => togglePeek(id, true));
      }
      const btn = $('.peek', card);
      btn.setAttribute('aria-pressed', String(state.peek.has(id)));
      $('.peek-label', btn).textContent = state.peek.has(id) ? 'Stop peeking' : 'Peek inside';
    });
  }

  function togglePeek(id, on) {
    if (on === true) state.peek.add(id);
    else if (state.peek.has(id)) state.peek.delete(id);
    else state.peek.add(id);
    render(false);
  }

  function ruleLabel(r) { return r.label ? r.label.charAt(0).toUpperCase() + r.label.slice(1) : r.text; }

  function renderMinds(w) {
    const ids = state.run.students.map((s) => s.id).filter((id) => state.peek.has(id));
    $('#minds').innerHTML = ids.map((id) => {
      const s = student(id), dropped = w.dropped[id] || [];
      const blocks = s.private.blocks.reduce((acc, b) => { const k = b.label + b.start + b.end; (acc[k] = acc[k] || { b, days: [] }).days.push(b.day); return acc; }, {});
      const busy = Object.values(blocks).map(({ b, days }) => `<li><b>${esc(days.join('/'))} ${hm(b.start)}–${hm(b.end)}</b> ${esc(b.label)}</li>`).join('');
      const rules = s.private.rules.map((r) => {
        const gone = !r.hard && dropped.includes(r.label);
        return `<li class="${r.hard ? 'hard' : 'soft'}${gone ? ' gone' : ''}">${r.hard ? '<span class="lock" aria-hidden="true">■</span>' : `<span class="imp" title="importance">${r.priority}</span>`}${esc(ruleLabel(r))}${r.hard ? '<em>hard rule</em>' : gone ? '<em>dropped</em>' : '<em>preference</em>'}</li>`;
      }).join('');
      const thought = w.thought[id];
      const col = state.run.students.findIndex((x) => x.id === id) + 1;
      return `<section class="mind" style="--c:${colorOf(id)};--col:${col}" aria-label="Inside ${esc(s.name)}'s agent">
        <h4><span class="eye" aria-hidden="true"></span>Inside ${esc(s.name)}'s agent <small>only ${esc(s.name)} sees this</small></h4>
        ${thought ? `<p class="thought">${esc(thought)}</p>` : '<p class="thought idle">Nothing on its mind yet.</p>'}
        <ul class="rules">${rules}</ul>
        ${busy ? `<ul class="busy">${busy}</ul>` : ''}
        <p class="mind-vault">GPA ${esc(s.private.gpa)} · ${esc(s.private.transcript.length)} past courses</p>
      </section>`;
    }).join('');
    $('#minds').classList.toggle('has', ids.length > 0);
  }

  function renderBanner(w) {
    const el = $('#banner');
    if (!w.banner) { el.hidden = true; return; }
    el.hidden = false;
    el.dataset.tone = w.banner.tone || '';
    el.textContent = w.banner.text;
  }

  /* ---------- the scene ---------- */
  function renderScene(w, beat, animate) {
    const el = $('#scene');
    let html = '';
    if (w.phase === 'intro' || !beat) html = sceneIntro();
    else if (w.ended || beat.kind === 'end') html = w.escalated ? sceneEscalated(w) : sceneEnd(w);
    else if (w.ask) html = sceneAsk(w.ask);
    else if (w.phase === 'share') html = sceneShare(w);
    else if (w.phase === 'find') html = sceneFind(w);
    else if (w.phase === 'seats') html = sceneSeats(w, animate);
    else if (w.phase === 'confirm') html = sceneWaiting(w);
    else html = sceneTable(w);
    el.innerHTML = html;
    el.dataset.kind = w.ended ? 'end' : w.ask ? 'ask' : w.phase;
    if (w.ask) wireAsk(w.ask);
    if (w.ended && !w.escalated) wireDownloads();
    if (w.ended && !w.escalated && animate) confetti();
    const again = $('#again', el);
    if (again) again.addEventListener('click', () => restart(true));
  }

  function sceneIntro() {
    return `<div class="intro">
      <p class="big">Three friends want one class together next semester.</p>
      <p>Ana works Tuesday and Thursday afternoons. Ben has hospital clinicals all Monday. Maya commutes. Each agent knows only its own student's life, and shares as little as it can.</p>
      <p class="hint">Press <b>Play</b>. Try <b>Peek inside</b> on any agent along the way.</p></div>`;
  }

  function sceneShare(w) {
    const rows = state.run.students.map((s) => {
      const cats = w.shared[s.id], win = w.windows[s.id];
      return `<div class="share-row" style="--c:${colorOf(s.id)}"><b>${esc(s.name)}'s agent</b>
        <div class="chips">${cats ? cats.map((c) => `<span class="chip">${esc(c)}</span>`).join('') : '<span class="chip ghost">…</span>'}${win != null ? `<span class="chip win">${win} free windows</span>` : ''}</div></div>`;
    }).join('');
    return `<div class="share"><h3>What each agent puts on the wire</h3><p class="hint">Requirement categories and bare free-time windows. Not the job, not the clinicals, not the GPA.</p>${rows}</div>`;
  }

  function sceneFind(w) {
    const f = w.find;
    if (!f) return sceneShare(w);
    const uses = f.uses.map((u) => `<li style="--c:${colorOf(u.id)}"><b>${esc(nameOf(u.id))}</b> counts it as <span class="chip">${esc(u.cats)}</span></li>`).join('');
    const misses = w.misses.length ? `<div class="misses"><h4>Close, but each leaves someone out</h4><ul>${w.misses.map((m) => `<li><s>${esc(m.course)}</s> no use to ${esc(nameOf(m.who))}</li>`).join('')}</ul></div>` : '';
    return `<div class="find"><p class="eyebrow">Three majors, one class</p>
      <div class="course-card"><span class="code">${esc(f.course)}</span><h3>${esc(f.title)}</h3><ul class="uses">${uses}</ul></div>${misses}</div>`;
  }

  // A week grid. items: {day, start, end, cls, style, html, title, lane, lanes}
  function weekGrid(items, opts) {
    opts = opts || {};
    const pct = (m) => ((m - START) / (END - START)) * 100;
    let html = `<div class="week${opts.cls ? ' ' + opts.cls : ''}"><div class="wk-corner"></div>` + DAYS.map((d) => `<div class="wk-head">${d}</div>`).join('');
    html += '<div class="wk-hours">' + Array.from({ length: (END - START) / 60 + 1 }, (_, i) => (i % 2 === 0 ? `<span style="top:${pct(START + i * 60)}%">${clock(START + i * 60).replace(':00', '')}</span>` : '')).join('') + '</div>';
    DAYS.forEach((day) => {
      html += '<div class="wk-day">';
      for (let h = 1; h < (END - START) / 60; h++) html += `<i style="top:${pct(START + h * 60)}%"></i>`;
      items.filter((it) => it.day === day && it.end > START && it.start < END).forEach((it) => {
        const lanes = it.lanes || 1, lane = it.lane || 0;
        it = Object.assign({}, it, { start: Math.max(it.start, START), end: Math.min(it.end, END) });
        html += `<div class="wk-blk ${it.cls || ''}" style="top:${pct(it.start)}%;height:${pct(it.end) - pct(it.start)}%;left:calc(${lane} * 100% / ${lanes});width:calc(100% / ${lanes});${it.style || ''}"${it.title ? ` title="${esc(it.title)}"` : ''}>${it.html || ''}</div>`;
      });
      html += '</div>';
    });
    return html + '</div>';
  }

  function privateOverlays(w, sid) {
    // For each peeked student: their private busy blocks and the rules that can be drawn on a week.
    const items = [];
    let clash = false;
    const sec = sid ? state.run.sections[sid] : null;
    const peeked = state.run.students.filter((s) => state.peek.has(s.id));
    peeked.forEach((s) => {
      const lane = state.run.students.indexOf(s), dropped = w.dropped[s.id] || [];
      s.private.blocks.forEach((b) => {
        const hit = sec && sec.meetings.some((m) => m.day === b.day && m.start < b.end && b.start < m.end);
        if (hit) clash = true;
        items.push({ day: b.day, start: b.start, end: b.end, cls: 'busy' + (hit ? ' hit' : ''), lane, lanes: 3, style: `--c:${colorOf(s.id)}`, html: `<span>${esc(s.name)}: ${esc(b.label.split(':')[0])}</span>`, title: `${s.name}, private: ${b.label}` });
      });
      s.private.rules.forEach((r) => {
        const [kind, val] = r.text.split(' ');
        const gone = !r.hard && dropped.includes(r.label);
        const cls = 'rule' + (r.hard ? ' hard' : '') + (gone ? ' gone' : '');
        const label = `${esc(s.name)}: ${esc(r.label)}${r.hard ? '' : ' (pref)'}`;
        const before = items.length;
        if (kind === 'day_off') items.push({ day: val, start: START, end: END, cls, lane, lanes: 3, style: `--c:${colorOf(s.id)}`, html: `<span>${label}</span>` });
        if (kind === 'no_before') { const t = +val.split(':')[0] * 60 + +val.split(':')[1]; DAYS.forEach((d) => items.push({ day: d, start: START, end: t, cls, lane, lanes: 3, style: `--c:${colorOf(s.id)}`, html: d === 'Mon' ? `<span>${label}</span>` : '' })); }
        if (kind === 'no_after') { const t = +val.split(':')[0] * 60 + +val.split(':')[1]; DAYS.forEach((d) => items.push({ day: d, start: t, end: END, cls, lane, lanes: 3, style: `--c:${colorOf(s.id)}`, html: d === 'Mon' ? `<span>${label}</span>` : '' })); }
        if (gone || !sec) return;
        items.slice(before).forEach((it) => {
          if (sec.meetings.some((m) => m.day === it.day && m.start < it.end && it.start < m.end)) { it.cls += ' hit'; clash = true; }
        });
      });
    });
    return { items, clash };
  }

  function voteDots(w, sid) {
    const v = w.votes[sid] || {};
    return state.run.students.map((s) => {
      const x = v[s.id];
      return `<span class="vote ${x || 'wait'}" style="--c:${colorOf(s.id)}" title="${esc(s.name)}: ${x === 'yes' ? 'accepts' : x === 'no' ? 'declines' : 'deciding'}">${esc(s.name[0])}${x === 'yes' ? '✓' : x === 'no' ? '✗' : '…'}</span>`;
    }).join('');
  }

  function sceneTable(w) {
    const sid = w.table;
    const ov = privateOverlays(w, sid);
    const items = [];
    Object.keys(w.tried).forEach((t) => {
      if (t === sid || !state.run.sections[t]) return;
      state.run.sections[t].meetings.forEach((m) => items.push({ day: m.day, start: m.start, end: m.end, cls: 'tried', html: `<span>${esc(t.split('-')[1])} ✗</span>`, title: `${t} was turned down` }));
    });
    items.push(...ov.items);
    if (sid) {
      const sec = state.run.sections[sid];
      const votes = Object.values(w.votes[sid] || {});
      const cls = 'table' + (votes.includes('no') ? ' rejected' : '') + (w.agreed === sid ? ' agreed' : '') + (ov.clash ? ' clash' : '');
      sec.meetings.forEach((m) => items.push({ day: m.day, start: m.start, end: m.end, cls, html: `<b>${esc(sid)}</b>` }));
    }
    const caption = sid
      ? `<p class="on-table"><span class="label">On the table</span> <b>${esc(sid)}</b> ${esc(sectionText(sid))}${state.run.sections[sid] ? ` · ${state.run.sections[sid].seats_left} seats left` : ''}</p>`
      : '<p class="on-table"><span class="label">On the table</span> nothing yet</p>';
    const tip = state.peek.size ? '<p class="hint">Hatched blocks are private. Only the peeked agent can see them.</p>' : '<p class="hint">The agents only see the section and each other\'s yes or no. Peek inside an agent to see its private week here.</p>';
    const level = (sid ? `<span class="votes">${voteDots(w, sid)}</span>` : '') + (w.level ? `<span class="tag relax">Relaxation level ${w.level}</span>` : '');
    return `<div class="table-scene"><div class="table-head">${caption}<div class="table-side">${level}</div></div>${weekGrid(items)}${tip}</div>`;
  }

  function swapSvg(sw, w, animate) {
    const trades = sw.trades;
    const order = [trades[0].giver];
    while (order.length < trades.length) {
      const nxt = trades.find((t) => t.giver === order[order.length - 1]).receiver;
      if (order.includes(nxt)) break;
      order.push(nxt);
    }
    const cx = 200, cy = 160, R = 108, NR = 30, count = order.length, pos = {};
    order.forEach((id, i) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / count; pos[id] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), a }; });
    let svg = `<svg viewBox="0 0 400 320" role="img" aria-label="${esc(count)}-way seat swap">`;
    trades.forEach((t, i) => {
      const a = pos[t.giver], b = pos[t.receiver];
      if (!a || !b) return;
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len;
      const x1 = a.x + ux * (NR + 4), y1 = a.y + uy * (NR + 4), x2 = b.x - ux * (NR + 10), y2 = b.y - uy * (NR + 10);
      const agreed = !COLOR[t.giver] ? w.holderYes[t.giver] : sw.done || Object.keys(w.holderYes).length > 0;
      svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="arrow${agreed ? ' on' : ''}"/>`;
      svg += `<polygon points="${x2 + ux * 9},${y2 + uy * 9} ${x2 - uy * 6},${y2 + ux * 6} ${x2 + uy * 6},${y2 - ux * 6}" class="head${agreed ? ' on' : ''}"/>`;
      svg += `<text x="${(x1 + x2) / 2 - uy * 22}" y="${(y1 + y2) / 2 + ux * 22 + 4}" text-anchor="middle" class="seat-label">${esc(t.section_id)}</text>`;
      if (sw.done && !reduceMotion) svg += `<g class="token"><rect x="-17" y="-9" width="34" height="18" rx="4" style="fill:${colorOf(t.receiver)}"/><text y="4" text-anchor="middle">seat</text><animateMotion dur="1.6s" begin="${i * 0.25}s" repeatCount="indefinite" path="M${x1},${y1} L${x2},${y2}"/></g>`;
    });
    order.forEach((id) => {
      const p = pos[id], nm = nameOf(id), friend = !!COLOR[id];
      const lx = p.x + Math.cos(p.a) * (NR + 16), ly = p.y + Math.sin(p.a) * (NR + 16) + 5;
      const ok = friend ? sw.done : w.holderYes[id];
      svg += `<circle cx="${p.x}" cy="${p.y}" r="${NR}" class="node${friend ? ' friend' : ''}" style="fill:${colorOf(id)}"/>` +
        `<text x="${p.x}" y="${p.y + 7}" text-anchor="middle" class="initial">${esc(nm[0])}</text>` +
        `<text x="${lx}" y="${ly}" text-anchor="${Math.abs(Math.cos(p.a)) < 0.3 ? 'middle' : Math.cos(p.a) > 0 ? 'start' : 'end'}" class="name">${esc(nm)}${ok ? ' ✓' : ''}</text>`;
    });
    return svg + '</svg>';
  }

  function sceneSeats(w, animate) {
    const sid = w.agreed, sec = sid ? state.run.sections[sid] : null;
    const seats = sec ? sec.seats_left : 0;
    const open = w.open.length ? `<p><b>${esc(w.open.map(nameOf).join(' and '))}</b> take${w.open.length === 1 ? 's' : ''} the open seat${w.open.length === 1 ? '' : 's'}.</p>` : '';
    let body = '';
    if (w.swap && w.swap.trades) {
      const list = w.swap.trades.map((t) => `<li>${esc(nameOf(t.giver))} gives a <b>${esc(t.section_id)}</b> seat to ${esc(nameOf(t.receiver))}</li>`).join('');
      body = `<div class="swap">${swapSvg(w.swap, w, animate)}<div class="swap-text">
        <p class="eyebrow">${w.swap.done ? 'Swap agreed' : 'Looking for a swap'}</p>
        <h3>${w.swap.done ? `${esc(nameOf(w.swap.friend))} is in, through a ${w.swap.trades.length}-way swap` : `${esc(nameOf(w.swap.friend || 'ana'))}'s agent searches for a trade cycle`}</h3>
        <p>Everyone in the circle gets a seat they actually want. Each seat holder sees only their own part of the trade, and says yes or no.</p><ul>${list}</ul></div></div>`;
    } else if (w.offers.length) {
      body = `<ul class="offers">${w.offers.map((o) => `<li>${esc(nameOf(o.who))}'s agent offers ${esc(nameOf(o.to))}: give ${esc(o.give)}, get ${esc(o.want)}</li>`).join('')}</ul>`;
    } else {
      body = `<p>${sid ? `${esc(sid)} has room for everyone, so no swap is needed.` : ''}</p>`;
    }
    return `<div class="seats"><div class="seat-head"><p class="eyebrow">Getting everyone a seat</p><h3>${esc(sid || '')}: ${seats} seat${seats === 1 ? '' : 's'} left for 3 friends</h3>${open}</div>${body}</div>`;
  }

  function sceneWaiting(w) {
    const done = state.run.students.filter((s) => w.verdict[s.id]);
    return `<div class="intro"><p class="big">${done.length ? esc(done.map((s) => s.name).join(', ')) + ' answered.' : 'Each student signs off.'}</p><p>Nothing is final until all three say yes.</p></div>`;
  }

  function briefLines(text) {
    const lines = (text || '').split('\n').filter((l) => !/^--- Private to/.test(l));
    const out = [];
    let inSched = false;
    lines.forEach((l) => {
      if (/^Your full schedule:/.test(l)) { out.push('<h4>Your week</h4><table class="sched"><tbody>'); inSched = true; return; }
      if (inSched && /^ {2}\S/.test(l) && !/ seat to /.test(l)) {
        const parts = l.trim().split(/\s{2,}/);
        out.push(`<tr><td class="req">${esc(parts[0] || '')}</td><td class="sid">${esc(parts[1] || '')}</td><td>${esc(parts[2] || '')}</td><td class="when">${esc(parts.slice(3).join(' '))}</td></tr>`);
        return;
      }
      if (inSched) { out.push('</tbody></table>'); inSched = false; }
      if (/^ {2}/.test(l)) out.push(`<p class="trade">${esc(l.trim())}</p>`);
      else if (/^To make this work, your agent relaxed/.test(l)) out.push(`<p class="gave">${esc(l)}</p>`);
      else out.push(`<p>${esc(l)}</p>`);
    });
    if (inSched) out.push('</tbody></table>');
    return out.join('');
  }

  function sceneAsk(a) {
    const s = student(a.who);
    return `<div class="ask" style="--c:${colorOf(a.who)}">
      <div class="letter"><p class="eyebrow">Private to ${esc(s.name)} · the others never see this</p>${briefLines(a.brief)}</div>
      <div class="decide"><p class="you">You are <b>${esc(s.name)}</b> now.</p><h3>Sign off on this plan?</h3>
        <p class="hint">A no goes out with no reason, and the agents re-plan without this section.</p>
        <div class="choices"><button type="button" class="btn primary yes" data-answer="y">Yes, lock it in</button><button type="button" class="btn no" data-answer="n">No, re-plan</button></div>
        <p class="rec">In the recorded story, ${esc(s.name)} says <b>${a.answer === 'y' ? 'yes' : 'no'}</b>.</p></div></div>`;
  }

  function wireAsk() {
    $$('#scene .choices button').forEach((b) => b.addEventListener('click', () => answer(b.dataset.answer)));
    const first = $('#scene .choices .yes');
    if (first && state.focusAsk) { first.focus({ preventScroll: true }); state.focusAsk = false; }
  }

  function sceneEnd(w) {
    const res = state.run.result, sid = res.section_id, sec = state.run.sections[sid];
    const studs = state.run.students;
    const items = [];
    studs.forEach((s, lane) => {
      (res.schedules[s.id]?.section_ids || []).forEach((x) => {
        const xs = state.run.sections[x];
        if (!xs) return;
        xs.meetings.forEach((m) => {
          if (x === sid) { if (lane === 0) items.push({ day: m.day, start: m.start, end: m.end, cls: 'table agreed', html: `<b>${esc(x)}</b><span>all three</span>` }); return; }
          items.push({ day: m.day, start: m.start, end: m.end, cls: 'own', lane, lanes: 3, style: `--c:${colorOf(s.id)}`, html: `<span>${esc(xs.course_id)}</span>`, title: `${s.name}: ${xs.course_id} ${xs.title}` });
        });
      });
    });
    const swaps = Object.keys(res.swaps).map((f) => `${nameOf(f)} got in through a ${res.swaps[f].length}-way swap`);
    const facts = [
      res.level ? `Relaxation level ${res.level}` : 'Nobody gave anything up',
      ...swaps,
      ...(res.rejected.length ? [`${res.rejected.length} re-plan${res.rejected.length > 1 ? 's' : ''}`] : []),
      `${state.run.audit.messages} messages`,
    ];
    const dl = studs.map((s) => `<button type="button" class="btn dl" data-id="${esc(s.id)}" style="--c:${colorOf(s.id)}">${esc(s.name)}'s calendar (.ics)</button>`).join('');
    return `<div class="end">
      <div class="end-head"><p class="eyebrow">All three confirmed ✓</p>
        <h3>${esc(sec.course_id)} ${esc(sec.title)}, section ${esc(sid)}</h3><p class="when">${esc(meetingsText(sec))}</p>
        <div class="facts">${facts.map((f) => `<span class="tag">${esc(f)}</span>`).join('')}<span class="tag good">${state.run.audit.leaks} private values leaked</span></div></div>
      ${weekGrid(items, { cls: 'final' })}
      <p class="legend">${studs.map((s) => `<span><i style="--c:${colorOf(s.id)}"></i>${esc(s.name)}</span>`).join('')}<span><i class="sh"></i>The class they share</span></p>
      <div class="downloads">${dl}</div>
      <p class="again-row"><button type="button" id="again" class="btn ghost light">↺ Watch again</button> or try a different story below.</p></div>`;
  }

  function sceneEscalated(w) {
    const e = w.escalated;
    return `<div class="end escalated"><div class="end-head"><p class="eyebrow">No plan, and that's on purpose</p>
      <h3>The agents ran out of options and hand the decision back to the students</h3>
      <p>They don't pick for anyone. Each student gets the sections with the most support: <b>${esc((e.options || []).join(', ') || 'none')}</b>. Nothing is final.</p>
      <div class="facts"><span class="tag">${w.replans.length} re-plan${w.replans.length === 1 ? '' : 's'}</span><span class="tag">${state.run.audit.messages} messages</span><span class="tag good">${state.run.audit.leaks} private values leaked</span></div></div>
      <p class="again-row"><button type="button" id="again" class="btn ghost light">↺ Try again and say yes</button></p></div>`;
  }

  function wireDownloads() {
    $$('#scene .dl').forEach((b) => b.addEventListener('click', () => {
      const text = state.run.calendars && state.run.calendars[b.dataset.id];
      if (!text) return;
      const url = URL.createObjectURL(new Blob([text], { type: 'text/calendar' }));
      const a = document.createElement('a');
      a.href = url; a.download = b.dataset.id + '-spring-2027.ics';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }));
  }

  function confetti() {
    if (reduceMotion) return;
    const box = $('#confetti');
    const colors = ['#2f6bea', '#12936b', '#b8327e', '#ffd54a', '#16202e'];
    box.innerHTML = Array.from({ length: 90 }, (_, i) => `<i style="left:${Math.random() * 100}%;background:${colors[i % colors.length]};animation-delay:${Math.random() * 0.6}s;animation-duration:${2.2 + Math.random() * 1.6}s;transform:rotate(${Math.random() * 360}deg)"></i>`).join('');
    clearTimeout(state.confettiTimer);
    state.confettiTimer = setTimeout(() => (box.innerHTML = ''), 4200);
  }

  /* ---------- the wire ---------- */
  function renderWire(w, beat) {
    const el = $('#wire');
    const m = beat && beat.msg ? beat.msg : null;
    if (!m) {
      el.innerHTML = `<span class="wire-label">On the wire</span><span class="wire-quiet">${beat && beat.kind === 'ask' ? 'Nothing. A private briefing never leaves the agent.' : 'No message right now.'}</span>`;
      return;
    }
    let payload = Object.assign({}, m.payload);
    if (payload.free_windows) payload = { free_windows: `[${payload.free_windows.length} windows like ${payload.free_windows[0].day} ${payload.free_windows[0].start}–${payload.free_windows[0].end}]` };
    const body = Object.entries(payload).map(([k, v]) => `<span class="k">${esc(k)}</span>: <span class="v">${esc(Array.isArray(v) ? '[' + v.join(', ') + ']' : v)}</span>`).join(', ');
    const note = {
      DECLINE: 'No reason field. The message format has nowhere to put one.',
      SHARE: payload.free_windows ? 'Bare windows. Nobody learns why a time is blocked.' : 'Categories only. No transcript, no GPA.',
      RELAX: 'Just a number. Who dropped what stays inside each agent.',
      SWAP_OFFER: 'Each seat holder sees only their own half of the trade.',
      ESCALATE_TO_HUMAN: 'Sent to the student, not to the other agents.',
    }[m.type] || '';
    const to = m.recipient === 'all' ? 'everyone' : m.recipient.startsWith('human:') ? nameOf(m.recipient.slice(6)) + ' (the human)' : nameOf(m.recipient) + "'s agent";
    el.innerHTML = `<span class="wire-label">On the wire</span><code class="packet" style="--c:${colorOf(m.sender)}"><span class="t">${esc(m.type)}</span> <span class="route">${esc(nameOf(m.sender))} → ${esc(to)}</span> {${body}}</code>${note ? `<span class="wire-note">${esc(note)}</span>` : ''}`;
  }

  /* ---------- playback ---------- */
  function renderTransport() {
    const play = $('#t-play');
    const atEnd = state.pos >= state.beats.length - 1;
    play.textContent = state.waiting ? 'Waiting for you' : state.playing ? '❚❚ Pause' : atEnd ? '↺ Replay' : '▶ Play';
    play.disabled = state.waiting || state.busy;
    $('#t-step').disabled = state.waiting || atEnd || state.busy;
    $('#t-skip').disabled = atEnd || state.busy;
    $('#t-speed').textContent = state.speed === 1 ? '1×' : '2×';
    $('#t-bar').style.width = (state.beats.length > 1 ? (state.pos / (state.beats.length - 1)) * 100 : 0) + '%';
  }

  function schedule() {
    clearTimeout(state.timer);
    if (!state.playing) return;
    const beat = state.beats[state.pos];
    if (beat && beat.kind === 'ask') { pauseForAsk(); return; }
    if (state.pos >= state.beats.length - 1) { state.playing = false; renderTransport(); return; }
    const next = state.beats[state.pos + 1];
    const secs = (SECONDS[beat.kind] || 1.2) / state.speed;
    state.timer = setTimeout(() => { advance(); }, (next && next.phase !== beat.phase ? secs + 0.5 : secs) * 1000);
  }

  function advance() {
    if (state.pos >= state.beats.length - 1) return;
    state.pos += 1;
    render(true);
    schedule();
  }

  function pauseForAsk() {
    state.playing = false; state.waiting = true; state.focusAsk = true;
    render(false);
  }

  function play() {
    if (state.waiting || state.busy) return;
    if (state.pos >= state.beats.length - 1) { restart(true); return; }
    state.playing = !state.playing;
    if (state.playing && state.pos === 0) { state.pos = 1; render(true); }
    renderTransport();
    schedule();
  }

  function step() {
    if (state.waiting || state.busy) return;
    state.playing = false;
    clearTimeout(state.timer);
    if (state.pos < state.beats.length - 1) { state.pos += 1; render(true); }
    if (state.beats[state.pos].kind === 'ask') pauseForAsk();
  }

  function restart(autoplay, from) {
    clearTimeout(state.timer);
    state.waiting = false;
    state.pos = from || 0;
    state.playing = false;
    render(false);
    if (autoplay) { state.playing = true; renderTransport(); schedule(); }
  }

  function skip() {
    if (state.busy) return;
    clearTimeout(state.timer);
    state.playing = false; state.waiting = false;
    state.pos = state.beats.length - 1;
    render(true);
  }

  async function answer(ans) {
    const beat = state.beats[state.pos];
    if (!beat || beat.kind !== 'ask' || state.busy) return;
    state.waiting = false;
    if (ans === beat.answer) { state.playing = true; advance(); return; }
    // A different answer than recorded: run the real engine again with the answers so far.
    const before = state.beats.filter((b) => b.kind === 'ask' && b.index < beat.index).map((b) => b.answer);
    const opts = Object.assign({}, merge(state.run.options), { answers: before.concat([ans]) });
    state.busy = true;
    $('#scene .decide').insertAdjacentHTML('beforeend', '<p class="working">The agents are re-planning…</p>');
    renderTransport();
    const run = await getRun(opts);
    state.busy = false;
    if (!run) {
      setStatus('warn', 'That answer needs the live engine, which could not load here. Continuing with the recorded answer.');
      state.playing = true; advance();
      return;
    }
    const keep = beat.index;
    useRun(run, null);
    const i = state.beats.findIndex((b) => b.kind === 'ask' && b.index === keep);
    state.pos = i >= 0 ? i : 0;
    state.playing = true;
    advance();
  }

  /* ---------- runs, presets and the live engine ---------- */
  function useRun(run, presetId) {
    state.run = run;
    state.runId = (state.runId || 0) + 1;
    state.presetId = presetId;
    state.beats = buildBeats(run);
    markPreset(presetId);
    writeControls(run.options);
    renderPrivacy();
    renderLedger();
  }

  async function getRun(opts) {
    const hit = state.presets.find((p) => same(p.options, opts));
    if (hit) return hit.run;
    if (!state.engine && !state.engineFailed && state.engineReady) {
      setStatus('', 'Loading the live engine to run your change…');
      await state.engineReady;
    }
    if (state.engine) {
      try {
        const r = JSON.parse(state.engine(JSON.stringify(opts)));
        r.live = true;
        setStatus('live', 'Live engine: this run was computed in your browser just now.');
        return r;
      } catch (err) {
        setStatus('warn', 'The engine stopped with an error: ' + (err && err.message ? err.message.split('\n').slice(-2).join(' ') : err));
        return null;
      }
    }
    // No engine: a recorded run with the same rules whose answers start the same way.
    const asks = (r) => r.timeline.filter((t) => t.kind === 'ask').map((t) => t.answer);
    const fallback = state.presets.find((p) => sameRules(p.options, opts) && opts.answers.every((a, i) => asks(p.run)[i] === a));
    return fallback ? fallback.run : null;
  }

  function firstOf(phase) { const i = state.beats.findIndex((b) => b.phase === phase); return i < 0 ? 0 : i; }

  function selectPreset(id, autoplay) {
    const p = state.presets.find((x) => x.id === id);
    if (!p) return;
    state.custom = false;
    useRun(p.run, id);
    restart(autoplay, autoplay ? firstOf('negotiate') : 0);
  }

  function renderPresets() {
    $('#presets').innerHTML = state.presets.map((p) =>
      `<button type="button" class="preset" role="radio" aria-checked="${p.id === state.presetId}" data-id="${esc(p.id)}"><strong>${esc(p.name)}</strong><span>${esc(p.blurb)}</span></button>`).join('');
    $$('#presets .preset').forEach((b) => b.addEventListener('click', () => { selectPreset(b.dataset.id, true); $('#stage').scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth' }); }));
  }

  function markPreset(id) { $$('.preset').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.id === id))); }

  function readControls() {
    const maya = $('#c-maya').value;
    return {
      ben_friday_priority: +$('#c-ben').value, maya_max_days: maya === '' ? null : +maya, ana_no_early: $('#c-ana').checked,
      seats_left: +$('#c-seats').value, priya_willing: $('#c-priya').checked,
      say_no_first: $$('input[name="no"]:checked').map((i) => i.value), answers: [],
    };
  }

  function writeControls(o) {
    o = merge(o);
    $('#c-ben').value = String(o.ben_friday_priority);
    $('#c-maya').value = o.maya_max_days == null ? '' : String(o.maya_max_days);
    $('#c-ana').checked = !!o.ana_no_early;
    $('#c-seats').value = String(o.seats_left);
    $('#c-priya').checked = !!o.priya_willing;
    $$('input[name="no"]').forEach((i) => (i.checked = o.say_no_first.includes(i.value)));
  }

  async function onControlChange() {
    const opts = readControls();
    const hit = state.presets.find((p) => same(p.options, opts));
    if (hit) { selectPreset(hit.id, true); return; }
    clearTimeout(state.timer);
    state.playing = false;
    const run = await getRun(opts);
    if (!run) { setStatus('warn', 'Changing the rules needs the live engine, which could not load here. The five stories still work.'); return; }
    state.custom = true;
    useRun(run, null);
    restart(true, firstOf('negotiate'));
  }

  /* ---------- below the stage: audit and raw log ---------- */
  function renderPrivacy() {
    const r = state.run;
    const tabs = $('#priv-tabs');
    tabs.innerHTML = r.students.map((s) => `<button type="button" class="tab" role="tab" aria-selected="${s.id === state.who}" data-id="${esc(s.id)}">${esc(s.name)}</button>`).join('');
    $$('.tab', tabs).forEach((b) => b.addEventListener('click', () => { state.who = b.dataset.id; renderPrivacy(); }));
    const s = r.students.find((x) => x.id === state.who) || r.students[0];
    const fields = r.audit.shared_fields[s.id] || [];
    $('#privacy').innerHTML = `<div class="priv">
      <div class="box vault"><h3>Stayed inside ${esc(s.name)}'s agent</h3><dl>
        <dt>GPA</dt><dd>${esc(s.private.gpa)}</dd>
        <dt>Transcript</dt><dd>${esc(s.private.transcript.join(', '))}</dd>
        <dt>Busy time</dt><dd>${s.private.busy.length ? esc(s.private.busy.join('; ')) : 'None'}</dd>
        <dt>Rules</dt><dd><ul>${s.private.rules.map((x) => `<li>${esc(ruleLabel(x))} (${x.hard ? 'hard rule' : 'preference, importance ' + x.priority})</li>`).join('')}</ul></dd></dl></div>
      <div class="box"><h3>All that ever left it</h3>
        <div class="chips">${fields.map((f) => `<span class="chip">${esc(f)}</span>`).join('')}</div>
        <p>Those are the only message fields ${esc(s.name)}'s agent ever sent. Free time went out as bare windows. Declines went out with no reason at all.</p></div>
      <p class="audit">The engine scanned all <b>${r.audit.messages}</b> messages for <b>${r.audit.private_values}</b> private values (every GPA, transcript entry and busy-time label). Found: <b>${r.audit.leaks}</b>.</p></div>`;
  }

  function renderLedger() {
    const r = state.run, items = [];
    r.timeline.forEach((it) => {
      if (it.kind === 'phase') items.push(`<h3 class="phase">${esc(it.title)}</h3>`);
      else if (it.kind === 'msg') {
        const text = (it.text || it.type).replace(/^\s*\[round \d+\]\s*/, '').trim();
        const reply = (it.type === 'ACCEPT' || it.type === 'DECLINE') && it.recipient !== 'all';
        items.push(`<div class="row ${esc(it.type)}${reply ? ' reply' : ''}" style="--c:${colorOf(it.sender)}"><span class="rnd">${it.round ? 'r' + it.round : ''}</span><span><span class="line">${esc(text)}</span>${it.fields.length ? `<span class="fields">fields: ${esc(it.fields.join(', '))}</span>` : ''}</span></div>`);
      } else if (it.kind === 'note') items.push(`<div class="row note"><span class="rnd"></span><span class="line">${esc(it.text.trim())}</span></div>`);
      else if (it.kind === 'ask') items.push(`<div class="row ${it.answer === 'y' ? 'ACCEPT' : 'DECLINE'}" style="--c:${colorOf(it.student)}"><span class="rnd"></span><span class="line">${esc(it.name)} reads a private briefing and answers ${it.answer === 'y' ? 'yes' : 'no'}.</span></div>`);
    });
    $('#ledger').innerHTML = items.join('');
    $('#log-count').textContent = `(${r.audit.messages} messages)`;
  }

  /* ---------- engine ---------- */
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src; s.onload = resolve; s.onerror = () => reject(new Error('Could not load ' + src));
      document.head.appendChild(s);
    });
  }

  async function loadEngine() {
    try {
      await loadScript(PYODIDE_BASE + 'pyodide.js');
      const py = await window.loadPyodide({ indexURL: PYODIDE_BASE });
      const manifest = await (await fetch('engine/manifest.json')).json();
      py.FS.mkdirTree('/home/pyodide/data');
      for (const f of manifest) {
        const text = await (await fetch('engine/' + f)).text();
        py.FS.writeFile('/home/pyodide/' + f, text);
      }
      await py.runPythonAsync("import sys\nif '/home/pyodide' not in sys.path:\n    sys.path.insert(0, '/home/pyodide')\nimport webapi");
      state.engine = py.pyimport('webapi').run;
      setStatus('live', 'Live engine ready. Your answers and rule changes re-run the real negotiation in your browser.');
    } catch (err) {
      state.engineFailed = true;
      setStatus('warn', 'The live engine could not load, so you are seeing recorded runs. The five stories still work. (' + (err && err.message ? err.message : err) + ')');
    }
  }

  /* ---------- start ---------- */
  async function init() {
    $('#t-play').addEventListener('click', play);
    $('#t-step').addEventListener('click', step);
    $('#t-restart').addEventListener('click', () => restart(false));
    $('#t-skip').addEventListener('click', skip);
    $('#t-speed').addEventListener('click', () => { state.speed = state.speed === 1 ? 2 : 1; renderTransport(); if (state.playing) schedule(); });
    $('#hero-play').addEventListener('click', () => {
      $('#stage').scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth' });
      if (state.presetId !== 'base' || state.pos > 0) selectPreset('base', false);
      play();
    });
    $$('#controls select, #controls input').forEach((el) => el.addEventListener('change', onControlChange));
    $('#reset').addEventListener('click', () => selectPreset('base', true));
    document.addEventListener('keydown', (e) => {
      if (e.target.closest('input, select, textarea, button, summary')) return;
      if (e.key === ' ' && document.activeElement === document.body) { e.preventDefault(); play(); }
      if (e.key === 'ArrowRight') step();
    });
    try {
      state.presets = await (await fetch('presets.json')).json();
    } catch (err) {
      setStatus('warn', 'Could not load presets.json. Open this page from a web server, such as GitHub Pages, not directly from a file.');
      return;
    }
    renderPresets();
    useRun(state.presets[0].run, state.presets[0].id);
    restart(false);
    state.engineReady = loadEngine();
  }
  init();
})();
