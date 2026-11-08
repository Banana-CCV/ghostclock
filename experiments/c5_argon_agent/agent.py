"""GhostClock C5 -- compact Gemini 4 Argon investigator loop (agy CLI backend) with a deterministic code gate.

Argon decides WHAT to investigate (modality / harmonics / analysis window) and writes the human-facing
explanation. Python executes the deterministic tools (C1 ENF traces + C1 NCC matcher, director's GB
Elexon scan). A code gate (C1 frozen per-length thresholds + duration + consistency + optional claim
check) decides the status; if Argon's proposed status differs, the gate wins and the conflict is logged.

usage:
  python work/C5/agent.py case_a [case_b ...]          # Argon-directed
  python work/C5/agent.py --fixed case_a [case_b ...]  # fixed pipeline, no Argon (ablation)
Outputs: work/C5/runs/<case>[ _fixed]/{trace.jsonl, report.json, report.md}
"""
import json, os, re, subprocess, sys, time, zlib
from pathlib import Path
import numpy as np, pandas as pd

C5 = Path(__file__).resolve().parent
ROOT = C5.parents[1]
sys.path.insert(0, str(ROOT / 'work' / 'C1'))
sys.path.insert(0, str(ROOT / 'work' / 'director'))
import match as c1match                      # read-only import of C1 matcher
from common import load_trace, ref_valid     # read-only import of C1 cache loader

AGY = os.path.join(os.environ['LOCALAPPDATA'], 'agy', 'bin', 'agy.exe')
MODEL = 'gemini-4-argon-high'
MAX_CALLS = 5
FROZEN = json.load(open(ROOT / 'work' / 'C1' / 'frozen.json'))
THR = {int(k): float(v) for k, v in FROZEN['thresholds'].items()}   # C1 dev-frozen peak-NCC thresholds
CAL_LENS = sorted(THR)
STATUSES = ['MATCH_SUPPORTED', 'INCONCLUSIVE', 'MATERIAL_DISCREPANCY_REVIEW']
GT = json.load(open(ROOT / 'work' / 'C1' / 'gt_w16.json'))

# Ground truth / C1 trial info stays in this table and is NEVER put in the dossier.
CASES = {
    'case_a': dict(kind='whu', grp='H1', name='011', ref_day='011', gt_lag0=GT['011']['lag_ref'],
                   expect='MATCH_SUPPORTED', c1_trial=dict(start=325, L=300), note='ENF-WHU holdout H1 011 vs its own day'),
    'case_b': dict(kind='whu', grp='H0', name='13', ref_day='070', gt_lag0=None,
                   expect='INCONCLUSIVE', c1_trial=dict(start=136, L=300), note='ENF-WHU holdout H0 negative 13 vs day 070'),
    'case_c': dict(kind='whu', grp='H1', name='011', ref_day='020-025', gt_lag0=None,
                   expect='INCONCLUSIVE', c1_trial=dict(start=325, L=300), note='same recording as case_a vs WRONG day 020-025'),
    'case_d': dict(kind='venue', dir='work/director/quick/A001_11081103_C002', gt_lag0=None,
                   media='datasets/raw/team_recordings/A001_11081103_C002.mp4',
                   search=('2026-11-07T00:00:00Z', '2026-11-08T12:21:45Z'),
                   expect='INCONCLUSIVE', c1_trial=None, note='team venue recording, 49 s'),
    'case_e': dict(kind='whu', grp='H1', name='011', ref_day='011', gt_lag0=GT['011']['lag_ref'],
                   claim_offset_s=GT['011']['lag_ref'] + 7200, expect='MATERIAL_DISCREPANCY_REVIEW',
                   c1_trial=dict(start=325, L=300), note='case_a recording with a FALSE claimed start (+2 h)'),
}


def opaque(case):
    return 'GC-%08X' % zlib.crc32(('ghostclock-c5|' + case).encode())


# ----------------------------------------------------------------------------- media + tools
def ffprobe_duration(path):
    sys.path.insert(0, str(ROOT / 'work' / 'C1'))
    import enf
    fp = str(Path(enf._ffmpeg()).with_name('ffprobe.exe'))
    out = subprocess.run([fp, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
                         capture_output=True, text=True)
    return round(float(json.loads(out.stdout)['format']['duration']), 2)


class Media:
    def __init__(self, case):
        self.c = CASES[case]
        if self.c['kind'] == 'whu':
            self.tr = load_trace('w16', self.c['grp'], self.c['name'])
            self.duration = float(len(self.tr['f']))
            rt = load_trace('w16', 'H1_ref_one_day', self.c['ref_day'] + '_ref')
            y, _ = c1match.preprocess(rt['f'], rt['q'], wmode='none', clip_hz=0.5)
            self.ref = c1match.Reference(y, ref_valid(rt))
            self.ref_len = len(rt['f'])
        else:
            d = ROOT / self.c['dir']
            self.tr = {m: pd.read_csv(d / f) for m, f in [('audio', 'audio_trace.csv'), ('video', 'video_rs_trace_dark.csv')]}
            self.duration = ffprobe_duration(ROOT / self.c['media'])
            import blind_match as bm
            a, b = [int(pd.Timestamp(s).timestamp()) for s in self.c['search']]
            self.t1, self.f1 = bm.load_ref(a, b, live=True)
            self.bm = bm

    def probe(self):
        if self.c['kind'] == 'whu':
            tr = self.tr; f = tr['f']
            return dict(duration_s=self.duration, modalities_available=['audio'], has_video=False,
                        per_harmonic_median_snr={int(k): round(float(v), 2) for k, v in zip(tr['harmonics'], np.median(tr['snrk'], 0))},
                        snr_note='per-harmonic median peak/median power ratio in a +-0.5 Hz band (higher = cleaner hum)',
                        median_frame_quality_db=round(float(np.median(tr['q'])), 2),
                        frac_frames_quality_ge_10db=round(float(np.mean(tr['q'] >= 10)), 3),
                        trace_std_mhz_all_harmonics=round(float(np.std(np.clip(f, np.median(f) - .05, np.median(f) + .05))) * 1e3, 2),
                        reference_window=dict(type='permitted 24 h grid-frequency reference trace (50 Hz grid)', length_s=self.ref_len))
        out = dict(duration_s=self.duration, modalities_available=['audio', 'video', 'fused'], has_video=True, harmonic_choice='not available (precomputed traces)')
        for m, t in self.tr.items():
            out[m] = dict(n_frames=len(t), span_s=[float(t.t_s.min()), float(t.t_s.max())],
                          median_quality_db=round(float(t.q_db.median()), 2),
                          std_mhz=round(float(t.enf_hz.std() * 1e3), 2), median_hz=round(float(t.enf_hz.median()), 4))
        out['reference_window'] = dict(type='permitted GB grid-frequency reference (Elexon 15 s, interpolated to 1 s)',
                                       length_s=len(self.t1))
        return out

    def _trace(self, modality, harmonics):
        if self.c['kind'] == 'whu':
            tr = self.tr; allh = [int(h) for h in tr['harmonics']]
            hs = sorted({int(h) for h in harmonics} & set(allh)) or allh
            if hs == allh:
                f = tr['f']                                   # exactly C1's frozen extraction
            else:                                             # SNR-weighted recombination of chosen harmonics
                idx = [allh.index(h) for h in hs]
                fk, sk = tr['fk'][:, idx], tr['snrk'][:, idx]
                use = (sk >= 2.0) & np.isfinite(fk)
                den = np.where(use, sk, 0).sum(1)
                f = np.where(den > 0, np.where(use, sk * fk, 0).sum(1) / np.maximum(den, 1e-30), tr['f'])
            return np.arange(len(f), dtype=float), f, tr['q'], hs
        a, v = self.tr['audio'], self.tr['video']
        if modality == 'audio':
            return a.t_s.values, a.enf_hz.values, a.q_db.values, []
        if modality == 'video':
            return v.t_s.values, v.enf_hz.values, v.q_db.values, []
        t = np.arange(np.ceil(max(a.t_s.min(), v.t_s.min())), np.floor(min(a.t_s.max(), v.t_s.max())) + 1)
        fa, fv = np.interp(t, a.t_s, a.enf_hz), np.interp(t, v.t_s, v.enf_hz)
        qa, qv = np.interp(t, a.t_s, a.q_db), np.interp(t, v.t_s, v.q_db)
        wa, wv = 10 ** (qa / 20), 10 ** (qv / 20)
        return t, (wa * fa + wv * fv) / (wa + wv), np.maximum(qa, qv), []

    def extract_and_match(self, modality, harmonics, window_start_s, window_len_s):
        modality = modality if modality in self.probe()['modalities_available'] else self.probe()['modalities_available'][0]
        t, f, q, hs = self._trace(modality, harmonics)
        L = int(window_len_s); s = int(max(0, round(window_start_s)))
        notes = []
        if self.c['kind'] == 'whu':
            if L not in CAL_LENS or L > len(f):
                L2 = max([l for l in CAL_LENS if l <= len(f)] or [len(f)])
                notes.append(f'window_len_s {window_len_s} not a calibrated length <= duration; used {L2}')
                L = L2
            if s + L > len(f):
                notes.append(f'window_start_s {s} too late; moved to {len(f) - L}'); s = len(f) - L
            x, w = c1match.preprocess(f, q, wmode='q', clip_hz=0.05)
            xs, ws = x[s:s + L], w[s:s + L]
            if ws.sum() < 0.2 * L:
                st = dict(lag=float('nan'), peak=-1.0, second=-1.0, margin=0.0, z=0.0)
            else:
                st = c1match.peak_stats(self.ref.ncc(xs, ws))
            thr = THR.get(L)
            res = dict(modality=modality, harmonics_used=hs, window_start_s=s, window_len_s=L,
                       valid_frame_fraction=round(float(np.mean(ws > 0)), 3),
                       trace_std_mhz=round(float(np.std(xs[ws > 0])) * 1e3, 2) if (ws > 0).any() else None,
                       peak_ncc=round(st['peak'], 5), second_peak_ncc=round(st['second'], 5), margin=round(st['margin'], 5),
                       z_score=round(st['z'], 2), best_offset_in_reference_s=round(st['lag'], 2),
                       implied_media_start_in_reference_s=round(st['lag'] - s, 2),
                       frozen_threshold_for_length=round(thr, 5) if thr else None,
                       passes_frozen_threshold=bool(thr is not None and st['peak'] > thr))
        else:
            sel = (t >= s) & (t < s + L) if L else np.ones_like(t, bool)
            t, f, q = t[sel], f[sel], q[sel]
            tt = np.arange(int(t.min()), int(t.max()) + 1)
            qq = np.interp(tt, t, f); w = 10 ** (np.interp(tt, t, q) / 20)
            ref = self.bm.smooth(self.f1, 16)
            r = self.bm.ncc_scan(ref, qq, w)
            st = c1match.peak_stats(r)
            k = int(np.argmax(r))
            res = dict(modality=modality, harmonics_used=hs, window_start_s=float(t.min()), window_len_s=len(tt),
                       peak_ncc=round(st['peak'], 5), second_peak_ncc=round(st['second'], 5), margin=round(st['margin'], 5),
                       z_score=round(st['z'], 2), best_offset_in_reference_s=k,
                       implied_media_start_in_reference_s=round(k - float(t.min()), 2),
                       frozen_threshold_for_length=None, passes_frozen_threshold=False)
            notes.append(f'usable trace {len(tt)} s is shorter than the shortest calibrated length ({CAL_LENS[0]} s); no frozen threshold exists')
        res['notes'] = notes
        return res


# ----------------------------------------------------------------------------- gate
def gate(case, media, matches, basis_idx):
    c = CASES[case]; reasons = []
    if media.duration < CAL_LENS[0]:
        return 'INCONCLUSIVE', [f'media duration {media.duration:.0f} s < shortest calibrated length {CAL_LENS[0]} s '
                                f'(C1 holdout: 1-min coverage 9/135, 5-min 105/135; need >= 5-10 min of usable hum)'], None
    if not matches:
        return 'INCONCLUSIVE', ['no verified match was computed'], None
    b = matches[basis_idx] if 0 <= basis_idx < len(matches) else matches[-1]
    if not b['passes_frozen_threshold']:
        return 'INCONCLUSIVE', [f"basis match peak NCC {b['peak_ncc']} <= frozen threshold {b['frozen_threshold_for_length']} "
                                f"for {b['window_len_s']} s"], b
    starts = [m['implied_media_start_in_reference_s'] for m in matches if m['passes_frozen_threshold']]
    if max(starts) - min(starts) > 5:
        return 'INCONCLUSIVE', [f'passing configurations disagree on the media start by {max(starts) - min(starts):.1f} s (> 5 s)'], b
    reasons.append(f"peak NCC {b['peak_ncc']} > frozen threshold {b['frozen_threshold_for_length']} for {b['window_len_s']} s")
    if len(matches) > 1:
        reasons.append(f'{len(matches)} configurations tried (look-elsewhere caveat: thresholds were frozen for one configuration)')
    if c.get('claim_offset_s') is not None:
        d = b['implied_media_start_in_reference_s'] - c['claim_offset_s']
        if abs(d) > 60:
            return 'MATERIAL_DISCREPANCY_REVIEW', reasons + [f'claimed start differs from the ENF-supported start by {d:+.0f} s (> 60 s tolerance)'], b
        reasons.append(f'claimed start within {abs(d):.0f} s of the ENF-supported start')
    return 'MATCH_SUPPORTED', reasons, b


# ----------------------------------------------------------------------------- argon
SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["extract_and_match", "decide"]},
        "rationale": {"type": "string"},
        "modality": {"type": "string", "enum": ["audio", "video", "fused"]},
        "harmonics": {"type": "array", "items": {"type": "integer"}},
        "window_start_s": {"type": "number"},
        "window_len_s": {"type": "integer"},
        "basis_match_index": {"type": "integer"},
        "proposed_status": {"type": "string", "enum": STATUSES + ["NONE"]},
        "explanation": {"type": "string"},
        "what_would_change": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["action", "rationale", "modality", "harmonics", "window_start_s", "window_len_s",
                 "basis_match_index", "proposed_status", "explanation", "what_would_change"],
}
SCHEMA_PATH = C5 / 'action_schema.json'

PROMPT = """You are the investigator in GhostClock, a forensic tool that dates media by Electrical Network Frequency (ENF):
mains hum in audio (50 Hz and harmonics) or lamp flicker in video, matched by normalised cross-correlation (NCC)
against a permitted grid-frequency reference window. Do NOT use any tools; reply only with the JSON object.

Your job: decide which deterministic analysis to run next, or decide. Python runs the tool `extract_and_match`
(modality, harmonics, window_start_s, window_len_s) and returns numbers. You have at most {max_calls} replies in total;
this is reply {call_no} of {max_calls}.{final_note}

The STATUS is decided by a deterministic code gate, not by you. Gate rules (fixed in advance on development data):
- media shorter than {minlen} s -> INCONCLUSIVE.
- otherwise the basis match (basis_match_index into previous_tool_results; -1 = last) must have peak NCC > frozen
  threshold for its window length {thr}; calibrated window lengths are {lens} s. Otherwise INCONCLUSIVE.
- all configurations that pass must agree on the implied media start within 5 s, else INCONCLUSIVE.
- if a claimed start exists (hidden from you) and differs by > 60 s from the supported start -> MATERIAL_DISCREPANCY_REVIEW.
Trying many configurations raises the false-match risk; prefer few, well-justified configurations (longest
calibrated window that fits, harmonics with strong SNR). A human makes the final decision.

When action = "decide": set proposed_status to what you expect the gate to output, write `explanation` (3-6 sentences
for a non-expert reviewer) and `what_would_change` (2-4 items). Cite ONLY numbers that appear in the dossier below.
When action = "extract_and_match": fill the analysis fields; set proposed_status "NONE", explanation "", what_would_change [].

DOSSIER (case id is opaque; you get no filenames, metadata or claimed times):
{dossier}
"""


def call_argon(prompt, cwd):
    t0 = time.time()
    cmd = [AGY, '--model', MODEL, '--output-format', 'json', '--print-timeout', '10m', '--json-schema', str(SCHEMA_PATH)]
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', cwd=str(cwd), timeout=700)
    lat = time.time() - t0
    try:
        out = json.loads(p.stdout)
    except Exception:
        return None, dict(error='unparseable stdout', rc=p.returncode, stdout=p.stdout[-800:], stderr=p.stderr[-800:]), lat
    return out.get('structured_output'), out, lat


NUM = re.compile(r'(?<![\w.])-?\d+(?:\.\d+)?')


def unsupported_numbers(text, dossier):
    pool = [float(x) for x in NUM.findall(json.dumps(dossier))]
    bad = []
    for tok in NUM.findall(text):
        v = float(tok); dec = len(tok.split('.')[1]) if '.' in tok else 0
        tol = 0.5 * 10 ** (-dec) + 1e-9
        if not any(abs(p - v) <= tol or abs(abs(p) - abs(v)) <= tol or abs(p * 100 - v) <= tol for p in pool):
            bad.append(tok)
    return bad


# ----------------------------------------------------------------------------- run
def run_case(case, fixed=False):
    c = CASES[case]; cid = opaque(case)
    out = C5 / 'runs' / (case + ({'long': '_fixedlong'}.get(fixed, '_fixed') if fixed else '')); out.mkdir(parents=True, exist_ok=True)
    tf = open(out / 'trace.jsonl', 'w', encoding='utf-8')
    def log(actor, step, inp, output, tokens=None, latency=None):
        tf.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), case_id=cid, step=step, actor=actor,
                                 input_summary=inp, output=output, tokens=tokens, latency_s=latency and round(latency, 2)),
                            default=str) + '\n'); tf.flush()
    media = Media(case)
    probe = media.probe()
    log('tool', 0, 'probe(media)', probe)
    matches, argon_calls, tokens, conflicts, final, step = [], [], dict(input=0, output=0, thinking=0, total=0), [], None, 1
    if fixed:   # fixed pipeline: one configuration, C1's frozen trial config (WHU) or full audio (venue)
        if c['kind'] == 'whu' and fixed == 'long':   # rule-based: all harmonics, longest calibrated window from 0
            cfg = dict(modality='audio', harmonics=list(range(1, 8)), window_start_s=0,
                       window_len_s=max(l for l in CAL_LENS if l <= media.duration))
        elif c['kind'] == 'whu':
            cfg = dict(modality='audio', harmonics=list(range(1, 8)), window_start_s=c['c1_trial']['start'], window_len_s=c['c1_trial']['L'])
        else:
            cfg = dict(modality='audio', harmonics=[], window_start_s=0, window_len_s=0)
        r = media.extract_and_match(**cfg); matches.append(r); log('tool', step, cfg, r)
        basis = 0
    else:
        cwd = C5 / 'agy_cwd'; cwd.mkdir(exist_ok=True)
        basis = -1
        for k in range(1, MAX_CALLS + 1):
            dossier = dict(case_id=cid, probe=probe, previous_tool_results=matches)
            last = k == MAX_CALLS
            prompt = PROMPT.format(max_calls=MAX_CALLS, call_no=k, minlen=CAL_LENS[0], lens=CAL_LENS,
                                   thr={l: round(v, 4) for l, v in THR.items()},
                                   final_note=' This is your LAST reply: you MUST use action "decide".' if last else '',
                                   dossier=json.dumps(dossier, indent=1))
            act, raw, lat = call_argon(prompt, cwd)
            if act is None:   # one retry
                log('argon', step, f'call {k} failed; retrying', raw, latency=lat); step += 1
                act, raw, lat = call_argon(prompt, cwd)
            u = (raw or {}).get('usage') or {}
            for a, b in [('input', 'input_tokens'), ('output', 'output_tokens'), ('thinking', 'thinking_tokens'), ('total', 'total_tokens')]:
                tokens[a] += int(u.get(b, 0) or 0)
            argon_calls.append(dict(call=k, latency_s=round(lat, 1), usage=u, conversation_id=(raw or {}).get('conversation_id')))
            log('argon', step, f'call {k}/{MAX_CALLS}: dossier with {len(matches)} prior tool results ({len(prompt)} chars)',
                act if act is not None else raw, tokens=u, latency=lat); step += 1
            if act is None:
                conflicts.append('Argon call failed twice; gate decided on available evidence'); break
            if act['action'] == 'decide' or last:
                final = act; basis = act.get('basis_match_index', -1); break
            cfg = dict(modality=act['modality'], harmonics=act['harmonics'], window_start_s=act['window_start_s'], window_len_s=act['window_len_s'])
            r = media.extract_and_match(**cfg); matches.append(r)
            log('tool', step, dict(tool='extract_and_match', **cfg), r); step += 1
    status, reasons, b = gate(case, media, matches, basis)
    log('gate', step, dict(n_matches=len(matches), basis_match_index=basis), dict(status=status, reasons=reasons)); step += 1
    num_bad = []
    if final:
        if final['proposed_status'] != status:
            conflicts.append(f"Argon proposed {final['proposed_status']}, gate decided {status}: gate wins")
            log('gate', step, 'conflict check', conflicts[-1]); step += 1
        num_bad = unsupported_numbers(final['explanation'] + ' ' + ' '.join(final['what_would_change']),
                                      dict(probe=probe, matches=matches, thr=THR, lens=CAL_LENS))
    # evaluation against ground truth: computed AFTER the run, never shown to Argon
    ev = dict(expected=c['expect'], status_as_expected=status == c['expect'])
    if b is not None and c.get('gt_lag0') is not None:
        ev['start_error_s'] = round(b['implied_media_start_in_reference_s'] - c['gt_lag0'], 2)
    rep = dict(case=case, case_id=cid, mode={'long': 'fixed_long'}.get(fixed, 'fixed') if fixed else 'argon', model=None if fixed else MODEL, note=c['note'],
               status=status, gate_reasons=reasons, basis_match=b, n_tool_calls=len(matches), tool_results=matches,
               argon_calls=argon_calls, tokens=tokens, argon_latency_s=round(sum(a['latency_s'] for a in argon_calls), 1),
               argon_final=final, conflicts=conflicts, unsupported_numbers_in_explanation=num_bad,
               evaluation_hidden_from_agent=ev, probe=probe)
    json.dump(rep, open(out / 'report.json', 'w'), indent=1, default=str)
    md = [f'# GhostClock case {cid} ({case}, {rep["mode"]})', '', f'**Status (code gate): {status}**', '']
    md += [f'- {r}' for r in reasons]
    if conflicts: md += ['', '**Conflicts:** ' + '; '.join(conflicts)]
    if final:
        md += ['', '## Argon explanation', final['explanation'], '', '## What would change this conclusion']
        md += [f'- {w}' for w in final['what_would_change']]
        if num_bad: md += ['', f'Numbers not found in tool outputs (flagged): {num_bad}']
    md += ['', '## Tool calls'] + [f"{i}. {m['modality']} h={m['harmonics_used']} win={m['window_start_s']}+{m['window_len_s']} s: "
                                    f"peak {m['peak_ncc']} (thr {m['frozen_threshold_for_length']}), margin {m['margin']}, "
                                    f"start {m['implied_media_start_in_reference_s']} s" for i, m in enumerate(matches)]
    md += ['', f"Argon calls: {len(argon_calls)}, tokens {tokens}, latency {rep['argon_latency_s']} s",
           '', f'Post-hoc evaluation (hidden from agent): {ev}']
    (out / 'report.md').write_text('\n'.join(md), encoding='utf-8')
    tf.close()
    print(json.dumps(dict(case=case, mode=rep['mode'], status=status, expected=c['expect'], n_tools=len(matches),
                          argon_calls=len(argon_calls), tokens=tokens['total'], latency=rep['argon_latency_s'],
                          conflicts=conflicts, ev=ev)))
    return rep


if __name__ == '__main__':
    json.dump(SCHEMA, open(SCHEMA_PATH, 'w'), indent=1)
    args = sys.argv[1:]; fixed = 'long' if '--fixed-long' in args else ('--fixed' in args)
    for cs in [a for a in args if not a.startswith('--')]:
        run_case(cs, fixed)
