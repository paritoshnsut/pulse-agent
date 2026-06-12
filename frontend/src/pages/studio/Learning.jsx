// Learning Dashboard — did it work, and what changed because of it?
// Approval rates by format and emotion, the rules the system learned from
// your reviews, topic-level historical performance, and your written feedback.

import { useEffect, useState } from 'react';
import { CheckCheck, MessageSquareText, Sparkles, TrendingUp } from 'lucide-react';
import { api } from '../../api.js';
import { Card, Chip, EmptyState, PageHeader, Select, Stat } from '../../components/ui.jsx';
import { KV, ScoreBar, fmtWhen } from './bits.jsx';

function RateTable({ bucket }) {
  const rows = Object.entries(bucket || {})
    .filter(([k]) => k !== 'unknown')
    .sort((a, b) => (b[1].rate ?? 0) - (a[1].rate ?? 0));
  if (!rows.length) return <div className="text-sm text-zinc-600">not enough reviews yet</div>;
  return (
    <div className="space-y-1.5">
      {rows.map(([k, d]) => (
        <ScoreBar key={k} label={k} value={(d.rate ?? 0) * 10} tone="green" />
      ))}
    </div>
  );
}

export default function Learning({ accounts }) {
  const [accountId, setAccountId] = useState(accounts[0]?.id || 0);
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!accountId) return;
    setData(null);
    api(`/api/studio/learning/${accountId}`).then(setData).catch(() => {});
  }, [accountId]);

  if (!accountId) {
    return <EmptyState icon={TrendingUp} title="No account yet"
      body="Create an account in Settings first." />;
  }

  const st = data?.stats || {};
  const by = data?.by_status || {};

  return (
    <div className="space-y-5">
      <PageHeader
        title="Learning Dashboard"
        desc="The feedback loop, visible. Every approve/reject teaches the system — here is what it learned."
        actions={
          <Select value={accountId} onChange={(e) => setAccountId(+e.target.value)}>
            {accounts.map((a) => <option key={a.id} value={a.id}>@{a.handle}</option>)}
          </Select>
        }
      />

      {!data && <div className="text-sm text-zinc-600">loading…</div>}
      {data && (
        <>
          <div className="flex flex-wrap gap-3">
            <Stat label="reviewed" value={st.total_reviewed ?? 0} icon={CheckCheck} />
            <Stat label="approval rate" tone="green" icon={TrendingUp}
              value={st.approval_rate != null ? `${Math.round(st.approval_rate * 100)}%` : '—'}
              sub={`${st.approved ?? 0} yes · ${st.rejected ?? 0} no`} />
            <Stat label="drafts waiting" value={by.draft || 0} tone="amber" />
            <Stat label="posted" value={by.posted || 0} tone="indigo" />
          </div>

          <div className="grid lg:grid-cols-2 gap-5">
            <Card title="Approval rate by format" icon={TrendingUp}
              desc="bars show the share of each format you approved">
              <RateTable bucket={st.by_format} />
            </Card>
            <Card title="Approval rate by emotion" icon={TrendingUp}
              desc="which emotional register lands with you">
              <RateTable bucket={st.by_emotion} />
            </Card>
          </div>

          <div className="grid lg:grid-cols-2 gap-5">
            <Card title="What the system learned" icon={Sparkles}
              desc="rules now injected into every generation prompt for this account">
              {Object.keys(data.learned_preferences || {}).length
                ? <KV obj={data.learned_preferences} />
                : <div className="text-sm text-zinc-600">
                    nothing yet — learning kicks in after enough reviews</div>}
              <div className="mt-3 pt-3 border-t border-zinc-800/70 grid grid-cols-2
                gap-2 text-[13px]">
                <div><span className="text-zinc-500">persona score (approved): </span>
                  <span className="text-emerald-400">{st.persona_score_approved ?? '—'}</span></div>
                <div><span className="text-zinc-500">persona score (rejected): </span>
                  <span className="text-rose-400">{st.persona_score_rejected ?? '—'}</span></div>
                <div><span className="text-zinc-500">avg length (approved): </span>
                  <span className="text-zinc-300">{st.avg_len_approved ?? '—'}</span></div>
                <div><span className="text-zinc-500">avg length (rejected): </span>
                  <span className="text-zinc-300">{st.avg_len_rejected ?? '—'}</span></div>
              </div>
            </Card>

            <Card title="Your written feedback" icon={MessageSquareText}
              desc="notes you left on redo / reject — the highest-signal training data">
              {(data.recent_feedback || []).length === 0 &&
                <div className="text-sm text-zinc-600">no notes yet</div>}
              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {(data.recent_feedback || []).map((f, i) => (
                  <div key={i} className="text-[13px] border-b border-zinc-800/50 pb-2">
                    <div className="flex items-center gap-2">
                      <Chip tone={f.kind === 'redo' ? 'amber' : 'red'}>{f.kind}</Chip>
                      {f.format && <Chip>{f.format}</Chip>}
                      <span className="text-zinc-600 text-xs">{fmtWhen(f.created_at)}</span>
                    </div>
                    <div className="text-zinc-300 mt-1 leading-relaxed">{f.note}</div>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          {data.historical_perf && (
            <Card title="Topic performance memory" icon={TrendingUp}
              desc="feeds the historical_perf subscore (0–10) — verticals you approved before rank higher">
              <div className="flex flex-wrap gap-1.5">
                <Chip tone="indigo">overall · {data.historical_perf.overall}</Chip>
                {Object.entries(data.historical_perf.by_vertical || {}).map(([v, score]) => (
                  <Chip key={v}
                    tone={score >= 6 ? 'green' : score <= 4 ? 'red' : 'zinc'}>
                    {v} · {score}
                  </Chip>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
