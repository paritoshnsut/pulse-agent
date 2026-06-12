// Mission Control — the whole factory in one view. The funnel from ingested
// articles down to posted drafts, the tier split, spend by module, and
// whether every source watcher is actually delivering.

import { useEffect, useState } from 'react';
import { Activity, Coins, Rss } from 'lucide-react';
import { api } from '../../api.js';
import { Card, Chip, PageHeader, Select } from '../../components/ui.jsx';
import { FunnelBar, TIER_TONE, fmtWhen } from './bits.jsx';

export default function MissionControl() {
  const [days, setDays] = useState(1);
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    api(`/api/studio/funnel?days=${days}`).then(setData).catch((e) => setErr(String(e)));
  }, [days]);

  if (err) return <div className="text-sm text-rose-400">{err}</div>;
  if (!data) return <div className="text-sm text-zinc-600">loading…</div>;

  const maxN = Math.max(...data.stages.map((s) => s.n), 1);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Mission Control"
        desc="What the machine did, end to end. Every article in, every judgement, every draft out."
        actions={
          <Select value={days} onChange={(e) => setDays(+e.target.value)}>
            <option value={1}>last 24h</option>
            <option value={7}>last 7 days</option>
            <option value={30}>last 30 days</option>
          </Select>
        }
      />

      <div className="grid lg:grid-cols-5 gap-5">
        <Card title="Pipeline funnel" icon={Activity} className="lg:col-span-3"
          desc="ingested → scored → qualified → drafted → approved → posted">
          <div className="space-y-3.5">
            {data.stages.map((s) => (
              <FunnelBar key={s.stage} stage={s.stage} n={s.n} maxN={maxN} desc={s.desc} />
            ))}
          </div>
          <div className="flex flex-wrap gap-2 mt-4 pt-3 border-t border-zinc-800/70">
            {['FIRE', 'WARM', 'COOL', 'SKIP'].map((t) => (
              <Chip key={t} tone={TIER_TONE[t]}>{t} {data.tiers[t] || 0}</Chip>
            ))}
            <Chip tone="red">rejected {data.rejected}</Chip>
          </div>
        </Card>

        <div className="lg:col-span-2 space-y-5">
          <Card title="Claude spend" icon={Coins}
            desc={`$${data.spend_total_usd} across ${days === 1 ? '24h' : `${days} days`}`}>
            {data.spend.length === 0 && <div className="text-sm text-zinc-600">no calls yet</div>}
            <div className="space-y-1.5">
              {data.spend.map((s) => (
                <div key={s.module} className="flex items-center justify-between text-[13px]">
                  <span className="text-zinc-300">{s.module}</span>
                  <span className="text-zinc-500 tabular-nums">
                    {s.calls} calls · ${s.usd ?? 0}
                  </span>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Source health" icon={Rss} desc="is every watcher delivering?">
            {data.sources.length === 0 && (
              <div className="text-sm text-zinc-600">no articles in this window</div>
            )}
            <div className="space-y-1.5">
              {data.sources.map((s) => (
                <div key={s.source} className="flex items-center justify-between text-[13px]">
                  <span className="text-zinc-300">{s.source}</span>
                  <span className="text-zinc-500 tabular-nums">
                    {s.n} · {fmtWhen(s.last_seen)}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
