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
  const [pasted, setPasted] = useState('');
  const [kind, setKind] = useState('own');
  const [corpus, setCorpus] = useState(null);
  const [watch, setWatch] = useState([]);
  const [w, setW] = useState({ kind: 'youtube_channel', ref: '', label: '' });
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => { api('/api/watch').then(setWatch).catch(() => {}); }, []);
  useEffect(() => {
    if (voiceFor) api(`/api/accounts/${voiceFor}/corpus`).then(setCorpus).catch(() => {});
    else setCorpus(null);
  }, [voiceFor]);
  const refreshCorpus = () =>
    voiceFor && api(`/api/accounts/${voiceFor}/corpus`).then(setCorpus).catch(() => {});

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
    setMsg('Account created. Now feed its voice corpus below.');
  };

  const addToCorpus = async () => {
    setBusy(true); setMsg('');
    try {
      const r = await api(`/api/accounts/${voiceFor}/corpus`,
        { method: 'POST', body: { text: pasted, kind } });
      setMsg(`Added ${r.added} sample(s) (${r.duplicates} already known). ` +
        `Corpus: ${r.corpus.own} of your posts + ${r.corpus.inspiration} inspiration pieces.`);
      setPasted('');
      refreshCorpus();
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  const retrain = async () => {
    setBusy(true); setMsg('');
    try {
      const r = await api(`/api/accounts/${voiceFor}/retrain`, { method: 'POST' });
      setMsg(`Voice retrained on ${r.trained_on} of your posts` +
        (r.inspiration_used ? ` + ${r.inspiration_used} inspiration pieces` : '') +
        ' ✓ — drafts pick this up immediately.');
      refreshAccounts(); refreshCorpus();
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  const judgeSuggestion = async (id, verdict) => {
    await api(`/api/suggestions/${id}/${verdict}?account_id=${voiceFor}`, { method: 'POST' });
    refreshCorpus();
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
        <div className="font-medium mb-2">🧬 Voice corpus — feed it daily</div>
        <div className="text-sm text-zinc-400 mb-2">
          Everything you add is kept forever and the voice retrains on the full
          set. Add your own tweets (one per line — optionally end a line with
          <code className="text-zinc-300"> | likes retweets replies</code> so
          proven winners weigh more) or paste a whole editorial/thread you
          admire as inspiration.
        </div>
        <div className="flex gap-2 mb-2 flex-wrap items-center">
          <select
            value={voiceFor}
            onChange={(e) => setVoiceFor(e.target.value)}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="">pick account…</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>@{a.handle}</option>
            ))}
          </select>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="own">my own posts (one per line)</option>
            <option value="inspiration">writing I admire (one whole piece)</option>
          </select>
          {corpus && (
            <Chip>
              corpus: {corpus.counts.own} own · {corpus.counts.inspiration} inspiration
              {corpus.voice_version ? ` · voice v${corpus.voice_version}` : ' · no voice yet'}
            </Chip>
          )}
        </div>
        <textarea
          rows="8"
          value={pasted}
          onInput={(e) => setPasted(e.target.value)}
          placeholder={kind === 'own'
            ? 'RBI holds rates again. let that sink in | 230 41 12\nNew GDP numbers out. 7.2%. Sounds great until you see the base effect.\n…'
            : 'Paste the full editorial / thread / article you admire — stored as one piece.'}
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-3 text-sm placeholder-zinc-600"
        />
        <div className="mt-2 flex gap-2">
          <Btn color="blue" disabled={!voiceFor || !pasted.trim() || busy} onClick={addToCorpus}>
            Add to corpus
          </Btn>
          <Btn color="green" disabled={!voiceFor || busy} onClick={retrain}>
            {busy ? 'analyzing the voice…' : 'Retrain voice from corpus'}
          </Btn>
        </div>
      </Card>

      {corpus && corpus.suggestions.length > 0 && (
        <Card>
          <div className="font-medium mb-2">📥 Suggested for your corpus</div>
          <div className="text-sm text-zinc-400 mb-2">
            Pieces from the watched feeds that match your interests. Nothing is
            used for training unless you accept it.
          </div>
          {corpus.suggestions.map((s) => (
            <div key={s.id} className="py-2 border-b border-zinc-800 last:border-0">
              <div className="text-sm">
                {s.url
                  ? <a href={s.url} target="_blank" rel="noreferrer" className="text-sky-400">{s.title}</a>
                  : s.title}
                {s.source && <span className="text-zinc-500"> — {s.source}</span>}
              </div>
              <div className="text-xs text-zinc-500 mb-1">{s.reason}</div>
              <div className="flex gap-2">
                <Btn color="green" onClick={() => judgeSuggestion(s.id, 'accept')}>add as inspiration</Btn>
                <Btn onClick={() => judgeSuggestion(s.id, 'reject')}>skip</Btn>
              </div>
            </div>
          ))}
        </Card>
      )}

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
