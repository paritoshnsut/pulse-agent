// The core screen: drafts arrive, you approve/reject, post on X yourself,
// then log engagement. Mirrors the Telegram flow exactly.

import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { Btn, Card, Chip, Input, copyText } from '../components/ui.jsx';

function DraftCard({ p, refresh }) {
  const [pkg, setPkg] = useState(null);
  const [postedUrl, setPostedUrl] = useState('');
  const [perf, setPerf] = useState({ likes: '', retweets: '', replies: '' });
  const [phase, setPhase] = useState(p.status);
  const [msg, setMsg] = useState('');
  const meta = p.meta_json || {};
  const hooks = meta.alt_hooks || [];
  const ungrounded = meta.ungrounded_claims || [];
  const conflicts = meta.stance_conflicts || [];
  const riskVectors = (meta.risk_level === 'high' || meta.risk_level === 'medium')
    ? (meta.risk_vectors || []) : [];
  const brandViolations = meta.brand_violations || [];
  const ageH = Math.round((Date.now() - new Date(p.created_at)) / 36e5);
  const [steer, setSteer] = useState('');
  const [rejectReason, setRejectReason] = useState('');
  const [busy, setBusy] = useState(false);

  const approve = async () => {
    setPkg(await api(`/api/drafts/${p.id}/approve`, { method: 'POST' }));
    setPhase('approved');
  };
  const rejectIt = async () => {
    await api(`/api/drafts/${p.id}/reject`,
      { method: 'POST', body: { reason: rejectReason || null } });
    refresh();
  };
  const redo = async () => {
    if (!steer.trim()) return;
    setBusy(true); setMsg('');
    try { await api(`/api/drafts/${p.id}/redo`, { method: 'POST', body: { instruction: steer } });
          setSteer(''); refresh(); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };
  const posted = async () => {
    const r = await api(`/api/drafts/${p.id}/posted`,
      { method: 'POST', body: { url: postedUrl || null } });
    setPhase('posted');
    setMsg(r.memory?.ok ? `filed under '${r.memory.topic}'` : '');
  };
  const sendPerf = async () => {
    await api(`/api/drafts/${p.id}/perf`, {
      method: 'POST',
      body: { likes: +perf.likes || 0, retweets: +perf.retweets || 0,
              replies: +perf.replies || 0 },
    });
    setMsg('engagement logged — the agent learns from this');
    refresh();
  };

  return (
    <Card>
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <Chip>#{p.id}</Chip>
        <Chip>{p.format}</Chip>
        {p.persona_score != null && <Chip>voice {Math.round(p.persona_score)}/100</Chip>}
        {!!p.needs_review && <Chip>⚠️ check carefully</Chip>}
        <Chip>{phase}</Chip>
        {Number.isFinite(ageH) && ageH >= 1 && (
          <span className={`px-2 py-0.5 rounded-full text-xs ${
            ageH >= 24 ? 'bg-rose-900 text-rose-200' : 'bg-zinc-800 text-zinc-400'}`}>
            {ageH}h old{ageH >= 24 ? ' — moment may have passed' : ''}
          </span>
        )}
      </div>
      <div className="whitespace-pre-wrap text-[15px] leading-relaxed">{p.content}</div>
      {ungrounded.length > 0 && (
        <div className="mt-3 rounded-lg border border-rose-800 bg-rose-950/50 p-3 text-sm">
          <div className="font-medium text-rose-300">
            🚨 Verify before posting — claims not found in the source:
          </div>
          {ungrounded.map((c, i) => (
            <div key={i} className="text-rose-200/90 mt-1">• {c}</div>
          ))}
        </div>
      )}
      {conflicts.length > 0 && (
        <div className="mt-3 rounded-lg border border-amber-700 bg-amber-950/40 p-3 text-sm">
          <div className="font-medium text-amber-300">
            ↩️ Contradicts your past stance — own the change on purpose:
          </div>
          {conflicts.map((c, i) => (
            <div key={i} className="text-amber-200/90 mt-1">
              • was: {c.past || '?'} → now: {c.now || '?'}
            </div>
          ))}
        </div>
      )}
      {riskVectors.length > 0 && (
        <div className="mt-3 rounded-lg border border-orange-800 bg-orange-950/40 p-3 text-sm">
          <div className="font-medium text-orange-300">
            ⚠️ Backlash risk ({meta.risk_level}) — could be turned against you:
          </div>
          {riskVectors.map((v, i) => (
            <div key={i} className="text-orange-200/90 mt-1">• {v}</div>
          ))}
        </div>
      )}
      {brandViolations.length > 0 && (
        <div className="mt-3 rounded-lg border border-fuchsia-800 bg-fuchsia-950/40 p-3 text-sm">
          <div className="font-medium text-fuchsia-300">
            🛡️ Off-brand — uses banned words: {brandViolations.join(', ')}
          </div>
        </div>
      )}

      {hooks.length > 0 && (
        <div className="mt-3 text-sm text-zinc-400">
          <div className="font-medium text-zinc-300">alt hooks — swap in if stronger:</div>
          {hooks.map((hk, i) => (
            <div key={i} className="flex gap-2 items-center mt-1">
              <span className="flex-1">{i + 1}. {hk}</span>
              <Btn onClick={() => copyText(hk).then(() => setMsg('hook copied'))}>copy</Btn>
            </div>
          ))}
        </div>
      )}

      {phase === 'draft' && (
        <div className="mt-4 space-y-2">
          <div className="flex gap-2 items-center">
            <Input placeholder="steer it: 'more savage', 'lead with the number', 'too soft'"
                   value={steer} onInput={(e) => setSteer(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && redo()} />
            <Btn color="blue" disabled={!steer.trim() || busy} onClick={redo}>
              {busy ? '…' : '🔁 Redo'}
            </Btn>
          </div>
          <div className="flex gap-2 items-center">
            <Btn color="green" onClick={approve}>✅ Approve</Btn>
            <Btn color="red" onClick={rejectIt}>❌ Reject</Btn>
            <Input placeholder="reject reason (optional — teaches the voice)"
                   value={rejectReason} onInput={(e) => setRejectReason(e.target.value)} />
          </div>
        </div>
      )}

      {pkg && phase === 'approved' && (
        <div className="mt-4 border-t border-zinc-800 pt-4 space-y-3">
          {pkg.texts.map((t, i) => (
            <div key={i} className="space-y-2">
              {pkg.texts.length > 1 && (
                <div className="text-xs text-zinc-500">tweet {i + 1}/{pkg.texts.length}</div>
              )}
              <div className="bg-zinc-800 rounded-lg p-3 whitespace-pre-wrap text-sm">{t}</div>
              <div className="flex gap-2">
                <a href={pkg.intent_urls[i]} target="_blank" rel="noreferrer"
                   className="px-3 py-1.5 rounded-lg text-sm font-medium bg-sky-600 hover:bg-sky-500">
                  🐦 Open in X (pre-filled)
                </a>
                <Btn onClick={() => copyText(t).then(() => setMsg('copied'))}>copy text</Btn>
              </div>
            </div>
          ))}
          {pkg.card_url && (
            <div>
              <img src={pkg.card_url} alt="post card"
                   className="rounded-xl border border-zinc-800 max-w-md w-full" />
              <a href={pkg.card_url} download className="text-sky-400 text-sm">
                download card (attach it when composing)
              </a>
            </div>
          )}
          {pkg.timing && <div className="text-sm text-zinc-400">⏰ {pkg.timing}</div>}
          <div className="flex gap-2 items-center pt-2">
            <Input placeholder="tweet URL (optional)" value={postedUrl}
                   onInput={(e) => setPostedUrl(e.target.value)} className="max-w-xs" />
            <Btn color="green" onClick={posted}>I posted it ✓</Btn>
          </div>
        </div>
      )}

      {phase === 'posted' && (
        <div className="mt-4 border-t border-zinc-800 pt-4">
          <div className="text-sm text-zinc-400 mb-2">
            When the numbers are in (a day later is fine):
          </div>
          <div className="flex gap-2 items-center flex-wrap">
            {['likes', 'retweets', 'replies'].map((k) => (
              <Input key={k} type="number" placeholder={k} value={perf[k]}
                     className="w-24"
                     onInput={(e) => setPerf({ ...perf, [k]: e.target.value })} />
            ))}
            <Btn color="blue" onClick={sendPerf}>log engagement</Btn>
          </div>
        </div>
      )}

      {msg && <div className="mt-2 text-emerald-400 text-sm">{msg}</div>}
    </Card>
  );
}

export default function Review({ accounts }) {
  const [drafts, setDrafts] = useState([]);
  const [outbox, setOutbox] = useState([]);
  const refresh = useCallback(async () => {
    setDrafts(await api('/api/drafts?status=draft'));
    setOutbox(await api('/api/drafts?status=approved'));
  }, []);
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 60000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <div className="space-y-4">
      {drafts.length === 0 && outbox.length === 0 && (
        <Card>
          <div className="text-zinc-400">
            No drafts waiting. The agent is watching — new drafts appear here
            (and on Telegram) the moment a story worth reacting to breaks.
            {accounts.length === 0 ? ' First: set up an account in Settings.' : ''}
          </div>
        </Card>
      )}
      {drafts.map((p) => <DraftCard key={p.id} p={p} refresh={refresh} />)}
      {outbox.length > 0 && (
        <div className="text-zinc-400 text-sm font-medium pt-2">
          📤 Approved, waiting for you to post ({outbox.length})
        </div>
      )}
      {outbox.map((p) => <DraftCard key={p.id} p={p} refresh={refresh} />)}
    </div>
  );
}
