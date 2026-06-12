// Voice Studio — the voice, visible. Genome A (measured + judged from the
// user's own posts), Genome B (crowd wisdom), the blend, the corpus it was
// trained on, and the samples that earn the most engagement.

import { useEffect, useState } from 'react';
import { Dna, Layers, Mic2, Quote } from 'lucide-react';
import { api } from '../../api.js';
import { Card, Chip, EmptyState, PageHeader, Select } from '../../components/ui.jsx';
import { KV } from './bits.jsx';

export default function Voice({ accounts }) {
  const [accountId, setAccountId] = useState(accounts[0]?.id || 0);
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!accountId) return;
    setData(null);
    api(`/api/studio/voice/${accountId}`).then(setData).catch(() => {});
  }, [accountId]);

  if (!accountId) {
    return <EmptyState icon={Mic2} title="No account yet"
      body="Create an account in Settings first." />;
  }

  const genomeA = data?.genome_a || {};
  const phrases = genomeA.signature_phrases || [];
  const learned = genomeA.learned_preferences || {};

  return (
    <div className="space-y-5">
      <PageHeader
        title="Voice Studio"
        desc="The style DNA this account writes with — what was measured, what Claude judged, and what the feedback loop has changed since."
        actions={
          <Select value={accountId} onChange={(e) => setAccountId(+e.target.value)}>
            {accounts.map((a) => <option key={a.id} value={a.id}>@{a.handle}</option>)}
          </Select>
        }
      />

      {!data && <div className="text-sm text-zinc-600">loading…</div>}
      {data && !data.trained && (
        <Card>
          <EmptyState icon={Dna} title="No voice trained yet"
            body="Add samples in Settings → Voice (or one-paste import) and retrain." />
        </Card>
      )}

      {data?.trained && (
        <>
          <div className="flex flex-wrap gap-2">
            <Chip tone="green">voice v{data.version}</Chip>
            <Chip>trained on {data.sample_count} samples</Chip>
            {data.blend != null && (
              <Chip tone="indigo">blend: {Math.round((1 - data.blend) * 100)}% you
                / {Math.round(data.blend * 100)}% crowd</Chip>
            )}
          </div>

          <div className="grid lg:grid-cols-2 gap-5">
            <Card title="Genome A — your voice" icon={Dna}
              desc="extracted from this account's own writing">
              <KV obj={genomeA} skip={['signature_phrases', 'learned_preferences', 'brand']} />
              {phrases.length > 0 && (
                <div className="mt-3 pt-3 border-t border-zinc-800/70">
                  <div className="text-xs text-zinc-500 mb-1.5">signature phrases</div>
                  <div className="flex flex-wrap gap-1.5">
                    {phrases.map((p) => <Chip key={p} tone="indigo">“{p}”</Chip>)}
                  </div>
                </div>
              )}
              {Object.keys(learned).length > 0 && (
                <div className="mt-3 pt-3 border-t border-zinc-800/70">
                  <div className="text-xs text-amber-400 mb-1.5">
                    learned from your approvals/rejections
                  </div>
                  <KV obj={learned} />
                </div>
              )}
            </Card>

            <div className="space-y-5">
              <Card title="Genome B — crowd wisdom" icon={Layers}
                desc="patterns from top-performing posts in this niche">
                {data.genome_b ? <KV obj={data.genome_b} />
                  : <div className="text-sm text-zinc-600">
                      not scraped yet — runs weekly once configured</div>}
              </Card>

              <Card title="Training corpus" icon={Quote}>
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {data.corpus.kinds.map((k) => (
                    <Chip key={k.kind}>{k.kind}: {k.n}</Chip>
                  ))}
                  {data.corpus.origins.map((o) => (
                    <Chip key={o.origin} tone="zinc">{o.origin}: {o.n}</Chip>
                  ))}
                </div>
                {(data.corpus.top_samples || []).length > 0 && (
                  <>
                    <div className="text-xs text-zinc-500 mb-1.5">
                      your highest-engagement samples
                    </div>
                    <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                      {data.corpus.top_samples.map((s, i) => (
                        <div key={i} className="text-[13px] text-zinc-300 leading-relaxed
                          border-b border-zinc-800/50 pb-2">
                          {s.content}
                          {(s.likes || s.retweets) ? (
                            <span className="text-zinc-600 text-xs ml-2">
                              ♥ {s.likes || 0} · ⟳ {s.retweets || 0}
                            </span>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
