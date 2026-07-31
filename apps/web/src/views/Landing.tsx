import { useEffect } from 'react'
import { fmtInt, fmtMoney, t } from '../i18n'
import type { PlatformStats } from '../types'

// The logged-out landing. Self-contained markup + styles so it stays isolated
// from the Tailwind dashboard (only mounted while signed out); CTAs go to the
// real OAuth entrypoint at /auth/login.

const STYLE = `
  .si-landing {
    --bg: #0b0a12; --bg-2: #100e1b; --bg-3: #17142499;
    --line: rgba(169,112,255,0.16); --line-strong: rgba(169,112,255,0.3);
    --ink: #f4f1fb; --muted: #a7a2c6; --muted-2: #706b90;
    --violet: #a970ff; --violet-hi: #cbaaff; --green: #34d399; --green-hi: #6ee7b7;
    --sans: system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    --mono: ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
    --maxw: 1140px;
    background: var(--bg); color: var(--ink); font-family: var(--sans);
    line-height: 1.55; -webkit-font-smoothing: antialiased;
    min-height: 100vh; overflow-x: hidden; position: relative;
  }
  .si-landing * { box-sizing: border-box; }
  .si-landing .aura { position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background:
      radial-gradient(60% 45% at 15% -5%, rgba(145,70,255,0.28), transparent 60%),
      radial-gradient(50% 40% at 100% 0%, rgba(52,211,153,0.12), transparent 55%),
      radial-gradient(55% 50% at 50% 115%, rgba(145,70,255,0.16), transparent 60%); }
  .si-landing .grid-lines { position: fixed; inset: 0; z-index: 0; pointer-events: none; opacity: 0.5;
    background-image: linear-gradient(rgba(169,112,255,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(169,112,255,0.045) 1px, transparent 1px);
    background-size: 64px 64px; -webkit-mask-image: radial-gradient(80% 60% at 50% 20%, #000 30%, transparent 80%); mask-image: radial-gradient(80% 60% at 50% 20%, #000 30%, transparent 80%); }
  .si-landing .wrap { position: relative; z-index: 1; max-width: var(--maxw); margin: 0 auto; padding: 0 24px; }
  .si-landing .eyebrow { font-family: var(--mono); font-size: 0.72rem; letter-spacing: 0.18em; text-transform: uppercase; color: var(--violet-hi); }
  .si-landing .eyebrow.green { color: var(--green-hi); }
  .si-landing a { color: inherit; }
  .si-landing nav { position: sticky; top: 0; z-index: 20; backdrop-filter: blur(12px);
    background: linear-gradient(180deg, rgba(11,10,18,0.9), rgba(11,10,18,0.55)); border-bottom: 1px solid var(--line); }
  .si-landing .nav-inner { max-width: var(--maxw); margin: 0 auto; padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .si-landing .brand { display: flex; align-items: center; gap: 10px; font-weight: 800; letter-spacing: -0.01em; }
  .si-landing .brand .mark { width: 26px; height: 26px; border-radius: 7px; background: linear-gradient(150deg, var(--violet), #6f3fd6);
    box-shadow: 0 0 18px rgba(145,70,255,0.5); display: grid; place-items: center; position: relative; }
  .si-landing .brand .mark::after { content: ""; width: 9px; height: 9px; border-radius: 50%; background: #fff; box-shadow: 0 0 10px #fff; }
  .si-landing .brand small { font-family: var(--mono); font-weight: 500; color: var(--muted-2); letter-spacing: 0.04em; }
  .si-landing .btn { display: inline-flex; align-items: center; gap: 10px; font-weight: 700; font-size: 0.98rem; padding: 13px 22px; border-radius: 12px;
    text-decoration: none; border: 1px solid transparent; cursor: pointer; transition: transform 0.15s ease, box-shadow 0.2s ease, background 0.2s ease; white-space: nowrap; }
  .si-landing .btn-primary { color: #150b2b; background: linear-gradient(135deg, var(--violet-hi), var(--violet));
    box-shadow: 0 8px 30px rgba(145,70,255,0.4), inset 0 1px 0 rgba(255,255,255,0.35); }
  .si-landing .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 12px 40px rgba(145,70,255,0.55); }
  .si-landing .btn-ghost { color: var(--ink); border-color: var(--line-strong); background: rgba(169,112,255,0.06); }
  .si-landing .btn-ghost:hover { background: rgba(169,112,255,0.12); transform: translateY(-1px); }
  .si-landing .btn-lg { padding: 17px 30px; font-size: 1.06rem; border-radius: 14px; }
  .si-landing nav .btn { padding: 10px 16px; }
  .si-landing .tw { width: 18px; height: 20px; display: block; fill: #150b2b; }
  .si-landing header.hero { padding: 74px 0 40px; }
  .si-landing .hero-grid { display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 52px; align-items: center; }
  .si-landing h1 { font-size: clamp(2.35rem, 5.4vw, 3.9rem); line-height: 1.03; letter-spacing: -0.025em; margin: 18px 0 0; text-wrap: balance; font-weight: 850; }
  .si-landing h1 .hl { color: var(--green-hi); }
  .si-landing .lead { color: var(--muted); font-size: 1.16rem; margin: 22px 0 0; max-width: 34ch; }
  .si-landing .cta-row { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 32px; }
  .si-landing .cta-note { font-family: var(--mono); font-size: 0.76rem; color: var(--muted-2); margin-top: 16px; letter-spacing: 0.02em; }
  .si-landing .cta-note b { color: var(--muted); font-weight: 600; }
  .si-landing .panel { background: linear-gradient(180deg, #14111f, #0e0c18); border: 1px solid var(--line-strong); border-radius: 18px; padding: 18px;
    box-shadow: 0 30px 80px -30px rgba(145,70,255,0.5), inset 0 1px 0 rgba(255,255,255,0.04); max-width: 100%; }
  .si-landing .panel-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
  .si-landing .live { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 0.72rem; letter-spacing: 0.14em; color: var(--muted); }
  .si-landing .dot { width: 9px; height: 9px; border-radius: 50%; background: #ff4d6d; box-shadow: 0 0 0 0 rgba(255,77,109,0.6); animation: si-pulse 2s infinite; }
  @keyframes si-pulse { 0% { box-shadow: 0 0 0 0 rgba(255,77,109,0.55); } 70% { box-shadow: 0 0 0 10px rgba(255,77,109,0); } 100% { box-shadow: 0 0 0 0 rgba(255,77,109,0); } }
  .si-landing .panel-tag { font-family: var(--mono); font-size: 0.7rem; color: var(--muted-2); }
  .si-landing .revenue { border: 1px solid var(--line); border-radius: 13px; padding: 16px; background: rgba(52,211,153,0.05); }
  .si-landing .revenue .k { font-family: var(--mono); font-size: 0.7rem; letter-spacing: 0.08em; color: var(--muted); text-transform: uppercase; }
  .si-landing .revenue .v { font-size: 2.3rem; font-weight: 800; color: var(--green-hi); font-variant-numeric: tabular-nums; letter-spacing: -0.02em; margin-top: 2px; }
  .si-landing .revenue .sub { font-size: 0.82rem; color: var(--muted); }
  .si-landing .revenue .sub b { color: var(--green); }
  .si-landing .spark { width: 100%; height: 46px; margin-top: 8px; display: block; }
  .si-landing .mini-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
  .si-landing .mini { border: 1px solid var(--line); border-radius: 11px; padding: 11px 12px; background: var(--bg-3); }
  .si-landing .mini .k { font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.06em; color: var(--muted-2); text-transform: uppercase; }
  .si-landing .mini .v { font-weight: 700; font-size: 1.02rem; margin-top: 3px; font-variant-numeric: tabular-nums; }
  .si-landing .mini .v.g { color: var(--green-hi); }
  .si-landing .mini .v.p { color: var(--violet-hi); }
  .si-landing .ai-chip { margin-top: 12px; display: flex; gap: 10px; align-items: flex-start; border: 1px solid var(--line-strong); border-radius: 11px; padding: 11px 12px;
    background: linear-gradient(180deg, rgba(169,112,255,0.12), rgba(169,112,255,0.04)); font-size: 0.86rem; }
  .si-landing .ai-chip .badge { font-family: var(--mono); font-size: 0.6rem; letter-spacing: 0.1em; color: var(--violet-hi); border: 1px solid var(--line-strong); border-radius: 6px; padding: 2px 6px; white-space: nowrap; margin-top: 1px; }
  .si-landing .strip { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); margin-top: 34px; }
  .si-landing .strip .wrap { padding-top: 34px; padding-bottom: 34px; }
  .si-landing .strip p { margin: 8px 0 0; font-size: clamp(1.2rem, 2.6vw, 1.7rem); font-weight: 650; letter-spacing: -0.01em; text-wrap: balance; max-width: 24ch; }
  .si-landing .strip .hl { color: var(--violet-hi); }
  .si-landing section { padding: 72px 0; }
  .si-landing .sec-head { max-width: 42ch; }
  .si-landing .sec-head h2 { font-size: clamp(1.8rem, 4vw, 2.6rem); letter-spacing: -0.02em; margin: 12px 0 0; line-height: 1.08; text-wrap: balance; font-weight: 820; }
  .si-landing .sec-head p { color: var(--muted); margin-top: 14px; font-size: 1.05rem; }
  .si-landing .benefits { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 40px; }
  .si-landing .card { position: relative; border: 1px solid var(--line); border-radius: 16px; padding: 22px; background: linear-gradient(180deg, var(--bg-2), #0c0b15);
    transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease; opacity: 0; transform: translateY(14px); }
  .si-landing .reveal-in { opacity: 1; transform: none; }
  .si-landing .card:hover { transform: translateY(-4px); border-color: var(--line-strong); box-shadow: 0 20px 50px -30px rgba(145,70,255,0.6); }
  .si-landing .card .num { font-family: var(--mono); font-size: 0.72rem; color: var(--muted-2); letter-spacing: 0.1em; }
  .si-landing .card h3 { font-size: 1.22rem; margin: 12px 0 0; letter-spacing: -0.01em; }
  .si-landing .card .solve { color: var(--muted); margin-top: 10px; font-size: 0.96rem; }
  .si-landing .card .win { margin-top: 14px; display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 0.74rem; color: var(--green-hi); border-top: 1px dashed var(--line); padding-top: 12px; width: 100%; }
  .si-landing .card .win::before { content: "\\2192"; color: var(--green); }
  .si-landing .card.wide { grid-column: span 3; display: grid; grid-template-columns: 1.1fr 2fr; gap: 22px; align-items: center; }
  .si-landing .card.wide .win { width: auto; border: 0; padding-top: 0; }
  .si-landing .steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 40px; counter-reset: step; }
  .si-landing .step { border: 1px solid var(--line); border-radius: 16px; padding: 24px; background: var(--bg-2); }
  .si-landing .step .n { counter-increment: step; font-family: var(--mono); font-weight: 700; width: 40px; height: 40px; border-radius: 11px; display: grid; place-items: center; background: rgba(169,112,255,0.12); border: 1px solid var(--line-strong); color: var(--violet-hi); }
  .si-landing .step .n::before { content: counter(step, decimal-leading-zero); }
  .si-landing .step h4 { margin: 16px 0 0; font-size: 1.12rem; }
  .si-landing .step p { color: var(--muted); margin-top: 8px; font-size: 0.95rem; }
  .si-landing .trust { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 40px; }
  .si-landing .trust .t { border: 1px solid var(--line); border-radius: 14px; padding: 18px; background: var(--bg-3); }
  .si-landing .trust .t .k { font-weight: 700; font-size: 0.98rem; }
  .si-landing .trust .t .d { color: var(--muted); font-size: 0.86rem; margin-top: 6px; }
  .si-landing .trust .t .k .ic { color: var(--green-hi); margin-right: 7px; }
  .si-landing .final { text-align: center; border: 1px solid var(--line-strong); border-radius: 22px; padding: 60px 28px;
    background: radial-gradient(80% 120% at 50% -20%, rgba(145,70,255,0.28), transparent 60%), linear-gradient(180deg, #140f24, #0c0b16); box-shadow: 0 40px 90px -40px rgba(145,70,255,0.6); }
  .si-landing .final h2 { font-size: clamp(2rem, 5vw, 3.1rem); letter-spacing: -0.025em; margin: 10px 0 0; text-wrap: balance; font-weight: 850; }
  .si-landing .final p { color: var(--muted); margin: 16px auto 0; max-width: 46ch; font-size: 1.08rem; }
  .si-landing .final .cta-row { justify-content: center; }
  .si-landing footer { border-top: 1px solid var(--line); margin-top: 40px; padding: 34px 0 60px; color: var(--muted-2); }
  .si-landing .foot-inner { display: flex; flex-wrap: wrap; gap: 12px 26px; align-items: center; justify-content: space-between; font-size: 0.86rem; }
  .si-landing .foot-inner .mono { font-family: var(--mono); }
  .si-landing .fine { color: var(--muted-2); font-size: 0.78rem; margin-top: 14px; max-width: 70ch; }
  .si-landing .statband { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; text-align: center;
    border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 26px 0; }
  .si-landing .statband .n { font-size: clamp(1.5rem, 3.2vw, 1.95rem); font-weight: 800; letter-spacing: -0.02em;
    color: var(--ink); font-variant-numeric: tabular-nums; }
  .si-landing .statband .l { margin-top: 4px; font-size: 0.8rem; color: var(--muted); text-wrap: balance; }
  @media (max-width: 940px) {
    .si-landing .hero-grid { grid-template-columns: 1fr; gap: 34px; }
    .si-landing .benefits { grid-template-columns: 1fr 1fr; }
    .si-landing .card.wide { grid-column: span 2; }
    .si-landing .steps { grid-template-columns: 1fr; }
    .si-landing .trust { grid-template-columns: 1fr 1fr; }
  }
  @media (max-width: 620px) {
    .si-landing .benefits { grid-template-columns: 1fr; }
    .si-landing .card.wide { grid-column: span 1; }
    .si-landing .trust { grid-template-columns: 1fr; }
    .si-landing .statband { grid-template-columns: repeat(2, 1fr); gap: 16px; }
    .si-landing nav .brand small { display: none; }
    .si-landing header.hero { padding-top: 48px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .si-landing *, .si-landing .dot { animation: none !important; transition: none !important; }
    .si-landing .card { opacity: 1; transform: none; }
  }
`

const TWITCH_SVG =
  '<svg class="tw" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 2 2.5 6v13h4.5v3h3l3-3h4L23 14V2H4zm2 2h15v9l-3 3h-5l-3 3v-3H6V4zm5.5 4v5H13V8h-1.5zM16 8v5h1.5V8H16z"/></svg>'

// A function, not a const: the markup has to be built after setLang() has run,
// otherwise every string would be resolved at import time in the default
// language.
function body(): string {
  return `
<div class="aura"></div>
<div class="grid-lines"></div>
<nav>
  <div class="nav-inner">
    <div class="brand"><span class="mark"></span><span>Stream Intel <small>${t('landing.tagline')}</small></span></div>
    <a class="btn btn-primary" href="/auth/login">${TWITCH_SVG} ${t('landing.connect')}</a>
  </div>
</nav>
<header class="hero">
  <div class="wrap hero-grid">
    <div>
      <span class="eyebrow">${t('landing.eyebrow')}</span>
      <h1>${t('landing.h1.before')} <span class="hl">${t('landing.h1.highlight')}</span>.</h1>
      <p class="lead">${t('landing.lead')}</p>
      <div class="cta-row">
        <a class="btn btn-primary btn-lg" href="/auth/login">${TWITCH_SVG} ${t('landing.connect')}</a>
        <a class="btn btn-ghost btn-lg" href="#beneficios">${t('landing.seeWhat')}</a>
      </div>
      <p class="cta-note">${t('landing.ctaNote.free')} <b>${t('landing.ctaNote.readOnly')}</b> ${t('landing.ctaNote.never')} <b>${t('landing.ctaNote.encrypted')}</b>.</p>
    </div>
    <div class="panel" aria-hidden="true">
      <div class="panel-top"><span class="live"><span class="dot"></span> ${t('landing.panel.live')}</span><span class="panel-tag">${t('landing.panel.tag')}</span></div>
      <div class="revenue">
        <div class="k">${t('money.estimated')}</div>
        <div class="v" data-count="44.50">${fmtMoney(0)}</div>
        <div class="sub"><b>fiel_carlos</b> ${t('landing.panel.topSupporter')}</div>
        <svg class="spark" viewBox="0 0 300 46" preserveAspectRatio="none">
          <defs><linearGradient id="sig" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="rgba(52,211,153,0.5)"/><stop offset="1" stop-color="rgba(52,211,153,0)"/></linearGradient></defs>
          <path d="M0,38 L40,34 L80,36 L120,26 L160,28 L200,16 L240,18 L300,6 L300,46 L0,46 Z" fill="url(#sig)"/>
          <path d="M0,38 L40,34 L80,36 L120,26 L160,28 L200,16 L240,18 L300,6" fill="none" stroke="#6ee7b7" stroke-width="2"/>
        </svg>
      </div>
      <div class="mini-grid">
        <div class="mini"><div class="k">${t('landing.panel.converts')}</div><div class="v g">${fmtMoney(91.5)}/h</div></div>
        <div class="mini"><div class="k">${t('landing.panel.followers')}</div><div class="v p">41</div></div>
      </div>
      <div class="ai-chip"><span class="badge">AI</span><span>${t('landing.panel.ai')}</span></div>
    </div>
  </div>
</header>
<div class="wrap"><div class="statband" id="si-stats" style="display:none">
  <div><div class="n" data-count="0" data-fmt="int" data-stat="chat_messages">—</div><div class="l">${t('landing.stats.messages')}</div></div>
  <div><div class="n" data-count="0" data-fmt="int" data-stat="streams_analyzed">—</div><div class="l">${t('landing.stats.streams')}</div></div>
  <div><div class="n" data-count="0" data-fmt="int" data-stat="hours_captured">—</div><div class="l">${t('landing.stats.hours')}</div></div>
  <div><div class="n" data-count="0" data-fmt="int" data-stat="segments_transcribed">—</div><div class="l">${t('landing.stats.segments')}</div></div>
</div></div>
<div class="strip"><div class="wrap"><span class="eyebrow green">${t('landing.problem.eyebrow')}</span><p>${t('landing.problem.before')} <span class="hl">${t('landing.problem.highlight')}</span>${t('landing.problem.after')}</p></div></div>
<section id="beneficios">
  <div class="wrap">
    <div class="sec-head"><span class="eyebrow">${t('landing.benefits.eyebrow')}</span><h2>${t('landing.benefits.h2')}</h2><p>${t('landing.benefits.p')}</p></div>
    <div class="benefits">
      <div class="card"><div class="num">${t('landing.b1.num')}</div><h3>${t('landing.b1.h3')}</h3><p class="solve">${t('landing.b1.p')}</p><span class="win">${t('landing.b1.win')}</span></div>
      <div class="card"><div class="num">${t('landing.b2.num')}</div><h3>${t('landing.b2.h3')}</h3><p class="solve">${t('landing.b2.p')}</p><span class="win">${t('landing.b2.win')}</span></div>
      <div class="card"><div class="num">${t('landing.b3.num')}</div><h3>${t('landing.b3.h3')}</h3><p class="solve">${t('landing.b3.p')}</p><span class="win">${t('landing.b3.win')}</span></div>
      <div class="card"><div class="num">${t('landing.b4.num')}</div><h3>${t('landing.b4.h3')}</h3><p class="solve">${t('landing.b4.p')}</p><span class="win">${t('landing.b4.win')}</span></div>
      <div class="card"><div class="num">${t('landing.b5.num')}</div><h3>${t('landing.b5.h3')}</h3><p class="solve">${t('landing.b5.p')}</p><span class="win">${t('landing.b5.win')}</span></div>
      <div class="card"><div class="num">${t('landing.b6.num')}</div><h3>${t('landing.b6.h3')}</h3><p class="solve">${t('landing.b6.p')}</p><span class="win">${t('landing.b6.win')}</span></div>
      <div class="card wide">
        <div><div class="num">${t('landing.b7.num')}</div><h3>${t('landing.b7.h3.before')} <span style="color:#6ee7b7">${t('landing.b7.h3.your')}</span> ${t('landing.b7.h3.after')}</h3></div>
        <div><p class="solve">${t('landing.b7.p.before')} <b style="color:#f4f1fb">${t('landing.b7.p.bold')}</b>${t('landing.b7.p.after')}</p><span class="win">${t('landing.b7.win')}</span></div>
      </div>
    </div>
  </div>
</section>
<section style="padding-top:0">
  <div class="wrap">
    <div class="sec-head"><span class="eyebrow">${t('landing.how.eyebrow')}</span><h2>${t('landing.how.h2')}</h2></div>
    <div class="steps">
      <div class="step"><div class="n"></div><h4>${t('landing.s1.h4')}</h4><p>${t('landing.s1.p')}</p></div>
      <div class="step"><div class="n"></div><h4>${t('landing.s2.h4')}</h4><p>${t('landing.s2.p')}</p></div>
      <div class="step"><div class="n"></div><h4>${t('landing.s3.h4')}</h4><p>${t('landing.s3.p')}</p></div>
    </div>
  </div>
</section>
<section style="padding-top:0">
  <div class="wrap">
    <div class="sec-head"><span class="eyebrow green">${t('landing.trust.eyebrow')}</span><h2>${t('landing.trust.h2')}</h2></div>
    <div class="trust">
      <div class="t"><div class="k"><span class="ic">&#9670;</span>${t('landing.t1.k')}</div><div class="d">${t('landing.t1.d')}</div></div>
      <div class="t"><div class="k"><span class="ic">&#9670;</span>${t('landing.t2.k')}</div><div class="d">${t('landing.t2.d')}</div></div>
      <div class="t"><div class="k"><span class="ic">&#9670;</span>${t('landing.t3.k')}</div><div class="d">${t('landing.t3.d')}</div></div>
      <div class="t"><div class="k"><span class="ic">&#9670;</span>${t('landing.t4.k')}</div><div class="d">${t('landing.t4.d')}</div></div>
    </div>
  </div>
</section>
<section>
  <div class="wrap">
    <div class="final">
      <span class="eyebrow">${t('landing.final.eyebrow')}</span>
      <h2>${t('landing.final.h2')}</h2>
      <p>${t('landing.final.p')}</p>
      <div class="cta-row"><a class="btn btn-primary btn-lg" href="/auth/login">${TWITCH_SVG} ${t('landing.connect')}</a></div>
      <p class="cta-note" style="margin-top:18px">${t('landing.final.note')}</p>
    </div>
  </div>
</section>
<footer>
  <div class="wrap">
    <div class="foot-inner"><div class="brand"><span class="mark"></span> Stream Intel</div><span class="mono">${t('landing.footer.made')}</span></div>
    <p class="fine">${t('landing.footer.fine')}</p>
  </div>
</footer>
`
}

export default function Landing() {
  useEffect(() => {
    const reduce =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const cards = Array.from(document.querySelectorAll<HTMLElement>('.si-landing .card'))

    if (reduce || !('IntersectionObserver' in window)) {
      cards.forEach((c) => c.classList.add('reveal-in'))
    } else {
      const io = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              const el = entry.target as HTMLElement
              window.setTimeout(() => el.classList.add('reveal-in'), (cards.indexOf(el) % 3) * 80)
              io.unobserve(el)
            }
          })
        },
        { threshold: 0.15 },
      )
      cards.forEach((c) => io.observe(c))
    }

    const animate = (el: HTMLElement, target: number) => {
      const fmt =
        el.getAttribute('data-fmt') === 'int'
          ? (n: number) => fmtInt(Math.round(n))
          : (n: number) => fmtMoney(n)
      if (reduce) {
        el.textContent = fmt(target)
        return
      }
      let start: number | null = null
      const dur = 1400
      const step = (ts: number) => {
        if (start === null) start = ts
        const p = Math.min((ts - start) / dur, 1)
        el.textContent = fmt(target * (1 - Math.pow(1 - p, 3)))
        if (p < 1) requestAnimationFrame(step)
      }
      requestAnimationFrame(step)
    }

    // the hero panel's mock revenue animates on mount; real stats wait on the fetch
    document
      .querySelectorAll<HTMLElement>('.si-landing .panel [data-count]')
      .forEach((el) => animate(el, parseFloat(el.getAttribute('data-count') || '0')))

    const band = document.getElementById('si-stats')
    if (band && typeof fetch === 'function') {
      fetch('/api/stats')
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error('stats'))))
        .then((stats: PlatformStats) => {
          band.style.display = 'grid'
          band.querySelectorAll<HTMLElement>('[data-stat]').forEach((el) => {
            const key = el.getAttribute('data-stat') as keyof PlatformStats | null
            animate(el, key ? (stats[key] ?? 0) : 0)
          })
        })
        .catch(() => {
          /* stats unavailable: leave the band hidden */
        })
    }
  }, [])

  return (
    <div className="si-landing">
      <style dangerouslySetInnerHTML={{ __html: STYLE }} />
      <div dangerouslySetInnerHTML={{ __html: body() }} />
    </div>
  )
}
