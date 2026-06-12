// Generation Inspector — one draft, fully explained. Pick any post and see
// the entire chain that produced it: the triggering signal with all subscores
// and reasoning, the source article, the idea/angle (squeezer drafts), the
// guard verdicts, the persona score, and any engagement that followed.

import { useEffect, useState } from 'react';
import { ExternalLink, SearchCode } from 'lucide-react';
import { api } from '../../api.js';
import { Card, Chip, EmptyState, PageHeader, Select } from '../../components/ui.jsx';
import { ScoreBar, TierChip, fmtWhen } from './bits.jsx';

const STATUS_TONE = {
  draft: 'zinc', approved: 'green', edited: 'green', posted: 'indigo',
  rejected: 'red', expired: 'amber',
};

const SUBSCORES = [
  ['velocity', 'velocity'], ['relevance', 'relevance'],
  ['corroboration', 'corroboration'], ['reaction_potential', 'reaction potential'],
  ['memory_leverage', 'memory leverage'], ['window_urgency', 'window urgency'],
  ['historical_perf', 'historical perf'],
];

export default function Inspector({ accounts }) {
  const [accountId, setAccountId] = useState(0);
  const [posts, setPosts] = useState(null);
  const [picked, setPicked] = useState(null);
  const [trace, setTrace] = useState(null);

  useEffect(() => {
    const p = accountId ? `?account_id=${accountId}` : '';
    api(`/api/studio/posts${p}`).then(setPosts).catch(() => setPosts([]));
  }, [accountId]);

  useEffect(() => {
    if (!picked) { setTrace(null); return; }
    setTrace(null);
    api(`/api/studio/trace/${picked}`).then(setTrace).catch(() => {});
  }, [picked]);

  const meta = trace?.post?.meta_json || {};

  return (
    <div className="space-y-5">
      <PageHeader
        title="Generation Inspector"
        desc="Pick a draft, see its whole life: the signal that fired, the judgement, the angle, the guards, the outcome."
        actions={
          <Select value={accountId} onChange={(e) => { setAccountId(+e.target.value); setPicked(null); }}>
            <option value={0}>all accounts</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>@{a.handle}</option>)}
          </Select>
        }
      />

      <div className="grid lg:grid-cols-5 gap-5">
        {/* pick list */}
        <Card title="Recent drafts" className="lg:col-span-2">
          {posts === null && <div className="text-sm text-zinc-600">loading…</div>}
          {posts?.length === 0 && (
            <EmptyState icon={SearchCode} title="No drafts yet"
              body="Run the pipeline or squeeze some content first." />
          )}
          <div className="space-y-1 max-h-[32rem] overflow-y-auto pr-1">
            {posts?.map((p) => (
              <button key={p.id} onClick={() => setPicked(p.id)}
                className={`w-full text-left px-3 py-2 rounded-xl text-[13px] transition-colors
                  ${picked === p.id
                    ? 'bg-amber-500/10 border border-amber-500/30'
                    : 'hover:bg-zinc-900 border border-transparent'}`}>
                <div className="flex items-center gap-2">
                  <Chip tone={STATUS_TONE[p.status] || 'zinc'}>{p.status}</Chip>
                  <Chip>{p.format}</Chip>
                  <span className="text-zinc-600 text-xs ml-auto">{fmtWhen(p.created_at)}</span>
                </div>
                <div className="text-zinc-400 mt-1 truncate">{p.preview}</div>
              </button>
            ))}
          </div>
        </Card>

        {/* trace */}
        <div className="lg:col-span-3 space-y-5">
          {!picked && (
            <Card><EmptyState icon={SearchCode} title="Select a draft"
              body="Its full generation trace appears here." /></Card>
          )}
          {picked && !trace && <div className="text-sm text-zinc-600">loading trace…</div>}
          {trace && (
            <>
              <Card title="The draft"
                actions={<div className="flex gap-1.5">
                  <Chip tone={STATUS_TONE[trace.post.status] || 'zinc'}>{trace.post.status}</Chip>
                  {trace.post.persona_score != null && (
                    <Chip tone={trace.post.persona_score > 70 ? 'green' : 'amber'}>
                      persona {trace.post.persona_score}</Chip>
                  )}
                </div>}>
                <div className="text-sm text-zinc-200 whitespace-pre-wrap leading-relaxed">
                  {trace.post.content}
                </div>
                <div className="flex flex-wrap gap-1.5 mt-3">
                  <Chip>{trace.post.format}</Chip>
                  {meta.emotion && <Chip tone="indigo">{meta.emotion}</Chip>}
                  {meta.idea && <Chip tone="amber">💡 {meta.idea}</Chip>}
                  {meta.angle && <Chip>{meta.angle}</Chip>}
                  {(meta.guards || []).map((g) => <Chip key={g} tone="amber">⚠ {g}</Chip>)}
                  {(meta.brand_violations || []).map((b) => <Chip key={b} tone="red">🚫 {b}</Chip>)}
                </div>
              </Card>

              {trace.signal && (
                <Card title="The signal that triggered it"
                  actions={<TierChip tier={trace.signal.tier} />}>
                  <div className="space-y-1.5">
                    <ScoreBar label="composite" value={trace.signal.score} tone="amber" />
                    {SUBSCORES.map(([k, label]) => (
                      <ScoreBar key={k} label={label} value={trace.signal[k]} tone="zinc" />
                    ))}
                  </div>
                  {trace.signal.reasoning && (
                    <div className="text-[13px] text-zinc-400 mt-3 leading-relaxed">
                      <span className="text-zinc-500">reasoning: </span>{trace.signal.reasoning}
                    </div>
                  )}
                </Card>
              )}

              {trace.article && (
                <Card title="The source">
                  <div className="text-sm text-zinc-300">{trace.article.title}</div>
                  <div className="text-xs text-zinc-600 mt-1">
                    {trace.article.source_name || trace.article.source} · {fmtWhen(trace.article.published_at)}
                  </div>
                  {trace.article.url && (
                    <a href={trace.article.url} target="_blank" rel="noreferrer"
                      className="inline-flex items-center gap-1 text-indigo-400
                        hover:text-indigo-300 text-[13px] mt-2">
                      <ExternalLink size={12} /> open article
                    </a>
                  )}
                </Card>
              )}

              {trace.pack && (
                <Card title="Squeezed from">
                  <div className="text-[13px] text-zinc-300">
                    pack #{trace.pack.id}{trace.pack.idea ? ` — 💡 ${trace.pack.idea}` : ''}
                  </div>
                </Card>
              )}

              {trace.engagement && (
                <Card title="Engagement">
                  <div className="flex gap-4 text-sm text-zinc-300">
                    <span>♥ {trace.engagement.likes ?? 0}</span>
                    <span>⟳ {trace.engagement.retweets ?? 0}</span>
                    <span>💬 {trace.engagement.replies ?? 0}</span>
                    {trace.engagement.impressions != null &&
                      <span>👁 {trace.engagement.impressions}</span>}
                  </div>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
