// Memory Inspector — what the agent knows. Stances it has taken, predictions
// it has staked, the events timeline it files everything against. Searchable:
// "show me everything we've said about AI regulation".

import { useEffect, useState } from 'react';
import { Brain, CalendarClock, MessageSquareQuote, Target } from 'lucide-react';
import { api } from '../../api.js';
import { Card, Chip, EmptyState, Input, PageHeader, Select, Stat } from '../../components/ui.jsx';
import { fmtWhen } from './bits.jsx';

export default function Memory({ accounts }) {
  const [accountId, setAccountId] = useState(accounts[0]?.id || 0);
  const [q, setQ] = useState('');
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!accountId) return;
    const t = setTimeout(() => {
      const p = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : '';
      api(`/api/studio/memory/${accountId}${p}`).then(setData).catch(() => setData(null));
    }, 250);
    return () => clearTimeout(t);
  }, [accountId, q]);

  if (!accountId) {
    return <EmptyState icon={Brain} title="No account yet"
      body="Create an account in Settings first." />;
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Memory Inspector"
        desc="The agent's long-term memory: every stance, every prediction, the running events timeline. This is the moat — and here you can read it."
        actions={
          <Select value={accountId} onChange={(e) => setAccountId(+e.target.value)}>
            {accounts.map((a) => <option key={a.id} value={a.id}>@{a.handle}</option>)}
          </Select>
        }
      />

      <Input placeholder="search topics, stances, predictions… (e.g. ai-regulation)"
        value={q} onChange={(e) => setQ(e.target.value)} />

      {!data && <div className="text-sm text-zinc-600">loading…</div>}
      {data && (
        <>
          <div className="flex flex-wrap gap-3">
            <Stat label="stances held" value={data.totals.stances} icon={MessageSquareQuote} />
            <Stat label="predictions" value={data.totals.predictions} icon={Target}
              sub={`${data.totals.open_predictions} still open`} tone="amber" />
            <Stat label="events filed" value={data.totals.events} icon={CalendarClock} />
          </div>

          {data.topics.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {data.topics.map((t) => (
                <button key={t.topic} onClick={() => setQ(t.topic)}>
                  <Chip tone={q === t.topic ? 'amber' : 'zinc'}>{t.topic} · {t.n}</Chip>
                </button>
              ))}
            </div>
          )}

          <div className="grid lg:grid-cols-2 gap-5">
            <Card title="Stances" icon={MessageSquareQuote}
              desc="positions this account has taken — checked before every new draft">
              {data.stances.length === 0 && <div className="text-sm text-zinc-600">none match</div>}
              <div className="space-y-2.5 max-h-96 overflow-y-auto pr-1">
                {data.stances.map((s) => (
                  <div key={s.id} className="text-[13px] border-b border-zinc-800/50 pb-2">
                    <div className="flex items-center gap-2">
                      <Chip>{s.topic}</Chip>
                      <span className="text-zinc-600 text-xs">{fmtWhen(s.created_at)}</span>
                    </div>
                    <div className="text-zinc-300 mt-1 leading-relaxed">{s.stance}</div>
                  </div>
                ))}
              </div>
            </Card>

            <div className="space-y-5">
              <Card title="Predictions" icon={Target}
                desc="staked positions — when an outcome arrives, the agent drafts the callback">
                {data.predictions.length === 0 && <div className="text-sm text-zinc-600">none match</div>}
                <div className="space-y-2.5 max-h-44 overflow-y-auto pr-1">
                  {data.predictions.map((p) => (
                    <div key={p.id} className="text-[13px] border-b border-zinc-800/50 pb-2">
                      <div className="flex items-center gap-2">
                        <Chip tone={p.status === 'open' ? 'amber' : 'green'}>{p.status}</Chip>
                        <Chip>{p.topic}</Chip>
                      </div>
                      <div className="text-zinc-300 mt-1 leading-relaxed">{p.prediction}</div>
                    </div>
                  ))}
                </div>
              </Card>

              <Card title="Events timeline" icon={CalendarClock}
                desc="the shared world-model every account draws context from">
                {data.events.length === 0 && <div className="text-sm text-zinc-600">none match</div>}
                <div className="space-y-2.5 max-h-44 overflow-y-auto pr-1">
                  {data.events.map((e) => (
                    <div key={e.id} className="text-[13px] border-b border-zinc-800/50 pb-2">
                      <div className="flex items-center gap-2">
                        <Chip>{e.topic}</Chip>
                        <span className="text-zinc-600 text-xs">{fmtWhen(e.created_at)}</span>
                      </div>
                      <div className="text-zinc-400 mt-1 leading-relaxed">{e.summary}</div>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
