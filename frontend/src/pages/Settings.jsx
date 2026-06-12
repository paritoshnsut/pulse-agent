// Onboarding + persona management + voice training + watch list.

import { useEffect, useState } from 'react';
import { api, apiBlob } from '../api.js';
import { Btn, Card, Chip, Input, PageHeader } from '../components/ui.jsx';

const WATCH_PLACEHOLDERS = {
  youtube_channel: 'channel ID (UC…)',
  subreddit: 'subreddit name',
  trends_geo: 'IN / US',
};

const BLANK_BRAND = { banned_words: '', word_swaps: '', disclaimers: '',
  cta_text: '', cta_url: '', website_url: '', notes: '',
  accent_color: '#4da3ff', secondary_color: '', bg_style: 'dark',
  font_family: 'sans', watermark_text: '', logo_url: '' };

export default function Settings({ accounts, refreshAccounts }) {
  const [form, setForm] = useState({ handle: '', niche: '', topics: '', kind: '' });
  const [presets, setPresets] = useState([]);
  const [voiceFor, setVoiceFor] = useState('');
  const [pasted, setPasted] = useState('');
  const [kind, setKind] = useState('own');
  const [corpus, setCorpus] = useState(null);
  const [brandFor, setBrandFor] = useState('');
  const [brand, setBrand] = useState(BLANK_BRAND);
  const [watch, setWatch] = useState([]);
  const [w, setW] = useState({ kind: 'youtube_channel', ref: '', label: '' });
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [importUrl, setImportUrl] = useState('');
  const [previewUrl, setPreviewUrl] = useState(null);
  const [previewBusy, setPreviewBusy] = useState(false);

  useEffect(() => {
    api('/api/watch').then(setWatch).catch(() => {});
    api('/api/presets').then(setPresets).catch(() => {});
  }, []);
  useEffect(() => {
    if (voiceFor) api(`/api/accounts/${voiceFor}/corpus`).then(setCorpus).catch(() => {});
    else setCorpus(null);
  }, [voiceFor]);
  useEffect(() => {
    if (!brandFor) { setBrand(BLANK_BRAND); return; }
    api(`/api/accounts/${brandFor}/brand`).then((b) => setBrand({
      banned_words: (b.banned_words || []).join(', '),
      word_swaps: Object.entries(b.word_swaps || {}).map(([k, v]) => `${k} -> ${v}`).join('\n'),
      disclaimers: (b.disclaimers || []).join('\n'),
      cta_text: b.cta_text || '', cta_url: b.cta_url || '',
      website_url: b.website_url || '', notes: b.notes || '',
      accent_color: b.accent_color || '#4da3ff',
      secondary_color: b.secondary_color || '',
      bg_style: b.bg_style || 'dark', font_family: b.font_family || 'sans',
      watermark_text: b.watermark_text || '',
      logo_url: b.logo_url || '',
    })).catch(() => setBrand(BLANK_BRAND));
  }, [brandFor]);
  const refreshCorpus = () =>
    voiceFor && api(`/api/accounts/${voiceFor}/corpus`).then(setCorpus).catch(() => {});

  const applyPreset = (pid) => {
    const p = presets.find((x) => x.id === pid);
    if (p) setForm({ handle: form.handle, niche: p.niche,
                     topics: (p.topics || []).join(', '), kind: p.kind,
                     preset: p.id });
  };

  const createAccount = async () => {
    await api('/api/accounts', {
      method: 'POST',
      body: {
        handle: form.handle,
        niche: form.niche,
        kind: form.kind || null,
        preset: form.preset || null,  // seeds the brand kit's visual defaults
        topics: form.topics.split(',').map((t) => t.trim()).filter(Boolean),
      },
    });
    setForm({ handle: '', niche: '', topics: '', kind: '' });
    refreshAccounts();
    setMsg('Account created. Now feed its voice corpus below.');
  };

  const brandBody = () => {
    const swaps = {};
    brand.word_swaps.split('\n').forEach((line) => {
      const [a, b] = line.split('->').map((x) => x.trim());
      if (a && b) swaps[a] = b;
    });
    return {
      banned_words: brand.banned_words.split(',').map((x) => x.trim()).filter(Boolean),
      word_swaps: swaps,
      disclaimers: brand.disclaimers.split('\n').map((x) => x.trim()).filter(Boolean),
      cta_text: brand.cta_text || null, cta_url: brand.cta_url || null,
      website_url: brand.website_url || null, notes: brand.notes || null,
      accent_color: brand.accent_color || null,
      secondary_color: brand.secondary_color || null,
      bg_style: brand.bg_style || null, font_family: brand.font_family || null,
      watermark_text: brand.watermark_text || null,
      logo_url: brand.logo_url || null,
    };
  };

  const saveBrand = async () => {
    await api(`/api/accounts/${brandFor}/brand`, { method: 'POST', body: brandBody() });
    setMsg('Brand kit saved — every draft now obeys these rules.');
  };

  const previewBrand = async () => {
    setPreviewBusy(true);
    try {
      setPreviewUrl(await apiBlob(`/api/accounts/${brandFor}/brand/preview`,
        { method: 'POST', body: brandBody() }));
    } catch (e) { setMsg(e.message); } finally { setPreviewBusy(false); }
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

  const importVoice = async () => {
    if (!voiceFor || !importUrl.trim()) return;
    setBusy(true); setMsg('');
    try {
      const r = await api(`/api/accounts/${voiceFor}/import-voice`,
        { method: 'POST', body: { url: importUrl.trim(), kind } });
      setMsg(`Imported ${r.imported} post(s) from ${r.feed}` +
        (r.duplicates ? ` (${r.duplicates} already known)` : '') +
        (r.trained ? ` — voice trained on ${r.trained_on} ✓` : '') +
        (r.niche ? ` — topics detected: ${r.niche}` : ''));
      setImportUrl('');
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
      <PageHeader title="Settings"
        desc="Accounts, voice training, brand identity, and what the agent watches." />
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
          <div key={a.id} className="py-1.5 border-b border-zinc-800/60 last:border-0">
            <div className="flex items-center gap-2 text-sm">
              <span className="font-medium">@{a.handle}</span>
              {a.has_voice
                ? <Chip tone="green">voice ✓ v{a.voice_version}</Chip>
                : <Chip tone="amber">⚠ no voice yet</Chip>}
            </div>
            {a.niche && (
              <div className="text-xs text-zinc-500 mt-0.5 leading-relaxed">{a.niche}</div>
            )}
          </div>
        ))}
        {presets.length > 0 && (
          <div className="mt-3">
            <select onChange={(e) => applyPreset(e.target.value)}
              className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm w-full">
              <option value="">start from a template (politics, SaaS, D2C, creator, finance…)</option>
              {presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
        )}
        <div className="grid md:grid-cols-2 gap-2 mt-2">
          <Input placeholder="handle (no @)" value={form.handle}
                 onInput={(e) => setForm({ ...form, handle: e.target.value })} />
          <Input placeholder="topics, comma separated (e.g. politics, policy, economy)"
                 value={form.topics}
                 onInput={(e) => setForm({ ...form, topics: e.target.value })} />
        </div>
        <textarea rows={2}
          placeholder="niche — be specific, this is injected into every scoring and generation prompt (e.g. political commentary: data-backed contrarian takes on policy and governance — India focus)"
          value={form.niche}
          onInput={(e) => setForm({ ...form, niche: e.target.value })}
          className="w-full mt-2 bg-zinc-900 border border-zinc-700/70 rounded-lg p-3 text-sm
            placeholder-zinc-600 focus:outline-none focus:border-indigo-500/60
            focus:ring-1 focus:ring-indigo-500/30 transition-colors resize-none" />
        <div className="mt-2">
          <Btn color="blue" disabled={!form.handle} onClick={createAccount}>Add account</Btn>
          {form.kind && <span className="text-xs text-zinc-500 ml-2">type: {form.kind}</span>}
        </div>
      </Card>

      <Card>
        <div className="font-medium mb-2">🛡️ Brand kit</div>
        <div className="text-sm text-zinc-400 mb-2">
          The rules every draft must obey — banned words, preferred swaps, a
          default CTA, disclaimers. Enforced on every generation path.
        </div>
        <select value={brandFor} onChange={(e) => setBrandFor(e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm mb-2">
          <option value="">pick account…</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>@{a.handle}</option>)}
        </select>
        {brandFor && (
          <div className="space-y-2">
            <Input placeholder="banned words, comma separated (e.g. cheap, guys)"
                   value={brand.banned_words}
                   onInput={(e) => setBrand({ ...brand, banned_words: e.target.value })} />
            <textarea rows="3" placeholder={'preferred swaps, one per line:\ncheap -> affordable\nclient -> partner'}
              value={brand.word_swaps}
              onInput={(e) => setBrand({ ...brand, word_swaps: e.target.value })}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2 text-sm placeholder-zinc-600" />
            <textarea rows="2" placeholder="disclaimers, one per line (e.g. Not financial advice.)"
              value={brand.disclaimers}
              onInput={(e) => setBrand({ ...brand, disclaimers: e.target.value })}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2 text-sm placeholder-zinc-600" />
            <div className="grid md:grid-cols-2 gap-2">
              <Input placeholder="default CTA text" value={brand.cta_text}
                     onInput={(e) => setBrand({ ...brand, cta_text: e.target.value })} />
              <Input placeholder="CTA / website URL" value={brand.cta_url}
                     onInput={(e) => setBrand({ ...brand, cta_url: e.target.value })} />
            </div>
            <textarea rows="2" placeholder="brand voice / compliance notes (freeform)"
              value={brand.notes}
              onInput={(e) => setBrand({ ...brand, notes: e.target.value })}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2 text-sm placeholder-zinc-600" />
            <div className="text-sm text-zinc-400 pt-1">🎨 Visual identity (used on every generated graphic):</div>
            <div className="grid md:grid-cols-4 gap-2 items-center">
              <label className="flex items-center gap-2 text-sm text-zinc-400">
                accent
                <input type="color" value={brand.accent_color}
                  onInput={(e) => setBrand({ ...brand, accent_color: e.target.value })}
                  className="h-8 w-12 bg-zinc-800 border border-zinc-700 rounded" />
              </label>
              <select value={brand.bg_style}
                onChange={(e) => setBrand({ ...brand, bg_style: e.target.value })}
                className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm">
                <option value="dark">dark background</option>
                <option value="light">light background</option>
                <option value="gradient">gradient background</option>
              </select>
              <select value={brand.font_family}
                onChange={(e) => setBrand({ ...brand, font_family: e.target.value })}
                className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm">
                <option value="sans">sans (Inter)</option>
                <option value="serif">serif (Lora)</option>
                <option value="mono">mono (JetBrains)</option>
              </select>
              <Input placeholder="watermark text" value={brand.watermark_text}
                onInput={(e) => setBrand({ ...brand, watermark_text: e.target.value })} />
            </div>
            <Input placeholder="logo URL (PNG/JPG — appears on every graphic)" value={brand.logo_url}
              onInput={(e) => setBrand({ ...brand, logo_url: e.target.value })} />
            <div className="flex gap-2 items-center">
              <Btn color="blue" onClick={saveBrand}>Save brand kit</Btn>
              <Btn color="zinc" disabled={previewBusy} onClick={previewBrand}>
                {previewBusy ? 'rendering…' : '👁 Preview the look'}
              </Btn>
            </div>
            {previewUrl && (
              <img src={previewUrl} alt="brand preview"
                   className="rounded-xl border border-zinc-800 max-w-lg w-full mt-2" />
            )}
          </div>
        )}
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
        <div className="mt-4 border-t border-zinc-800 pt-3">
          <div className="text-sm font-medium mb-1">⚡ Or import everything from one URL</div>
          <div className="text-xs text-zinc-500 mb-2">
            Paste your blog / Substack / Medium / newsletter URL. We find the
            feed, pull your posts into the corpus, train the voice, and fill in
            your topics — automatically. (X/LinkedIn can't be read without paid
            APIs — paste those posts above.)
          </div>
          <div className="flex gap-2 items-center">
            <Input placeholder="https://yourname.substack.com" value={importUrl}
                   onInput={(e) => setImportUrl(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && importVoice()} />
            <Btn color="green" disabled={!voiceFor || !importUrl.trim() || busy}
                 onClick={importVoice}>
              {busy ? 'importing…' : 'Import & train'}
            </Btn>
          </div>
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
