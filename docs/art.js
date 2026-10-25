/* Co-Register illustrations: the three students, their robot agents, and small scenes.
 *
 * Everything is inline SVG drawn from code (no image files). face(id, mood) draws a student
 * with one of these moods: neutral, think, yes, no, worry, relief, joy. robot(color, mood)
 * draws that student's agent. app.js picks the mood from what is happening in the story.
 */
(function () {
  'use strict';

  const INK = '#1d1d27';
  const PEOPLE = {
    ana: { skin: '#f2c9a5', hair: '#2b2233', shirt: '#2f6bea' },
    ben: { skin: '#9a6544', hair: '#1f1611', shirt: '#12936b' },
    maya: { skin: '#d49a6a', hair: '#4a2a1d', shirt: '#b8327e' },
    holder: { skin: '#e3b48e', hair: '#5b5f6b', shirt: '#6b7788' },
  };

  function hairBack(id, p) {
    if (id === 'maya') return `<path d="M25 44 C 20 64, 22 84, 30 90 L 70 90 C 78 84, 80 64, 75 44 Z" fill="${p.hair}"/><circle cx="50" cy="17" r="10" fill="${p.hair}"/>`;
    if (id === 'ana') return `<path d="M24 50 C 22 70, 26 76, 32 76 L 68 76 C 74 76, 78 70, 76 50 Z" fill="${p.hair}"/>`;
    return '';
  }

  function hairFront(id, p) {
    if (id === 'ana') return `<path d="M25 52 C 22 22, 78 20, 76 50 C 70 40, 64 34, 56 32 C 50 38, 38 40, 30 38 C 28 42, 27 47, 25 52 Z" fill="${p.hair}"/>`;
    if (id === 'ben') return [[30, 35, 8], [37, 27, 9], [49, 23, 9.5], [61, 26, 9], [69, 34, 8], [27, 43, 5.5], [73, 43, 5.5]].map(([x, y, r]) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${p.hair}"/>`).join('');
    if (id === 'maya') return `<path d="M26 47 C 27 25, 73 23, 74 47 C 66 36, 50 33, 40 36 C 34 38, 29 42, 26 47 Z" fill="${p.hair}"/>`;
    return `<path d="M27 44 C 28 26, 72 24, 73 44 C 64 34, 38 34, 27 44 Z" fill="${p.hair}"/>`;
  }

  function eyes(mood) {
    const dot = (dx, dy, r) => `<circle cx="${41 + dx}" cy="${50 + dy}" r="${r}" fill="${INK}"/><circle cx="${59 + dx}" cy="${50 + dy}" r="${r}" fill="${INK}"/>`;
    const lid = (d) => `<path d="${d}" stroke="${INK}" stroke-width="2.7" fill="none" stroke-linecap="round"/>`;
    switch (mood) {
      case 'think': return dot(2, -2, 3);
      case 'joy': return lid('M36 52 Q41 45 46 52 M54 52 Q59 45 64 52');
      case 'relief': return lid('M36 50 Q41 54 46 50 M54 50 Q59 54 64 50');
      case 'no': return dot(0, 1, 3);
      case 'worry': return dot(0, 0, 3.2);
      default: return dot(0, 0, 3.3);
    }
  }

  function brows(mood) {
    const line = (d) => `<path d="${d}" stroke="${INK}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`;
    switch (mood) {
      case 'no': return line('M34 40 L46 44 M66 40 L54 44');
      case 'worry': return line('M34 43 L46 39 M66 43 L54 39');
      case 'think': return line('M35 42 Q41 40 47 42 M53 38 Q59 35 65 38');
      case 'joy': case 'relief': return line('M35 40 Q41 37 47 40 M53 40 Q59 37 65 40');
      default: return line('M35 42 Q41 39 47 42 M53 42 Q59 39 65 42');
    }
  }

  function mouth(mood) {
    const s = (d) => `<path d="${d}" stroke="${INK}" stroke-width="2.6" fill="none" stroke-linecap="round"/>`;
    switch (mood) {
      case 'yes': return s('M41 61 Q50 70 59 61');
      case 'joy': return `<path d="M39 60 Q50 76 61 60 Z" fill="#7a2230"/><path d="M44 66 Q50 70 56 66 Q50 74 44 66 Z" fill="#e8697a"/>`;
      case 'no': return s('M42 67 Q50 60 58 67');
      case 'worry': return s('M42 65 Q46 62 50 65 Q54 68 58 65');
      case 'think': return s('M46 64 L55 63');
      case 'relief': return s('M43 62 Q50 67 57 62') + '<path d="M70 34 Q74 40 70 43 Q66 40 70 34 Z" fill="#8fd3ff"/>';
      default: return s('M43 63 Q50 66 57 63');
    }
  }

  function extras(id, mood) {
    let out = '';
    if (mood === 'joy' || mood === 'yes') out += '<ellipse cx="33" cy="59" rx="5" ry="3" fill="#ff7a8a" opacity="0.45"/><ellipse cx="67" cy="59" rx="5" ry="3" fill="#ff7a8a" opacity="0.45"/>';
    if (id === 'ana') out += `<g stroke="${INK}" stroke-width="2" fill="none"><circle cx="41" cy="50" r="7.5"/><circle cx="59" cy="50" r="7.5"/><path d="M48.5 50 L51.5 50"/></g>`;
    if (id === 'maya') out += '<circle cx="25.5" cy="60" r="3.2" fill="none" stroke="#e0b341" stroke-width="1.8"/><circle cx="74.5" cy="60" r="3.2" fill="none" stroke="#e0b341" stroke-width="1.8"/>';
    return out;
  }

  function shirt(id, p) {
    let out = `<path d="M16 100 C 18 80, 82 80, 84 100 Z" fill="${p.shirt}"/>`;
    if (id === 'ben') out += '<path d="M40 82 L50 94 L60 82" stroke="#fff" stroke-width="2.4" fill="none" stroke-linejoin="round"/>';
    if (id === 'ana') out += '<path d="M42 82 Q50 88 58 82" stroke="#fff" stroke-width="2" fill="none" opacity="0.7"/>';
    if (id === 'maya') out += '<path d="M44 82 L50 90 L56 82" fill="#fff" opacity="0.85"/>';
    return out;
  }

  // A student. `bg` draws the round colored backdrop.
  function face(id, mood, opts) {
    opts = opts || {};
    const p = PEOPLE[id] || PEOPLE.holder;
    mood = mood || 'neutral';
    const bg = opts.bg === false ? '' : `<circle cx="50" cy="50" r="50" fill="${p.shirt}" opacity="0.14"/>`;
    return `<svg class="face" data-mood="${mood}" viewBox="0 0 100 100" aria-hidden="true" focusable="false"><defs><clipPath id="c-${id}-${opts.key || 'x'}"><circle cx="50" cy="50" r="50"/></clipPath></defs>
      <g clip-path="url(#c-${id}-${opts.key || 'x'})">${bg}${hairBack(id, p)}${shirt(id, p)}
      <rect x="44" y="66" width="12" height="16" rx="4" fill="${p.skin}"/>
      <ellipse cx="50" cy="50" rx="24" ry="26" fill="${p.skin}"/>
      <g class="feat">${eyes(mood)}${brows(mood)}${mouth(mood)}${extras(id, mood)}</g>${hairFront(id, p)}</g></svg>`;
  }

  // The agent: a small robot in the student's color.
  function robot(id, mood) {
    const c = (PEOPLE[id] || PEOPLE.holder).shirt;
    const eye = {
      yes: '<path d="M13 21 Q15.5 18 18 21 M22 21 Q24.5 18 27 21" stroke="#9ff3d4" stroke-width="2" fill="none" stroke-linecap="round"/>',
      joy: '<path d="M13 21 Q15.5 18 18 21 M22 21 Q24.5 18 27 21" stroke="#ffe27a" stroke-width="2" fill="none" stroke-linecap="round"/>',
      no: '<path d="M13.5 18.5 L17.5 22.5 M17.5 18.5 L13.5 22.5 M22.5 18.5 L26.5 22.5 M26.5 18.5 L22.5 22.5" stroke="#ff9e9e" stroke-width="1.8" stroke-linecap="round"/>',
      think: '<circle cx="15.5" cy="20.5" r="1.6" fill="#9fd8ff"/><circle cx="24.5" cy="20.5" r="2.6" fill="#9fd8ff"/>',
    }[mood] || '<circle class="blink" cx="15.5" cy="20.5" r="2.2" fill="#9fd8ff"/><circle class="blink" cx="24.5" cy="20.5" r="2.2" fill="#9fd8ff"/>';
    return `<svg class="robot" viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <path d="M20 10 L20 5" stroke="${c}" stroke-width="2"/><circle class="antenna" cx="20" cy="4" r="3" fill="${c}"/>
      <rect x="5" y="9" width="30" height="24" rx="8" fill="${c}"/><rect x="9" y="13" width="22" height="15" rx="5" fill="#0f1724"/>${eye}
      <rect x="2" y="17" width="3" height="8" rx="1.5" fill="${c}"/><rect x="35" y="17" width="3" height="8" rx="1.5" fill="${c}"/></svg>`;
  }

  // Hero: the three friends, with messages flying between them.
  function heroArt(still) {
    const spots = { ana: [120, 118], ben: [400, 118], maya: [260, 330] };
    const R = 74;
    const paths = [['ana', 'ben', -60], ['ben', 'maya', -40], ['maya', 'ana', -40], ['ben', 'ana', 60], ['ana', 'maya', 40]];
    const curve = ([a, b, bend]) => {
      const [x1, y1] = spots[a], [x2, y2] = spots[b];
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy);
      const cx = mx - (dy / len) * bend, cy = my + (dx / len) * bend;
      return `M${x1} ${y1} Q${cx} ${cy} ${x2} ${y2}`;
    };
    const labels = [['PROPOSE', '#ffd54a', '#4d3a00'], ['DECLINE', '#c53b3b', '#fff'], ['ACCEPT ✓', '#0d8a63', '#fff'], ['RELAX', '#5b3fb4', '#fff'], ['SWAP', '#2f6bea', '#fff']];
    let svg = '<svg viewBox="0 0 520 440" class="hero-svg" aria-hidden="true" focusable="false">';
    svg += '<circle cx="260" cy="200" r="190" fill="url(#heroGlow)"/><defs><radialGradient id="heroGlow"><stop offset="0" stop-color="#ffd54a" stop-opacity="0.35"/><stop offset="1" stop-color="#ffd54a" stop-opacity="0"/></radialGradient></defs>';
    paths.forEach((p, i) => { svg += `<path id="hp${i}" d="${curve(p)}" fill="none" stroke="#c3cad5" stroke-width="2" stroke-dasharray="3 7" stroke-linecap="round"/>`; });
    svg += '<g class="hero-course"><rect x="196" y="186" width="128" height="52" rx="12" fill="#fffbea" stroke="#c9a21c" stroke-width="2"/><text x="260" y="208" text-anchor="middle" class="hc-code">PHIL215</text><text x="260" y="226" text-anchor="middle" class="hc-sub">counts for all 3</text></g>';
    if (!still) paths.forEach((p, i) => {
      const [txt, bg, fg] = labels[i % labels.length];
      const w = txt.length * 7.4 + 18;
      svg += `<g class="env" opacity="0"><rect x="${-w / 2}" y="-12" width="${w}" height="24" rx="12" fill="${bg}"/><text y="4.5" text-anchor="middle" fill="${fg}" class="env-t">${txt}</text>` +
        `<animateMotion dur="5.5s" begin="${i * 1.1}s" repeatCount="indefinite" keyPoints="0;1;1" keyTimes="0;0.45;1" calcMode="linear"><mpath href="#hp${i}"/></animateMotion>` +
        `<animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;0.06;0.4;0.47;1" dur="5.5s" begin="${i * 1.1}s" repeatCount="indefinite"/></g>`;
    });
    Object.entries(spots).forEach(([id, [x, y]], i) => {
      const c = PEOPLE[id].shirt;
      svg += `<g class="hero-person" style="animation-delay:${i * 0.4}s"><circle cx="${x}" cy="${y}" r="${R + 6}" fill="#fff" stroke="${c}" stroke-width="5"/>` +
        `<svg x="${x - R}" y="${y - R}" width="${R * 2}" height="${R * 2}" viewBox="0 0 100 100">${face(id, ['yes', 'think', 'joy'][i], { key: 'hero', bg: true }).replace(/^<svg[^>]*>/, '').replace(/<\/svg>$/, '')}</svg>` +
        `<svg x="${x + R * 0.45}" y="${y + R * 0.4}" width="44" height="44" viewBox="0 0 40 40">${robot(id, ['yes', 'think', 'joy'][i]).replace(/^<svg[^>]*>/, '').replace(/<\/svg>$/, '')}</svg></g>`;
    });
    return svg + '</svg>';
  }

  // A small picture for each story card.
  function presetArt(id) {
    const cast = {
      base: [['ana', 'joy'], ['ben', 'relief'], ['maya', 'yes']],
      'ben-no': [['ana', 'think'], ['ben', 'no'], ['maya', 'think']],
      'no-swap': [['holder', 'no'], ['ana', 'worry']],
      flexible: [['ana', 'joy'], ['ben', 'joy'], ['maya', 'joy']],
      stuck: [['ana', 'no'], ['ben', 'no'], ['maya', 'worry']],
    }[id] || [['ana', 'neutral'], ['ben', 'neutral'], ['maya', 'neutral']];
    const badge = { base: '⇄', 'ben-no': '✗', 'no-swap': '🔒', flexible: '✓', stuck: '↩' }[id] || '';
    return `<span class="pa-faces">${cast.map(([who, mood], i) => `<span class="pa-face" style="z-index:${3 - i}">${face(who, mood, { key: id + i })}</span>`).join('')}</span>${badge ? `<span class="pa-badge" data-id="${id}">${badge}</span>` : ''}`;
  }

  window.CoArt = { face, robot, heroArt, presetArt };
})();
