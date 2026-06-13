// Ideas bank (yesterday's COOL signals) + morning briefing + evergreen button.

import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { AccountPicker, Btn, Card, Input, PageHeader } from '../components/ui.jsx';

export default function Ideas({ accounts }) {
  const [acct, setAcct] = useState(null);
  const [ideas, setIdeas] = useState([]);
  const [brief, setBrief] = useState('');
  const [topic, setTopic] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [draftingId, setDraftingId] = useState(null);
  const [ideaMsg, setIdeaMsg] = useState('');
  const id = acct ?? accounts[0]?.id;

  const draftIdea = async (sigId) => {
    setDraftingId(sigId); setIdeaMsg('');
    try {
      const p = await api(`/api/signals/${sigId}/draft`, { method: 'POST' });
      setIdeaMsg(`✍️ drafted #${p.id} — it's in the Review tab`);
    } catch (e) { setIdeaMsg(e.message); } finally { setDraftingId(null); }
  };

  useEffect(() => {
    if (!id) return;
    api(`/api/ideas/${id}`).then(setIdeas).catch(() => {});
    api(`/api/briefing/${id}`).then((r) => setBrief(r.text)).catch(() => {});
  }, [id]);

  const evergreen = async () => {
    setBusy(true); setMsg('');
    try {
      const p = await api('/api/evergreen',
        { method: 'POST', body: { account_id: id, topic: topic || null } });
      setMsg(`🌲 drafted #${p.id} — it's in the Review tab`);
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  if (!id) return <Card><div className="text-zinc-400">Create an account in Settings first.</div></Card>;

  return (
    <div className="space-y-4">
      <PageHeader title="Ideas"
        desc="The mid-tier signals worth a look, your morning briefing, and evergreen — a post from your standing arguments when news is slow." />
      <AccountPicker accounts={accounts} value={id} onChange={setAcct} />
      <Card>
        <div className="font-medium mb-2">🌲 Evergreen — no news needed</div>
        <div className="text-sm text-zinc-400 mb-2">
          Drafts your strongest recurring argument from memory. Topic optional.
        </div>
        <div className="flex gap-2">
          <Input placeholder="topic (optional)" value={topic}
                 onInput={(e) => setTopic(e.target.value)} className="max-w-xs" />
          <Btn color="green" disabled={busy} onClick={evergreen}>
            {busy ? 'drafting…' : 'Draft it'}
          </Btn>
        </div>
        {msg && <div className="mt-2 text-sm text-emerald-400">{msg}</div>}
      </Card>
      <Card>
        <div className="font-medium mb-2">💡 Ideas bank (yesterday's mid-tier signals)</div>
        {ideas.length === 0 && <div className="text-sm text-zinc-400">Empty — quiet day.</div>}
        {ideas.map((s) => (
          <div key={s.id}
               className="py-2 border-b border-zinc-800 last:border-0 flex items-start gap-3">
            <div className="flex-1">
              <div className="text-sm">[{s.score.toFixed(1)}] {s.title}</div>
              {s.angle && <div className="text-xs text-zinc-500">angle: {s.angle}</div>}
            </div>
            <Btn color="green" disabled={draftingId === s.id}
                 onClick={() => draftIdea(s.id)}>
              {draftingId === s.id ? 'drafting…' : '✍️ Draft this'}
            </Btn>
          </div>
        ))}
        {ideaMsg && <div className="mt-2 text-sm text-emerald-400">{ideaMsg}</div>}
      </Card>
      <Card>
        <div className="font-medium mb-2">☀️ Briefing</div>
        <pre className="text-sm text-zinc-300 whitespace-pre-wrap font-sans">{brief}</pre>
      </Card>
    </div>
  );
}
