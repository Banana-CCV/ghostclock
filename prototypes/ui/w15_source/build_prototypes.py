"""Build self-contained static HTML/JS prototypes proto_A and proto_B for GhostClock W15."""
import json
from pathlib import Path


def build():
    data_path = Path("work/W15/data/cases_illustrative.json")
    bundle = json.loads(data_path.read_text(encoding="utf-8"))
    bundle_json_str = json.dumps(bundle)

    proto_a_dir = Path("work/W15/proto_A")
    proto_b_dir = Path("work/W15/proto_B")
    proto_a_dir.mkdir(parents=True, exist_ok=True)
    proto_b_dir.mkdir(parents=True, exist_ok=True)

    # Shared JS logic for both prototypes (SVG chart renderers, JSON drop-in loader, URL param support, audit export)
    shared_js = """
window.GHOSTCLOCK_BUNDLE = __BUNDLE_JSON__;
window.currentCaseIndex = 0;
window.showFailedAttempt = false;
window.humanGateSelection = null;

function getInitialCaseIndex() {
  const params = new URLSearchParams(window.location.search);
  const c = parseInt(params.get('case') || '0', 10);
  if (!isNaN(c) && c >= 0 && c < window.GHOSTCLOCK_BUNDLE.cases.length) return c;
  return 0;
}

function formatUTC(ts) {
  const d = new Date(ts * 1000);
  return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
}

function statusClass(status) {
  if (status === 'MATCH_SUPPORTED') return 'status-supported';
  if (status === 'INCONCLUSIVE') return 'status-inconclusive';
  return 'status-discrepancy';
}

function renderTraceOverlaySVG(c, height) {
  const w = 780, h = height || 215;
  const padL = 56, padR = 24, padT = 28, padB = 34;
  const pw = w - padL - padR, ph = h - padT - padB;
  const t = c.trace.t;
  const refF = c.reference.aligned_f;
  const att1 = c.investigation_replay[0];
  const traceF = (window.showFailedAttempt && att1 && att1.failed_trace_f) ? att1.failed_trace_f : c.trace.f;
  const traceQ = (window.showFailedAttempt && att1 && att1.failed_trace_q) ? att1.failed_trace_q : c.trace.q;

  const allVals = refF.concat(traceF);
  const minF = Math.min(...allVals, 49.91) - 0.008;
  const maxF = Math.max(...allVals, 50.09) + 0.008;
  const x = (i) => padL + (i / (t.length - 1)) * pw;
  const y = (val) => padT + (1 - (val - minF) / (maxF - minF)) * ph;

  let refPts = refF.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  let trPts = traceF.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');

  let qRects = traceQ.map((q, i) => {
    const col = q >= 0.75 ? '#10b981' : (q >= 0.5 ? '#f59e0b' : '#ef4444');
    const bw = pw / t.length;
    return `<rect x="${(padL + i * bw).toFixed(1)}" y="${h - 10}" width="${Math.max(1, bw - 1).toFixed(1)}" height="5" fill="${col}" opacity="0.85"/>`;
  }).join('');

  const spliceMarker = (c.speed_check && c.speed_check.splice_detected && c.speed_check.splice_time_s)
    ? `<line x1="${x(c.speed_check.splice_time_s)}" y1="${padT}" x2="${x(c.speed_check.splice_time_s)}" y2="${padT+ph}" stroke="#ef4444" stroke-width="2" stroke-dasharray="4,3"/>
       <text x="${x(c.speed_check.splice_time_s)+5}" y="${padT+14}" fill="#ef4444" font-size="10" font-family="JetBrains Mono, monospace" font-weight="700">W13 SPLICE Δφ=142.4° (t=28s)</text>`
    : '';

  const yNom = y(50.0);
  const traceColor = window.showFailedAttempt ? '#ef4444' : (c.match.status === 'INCONCLUSIVE' ? '#f59e0b' : '#38bdf8');
  const modeLabel = window.showFailedAttempt
    ? 'SHOWING REJECTED ATTEMPT 1 TRACE (Unusable Noise / Saturated ROI)'
    : `EXTRACTED ENF TRACE (${c.trace.source.toUpperCase()} · ${c.trace.method}) vs NESO 1s GB REFERENCE`;

  return `<svg viewBox="0 0 ${w} ${h}" class="chart-svg">
    <rect x="0" y="0" width="${w}" height="${h}" fill="#0b101b" rx="6"/>
    <line x1="${padL}" y1="${yNom}" x2="${w-padR}" y2="${yNom}" stroke="#334155" stroke-dasharray="3,3" stroke-width="1"/>
    <text x="${padL-6}" y="${padT+8}" text-anchor="end" fill="#94a3b8" font-size="10" font-family="JetBrains Mono">${maxF.toFixed(3)}</text>
    <text x="${padL-6}" y="${yNom+3}" text-anchor="end" fill="#94a3b8" font-size="10" font-family="JetBrains Mono">50.000</text>
    <text x="${padL-6}" y="${padT+ph}" text-anchor="end" fill="#94a3b8" font-size="10" font-family="JetBrains Mono">${minF.toFixed(3)}</text>
    <text x="${padL}" y="16" fill="#cbd5e1" font-size="10.5" font-weight="600" font-family="JetBrains Mono">${modeLabel}</text>
    <text x="${w-padR}" y="16" text-anchor="end" fill="#fbbf24" font-size="9.5" font-weight="700" font-family="JetBrains Mono">[${c.data_provenance.split('(')[0].trim()}]</text>
    <polyline fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="4,2" points="${refPts}"/>
    <polyline fill="none" stroke="${traceColor}" stroke-width="2.2" points="${trPts}"/>
    ${spliceMarker}
    ${qRects}
    <text x="${padL}" y="${h-14}" fill="#64748b" font-size="9.5" font-family="JetBrains Mono">0s (Window quality strip below: green q≥0.75, amber 0.50–0.74, red &lt;0.50)</text>
    <text x="${w-padR}" y="${h-14}" text-anchor="end" fill="#64748b" font-size="9.5" font-family="JetBrains Mono">${c.trace.duration_s.toFixed(0)}s · RMSE=${c.match.best.rmse_mhz} mHz</text>
  </svg>`;
}

function renderLandscapeSVG(c, height) {
  const w = 780, h = height || 205;
  const padL = 56, padR = 24, padT = 28, padB = 34;
  const pw = w - padL - padR, ph = h - padT - padB;
  const pts = c.match.landscape;
  const minTs = c.claim_context.search_window_utc[0];
  const maxTs = c.claim_context.search_window_utc[1];
  const minS = -0.2, maxS = 1.05;

  const x = (ts) => padL + ((ts - minTs) / (maxTs - minTs)) * pw;
  const y = (s) => padT + (1 - (s - minS) / (maxS - minS)) * ph;

  const poly = pts.map(p => `${x(p.ts_utc).toFixed(1)},${y(p.score).toFixed(1)}`).join(' ');
  const yThresh = y(c.match.null.score_threshold);
  const bestPt = pts.find(p => p.label === 'best_peak') || pts[0];
  const secPt = pts.find(p => p.label === 'second_best') || pts[1];
  const claimTs = c.claim_context.claimed_start_utc;
  const xClaim = x(claimTs);
  const xBest = x(bestPt.ts_utc);
  const peakPass = bestPt.score >= c.match.null.score_threshold;
  const peakColor = peakPass ? '#10b981' : '#f59e0b';

  return `<svg viewBox="0 0 ${w} ${h}" class="chart-svg">
    <rect x="0" y="0" width="${w}" height="${h}" fill="#0b101b" rx="6"/>
    <rect x="${padL}" y="${yThresh}" width="${pw}" height="${padT+ph-yThresh}" fill="#ef4444" opacity="0.07"/>
    <line x1="${padL}" y1="${yThresh}" x2="${w-padR}" y2="${yThresh}" stroke="#f43f5e" stroke-width="1.6" stroke-dasharray="5,4"/>
    <text x="${w-padR-4}" y="${yThresh-5}" text-anchor="end" fill="#fda4af" font-size="10" font-weight="600" font-family="JetBrains Mono">NULL THRESHOLD = ${c.match.null.score_threshold.toFixed(3)} (H0 n=${c.match.null.n}, p=${c.match.null.p_empirical})</text>
    <line x1="${xClaim}" y1="${padT}" x2="${xClaim}" y2="${padT+ph}" stroke="#a855f7" stroke-width="1.6" stroke-dasharray="3,3"/>
    <text x="${Math.min(w-padR-95, Math.max(padL+4, xClaim-40))}" y="${padT+ph-6}" fill="#d8b4fe" font-size="9.5" font-weight="600" font-family="JetBrains Mono">CLAIMED TIME (r=${c.match.diagnostics.claimed_time_score})</text>
    <polyline fill="none" stroke="#475569" stroke-width="1.4" points="${poly}"/>
    <circle cx="${x(secPt.ts_utc)}" cy="${y(secPt.score)}" r="4" fill="#94a3b8"/>
    <text x="${x(secPt.ts_utc)+6}" y="${y(secPt.score)+3}" fill="#94a3b8" font-size="9.5" font-family="JetBrains Mono">2nd Peak (${secPt.score.toFixed(3)})</text>
    <circle cx="${xBest}" cy="${y(bestPt.score)}" r="6" fill="${peakColor}" stroke="#fff" stroke-width="1.5"/>
    <text x="${Math.min(w-padR-150, Math.max(padL+6, xBest+8))}" y="${Math.max(padT+14, y(bestPt.score)-6)}" fill="${peakColor}" font-size="10.5" font-weight="700" font-family="JetBrains Mono">BEST PEAK r=${bestPt.score.toFixed(3)} (Δ=${c.match.uniqueness.margin_vs_second.toFixed(3)})</text>
    <text x="${padL}" y="16" fill="#cbd5e1" font-size="10.5" font-weight="600" font-family="JetBrains Mono">MATCH LANDSCAPE — CORRELATION SCORE vs CANDIDATE START TIME (259,200 CANDIDATES)</text>
    <text x="${padL-6}" y="${padT+8}" text-anchor="end" fill="#94a3b8" font-size="10" font-family="JetBrains Mono">1.00</text>
    <text x="${padL-6}" y="${yThresh+3}" text-anchor="end" fill="#fda4af" font-size="10" font-family="JetBrains Mono">${c.match.null.score_threshold.toFixed(2)}</text>
    <text x="${padL-6}" y="${padT+ph}" text-anchor="end" fill="#94a3b8" font-size="10" font-family="JetBrains Mono">0.00</text>
    <text x="${padL}" y="${h-8}" fill="#64748b" font-size="9.5" font-family="JetBrains Mono">Search Start: ${formatUTC(minTs)}</text>
    <text x="${w-padR}" y="${h-8}" text-anchor="end" fill="#64748b" font-size="9.5" font-family="JetBrains Mono">Search End: ${formatUTC(maxTs)}</text>
  </svg>`;
}

function handleFileUpload(evt) {
  const file = evt.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const obj = JSON.parse(e.target.result);
      if (obj.cases && Array.isArray(obj.cases)) {
        window.GHOSTCLOCK_BUNDLE = obj;
        window.currentCaseIndex = 0;
      } else if (obj.best && obj.status) {
        // Standalone match.json dropped in -> patch current case match
        window.GHOSTCLOCK_BUNDLE.cases[window.currentCaseIndex].match = Object.assign(
          window.GHOSTCLOCK_BUNDLE.cases[window.currentCaseIndex].match, obj
        );
        window.GHOSTCLOCK_BUNDLE.cases[window.currentCaseIndex].data_provenance = "USER_LOADED_JSON (interfaces.md v1)";
      } else if (obj.harmonics_used && obj.quality_summary) {
        // Standalone trace.json dropped in -> patch current case trace
        window.GHOSTCLOCK_BUNDLE.cases[window.currentCaseIndex].trace = Object.assign(
          window.GHOSTCLOCK_BUNDLE.cases[window.currentCaseIndex].trace, obj
        );
        window.GHOSTCLOCK_BUNDLE.cases[window.currentCaseIndex].data_provenance = "USER_LOADED_JSON (interfaces.md v1)";
      }
      renderApp();
    } catch (err) {
      alert("Invalid JSON file: " + err.message);
    }
  };
  reader.readAsText(file);
}

function exportAuditLog() {
  const c = window.GHOSTCLOCK_BUNDLE.cases[window.currentCaseIndex];
  const noteEl = document.getElementById('investigator-note');
  const exportPayload = {
    export_timestamp_utc: new Date().toISOString(),
    schema_version: "interfaces.md.v1",
    data_provenance: c.data_provenance,
    regulatory_compliance: "FCA ICOBS 8.1.1R & UK GDPR Chain-of-Custody — GhostClock cannot deny a claim or allege fraud.",
    case_id: c.case_id,
    intake: c.intake,
    investigation_replay: c.investigation_replay,
    trace_summary: {
      source: c.trace.source,
      method: c.trace.method,
      nominal_hz: c.trace.nominal_hz,
      harmonics_used: c.trace.harmonics_used,
      quality_summary: c.trace.quality_summary,
      provenance: c.trace.provenance
    },
    reference: {
      source: c.reference.source,
      cadence_s: c.reference.cadence_s,
      grid: c.reference.grid,
      coverage: c.reference.coverage,
      sha256: c.reference.sha256
    },
    match: {
      best: c.match.best,
      null: c.match.null,
      uniqueness: c.match.uniqueness,
      status: c.match.status,
      status_reasons: c.match.status_reasons,
      what_would_change_this: c.match.what_would_change_this
    },
    speed_check_w13: c.speed_check,
    human_review_gate: {
      selected_action: window.humanGateSelection || "PENDING_HUMAN_SIGN_OFF",
      investigator_rationale: noteEl ? noteEl.value : "",
      automated_claim_denial_blocked: true
    }
  };
  const modal = document.getElementById('export-modal');
  const pre = document.getElementById('export-json-preview');
  if (modal && pre) {
    pre.textContent = JSON.stringify(exportPayload, null, 2);
    modal.style.display = 'flex';
  }
}
""".replace("__BUNDLE_JSON__", bundle_json_str)

    # -------------------------------------------------------------------------
    # PROTOTYPE A: "Case File & Investigation Dossier" Layout
    # -------------------------------------------------------------------------
    proto_a_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GhostClock — Prototype A: Case File & SIU Investigation Dossier</title>
<style>
  :root {{
    --bg: #0f172a;
    --panel: #1e293b;
    --panel-alt: #162032;
    --border: #334155;
    --text: #f8fafc;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --green: #10b981;
    --amber: #f59e0b;
    --red: #f43f5e;
    --purple: #a855f7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 13px;
    line-height: 1.45;
  }}
  code, pre, .mono {{ font-family: 'JetBrains Mono', 'Consolas', monospace; }}
  .top-banner {{
    background: #422006;
    border-bottom: 1px solid #f59e0b;
    color: #fde68a;
    padding: 6px 18px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11.5px;
    font-weight: 600;
  }}
  .header {{
    background: #090d16;
    border-bottom: 1px solid var(--border);
    padding: 12px 18px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }}
  .brand {{ display: flex; align-items: center; gap: 12px; }}
  .brand-badge {{
    background: rgba(56, 189, 248, 0.15);
    border: 1px solid var(--accent);
    color: var(--accent);
    padding: 4px 8px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 0.06em;
  }}
  .case-tabs {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .case-tab {{
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 6px 11px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 11.5px;
    font-weight: 600;
  }}
  .case-tab.active {{
    background: rgba(56, 189, 248, 0.16);
    border-color: var(--accent);
    color: #fff;
  }}
  .layout-grid {{
    display: grid;
    grid-template-columns: 335px 1fr 375px;
    gap: 10px;
    padding: 9px 16px;
    max-width: 1720px;
    margin: 0 auto;
  }}
  .col {{ display: flex; flex-direction: column; gap: 8px; }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 9px 11px;
  }}
  .card-title {{
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--accent);
    font-weight: 700;
    margin-bottom: 6px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .kv-row {{
    display: flex;
    justify-content: space-between;
    padding: 2.5px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    font-size: 11.5px;
  }}
  .kv-label {{ color: var(--muted); }}
  .kv-val {{ font-weight: 600; text-align: right; }}
  .blinding-box {{
    background: rgba(16, 185, 129, 0.1);
    border: 1px solid rgba(16, 185, 129, 0.45);
    border-radius: 6px;
    padding: 6px 8px;
    margin-top: 5px;
    color: #a7f3d0;
    font-size: 11px;
  }}
  .replay-step {{
    background: var(--panel-alt);
    border-left: 3px solid var(--border);
    border-radius: 5px;
    padding: 7px 9px;
    margin-bottom: 6px;
  }}
  .replay-step.rejected {{ border-left-color: var(--red); }}
  .replay-step.accepted {{ border-left-color: var(--green); }}
  .replay-step.safeguard {{ border-left-color: var(--amber); }}
  .outcome-pill {{
    display: inline-block;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 700;
  }}
  .pill-rejected {{ background: rgba(244,63,94,0.2); color: #fda4af; border: 1px solid var(--red); }}
  .pill-accepted {{ background: rgba(16,185,129,0.2); color: #6ee7b7; border: 1px solid var(--green); }}
  .pill-safeguard {{ background: rgba(245,158,11,0.2); color: #fde68a; border: 1px solid var(--amber); }}
  .chart-svg {{ width: 100%; height: auto; display: block; border: 1px solid #1e293b; border-radius: 6px; }}
  .status-banner {{
    padding: 12px;
    border-radius: 7px;
    margin-bottom: 10px;
    border: 2px solid;
  }}
  .status-discrepancy {{ background: rgba(244,63,94,0.12); border-color: var(--red); color: #fecdd3; }}
  .status-inconclusive {{ background: rgba(245,158,11,0.14); border-color: var(--amber); color: #fef3c7; }}
  .status-supported {{ background: rgba(16,185,129,0.12); border-color: var(--green); color: #d1fae5; }}
  .bullet-list {{ padding-left: 16px; font-size: 12px; }}
  .bullet-list li {{ margin-bottom: 5px; }}
  .gate-btn {{
    width: 100%;
    text-align: left;
    padding: 9px 11px;
    margin-bottom: 6px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--panel-alt);
    color: #fff;
    cursor: pointer;
    font-weight: 600;
    font-size: 12px;
  }}
  .gate-btn.selected {{ border-color: var(--accent); background: rgba(56,189,248,0.2); }}
  .gate-btn.disabled-denial {{
    opacity: 0.48;
    cursor: not-allowed;
    border-color: #7f1d1d;
    background: rgba(127,29,29,0.2);
    color: #fca5a5;
  }}
  .btn-action {{
    background: var(--accent);
    color: #0f172a;
    border: none;
    padding: 8px 12px;
    border-radius: 6px;
    font-weight: 700;
    cursor: pointer;
    font-size: 12px;
  }}
  .btn-secondary {{
    background: transparent;
    color: var(--accent);
    border: 1px solid var(--accent);
    padding: 5px 10px;
    border-radius: 5px;
    font-weight: 600;
    cursor: pointer;
    font-size: 11px;
  }}
  #export-modal {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.75);
    align-items: center;
    justify-content: center;
    z-index: 100;
  }}
  .modal-box {{
    background: var(--panel);
    border: 1px solid var(--accent);
    border-radius: 8px;
    width: 760px;
    max-height: 82vh;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
</style>
</head>
<body>
<div class="top-banner">
  <span id="provenance-banner">DATA PROVENANCE: ILLUSTRATIVE — SYNTHETIC FIXTURE (NO LIVE MEASUREMENT CLAIMED)</span>
  <span>INTERFACE CONTRACT: integration/interfaces.md v1 · SCIENTIFIC RULE #3 &amp; #8 ENFORCED IN CODE</span>
</div>

<div class="header">
  <div class="brand">
    <span class="brand-badge">PROTOTYPE A · CASE FILE DOSSIER</span>
    <div>
      <div style="font-size:16px;font-weight:800;">GhostClock Forensic Evidence Corroboration Console</div>
      <div style="font-size:11.5px;color:var(--muted);">Gemini 4 Argon Investigative Planner · Deterministic Signal &amp; Null-Calibrated Verifier · UK Insurance SIU Triage</div>
    </div>
  </div>
  <div class="case-tabs" id="case-tabs"></div>
  <div>
    <label class="btn-secondary" style="display:inline-block;">
      Load interfaces.md JSON <input type="file" accept=".json" style="display:none;" onchange="handleFileUpload(event)">
    </label>
  </div>
</div>

<div class="layout-grid" id="app-root"></div>

<div id="export-modal">
  <div class="modal-box">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <strong style="color:var(--accent);">Immutable Forensic Evidence &amp; Chain-of-Custody Log (interfaces.md v1)</strong>
      <button class="btn-secondary" onclick="document.getElementById('export-modal').style.display='none'">Close</button>
    </div>
    <pre id="export-json-preview" style="background:#090d16;padding:12px;border-radius:6px;overflow:auto;max-height:60vh;font-size:11px;color:#a7f3d0;"></pre>
  </div>
</div>

<script>
{shared_js}

function selectCase(idx) {{
  window.currentCaseIndex = idx;
  window.showFailedAttempt = false;
  renderApp();
}}

function toggleAttemptOverlay() {{
  window.showFailedAttempt = !window.showFailedAttempt;
  renderApp();
}}

function selectGate(act) {{
  window.humanGateSelection = act;
  renderApp();
}}

function renderApp() {{
  const cases = window.GHOSTCLOCK_BUNDLE.cases;
  const c = cases[window.currentCaseIndex];
  document.getElementById('provenance-banner').textContent = 'DATA PROVENANCE: ' + c.data_provenance + ' · FICTIONAL CLAIM SCENARIO';

  const tabsEl = document.getElementById('case-tabs');
  tabsEl.innerHTML = cases.map((item, idx) =>
    `<button class="case-tab ${{idx === window.currentCaseIndex ? 'active' : ''}}" onclick="selectCase(${{idx}})">${{item.case_id}}: ${{item.scenario_type}}</button>`
  ).join('');

  const replayHtml = c.investigation_replay.map(step => {{
    const cls = step.verifier_outcome === 'REJECTED' ? 'rejected' : (step.verifier_outcome === 'ACCEPTED' ? 'accepted' : 'safeguard');
    const pillCls = step.verifier_outcome === 'REJECTED' ? 'pill-rejected' : (step.verifier_outcome === 'ACCEPTED' ? 'pill-accepted' : 'pill-safeguard');
    return `<div class="replay-step ${{cls}}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
        <strong>Attempt #${{step.attempt_id}} — ${{step.stage}}</strong>
        <span class="outcome-pill ${{pillCls}}">VERIFIER: ${{step.verifier_outcome}}</span>
      </div>
      <div style="font-size:11.5px;color:#cbd5e1;margin-bottom:4px;"><b>Argon Hypothesis:</b> ${{step.argon_hypothesis}}</div>
      <div class="mono" style="font-size:11px;background:#090d16;padding:4px 7px;border-radius:4px;color:#38bdf8;margin-bottom:5px;">Tool Call: ${{step.tool_call}}</div>
      <div style="font-size:11.5px;color:#fde68a;"><b>Deterministic Gate (${{step.verifier_rule_triggered}}):</b> ${{step.verifier_reason}}</div>
      <div class="mono" style="font-size:10.5px;color:var(--muted);margin-top:4px;">Measured Diagnostics: median_q=${{step.metrics.median_q}} · frac_valid=${{step.metrics.frac_valid}} · snr_db=${{step.metrics.snr_db}} dB</div>
    </div>`;
  }}).join('');

  const hasFailedTrace = c.investigation_replay[0] && c.investigation_replay[0].failed_trace_f;

  document.getElementById('app-root').innerHTML = `
    <!-- LEFT COLUMN: Claim Context & Blinded Evidence Intake -->
    <div class="col">
      <div class="card">
        <div class="card-title"><span>1. Claim Dossier (Fictional)</span><span class="mono">${{c.claim_context.claim_id.split(' ')[0]}}</span></div>
        <div class="kv-row"><span class="kv-label">Named User Role</span><span class="kv-val">${{c.claim_context.named_user}}</span></div>
        <div class="kv-row"><span class="kv-label">Policy Type</span><span class="kv-val">${{c.claim_context.policy_type}}</span></div>
        <div class="kv-row"><span class="kv-label">Claim Reserve</span><span class="kv-val" style="color:#fbbf24;">£${{c.claim_context.reserve_gbp.toLocaleString()}} (Illustrative)</span></div>
        <div class="kv-row"><span class="kv-label">Claimant Stated Time</span><span class="kv-val mono">${{c.claim_context.claimed_start_iso}}</span></div>
        <div class="kv-row"><span class="kv-label">ENF Corroborated Time</span><span class="kv-val mono" style="color:var(--accent);">${{c.claim_context.matched_start_iso}}</span></div>
        <div style="margin-top:8px;font-size:11.5px;color:#cbd5e1;background:var(--panel-alt);padding:8px;border-radius:5px;">
          <b>Financial Decision at Stake:</b> ${{c.claim_context.financial_decision}}
        </div>
      </div>

      <div class="card">
        <div class="card-title"><span>2. Evidence Intake &amp; Blinding Lock</span><span>FFprobe</span></div>
        <div class="kv-row"><span class="kv-label">Media File</span><span class="kv-val mono">${{c.intake.media_filename}}</span></div>
        <div class="kv-row"><span class="kv-label">SHA-256 Digest</span><span class="kv-val mono" style="font-size:10.5px;">${{c.intake.media_sha256.substring(0,24)}}…</span></div>
        <div class="kv-row"><span class="kv-label">Container / Video</span><span class="kv-val">${{c.intake.probe.codec_video}}</span></div>
        <div class="kv-row"><span class="kv-label">Audio Track</span><span class="kv-val">${{c.intake.probe.codec_audio}}</span></div>
        <div class="kv-row"><span class="kv-label">Duration / Frame Rate</span><span class="kv-val mono">${{c.intake.probe.duration_s}}s @ ${{c.intake.probe.fps}} fps (VFR=${{c.intake.probe.is_vfr}})</span></div>
        <div class="kv-row"><span class="kv-label">CMOS Row Readout</span><span class="kv-val mono">${{c.intake.probe.row_readout_us}} µs/row (${{c.intake.probe.resolution}})</span></div>
        <div class="blinding-box">
          <strong>🔒 ${{c.intake.blinding.notice}}</strong>
          <div style="margin-top:4px;font-size:10.5px;color:#d1fae5;">Withheld tags: ${{c.intake.blinding.stripped_fields.join(' · ')}}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-title"><span>3. W13 Speed &amp; Splice Audit</span><span class="mono">Nominal 50.000 Hz</span></div>
        <div class="kv-row"><span class="kv-label">Estimated ENF Carrier</span><span class="kv-val mono">${{c.speed_check.estimated_carrier_hz.toFixed(3)}} Hz</span></div>
        <div class="kv-row"><span class="kv-label">Playback Speed Ratio (α)</span><span class="kv-val mono">${{c.speed_check.speed_ratio_alpha.toFixed(5)}}x</span></div>
        <div class="kv-row"><span class="kv-label">Apparent vs True Duration</span><span class="kv-val mono">${{c.speed_check.apparent_duration_s}}s / ${{c.speed_check.true_duration_s}}s</span></div>
        <div class="kv-row"><span class="kv-label">Phase Jump / Splice</span><span class="kv-val mono" style="color:${{c.speed_check.splice_detected ? '#f43f5e' : '#10b981'}};">${{c.speed_check.splice_detected ? 'YES (t=' + c.speed_check.splice_time_s + 's, Δφ=' + c.speed_check.phase_jump_deg + '°)' : 'NONE (' + c.speed_check.phase_jump_deg + '° max)'}}</span></div>
        <div style="margin-top:6px;font-size:11px;font-weight:700;color:${{c.speed_check.splice_detected ? '#fda4af' : '#6ee7b7'}};">${{c.speed_check.verdict}}</div>
      </div>
    </div>

    <!-- CENTER COLUMN: Argon Investigation Replay & Physical Signal Match -->
    <div class="col">
      <div class="card">
        <div class="card-title">
          <span>4. Argon Investigation Replay (Propose → Verifier Reject → Revise)</span>
          ${{hasFailedTrace ? `<button class="btn-secondary" onclick="toggleAttemptOverlay()">${{window.showFailedAttempt ? 'Show Accepted Attempt 2 Trace' : 'Inspect Rejected Attempt 1 Trace'}}</button>` : ''}}
        </div>
        ${{replayHtml}}
      </div>

      <div class="card">
        <div class="card-title">
          <span>5. Extracted ENF Sequence vs. Independent Grid Reference (${{c.reference.source}} ${{c.reference.grid}} ${{c.reference.cadence_s}}s)</span>
          <span class="mono">Harmonics: [${{c.trace.harmonics_used.join(', ')}} Hz]</span>
        </div>
        ${{renderTraceOverlaySVG(c, 165)}}
        <div style="margin-top:4px;font-size:10.5px;color:#94a3b8;display:flex;justify-content:space-between;">
          <span>⚠️ <b>Non-Independence Rule:</b> ${{c.trace.visual_corroboration_note}}</span>
        </div>
      </div>

      <div class="card">
        <div class="card-title">
          <span>6. Blinded Search-Space Match Landscape &amp; Null Calibration</span>
          <span class="mono">Window: ${{c.claim_context.search_window_label}}</span>
        </div>
        ${{renderLandscapeSVG(c, 165)}}
      </div>
    </div>

    <!-- RIGHT COLUMN: Code-Enforced Decision Badge, Counterfactuals & Human Gate -->
    <div class="col">
      <div class="card">
        <div class="card-title"><span>7. Code-Enforced Decision Gate</span><span class="mono">LLM Cannot Override</span></div>
        <div class="status-banner ${{statusClass(c.match.status)}}">
          <div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.08em;font-weight:700;">DETERMINISTIC VERIFIER STATUS</div>
          <div class="mono" style="font-size:16px;font-weight:800;margin:3px 0;">${{c.match.status}}</div>
          <div style="font-size:11px;">Best r = ${{c.match.best.score.toFixed(3)}} (Null gate = ${{c.match.null.score_threshold.toFixed(3)}}, p = ${{c.match.null.p_empirical}}) · Margin Δ = ${{c.match.uniqueness.margin_vs_second.toFixed(3)}}</div>
        </div>
        <div style="font-weight:700;font-size:11.5px;margin-bottom:5px;color:#e2e8f0;">Auditable Decision Reasons:</div>
        <ul class="bullet-list">
          ${{c.match.status_reasons.map(r => `<li>${{r}}</li>`).join('')}}
        </ul>
      </div>

      <div class="card">
        <div class="card-title"><span>8. Counterfactuals: What Would Change This?</span><span>Traceability</span></div>
        <ul class="bullet-list" style="color:#bae6fd;">
          ${{c.match.what_would_change_this.map(w => `<li>${{w}}</li>`).join('')}}
        </ul>
      </div>

      <div class="card">
        <div class="card-title"><span>9. Human-in-the-Loop Decision Gate</span><span>FCA ICOBS 8.1.1R</span></div>
        <button class="gate-btn ${{window.humanGateSelection === 'APPROVE_STANDARD' ? 'selected' : ''}}" onclick="selectGate('APPROVE_STANDARD')">
          ✅ Clear Evidence for Standard Claim Settlement
        </button>
        <button class="gate-btn ${{window.humanGateSelection === 'HOLD_AND_REQUEST_RAW' ? 'selected' : ''}}" onclick="selectGate('HOLD_AND_REQUEST_RAW')">
          ⏸️ Hold Payout &amp; Request Original Camera Card / Utility Logs
        </button>
        <button class="gate-btn ${{window.humanGateSelection === 'ESCALATE_SIU' ? 'selected' : ''}}" onclick="selectGate('ESCALATE_SIU')">
          🔍 Escalate to Special Investigations Unit (SIU) Forensic Review
        </button>
        <button class="gate-btn disabled-denial" disabled title="Hardcoded Regulatory Guardrail: GhostClock cannot deny a claim">
          🚫 Auto-Deny Claim / Allege Fraud (BLOCKED IN CODE — FCA ICOBS 8)
        </button>
        <textarea id="investigator-note" rows="2" placeholder="Enter mandatory human investigator rationale before exporting audit log..." style="width:100%;margin-top:6px;background:#090d16;border:1px solid var(--border);color:#fff;padding:7px;border-radius:5px;font-size:11.5px;">Reviewer verified ENF match landscape and null threshold calibration.</textarea>
        <div style="margin-top:8px;display:flex;justify-content:space-between;align-items:center;">
          <button class="btn-action" style="width:100%;" onclick="exportAuditLog()">Export Signed Evidence Log (.JSON)</button>
        </div>
      </div>
    </div>
  `;
}}

window.currentCaseIndex = getInitialCaseIndex();
renderApp();
</script>
</body>
</html>
"""

    # -------------------------------------------------------------------------
    # PROTOTYPE B: "Signal Lab & Multi-Modal Workbench" Layout
    # -------------------------------------------------------------------------
    proto_b_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GhostClock — Prototype B: Signal Lab & Multi-Modal Forensic Workbench</title>
<style>
  :root {{
    --bg: #060911;
    --panel: #0d1322;
    --panel-hi: #131c31;
    --border: #1e293b;
    --accent: #22d3ee;
    --amber: #fbbf24;
    --green: #34d399;
    --red: #fb7185;
    --text: #f1f5f9;
    --muted: #94a3b8;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 12.5px;
  }}
  .mono, code, pre {{ font-family: 'JetBrains Mono', 'Consolas', monospace; }}
  .lab-topbar {{
    background: #04060c;
    border-bottom: 1px solid var(--border);
    padding: 8px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
  }}
  .prov-pill {{
    background: rgba(251, 191, 36, 0.15);
    border: 1px solid var(--amber);
    color: var(--amber);
    padding: 3px 9px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
  }}
  .PresetBar {{ display: flex; gap: 6px; }}
  .preset-btn {{
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 5px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
    font-weight: 600;
  }}
  .preset-btn.active {{
    border-color: var(--accent);
    color: var(--accent);
    background: rgba(34, 211, 238, 0.12);
  }}
  .workbench-grid {{
    display: grid;
    grid-template-columns: 410px 1fr 360px;
    grid-template-rows: auto auto;
    gap: 10px;
    padding: 10px 16px;
    max-width: 1740px;
    margin: 0 auto;
  }}
  .pane {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 11px;
  }}
  .pane-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--accent);
    border-bottom: 1px solid var(--border);
    padding-bottom: 6px;
    margin-bottom: 8px;
  }}
  .chart-svg {{ width: 100%; height: auto; display: block; }}
  .status-supported {{ color: var(--green); border-color: var(--green); }}
  .status-inconclusive {{ color: var(--amber); border-color: var(--amber); }}
  .status-discrepancy {{ color: var(--red); border-color: var(--red); }}
  .badge-large {{
    padding: 8px 10px;
    border: 1.5px solid;
    border-radius: 6px;
    background: rgba(15, 23, 42, 0.7);
    margin-bottom: 8px;
  }}
  .cand-table {{ width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 6px; }}
  .cand-table th, .cand-table td {{ padding: 4px 6px; border-bottom: 1px solid var(--border); text-align: left; }}
  .cand-table th {{ color: var(--muted); }}
  .action-chip {{
    display: block;
    width: 100%;
    text-align: left;
    padding: 7px 9px;
    margin-bottom: 5px;
    background: var(--panel-hi);
    border: 1px solid var(--border);
    color: #fff;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11.5px;
    font-weight: 600;
  }}
  .action-chip.selected {{ border-color: var(--accent); background: rgba(34,211,238,0.18); }}
  .action-chip.blocked {{ opacity: 0.45; cursor: not-allowed; color: #fda4af; border-color: #881337; }}
  #export-modal {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.8);
    align-items: center;
    justify-content: center;
    z-index: 100;
  }}
</style>
</head>
<body>
<div class="lab-topbar">
  <div style="display:flex;align-items:center;gap:10px;">
    <span style="background:#083344;color:#22d3ee;border:1px solid #22d3ee;padding:3px 8px;border-radius:4px;font-weight:800;font-size:11px;">PROTOTYPE B · SIGNAL LAB WORKBENCH</span>
    <strong style="font-size:14px;">GhostClock Multi-Modal ENF Analyzer &amp; Rolling-Shutter Lab</strong>
  </div>
  <div class="PresetBar" id="preset-bar"></div>
  <div style="display:flex;align-items:center;gap:8px;">
    <span class="prov-pill" id="lab-prov">ILLUSTRATIVE — SYNTHETIC FIXTURE</span>
    <label style="border:1px solid var(--accent);color:var(--accent);padding:4px 8px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:600;">
      Drop-in JSON <input type="file" accept=".json" style="display:none;" onchange="handleFileUpload(event)">
    </label>
  </div>
</div>

<div class="workbench-grid" id="lab-root"></div>

<div id="export-modal">
  <div style="background:var(--panel);border:1px solid var(--accent);padding:16px;border-radius:8px;width:760px;max-height:80vh;display:flex;flex-direction:column;gap:8px;">
    <div style="display:flex;justify-content:space-between;">
      <strong style="color:var(--accent);">Signed Forensic Audit Bundle (interfaces.md v1)</strong>
      <button onclick="document.getElementById('export-modal').style.display='none'" style="background:none;border:1px solid var(--accent);color:var(--accent);padding:3px 8px;cursor:pointer;">Close</button>
    </div>
    <pre id="export-json-preview" style="background:#04060c;padding:10px;overflow:auto;max-height:60vh;color:#6ee7b7;font-size:11px;"></pre>
  </div>
</div>

<script>
{shared_js}

function selectCase(idx) {{
  window.currentCaseIndex = idx;
  window.showFailedAttempt = false;
  renderApp();
}}

function renderRollingShutterViewport(c) {{
  const isRejected1 = c.investigation_replay.length > 1;
  return `<svg viewBox="0 0 380 210" class="chart-svg">
    <rect x="0" y="0" width="380" height="210" fill="#070b14" rx="5"/>
    <!-- Simulated CMOS Rolling Shutter Ridges -->
    <g opacity="0.35">
      <rect x="12" y="18" width="356" height="12" fill="#1e293b"/>
      <rect x="12" y="42" width="356" height="12" fill="#334155"/>
      <rect x="12" y="66" width="356" height="12" fill="#1e293b"/>
      <rect x="12" y="90" width="356" height="12" fill="#334155"/>
      <rect x="12" y="114" width="356" height="12" fill="#1e293b"/>
      <rect x="12" y="138" width="356" height="12" fill="#334155"/>
      <rect x="12" y="162" width="356" height="12" fill="#1e293b"/>
    </g>
    <!-- ROI 1: Rejected Ceiling Fixture -->
    <rect x="28" y="20" width="320" height="44" fill="rgba(244,63,94,0.12)" stroke="#f43f5e" stroke-width="1.5" stroke-dasharray="4,2"/>
    <text x="34" y="35" fill="#fda4af" font-size="9.5" font-family="JetBrains Mono" font-weight="700">ROI #1 (Attempt 1): REJECTED BY VERIFIER</text>
    <text x="34" y="50" fill="#fecdd3" font-size="9" font-family="JetBrains Mono">Reason: Clipping / DC Inverter (frac_valid=0.31 &lt; 0.60)</text>
    <!-- ROI 2: Accepted Static Wall / Acoustic Environment -->
    <rect x="28" y="82" width="320" height="86" fill="rgba(34,211,238,0.10)" stroke="#22d3ee" stroke-width="1.5"/>
    <text x="34" y="98" fill="#22d3ee" font-size="9.5" font-family="JetBrains Mono" font-weight="700">ROI #2 + AUDIO HARMONICS [${{c.trace.harmonics_used.join(',')}} Hz]</text>
    <text x="34" y="113" fill="#bae6fd" font-size="9" font-family="JetBrains Mono">CMOS Row Readout: ${{c.intake.probe.row_readout_us}} µs · VFR=${{c.intake.probe.is_vfr}}</text>
    <text x="34" y="128" fill="#6ee7b7" font-size="9" font-family="JetBrains Mono">Quality: median_q=${{c.trace.quality_summary.median_q}} · SNR=${{c.trace.quality_summary.snr_db}} dB</text>
    <text x="34" y="146" fill="#fde68a" font-size="8.5" font-family="JetBrains Mono">🔒 BLINDED: EXIF, OSD Clocks &amp; Claimed Time Masked</text>
    <text x="14" y="198" fill="#94a3b8" font-size="9" font-family="JetBrains Mono">SHA-256: ${{c.intake.media_sha256.substring(0,36)}}…</text>
  </svg>`;
}}

function renderApp() {{
  const cases = window.GHOSTCLOCK_BUNDLE.cases;
  const c = cases[window.currentCaseIndex];
  document.getElementById('lab-prov').textContent = c.data_provenance;

  document.getElementById('preset-bar').innerHTML = cases.map((item, idx) =>
    `<button class="preset-btn ${{idx === window.currentCaseIndex ? 'active' : ''}}" onclick="selectCase(${{idx}})">[${{idx+1}}] ${{item.case_id}} (${{item.match.status}})</button>`
  ).join('');

  const candsHtml = c.match.candidates.map(cand => `
    <tr>
      <td class="mono">#${{cand.rank}}</td>
      <td class="mono">${{cand.iso}}</td>
      <td class="mono" style="font-weight:700;color:${{cand.rank===1?'#22d3ee':'#94a3b8'}};">${{cand.score.toFixed(3)}}</td>
      <td class="mono">${{cand.rmse_mhz}} mHz</td>
    </tr>
  `).join('');

  const replayRows = c.investigation_replay.map(st => `
    <div style="background:#070b14;border-left:3px solid ${{st.verifier_outcome==='ACCEPTED'?'#34d399':(st.verifier_outcome==='REJECTED'?'#fb7185':'#fbbf24')}};padding:7px;margin-bottom:6px;border-radius:4px;">
      <div style="display:flex;justify-content:space-between;font-size:11px;font-weight:700;">
        <span>Attempt #${{st.attempt_id}}: ${{st.stage}}</span>
        <span class="mono" style="color:${{st.verifier_outcome==='ACCEPTED'?'#34d399':(st.verifier_outcome==='REJECTED'?'#fb7185':'#fbbf24')}};">${{st.verifier_outcome}}</span>
      </div>
      <div class="mono" style="font-size:10px;color:#38bdf8;margin:3px 0;">${{st.tool_call}}</div>
      <div style="font-size:11px;color:#cbd5e1;">${{st.verifier_reason}}</div>
    </div>
  `).join('');

  document.getElementById('lab-root').innerHTML = `
    <!-- LEFT PANE: Optical/Acoustic Sensor Viewport & Argon Tool Trace -->
    <div class="pane">
      <div class="pane-header"><span>A. Optical Rolling-Shutter &amp; Acoustic Probe</span><span class="mono">${{c.intake.media_filename}}</span></div>
      ${{renderRollingShutterViewport(c)}}
      <div style="margin-top:8px;padding:7px;background:#070b14;border:1px solid #1e293b;border-radius:4px;font-size:11px;">
        <div style="color:#34d399;font-weight:700;">🔒 ${{c.intake.blinding.notice}}</div>
        <div class="mono" style="font-size:10px;color:var(--muted);margin-top:3px;">Container: ${{c.intake.probe.container}} · ${{c.intake.probe.codec_video}} · ${{c.intake.probe.codec_audio}}</div>
      </div>

      <div class="pane-header" style="margin-top:10px;">
        <span>B. Argon Autonomous Loop &amp; Verifier Gates</span>
        <button onclick="window.showFailedAttempt=!window.showFailedAttempt;renderApp();" style="background:#131c31;border:1px solid var(--accent);color:var(--accent);padding:2px 6px;border-radius:3px;cursor:pointer;font-size:10px;">
          ${{window.showFailedAttempt ? 'View Accepted Trace' : 'Overlay Failed Attempt 1'}}
        </button>
      </div>
      ${{replayRows}}

      <div class="pane-header" style="margin-top:10px;"><span>C. W13 Carrier Speed &amp; Phase Continuity</span><span class="mono">α=${{c.speed_check.speed_ratio_alpha.toFixed(4)}}x</span></div>
      <div class="mono" style="font-size:11px;background:#070b14;padding:8px;border-radius:4px;border:1px solid ${{c.speed_check.splice_detected?'#fb7185':'#1e293b'}};">
        <div>Carrier: <b>${{c.speed_check.estimated_carrier_hz.toFixed(3)}} Hz</b> (Nominal ${{c.speed_check.nominal_hz.toFixed(1)}} Hz)</div>
        <div>Duration: Apparent ${{c.speed_check.apparent_duration_s}}s vs True ${{c.speed_check.true_duration_s}}s</div>
        <div style="color:${{c.speed_check.splice_detected?'#fb7185':'#34d399'}};margin-top:3px;font-weight:700;">${{c.speed_check.verdict}}</div>
      </div>
    </div>

    <!-- CENTER PANE: Synchronized Signal Trace + Match Landscape + Top-K Table -->
    <div class="pane">
      <div class="pane-header">
        <span>D. Synchronized Fundamental-Equivalent ENF Trace (Hz) vs. NESO 1s Reference</span>
        <span class="mono">Grid: ${{c.reference.grid}} (${{c.reference.source}})</span>
      </div>
      ${{renderTraceOverlaySVG(c, 225)}}
      <div style="font-size:10.5px;color:#94a3b8;margin:5px 0 10px 0;">
        <b>Scientific Ground Truth #3:</b> ${{c.trace.visual_corroboration_note}}
      </div>

      <div class="pane-header">
        <span>E. Full Search-Window Cross-Correlation Landscape &amp; H0 Null Threshold</span>
        <span class="mono">DOF=${{c.match.diagnostics.effective_dof}} · Sub-segments: ${{c.match.diagnostics.sub_segment_consistency.split(':')[0]}}</span>
      </div>
      ${{renderLandscapeSVG(c, 215)}}

      <table class="cand-table">
        <thead><tr><th>Rank</th><th>Candidate UTC Alignment</th><th>Correlation (r)</th><th>RMSE (mHz)</th></tr></thead>
        <tbody>${{candsHtml}}</tbody>
      </table>
    </div>

    <!-- RIGHT PANE: Deterministic Status, Counterfactuals & Human Review Gate -->
    <div class="pane">
      <div class="pane-header"><span>F. Deterministic Verifier Verdict</span><span class="mono">Code-Gated</span></div>
      <div class="badge-large ${{statusClass(c.match.status)}}">
        <div style="font-size:10px;opacity:0.85;">CODE-ENFORCED DECISION STATUS</div>
        <div class="mono" style="font-size:15.5px;font-weight:800;margin:2px 0;">${{c.match.status}}</div>
        <div class="mono" style="font-size:10.5px;">Claimed: ${{c.claim_context.claimed_start_iso}} | Matched: ${{c.claim_context.matched_start_iso}}</div>
      </div>

      <div style="font-size:11px;font-weight:700;color:var(--accent);margin-bottom:4px;">VERIFIER REASONS:</div>
      <ul style="padding-left:15px;font-size:11px;margin-bottom:10px;">
        ${{c.match.status_reasons.map(r => `<li style="margin-bottom:4px;">${{r}}</li>`).join('')}}
      </ul>

      <div style="font-size:11px;font-weight:700;color:#fbbf24;margin-bottom:4px;">WHAT WOULD CHANGE THIS FINDING?</div>
      <ul style="padding-left:15px;font-size:11px;color:#fde68a;margin-bottom:10px;">
        ${{c.match.what_would_change_this.map(w => `<li style="margin-bottom:4px;">${{w}}</li>`).join('')}}
      </ul>

      <div class="pane-header"><span>G. Human Investigator Gate (ICOBS 8)</span><span class="mono">£${{c.claim_context.reserve_gbp.toLocaleString()}}</span></div>
      <button class="action-chip ${{window.humanGateSelection==='CLEAR'?'selected':''}}" onclick="window.humanGateSelection='CLEAR';renderApp();">1. Approve Evidence for Standard Settlement</button>
      <button class="action-chip ${{window.humanGateSelection==='REQUEST_RAW'?'selected':''}}" onclick="window.humanGateSelection='REQUEST_RAW';renderApp();">2. Hold &amp; Request Original Uncompressed Media</button>
      <button class="action-chip ${{window.humanGateSelection==='SIU_ESCALATE'?'selected':''}}" onclick="window.humanGateSelection='SIU_ESCALATE';renderApp();">3. Escalate Discrepancy to SIU Specialist</button>
      <button class="action-chip blocked" disabled>4. Deny Claim / Allege Fraud (DISABLED IN CODE)</button>
      <textarea id="investigator-note" rows="2" style="width:100%;background:#04060c;border:1px solid var(--border);color:#fff;padding:6px;font-size:11px;margin-top:4px;">Signal Lab telemetry audited; null threshold and W13 speed-check verified.</textarea>
      <button onclick="exportAuditLog()" style="width:100%;margin-top:6px;background:var(--accent);color:#04060c;border:none;padding:8px;border-radius:4px;font-weight:800;cursor:pointer;font-size:11.5px;">
        Export Evidence Log Bundle (.JSON)
      </button>
    </div>
  `;
}}

window.currentCaseIndex = getInitialCaseIndex();
renderApp();
</script>
</body>
</html>
"""

    (proto_a_dir / "index.html").write_text(proto_a_html, encoding="utf-8")
    (proto_b_dir / "index.html").write_text(proto_b_html, encoding="utf-8")
    print("Built work/W15/proto_A/index.html and work/W15/proto_B/index.html successfully.")


if __name__ == "__main__":
    build()
