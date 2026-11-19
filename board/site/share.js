// Share a slip (Thomas, 2026-11-19): draws a compact card of the slip's legs on a canvas, sized for one phone screenshot,
// and shows it over the page with Share (phone share sheet, as an image), Save image and Copy text.
// Used by every parlay builder and the Bank Builder: shareSlip({ title, legs: [{ label, sub, odds, tag }], odds, chance, pays, warn })
(function () {
  const C = { bg: '#0f1511', panel: '#161e18', ink: '#e6ece7', muted: '#95a399', turf: '#5fc27f', gold: '#e3ac4a', line: '#27322a' };
  const W = 360, S = 3, PAD = 18;   // card width in CSS px, drawn at 3x so the image stays sharp
  const DISP = '"Barlow Condensed", "Arial Narrow", sans-serif', BODY = '"Barlow", "Segoe UI", system-ui, sans-serif';
  const font = (w, px, fam) => `${w} ${px}px ${fam || BODY}`;
  // wrap text to the width, at most `max` lines (the last one ends in … when cut)
  function wrap(ctx, text, width, max) {
    const words = String(text).split(/\s+/), lines = [];
    let cur = '';
    for (const w of words) {
      const t = cur ? cur + ' ' + w : w;
      if (ctx.measureText(t).width <= width || !cur) cur = t; else { lines.push(cur); cur = w; }
    }
    if (cur) lines.push(cur);
    if (lines.length > max) { let last = lines.slice(max - 1).join(' '); while (last.length > 1 && ctx.measureText(last + '…').width > width) last = last.slice(0, -1); lines.splice(max - 1, lines.length, last + '…'); }
    return lines;
  }
  function draw(d) {
    const cv = document.createElement('canvas'), ctx = cv.getContext('2d');
    const oddsW = 64, textW = W - PAD * 2 - oddsW - 8;
    // layout pass: measure each leg's lines so the card is exactly as tall as it needs
    ctx.font = font(600, 16);
    const rows = d.legs.map((l) => { ctx.font = font(600, 16); const a = wrap(ctx, l.label, textW, 2); ctx.font = font(400, 13); const b = wrap(ctx, [l.sub, l.tag].filter(Boolean).join(' · '), textW, 1); return { l, a, b, h: 10 + a.length * 20 + b.length * 17 + 10 }; });
    ctx.font = font(500, 13); const warn = d.warn ? wrap(ctx, d.warn, W - PAD * 2, 3) : [];
    const head = 76, stats = 74, foot = 34 + warn.length * 17;
    const H = head + rows.reduce((a, r) => a + r.h, 0) + 12 + stats + foot;
    cv.width = W * S; cv.height = H * S; ctx.scale(S, S); ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = C.turf; ctx.fillRect(0, 0, W, 4);
    // header
    ctx.fillStyle = C.turf; ctx.font = font(600, 12, DISP); ctx.fillText('GOONERGAMBLE', PAD, 26);
    ctx.fillStyle = C.muted; ctx.font = font(400, 12); ctx.textAlign = 'right';
    ctx.fillText(new Date().toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }), W - PAD, 26); ctx.textAlign = 'left';
    ctx.fillStyle = C.ink; ctx.font = font(700, 26, DISP); ctx.fillText(d.title, PAD, 56);
    // legs
    let y = head;
    ctx.strokeStyle = C.line; ctx.lineWidth = 1;
    rows.forEach((r, i) => {
      if (i) { ctx.beginPath(); ctx.moveTo(PAD, y + 0.5); ctx.lineTo(W - PAD, y + 0.5); ctx.stroke(); }
      let ty = y + 10;
      ctx.fillStyle = C.ink; ctx.font = font(600, 16); r.a.forEach((t) => { ty += 20; ctx.fillText(t, PAD, ty - 4); });
      ctx.fillStyle = r.l.tag ? C.gold : C.muted; ctx.font = font(400, 13); r.b.forEach((t) => { ty += 17; ctx.fillText(t, PAD, ty - 3); });
      ctx.fillStyle = C.ink; ctx.font = font(700, 18, DISP); ctx.textAlign = 'right'; ctx.fillText(r.l.odds, W - PAD, y + 10 + 20 - 3); ctx.textAlign = 'left';
      y += r.h;
    });
    // totals
    y += 12;
    ctx.fillStyle = C.panel; ctx.beginPath(); (ctx.roundRect ? ctx.roundRect(PAD, y, W - PAD * 2, stats - 8, 10) : ctx.rect(PAD, y, W - PAD * 2, stats - 8)); ctx.fill();
    const cols = [[d.odds, 'Parlay odds'], [d.chance, 'Hit chance'], [d.pays, '$10 pays']].filter((c) => c[0]);
    const cw = (W - PAD * 2) / cols.length;
    cols.forEach(([v, k], i) => {
      const x = PAD + cw * i + cw / 2; ctx.textAlign = 'center';
      ctx.fillStyle = i ? C.ink : C.turf; ctx.font = font(700, 24, DISP); ctx.fillText(v, x, y + 32);
      ctx.fillStyle = C.muted; ctx.font = font(400, 12); ctx.fillText(k, x, y + 52);
    });
    ctx.textAlign = 'left'; y += stats;
    ctx.fillStyle = C.gold; ctx.font = font(500, 13); warn.forEach((t) => { y += 17; ctx.fillText(t, PAD, y - 4); });
    ctx.fillStyle = C.muted; ctx.font = font(400, 11); ctx.fillText(`${d.legs.length} leg${d.legs.length === 1 ? '' : 's'} at DraftKings prices · model picks, not betting advice`, PAD, y + 20);
    return cv;
  }
  const text = (d) => [d.title].concat(d.legs.map((l) => `• ${l.label} (${l.odds})${l.sub ? ' – ' + l.sub : ''}`), [[d.odds && 'Odds ' + d.odds, d.chance && 'hit chance ' + d.chance, d.pays && '$10 pays ' + d.pays].filter(Boolean).join(' · ')]).join('\n');
  window.shareSlip = async function (d) {
    if (!d || !d.legs || !d.legs.length) return;
    try { if (document.fonts) await document.fonts.ready; } catch (e) {}
    const cv = draw(d), name = 'slip-' + new Date().toISOString().slice(0, 10) + '.png';
    const blob = await new Promise((r) => cv.toBlob(r, 'image/png'));
    const url = URL.createObjectURL(blob);
    const ov = document.createElement('div');
    ov.setAttribute('role', 'dialog'); ov.setAttribute('aria-label', 'Share this slip');
    ov.style.cssText = 'position:fixed;inset:0;z-index:1000;background:rgba(8,12,9,.95);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:16px;overflow:auto';
    const img = document.createElement('img'); img.src = url; img.alt = text(d);
    img.style.cssText = `width:min(${W}px,92vw);height:auto;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.5);flex:none`;
    const bar = document.createElement('div'); bar.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;justify-content:center;flex:none';
    const btn = (label, fn, main) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = label;
      b.style.cssText = `font:600 15px ${BODY};padding:10px 16px;border-radius:999px;border:1px solid ${main ? C.turf : '#3a4a3e'};background:${main ? C.turf : C.panel};color:${main ? '#0f1511' : C.ink};cursor:pointer`;
      b.onclick = fn; bar.append(b); return b; };
    const close = () => { ov.remove(); URL.revokeObjectURL(url); document.removeEventListener('keydown', esc); };
    const esc = (e) => { if (e.key === 'Escape') close(); };
    const file = typeof File === 'function' ? new File([blob], name, { type: 'image/png' }) : null;
    if (file && navigator.canShare && navigator.canShare({ files: [file] })) btn('Share', async () => { try { await navigator.share({ files: [file], title: d.title }); } catch (e) {} }, true);
    const save = document.createElement('a'); save.href = url; save.download = name;
    btn('Save image', () => save.click(), !(file && navigator.canShare && navigator.canShare({ files: [file] })));
    const cp = btn('Copy text', async () => { try { await navigator.clipboard.writeText(text(d)); cp.textContent = 'Copied'; } catch (e) { cp.textContent = 'Copy failed'; } });
    btn('Close', close);
    const tip = document.createElement('p'); tip.textContent = 'Screenshot the card, or press and hold it to save.';
    tip.style.cssText = `margin:0;color:${C.muted};font:13px ${BODY};text-align:center;flex:none`;
    ov.append(img, bar, tip);
    ov.onclick = (e) => { if (e.target === ov) close(); };
    document.addEventListener('keydown', esc);
    document.body.append(ov);
  };
})();
