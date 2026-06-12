// Content Squeezer: paste a blog/podcast/announcement (or a YouTube link),
// get idea-grouped packs of drafts. Every source is filed into a re-squeezable
// asset library — asset-driven content, vs the watchers' event-driven content.

import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { AccountPicker, Btn, Card, PageHeader } from '../components/ui.jsx';

export default function Repurpose({ accounts }) {
  const [acct, setAcct] = useState(null);
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState('');
  const [assets, setAssets] = useState([]);
  const id = acct ?? accounts[0]?.id;

  const refreshAssets = async (aid) => {
    try { setAssets(await api(`/api/accounts/${aid}/assets`)); }
    catch { setAssets([]); }
  };
  useEffect(() => { if (id) refreshAssets(id); }, [id]);

  const go = async () => {
    setBusy(true); setErr(''); setResult(null);
    try {
      const out = await api('/api/repurpose', {
        method: 'POST',
        body: { account_id: id, text: text || null, url: url || null },
      });
      setResult(out);
      refreshAssets(id);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const resqueeze = async (assetId) => {
    setBusy(true); setErr(''); setResult(null);
    try {
      const out = await api(`/api/accounts/${id}/assets/${assetId}/squeeze`, { method: 'POST' });
      setResult(out);
      refreshAssets(id);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  if (!id) return <Card><div className="text-zinc-400">Create an account in Settings first.</div></Card>;

  return (
    <div className="space-y-4">
      <PageHeader title="Repurpose"
        desc="One input — a blog post, a YouTube/podcast link, a launch note — becomes idea-grouped packs of drafts in your voice." />
      <AccountPicker accounts={accounts} value={id} onChange={setAcct} />
      <Card>
        <div className="font-medium mb-1">📦 Content Squeezer</div>
        <div className="text-sm text-zinc-400 mb-3">
          Paste one thing you already made — a blog post, a launch, a
          transcript, a newsletter — or drop a URL (YouTube links work: we
          read the captions). The squeezer extracts the core ideas, builds a
          content pack per idea, and the drafts land in the Review tab.
        </div>
        <textarea
          rows="10" value={text} onInput={(e) => setText(e.target.value)}
          placeholder="Paste your blog post / announcement / transcript here…"
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-3 text-sm placeholder-zinc-600"
        />
        <div className="flex gap-2 items-center mt-2">
          <span className="text-xs text-zinc-500">or a URL:</span>
          <input
            value={url} onInput={(e) => setUrl(e.target.value)}
            placeholder="https://yourblog.com/post — or a YouTube link"
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm placeholder-zinc-600"
          />
        </div>
        <div className="mt-3">
          <Btn color="green" disabled={busy || (!text.trim() && !url.trim())} onClick={go}>
            {busy ? 'squeezing… (this takes a moment)' : '📦 Squeeze into content packs'}
          </Btn>
        </div>
        {err && <div className="mt-2 text-rose-400 text-sm">{err}</div>}
        {result && (
          <div className="mt-3 space-y-2">
            <div className="text-emerald-400 text-sm">
              ✅ {result.ideas?.length
                ? `Extracted ${result.ideas.length} core ideas → ${result.live} drafts`
                : `Created ${result.live} drafts`} — waiting in the Review tab.
            </div>
            {(result.packs || []).filter((p) => p.idea).map((p) => (
              <div key={p.pack_id} className="text-sm bg-zinc-800/60 rounded-lg px-3 py-2">
                <span className="text-zinc-200">💡 {p.idea}</span>
                <span className="text-zinc-500"> — {p.drafts} drafts (pack #{p.pack_id})</span>
                {p.novelty && (
                  <div className="text-amber-400 text-xs mt-0.5">⚠ {p.novelty}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
      {assets.length > 0 && (
        <Card>
          <div className="font-medium mb-1">🗂 Your content library</div>
          <div className="text-sm text-zinc-400 mb-3">
            Every source you've squeezed stays here. Re-squeeze any of them —
            you get a fresh decomposition with everything your voice has
            learned since.
          </div>
          <div className="space-y-2">
            {assets.map((a) => (
              <div key={a.id} className="flex items-center gap-3 text-sm bg-zinc-800/60 rounded-lg px-3 py-2">
                <div className="flex-1 min-w-0">
                  <div className="truncate text-zinc-200">{a.title || `asset #${a.id}`}</div>
                  <div className="text-xs text-zinc-500">
                    {a.source_type} · {(a.created_at || '').slice(0, 10)} ·
                    {' '}{a.ideas ? `${a.ideas} ideas · ` : ''}{a.drafts} drafts so far
                  </div>
                </div>
                <Btn disabled={busy} onClick={() => resqueeze(a.id)}>♻ Re-squeeze</Btn>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
