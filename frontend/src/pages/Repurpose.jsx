// Content Squeezer: paste a blog/podcast/announcement, get a pack of drafts.

import { useState } from 'react';
import { api } from '../api.js';
import { AccountPicker, Btn, Card } from '../components/ui.jsx';

export default function Repurpose({ accounts }) {
  const [acct, setAcct] = useState(null);
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState('');
  const id = acct ?? accounts[0]?.id;

  const go = async () => {
    setBusy(true); setErr(''); setResult(null);
    try {
      const out = await api('/api/repurpose', {
        method: 'POST',
        body: { account_id: id, text: text || null, url: url || null },
      });
      setResult(out);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  if (!id) return <Card><div className="text-zinc-400">Create an account in Settings first.</div></Card>;

  return (
    <div className="space-y-4">
      <AccountPicker accounts={accounts} value={id} onChange={setAcct} />
      <Card>
        <div className="font-medium mb-1">📦 Content Squeezer</div>
        <div className="text-sm text-zinc-400 mb-3">
          Paste one thing you already made — a blog post, a launch, a podcast
          transcript, a newsletter — and get a whole pack of platform-shaped
          drafts in your voice. They land in the Review tab.
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
            placeholder="https://yourblog.com/post"
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm placeholder-zinc-600"
          />
        </div>
        <div className="mt-3">
          <Btn color="green" disabled={busy || (!text.trim() && !url.trim())} onClick={go}>
            {busy ? 'squeezing… (this takes a moment)' : '📦 Repurpose into a content pack'}
          </Btn>
        </div>
        {err && <div className="mt-2 text-rose-400 text-sm">{err}</div>}
        {result && (
          <div className="mt-3 text-emerald-400 text-sm">
            ✅ Created {result.live} drafts (content pack #{result.pack_id}) —
            they're waiting in the Review tab.
          </div>
        )}
      </Card>
    </div>
  );
}
