/* Co-Register demo page.
 *
 * Loads presets.json (recorded runs of the real engine) so the page works instantly, then loads
 * the engine itself into Pyodide (Python in WebAssembly) so every change re-runs the real
 * negotiation in the browser. Nothing on this page makes a decision: it only draws what
 * webapi.run() returns.
 */
(function () {
  'use strict';

  const $ = (sel, el) => (el || document).querySelector(sel);
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
  const START = 8 * 60, END = 21 * 60, HOUR = 34;
  const DEFAULTS = { ben_friday_priority: 1, maya_max_days: 3, ana_no_early: true, seats_left: 2, priya_willing: true, say_no_first: [] };
  const COLOR = { ana: 'var(--ana)', ben: 'var(--ben)', maya: 'var(--maya)' };
  const PYODIDE_BASE = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';

  const state = { presets: [], presetId: 'base', run: null, engine: null, view: 'everyone', who: 'ana', timer: null, replay: null, engineFailed: false };

  /* ---------- small helpers ---------- */
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const hm = (m) => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
  const hourLabel = (h) => (h === 12 ? '12 PM' : h < 12 ? h + ' AM' : h - 12 + ' PM');
  const colorOf = (id) => COLOR[id] || 'var(--holder)';
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const merge = (o) => Object.assign({}, DEFAULTS, o || {});
  const same = (a, b) => {
    const norm = (o) => JSON.stringify(Object.assign({}, merge(o), { say_no_first: [...merge(o).say_no_first].sort() }));
    return norm(a) === norm(b);
  };

  function setStatus(kind, text) {
    const el = $('#engine-status');
    el.className = 'status' + (kind ? ' ' + kind : '');
    el.textContent = text;
  }

  function meetingsText(sec) {
    const groups = new Map();
    sec.meetings.forEach((m) => {
      const k = m.start + '-' + m.end + (m.label && m.label !== 'Lecture' ? ' ' + m.label.toLowerCase() : '');
      if (!groups.has(k)) groups.set(k, { days: [], m });
      groups.get(k).days.push(m.day);
    });
    return [...groups.values()].map((g) => g.days.join('/') + ' ' + hm(g.m.start) + '–' + hm(g.m.end)
      + (g.m.label && g.m.label !== 'Lecture' ? ' ' + g.m.label.toLowerCase() : '')).join(', ');
  }

  function nameMap(r) {
    const m = {};
    r.students.forEach((s) => (m[s.id] = s.name));
    r.seat_holders.forEach((h) => (m[h.id] = h.name));
    return m;
  }

  /* ---------- controls ---------- */
  function readControls() {
    const maya = $('#c-maya').value;
    return {
      ben_friday_priority: +$('#c-ben').value,
      maya_max_days: maya === '' ? null : +maya,
      ana_no_early: $('#c-ana').checked,
      seats_left: +$('#c-seats').value,
      priya_willing: $('#c-priya').checked,
      say_no_first: [...document.querySelectorAll('input[name="no"]:checked')].map((i) => i.value),
    };
  }

  function writeControls(o) {
    o = merge(o);
    $('#c-ben').value = String(o.ben_friday_priority);
    $('#c-maya').value = o.maya_max_days == null ? '' : String(o.maya_max_days);
    $('#c-ana').checked = !!o.ana_no_early;
    $('#c-seats').value = String(o.seats_left);
    $('#c-priya').checked = !!o.priya_willing;
    document.querySelectorAll('input[name="no"]').forEach((i) => (i.checked = o.say_no_first.includes(i.value)));
  }

  function renderPresets() {
    const box = $('#presets');
    box.innerHTML = state.presets.map((p) =>
      `<button type="button" class="preset" role="radio" aria-checked="${p.id === state.presetId}" data-id="${esc(p.id)}">
         <strong>${esc(p.name)}</strong><span>${esc(p.blurb)}</span></button>`).join('');
    box.querySelectorAll('.preset').forEach((b) => b.addEventListener('click', () => selectPreset(b.dataset.id)));
  }

  function markPreset(id) {
    state.presetId = id;
    document.querySelectorAll('.preset').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.id === id)));
  }

  function selectPreset(id) {
    const p = state.presets.find((x) => x.id === id);
    if (!p) return;
    markPreset(id);
    writeControls(p.options);
    state.who = 'ana';
    render(p.run, { animate: true });
    $('#controls').dataset.disabled = String(state.engineFailed);
  }

  function onControlChange() {
    const opts = readControls();
    const hit = state.presets.find((p) => same(p.options, opts));
    if (hit) {
      markPreset(hit.id);
      render(hit.run, { animate: false });
      return;
    }
    markPreset(null);
    clearTimeout(state.timer);
    if (state.engine) {
      state.timer = setTimeout(() => runLive(opts), 80);
    } else if (!state.engineFailed) {
      setStatus('', 'Your change will run as soon as the live engine finishes loading.');
    }
  }

  function runLive(opts) {
    try {
      const r = JSON.parse(state.engine(JSON.stringify(opts)));
      render(r, { animate: false });
      setStatus('live', 'Live engine: this run was computed in your browser just now.');
    } catch (err) {
      setStatus('warn', 'The engine stopped with an error: ' + (err && err.message ? err.message.split('\n').slice(-2).join(' ') : err));
    }
  }

  /* ---------- rendering ---------- */
  function render(r, opts) {
    state.run = r;
    renderOutcome(r);
    renderGrid(r);
    renderSeat(r);
    renderLedger(r, !!(opts && opts.animate));
    renderPrivacy(r);
  }

  function viewTabs(r) { return [{ id: 'everyone', label: 'Everyone' }].concat(r.students.map((s) => ({ id: s.id, label: s.name }))); }

  function renderTabs(containerId, items, current, onPick) {
    const box = $('#' + containerId);
    box.innerHTML = items.map((t) => `<button type="button" class="tab" role="tab" aria-selected="${t.id === current}" data-id="${esc(t.id)}">${esc(t.label)}</button>`).join('');
    box.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => onPick(b.dataset.id)));
  }

  function setView(id) {
    state.view = id;
    renderTabs('view-tabs', viewTabs(state.run), state.view, setView);
    renderGrid(state.run);
  }
  function setWho(id) {
    state.who = id;
    renderTabs('priv-tabs', state.run.students.map((s) => ({ id: s.id, label: s.name })), state.who, setWho);
    renderPrivacy(state.run);
  }

  function renderOutcome(r) {
    const res = r.result, names = nameMap(r), sec = r.sections[res.section_id];
    const out = $('#outcome');
    renderTabs('view-tabs', viewTabs(r), state.view, setView);
    renderTabs('priv-tabs', r.students.map((s) => ({ id: s.id, label: s.name })), state.who, setWho);

    if (res.status !== 'confirmed') {
      const tried = res.rejected.length;
      out.innerHTML = `<h2>No plan yet</h2>
        <p>The agents ran out of options${tried ? ' after ' + tried + ' re-plan' + (tried > 1 ? 's' : '') : ''} and are handing the decision to the students, starting with the section that had the most support. Nothing is final.</p>
        <div class="tags"><span class="tag warn">Escalated to the students</span><span class="tag">${r.audit.messages} messages</span></div>`;
      return;
    }
    const tags = [];
    tags.push(res.level === 0 ? '<span class="tag">Nobody gave anything up</span>' : `<span class="tag">Relaxation level ${res.level}</span>`);
    const swaps = Object.keys(res.swaps);
    swaps.forEach((f) => tags.push(`<span class="tag shared">${esc(names[f])} got in through a ${res.swaps[f].length}-way swap</span>`));
    if (res.rejected.length) tags.push(`<span class="tag">${res.rejected.length} re-plan${res.rejected.length > 1 ? 's' : ''}</span>`);
    tags.push(`<span class="tag">${r.audit.messages} messages</span>`);
    tags.push(`<span class="tag">${r.audit.leaks} private values leaked</span>`);

    const bits = [];
    bits.push(res.level === 0
      ? 'It fit everyone as it was, so no agent had to give anything up.'
      : `To get there, every agent privately dropped its least important preferences (level ${res.level}). The others were not told whose or what.`);
    res.rejected.forEach((x) => bits.push(x.by === 'no seat'
      ? `${x.section_id} was dropped because not everyone could get a seat.`
      : `${x.section_id} was dropped because ${x.by_name} said no, so the agents started over.`));
    bits.push('Every student confirmed.');
    out.innerHTML = `<h2>${esc(sec.course_id)}: ${esc(sec.title)}, section ${esc(res.section_id)}, ${esc(meetingsText(sec))}</h2>
      <p>${esc(bits.join(' '))}</p><div class="tags">${tags.join('')}</div>`;
  }

  function renderGrid(r) {
    const grid = $('#grid'), legend = $('#legend'), res = r.result;
    if (res.status !== 'confirmed') {
      grid.innerHTML = '<p class="hint">No schedules to show, because the agents did not reach a confirmed plan.</p>';
      legend.innerHTML = '';
      return;
    }
    const lanes = state.view === 'everyone' ? r.students : r.students.filter((s) => s.id === state.view);
    const n = lanes.length, H = ((END - START) / 60) * HOUR;
    let html = '<div class="tt" aria-hidden="true"><div></div>' + DAYS.map((d) => `<div class="tt-head">${d}</div>`).join('');
    html += `<div class="tt-hours" style="height:${H}px">` +
      Array.from({ length: (END - START) / 60 + 1 }, (_, i) => `<span style="top:${i * HOUR}px">${hourLabel(8 + i)}</span>`).join('') + '</div>';
    DAYS.forEach((day) => {
      html += `<div class="tt-day" style="height:${H}px">`;
      for (let i = 0; i <= (END - START) / 60; i++) html += `<div class="tt-line" style="top:${i * HOUR}px"></div>`;
      let sharedDrawn = false;
      lanes.forEach((stu, li) => {
        const sched = res.schedules[stu.id];
        if (!sched) return;
        sched.section_ids.forEach((sid) => {
          const sec = r.sections[sid];
          const isShared = sid === res.section_id;
          sec.meetings.filter((m) => m.day === day).forEach((m) => {
            if (isShared && sharedDrawn) return;
            const top = ((m.start - START) / 60) * HOUR, height = ((m.end - m.start) / 60) * HOUR - 1;
            const left = isShared ? '1px' : `calc(${li} * 100% / ${n} + 1px)`;
            const width = isShared ? 'calc(100% - 2px)' : `calc(100% / ${n} - 2px)`;
            const detail = n === 1 || isShared ? `<small>${esc(sec.title)}<br>${hm(m.start)}–${hm(m.end)}</small>` : '';
            html += `<div class="blk${isShared ? ' shared' : ''}" style="--c:${colorOf(stu.id)};top:${top}px;height:${height}px;left:${left};width:${width}" title="${esc(stu.name)}: ${esc(sec.course_id)} ${esc(sec.title)}">${esc(sec.course_id)}${detail}</div>`;
          });
        });
        if (isSharedDay(sched, res, r, day)) sharedDrawn = true;
      });
      html += '</div>';
    });
    html += '</div>';
    grid.innerHTML = html;

    legend.innerHTML = '<p><span class="key-shared"></span>Yellow is the class all three take together.</p>' +
      lanes.map((stu) => {
        const sched = res.schedules[stu.id];
        const list = sched.section_ids.map((sid) => `${esc(r.sections[sid].course_id)} (${esc(meetingsText(r.sections[sid]))})`).join('; ');
        return `<p><span class="dot" style="--c:${colorOf(stu.id)}"></span><b>${esc(stu.name)}</b>, ${esc(stu.major)}: ${list}</p>`;
      }).join('');
  }
  function isSharedDay(sched, res, r, day) {
    return sched.section_ids.some((sid) => sid === res.section_id && r.sections[sid].meetings.some((m) => m.day === day));
  }

  function renderSeat(r) {
    const box = $('#seat'), res = r.result, names = nameMap(r);
    if (res.status !== 'confirmed') { box.innerHTML = '<p class="seat-text">No seats were assigned, because no plan was agreed.</p>'; return; }
    const sec = r.sections[res.section_id];
    const parts = [];
    const open = res.open_seats.map((id) => names[id]);
    const swaps = Object.entries(res.swaps);
    if (!swaps.length) {
      parts.push(`<p class="seat-text">${esc(res.section_id)} had room for everyone, so no swap was needed.</p>`);
    } else {
      parts.push(`<p class="seat-text">${esc(res.section_id)} had only ${sec.seats_left} seat${sec.seats_left === 1 ? '' : 's'} left. ${open.length ? esc(open.join(' and ')) + ' took the open seat' + (open.length > 1 ? 's' : '') + '.' : ''}</p>`);
      swaps.forEach(([friend, trades]) => {
        parts.push(`<div class="swap">${swapSvg(trades, names)}<div><p class="seat-text"><b>${esc(names[friend])}</b> got a seat through a ${trades.length}-way swap. Everyone in the circle gets a seat they asked for, and each one confirmed their part:</p><ul>` +
          trades.map((t) => `<li>${esc(t.giver_name)} gives a ${esc(t.section_id)} seat to ${esc(t.receiver_name)}</li>`).join('') + '</ul></div></div>');
      });
    }
    box.innerHTML = parts.join('');
  }

  function swapSvg(trades, names) {
    const order = [trades[0].giver];
    while (order.length < trades.length) {
      const nxt = trades.find((t) => t.giver === order[order.length - 1]).receiver;
      if (order.includes(nxt)) break;
      order.push(nxt);
    }
    const cx = 170, cy = 150, R = 100, NR = 26, count = order.length;
    const pos = {};
    order.forEach((id, i) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / count; pos[id] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), a }; });
    let svg = '<svg viewBox="0 0 340 300" role="img" aria-label="Seat swap circle"><defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#16202e"/></marker></defs>';
    trades.forEach((t) => {
      const a = pos[t.giver], b = pos[t.receiver];
      if (!a || !b) return;
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len;
      const x1 = a.x + ux * (NR + 3), y1 = a.y + uy * (NR + 3), x2 = b.x - ux * (NR + 9), y2 = b.y - uy * (NR + 9);
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#16202e" stroke-width="2" marker-end="url(#ah)"/>`;
      svg += `<text x="${mx}" y="${my - 6}" text-anchor="middle" font-size="11" font-family="DM Mono, monospace" fill="#16202e" stroke="#fff" stroke-width="4" paint-order="stroke">${esc(t.section_id)}</text>`;
    });
    order.forEach((id) => {
      const p = pos[id], nm = names[id] || id, isFriend = !!COLOR[id];
      const lx = p.x + Math.cos(p.a) * (NR + 14), ly = p.y + Math.sin(p.a) * (NR + 14) + 4;
      svg += `<circle cx="${p.x}" cy="${p.y}" r="${NR}" style="fill:${colorOf(id)}"/>` +
        `<text x="${p.x}" y="${p.y + 6}" text-anchor="middle" font-size="17" font-weight="700" font-family="Bricolage Grotesque, sans-serif" fill="#fff">${esc(nm[0])}</text>` +
        `<text x="${lx}" y="${ly}" text-anchor="${Math.abs(Math.cos(p.a)) < 0.3 ? 'middle' : Math.cos(p.a) > 0 ? 'start' : 'end'}" font-size="13" font-weight="${isFriend ? 700 : 500}" fill="#16202e">${esc(nm)}</text>`;
    });
    return svg + '</svg>';
  }

  function renderLedger(r, animate) {
    clearInterval(state.replay);
    const names = nameMap(r), box = $('#ledger');
    const items = [];
    r.timeline.forEach((it) => {
      if (it.kind === 'phase') items.push(`<h3 class="phase">${esc(it.title)}</h3>`);
      else if (it.kind === 'msg') {
        const text = (it.text || it.type).replace(/^\s*\[round \d+\]\s*/, '').trim();
        const reply = (it.type === 'ACCEPT' || it.type === 'DECLINE') && it.recipient !== 'all';
        items.push(`<div class="row ${esc(it.type)}${reply ? ' reply' : ''}" style="--c:${colorOf(it.sender)}"><span class="rnd">${it.round ? 'r' + it.round : ''}</span><span><span class="line">${esc(text)}</span>${it.fields.length ? `<span class="fields">fields: ${esc(it.fields.join(', '))}</span>` : ''}</span></div>`);
      } else if (it.kind === 'note') {
        items.push(`<div class="row note"><span class="rnd"></span><span class="line">${esc(it.text.trim())}</span></div>`);
      } else if (it.kind === 'ask') {
        items.push(`<div class="row ${it.answer === 'y' ? 'ACCEPT' : 'DECLINE'}" style="--c:${colorOf(it.student)}"><span class="rnd"></span><span class="line">${esc(it.name)} reads a private briefing and answers ${it.answer === 'y' ? 'yes' : 'no'}.</span></div>`);
      }
    });
    box.innerHTML = items.join('');
    box.scrollTop = 0;
    const els = [...box.children];
    if (!animate || reduceMotion) return;
    els.forEach((el) => el.classList.add('hide'));
    let i = 0;
    state.replay = setInterval(() => {
      if (i >= els.length) { clearInterval(state.replay); return; }
      els[i].classList.remove('hide');
      els[i].classList.add('fresh');
      els[i].scrollIntoView({ block: 'nearest' });
      i += 1;
    }, 90);
  }

  function ruleText(rule) {
    const [kind, val] = rule.text.split(' ');
    const label = { no_before: `No classes before ${val}`, no_after: `Nothing after ${val}`, day_off: `${val} off`, max_days: `At most ${val} days on campus`, max_credits: `At most ${val} credits` }[kind] || rule.text;
    return rule.hard ? `${label} (hard rule, cannot be relaxed)` : `${label} (preference, importance ${rule.priority})`;
  }

  function renderPrivacy(r) {
    const stu = r.students.find((s) => s.id === state.who) || r.students[0];
    const fields = r.audit.shared_fields[stu.id] || [];
    const a = r.audit;
    const brief = r.briefings[stu.id];
    $('#privacy').innerHTML = `<div class="priv">
      <div class="box vault"><h3>Only ${esc(stu.name)} and their agent know</h3><dl>
        <dt>GPA</dt><dd>${esc(stu.private.gpa)}</dd>
        <dt>Transcript</dt><dd>${esc(stu.private.transcript.join(', '))}</dd>
        <dt>Busy time</dt><dd>${stu.private.busy.length ? esc(stu.private.busy.join('; ')) : 'None'}</dd>
        <dt>Rules</dt><dd><ul>${stu.private.rules.map((x) => `<li>${esc(ruleText(x))}</li>`).join('')}</ul></dd></dl></div>
      <div class="box"><h3>What ${esc(stu.name)}'s agent shared</h3>
        <p>Only these message fields ever left it:</p>
        <div class="chips">${fields.map((f) => `<span class="chip">${esc(f)}</span>`).join('')}</div>
        <p>Free time went out as bare windows, with no reasons attached. Declines went out with no reason at all.</p></div>
      <p class="audit">Audit: the engine scanned all <b>${a.messages}</b> messages for <b>${a.private_values}</b> private values (every GPA, transcript entry and busy-time label). Found: <b>${a.leaks}</b>.</p>
      <div class="box brief"><h3>${esc(stu.name)}'s private briefing</h3>${brief ? `<pre>${esc(brief)}</pre>` : '<p>No briefing, because the agents did not reach a plan.</p>'}</div></div>`;
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
      const base = new URLSearchParams(location.search).get('pyodide') || PYODIDE_BASE;
      await loadScript(base + 'pyodide.js');
      const py = await window.loadPyodide({ indexURL: base });
      const manifest = await (await fetch('engine/manifest.json')).json();
      py.FS.mkdirTree('/home/pyodide/data');
      for (const f of manifest) {
        const text = await (await fetch('engine/' + f)).text();
        py.FS.writeFile('/home/pyodide/' + f, text);
      }
      await py.runPythonAsync("import sys\nif '/home/pyodide' not in sys.path:\n    sys.path.insert(0, '/home/pyodide')\nimport webapi");
      state.engine = py.pyimport('webapi').run;
      $('#controls').dataset.disabled = 'false';
      setStatus('live', 'Live engine ready. Every change you make re-runs the real negotiation in your browser.');
      if (!state.presetId) runLive(readControls());
    } catch (err) {
      state.engineFailed = true;
      $('#controls').dataset.disabled = 'true';
      setStatus('warn', 'The live engine could not load, so you are seeing recorded runs of it. The five stories still work. (' + (err && err.message ? err.message : err) + ')');
    }
  }

  /* ---------- start ---------- */
  async function init() {
    $('#custom').closest('aside').id = 'controls';
    document.querySelectorAll('#custom select, #custom input').forEach((el) => el.addEventListener('change', onControlChange));
    $('#reset').addEventListener('click', () => selectPreset('base'));
    $('#replay').addEventListener('click', () => state.run && renderLedger(state.run, true));
    $('#showall').addEventListener('click', () => { clearInterval(state.replay); document.querySelectorAll('#ledger .hide').forEach((e) => e.classList.remove('hide')); });
    try {
      state.presets = await (await fetch('presets.json')).json();
    } catch (err) {
      setStatus('warn', 'Could not load presets.json. Open this page from a web server, such as GitHub Pages, not directly from a file.');
      return;
    }
    renderPresets();
    selectPreset('base');
    loadEngine();
  }
  init();
})();
