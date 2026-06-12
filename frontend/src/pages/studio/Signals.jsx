// Signal Center — every judged story, ranked. Expand a row to see all seven
// subscores, the model's reasoning, the suggested angle, and brand safety.
// This is "why did the agent care about THIS story" made visible.

import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, ExternalLink, Radar } from 'lucide-react';
import { api } from '../../api.js';
import { Card, Chip, EmptyState, PageHeader, Select } from '../../components/ui.jsx';
import { ScoreBar, TierChip, fmtWhen } from './bits.jsx';

const SUBSCORES = [
  ['velocity', 'velocity'],
  ['relevance', 'relevance'],
  ['corroboration', 'corroboration'],
  ['reaction_potential', 'reaction potential'],
  ['memory_leverage', 'memory leverage'],
  ['window_urgency', 'window urgency'],
  ['historical_perf', 'historical perf'],
];

export default function Signals({ accounts }) {
  const [accountId, setAccountId] = useState(0);          // 0 = all
  const [tier, setTier] = useState('');
  const [days, setDays] = useState(3);
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    const p = new URLSearchParams({ days });
    if (tier) p.set('tier', tier);
    if (accountId) p.set('account_id', accountId);
    api(`/api/studio/signals?${p}`).then(setRows).catch(() => setRows([]));
  }, [accountId, tier, days]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Signal Center"
        desc="Every story the decision agent judged, ranked by score. Expand one to see exactly why."
        actions={
          <div className="flex gap-2">
            <Select value={accountId} onChange={(e) => setAccountId(+e.target.value)}>
              <option value={0}>all accounts</option>
              {accounts.map((a) => <option key={a.id} value={a.id}>@{a.handle}</option>)}
            </Select>
            <Select value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value="">all tiers</option>
              {['FIRE', 'WARM', 'COOL', 'SKIP'].map((t) => <option key={t}>{t}</option>)}
            </Select>
            <Select value={days} onChange={(e) => setDays(+e.target.value)}>
              <option value={1}>24h</option>
              <option value={3}>3 days</option>
              <option value={7}>7 days</option>
            </Select>
          </div>
        }
      />

      {rows === null && <div className="text-sm text-zinc-600">loading…</div>}
      {rows?.length === 0 && (
        <Card><EmptyState icon={Radar} title="No signals in this window"
          body="Run the pipeline, or widen the time range." /></Card>
      )}

      <div className="space-y-2">
        {rows?.map((s) => {
          const isOpen = open === s.id;
          return (
            <div key={s.id}
              className="bg-zinc-900/60 border border-zinc-800/70 rounded-2xl px-4 py-3">
              <button onClick={() => setOpen(isOpen ? null : s.id)}
                className="w-full flex items-center gap-3 text-left">
                {isOpen ? <ChevronDown size={15} className="text-zinc-500 shrink-0" />
                        : <ChevronRight size={15} className="text-zinc-500 shrink-0" />}
                <span className="text-lg font-bold tabular-nums w-10 shrink-0
                  text-amber-400">{Number(s.score).toFixed(1)}</span>
                <TierChip tier={s.tier} />
                <span className="flex-1 min-w-0 text-sm text-zinc-200 truncate">{s.title}</span>
                <span className="hidden sm:block text-xs text-zinc-600 shrink-0">
                  {s.handle ? `@${s.handle} · ` : ''}{s.source_name || ''} · {fmtWhen(s.created_at)}
                </span>
              </button>

              {isOpen && (
                <div className="mt-3 pt-3 border-t border-zinc-800/70 grid md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    {SUBSCORES.map(([k, label]) => (
                      <ScoreBar key={k} label={label} value={s[k]} tone="amber" />
                    ))}
                    <ScoreBar label="brand safety" value={s.brand_safety} tone="green" />
                  </div>
                  <div className="space-y-2 text-[13px]">
                    <div className="flex flex-wrap gap-1.5">
                      {s.topic && <Chip>{s.topic}</Chip>}
                      {s.format && <Chip tone="indigo">{s.format}</Chip>}
                      {s.sensitivity && s.sensitivity !== 'safe' &&
                        <Chip tone="amber">{s.sensitivity}</Chip>}
                      {s.vertical && <Chip>{s.vertical}</Chip>}
                    </div>
                    {s.angle && (
                      <div><span className="text-zinc-500">angle: </span>
                        <span className="text-zinc-300">{s.angle}</span></div>
                    )}
                    {s.reasoning && (
                      <div className="text-zinc-400 leading-relaxed">
                        <span className="text-zinc-500">reasoning: </span>{s.reasoning}
                      </div>
                    )}
                    {s.url && (
                      <a href={s.url} target="_blank" rel="noreferrer"
                        className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300">
                        <ExternalLink size={12} /> source article
                      </a>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
