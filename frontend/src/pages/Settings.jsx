// Onboarding + persona management + voice training + watch list.

import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { Btn, Card, Chip, Input } from '../components/ui.jsx';

const WATCH_PLACEHOLDERS = {
  youtube_channel: 'channel ID (UC…)',
  subreddit: 'subreddit name',
  trends_geo: 'IN / US',
};

export default function Settings({ accounts, refreshAccounts }) {
  const [form, setForm] = useState({ handle: '', niche: '', topics: '' });
  const [voiceFor, setVoiceFor] = useState('');
  const [pastedPosts, setPastedPosts] = useState('');
  const [watch, setWatch] = useState([]);
  const [w, setW] = useState({ kind: 'youtube_channel', ref: '', label: '' });
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => { api('/api/watch').then(setWatch).catch(() => {}); }, []);

  const createAccount = async () => {
    await api('/api/accounts', {
      method: 'POST',
      body: {
        handle: form.handle,
        niche: form.niche,
        topics: form.topics.split(',').map((t) => t.trim()).filter(Boolean),
      },
    });
    setForm({ handle: '', niche: '', topics: '' });
    refreshAccounts();
    setMsg('Account created. Now train its voice below — paste 50-200 of its past posts.');
  };

  const train = async () => {
    const posts = pastedPosts.split('\n').map((l) => l.trim()).filter(Boolean);
    setBusy(true); setMsg('');
    try {
      await api(`/api/accounts/${voiceFor}/style`, { method: 'POST', body: { posts } });
      setMsg(`Voice trained on ${posts.length} posts ✓ — drafts will now sound like this account.`);
      setPastedPosts('');
      refreshAccounts();
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  const addWatch = async () => {
    await api('/api/watch', { method: 'POST', body: w });
    setW({ ...w, ref: '', label: '' });
    setWatch(await api('/api/watch'));
  };
  const delWatch = async (id) => {
    await api(`/api/watch/${id}`, { method: 'DELETE' });
    setWatch(await api('/api/watch'));
  };

  return (
    <div className="space-y-4">
      {accounts.length === 0 && (
        <Card>
          <div className="font-medium text-lg mb-1">👋 Let's set you up (2 steps)</div>
          <div className="text-sm text-zinc-400">
            1. Create your account below. 2. Paste your past posts to teach it
            your voice. That's it — drafts start appearing in Review.
          </div>
        </Card>
      )}

      <Card>
        <div className="font-medium mb-2">Accounts</div>
        {accounts.map((a) => (
          <div key={a.id} className="flex items-center gap-2 py-1 text-sm">
            <span>@{a.handle}</span>
            <Chip>{a.niche || 'no niche set'}</Chip>
            {a.has_voice
              ? <Chip>voice ✓ v{a.voice_version}</Chip>
              : <Chip>⚠️ no voice yet</Chip>}
          </div>
        ))}
        <div className="grid md:grid-cols-3 gap-2 mt-3">
          <Input placeholder="X handle (no @)" value={form.handle}
                 onInput={(e) => setForm({ ...form, handle: e.target.value })} />
          <Input placeholder="niche — be specific, this drives everything" value={form.niche}
                 onInput={(e) => setForm({ ...form, niche: e.target.value })} />
          <Input placeholder="topics, comma separated" value={form.topics}
                 onInput={(e) => setForm({ ...form, topics: e.target.value })} />
        </div>
        <div className="mt-2">
          <Btn color="blue" disabled={!form.handle} onClick={createAccount}>Add account</Btn>
        </div>
      </Card>

      <Card>
        <div className="font-medium mb-2">🧬 Train a voice</div>
        <div className="text-sm text-zinc-400 mb-2">
          Paste 50–200 of the account's past posts, ONE PER LINE. The best
          predictor of quality in the whole system.
        </div>
        <select
          value={voiceFor}
          onChange={(e) => setVoiceFor(e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm mb-2"
        >
          <option value="">pick account…</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>@{a.handle}</option>
          ))}
        </select>
        <textarea
          rows="8"
          value={pastedPosts}
          onInput={(e) => setPastedPosts(e.target.value)}
          placeholder={'RBI holds rates again. let that sink in\nNew GDP numbers out. 7.2%. Sounds great until you see the base effect.\n…'}
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-3 text-sm placeholder-zinc-600"
        />
        <div className="mt-2">
          <Btn color="green" disabled={!voiceFor || busy} onClick={train}>
            {busy ? 'analyzing your voice…' : 'Train voice'}
          </Btn>
        </div>
      </Card>

      <Card>
        <div className="font-medium mb-2">👀 What it watches</div>
        {watch.map((x) => (
          <div key={x.id} className="flex items-center gap-2 py-1 text-sm">
            <Chip>{x.kind}</Chip>
            <span className="flex-1">{x.label || x.ref}</span>
            <button onClick={() => delWatch(x.id)} className="text-rose-400 text-xs">
              remove
            </button>
          </div>
        ))}
        <div className="grid md:grid-cols-4 gap-2 mt-3">
          <select
            value={w.kind}
            onChange={(e) => setW({ ...w, kind: e.target.value })}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="youtube_channel">YouTube channel</option>
            <option value="subreddit">Subreddit</option>
            <option value="trends_geo">Google Trends geo</option>
          </select>
          <Input placeholder={WATCH_PLACEHOLDERS[w.kind]} value={w.ref}
                 onInput={(e) => setW({ ...w, ref: e.target.value })} />
          <Input placeholder="label (optional)" value={w.label}
                 onInput={(e) => setW({ ...w, label: e.target.value })} />
          <Btn color="blue" disabled={!w.ref} onClick={addWatch}>Add</Btn>
        </div>
        <div className="text-xs text-zinc-500 mt-2">
          YouTube channel ID: channel page → ⋯ → Share channel → Copy channel
          ID. News feeds (65 sources) are built in.
        </div>
      </Card>

      {msg && <div className="text-emerald-400 text-sm">{msg}</div>}
    </div>
  );
}
