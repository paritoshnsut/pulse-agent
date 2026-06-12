// Content Graph Viewer — one asset's full decomposition tree. The squeezer's
// "understanding" made visible: asset → ideas (with angles) → packs → drafts,
// plus every extracted claim, statistic, quote, story, and opinion.

import { useEffect, useState } from 'react';
import { GitBranch, Lightbulb } from 'lucide-react';
import { api } from '../../api.js';
import { Card, Chip, EmptyState, PageHeader, Select } from '../../components/ui.jsx';
import { fmtWhen } from './bits.jsx';

const NODE_LABEL = {
  claim: '🔎 claims', story: '📖 stories', statistic: '📊 statistics',
  quote: '💬 quotes', opinion: '🗣 opinions',
};

const STATUS_TONE = {
  draft: 'zinc', approved: 'green', edited: 'green', posted: 'indigo',
  rejected: 'red', expired: 'amber',
};

export default function Graph({ accounts }) {
  const [accountId, setAccountId] = useState(accounts[0]?.id || 0);
  const [assets, setAssets] = useState(null);
  const [picked, setPicked] = useState(null);
  const [graph, setGraph] = useState(null);

  useEffect(() => {
    if (!accountId) return;
    setPicked(null);
    api(`/api/accounts/${accountId}/assets`).then(setAssets).catch(() => setAssets([]));
  }, [accountId]);

  useEffect(() => {
    if (!picked) { setGraph(null); return; }
    setGraph(null);
    api(`/api/studio/graph/${picked}`).then(setGraph).catch(() => {});
  }, [picked]);

  if (!accountId) {
    return <EmptyState icon={GitBranch} title="No account yet"
      body="Create an account in Settings first." />;
  }

  const ideas = graph?.nodes?.idea || [];
  const otherKinds = Object.entries(graph?.nodes || {}).filter(([k]) => k !== 'idea');

  return (
    <div className="space-y-5">
      <PageHeader
        title="Content Graph"
        desc="How the squeezer read your content: the ideas it found, the angles on each, and every draft built from them."
        actions={
          <Select value={accountId} onChange={(e) => setAccountId(+e.target.value)}>
            {accounts.map((a) => <option key={a.id} value={a.id}>@{a.handle}</option>)}
          </Select>
        }
      />

      <div className="grid lg:grid-cols-5 gap-5">
        <Card title="Asset library" className="lg:col-span-2">
          {assets === null && <div className="text-sm text-zinc-600">loading…</div>}
          {assets?.length === 0 && (
            <EmptyState icon={GitBranch} title="No assets yet"
              body="Squeeze something in the App's Repurpose tab — it lands here." />
          )}
          <div className="space-y-1 max-h-[30rem] overflow-y-auto pr-1">
            {assets?.map((a) => (
              <button key={a.id} onClick={() => setPicked(a.id)}
                className={`w-full text-left px-3 py-2 rounded-xl text-[13px] transition-colors
                  ${picked === a.id
                    ? 'bg-amber-500/10 border border-amber-500/30'
                    : 'hover:bg-zinc-900 border border-transparent'}`}>
                <div className="text-zinc-200 font-medium truncate">
                  {a.title || `asset #${a.id}`}
                </div>
                <div className="text-zinc-600 text-xs mt-0.5">
                  {a.source_type} · {a.chars} chars · {a.ideas || 0} ideas ·
                  {' '}{a.drafts || 0} drafts · {fmtWhen(a.created_at)}
                </div>
              </button>
            ))}
          </div>
        </Card>

        <div className="lg:col-span-3 space-y-5">
          {!picked && (
            <Card><EmptyState icon={GitBranch} title="Select an asset"
              body="Its decomposition tree appears here." /></Card>
          )}
          {picked && !graph && <div className="text-sm text-zinc-600">loading graph…</div>}
          {graph && (
            <>
              <Card title={graph.asset.title || `Asset #${graph.asset.id}`}
                desc={`${graph.asset.source_type}${graph.asset.source_url ? ` · ${graph.asset.source_url}` : ''}`}>
                <div className="text-[13px] text-zinc-500 leading-relaxed italic">
                  “{graph.asset.excerpt}{graph.asset.excerpt?.length >= 600 ? '…' : ''}”
                </div>
              </Card>

              {ideas.length === 0 && graph.packs.length === 0 && (
                <Card><EmptyState icon={Lightbulb} title="Not decomposed yet"
                  body="Re-squeeze this asset to build its content graph." /></Card>
              )}

              {graph.packs.map((pack) => {
                const ideaNode = ideas.find((n) => n.text === pack.idea);
                return (
                <Card key={pack.id} title={`💡 ${pack.idea || `pack #${pack.id}`}`}
                  desc={ideaNode?.angles?.length
                    ? `angles: ${ideaNode.angles.join('  ·  ')}` : undefined}>
                  {pack.drafts.length === 0 &&
                    <div className="text-sm text-zinc-600">no drafts in this pack</div>}
                  <div className="flex flex-wrap gap-1.5">
                    {pack.drafts.map((d) => (
                      <Chip key={d.id} tone={STATUS_TONE[d.status] || 'zinc'}>
                        {d.format} · {d.status}
                        {d.persona_score != null ? ` · ${d.persona_score}` : ''}
                      </Chip>
                    ))}
                  </div>
                </Card>
                );
              })}

              {otherKinds.length > 0 && (
                <Card title="Extracted nodes"
                  desc="the raw material drafts are grounded in — extracted, never invented">
                  <div className="space-y-3">
                    {otherKinds.map(([kind, nodes]) => (
                      <div key={kind}>
                        <div className="text-xs text-zinc-500 mb-1">
                          {NODE_LABEL[kind] || kind}
                        </div>
                        <div className="space-y-1">
                          {nodes.map((n, i) => (
                            <div key={i} className="text-[13px] text-zinc-300 leading-relaxed">
                              · {n.text}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
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
