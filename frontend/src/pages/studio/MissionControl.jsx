// Mission Control — the whole factory in one view. The funnel from ingested
// articles down to posted drafts, the tier split, spend by module, and
// whether every source watcher is actually delivering.

import { useEffect, useRef, useState } from 'react';
import { Activity, Coins, Rss, X, ExternalLink, ChevronDown, ChevronRight } from 'lucide-react';
import { api } from '../../api.js';
import { Card, Chip, PageHeader, Select } from '../../components/ui.jsx';
import { FunnelBar, TIER_TONE, fmtWhen } from './bits.jsx';

// ── Source badge colours ────────────────────────────────────────────────────
const SOURCE_TONE = {
  rss: 'amber', gnews: 'indigo', trends: 'emerald', wikipedia: 'zinc',
  moments: 'rose', yt_search: 'red', reddit: 'orange', youtube: 'red',
};
function SourceBadge({ source }) {
  const tone = SOURCE_TONE[source] || 'zinc';
  const cls = {
    amber: 'bg-amber-500/15 text-amber-300', indigo: 'bg-indigo-500/15 text-indigo-300',
    emerald: 'bg-emerald-500/15 text-emerald-300', zinc: 'bg-zinc-700 text-zinc-300',
    rose: 'bg-rose-500/15 text-rose-300', red: 'bg-red-500/15 text-red-300',
    orange: 'bg-orange-500/15 text-orange-300',
  }[tone] || 'bg-zinc-700 text-zinc-300';
  return <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-medium ${cls}`}>{source}</span>;
}

// ── Collapsible raw JSON row ────────────────────────────────────────────────
function ArticleRow({ art }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-zinc-800 last:border-0">
      <div className="flex items-start gap-3 py-2.5 px-3 hover:bg-zinc-800/40 transition-colors">
        <button onClick={() => setOpen((v) => !v)}
          className="mt-0.5 text-zinc-600 hover:text-zinc-400 shrink-0">
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <SourceBadge source={art.source} />
            {art.vertical && (
              <span className="text-[10px] text-zinc-600">{art.vertical}</span>
            )}
          </div>
          <p className="text-[13px] text-zinc-200 mt-0.5 leading-snug line-clamp-2">
            {art.title || <span className="text-zinc-600 italic">no title</span>}
          </p>
          <div className="flex items-center gap-3 mt-1 text-[11px] text-zinc-600">
            <span>{fmtWhen(art.fetched_at)}</span>
            {art.velocity_hint != null && (
              <span className="text-zinc-500">vel {Number(art.velocity_hint).toFixed(1)}</span>
            )}
            {art.url && !art.url.startsWith('moment://') && (
              <a href={art.url} target="_blank" rel="noreferrer"
                className="flex items-center gap-0.5 hover:text-zinc-300">
                <ExternalLink size={10} /> source
              </a>
            )}
          </div>
        </div>
      </div>
      {open && (
        <div className="px-3 pb-3 bg-zinc-900/60">
          <pre className="text-[11px] text-zinc-400 bg-zinc-950 rounded p-2.5 overflow-x-auto max-h-48
                          scrollbar-thin scrollbar-thumb-zinc-700 whitespace-pre-wrap break-all">
            {JSON.stringify(
              { id: art.id, source: art.source, source_name: art.source_name,
                url: art.url, vertical: art.vertical, velocity_hint: art.velocity_hint,
                published_at: art.published_at, fetched_at: art.fetched_at,
                raw_json: art.raw_json },
              null, 2
            )}
          </pre>
        </div>
      )}
    </div>
  );
}

// ── Ingested articles drawer ────────────────────────────────────────────────
function ArticlesDrawer({ days, onClose }) {
  const [source, setSource] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const LIMIT = 80;
  const overlayRef = useRef(null);

  useEffect(() => {
    setLoading(true);
    setOffset(0);
    api(`/api/studio/articles?days=${days}&limit=${LIMIT}&offset=0${source ? `&source=${source}` : ''}`)
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [days, source]);

  const loadMore = () => {
    const next = offset + LIMIT;
    api(`/api/studio/articles?days=${days}&limit=${LIMIT}&offset=${next}${source ? `&source=${source}` : ''}`)
      .then((d) => {
        setData((prev) => ({ ...d, articles: [...(prev?.articles || []), ...d.articles] }));
        setOffset(next);
      });
  };

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* backdrop */}
      <div ref={overlayRef} className="flex-1 bg-black/60 backdrop-blur-sm"
        onClick={onClose} />
      {/* panel */}
      <div className="w-full max-w-2xl bg-zinc-900 border-l border-zinc-800
                      flex flex-col h-full shadow-2xl"
           style={{ animation: 'slideInRight 0.2s ease-out' }}>
        {/* header */}
        <div className="flex items-center justify-between px-4 py-3.5 border-b border-zinc-800 shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-zinc-100">Ingested articles</h2>
            <p className="text-[11px] text-zinc-500 mt-0.5">
              Everything the watchers pulled in — last {days === 1 ? '24h' : `${days} days`}
            </p>
          </div>
          <button onClick={onClose}
            className="text-zinc-600 hover:text-zinc-300 transition-colors p-1 rounded hover:bg-zinc-800">
            <X size={16} />
          </button>
        </div>

        {/* source filter pills */}
        {data?.sources?.length > 0 && (
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-zinc-800/60 flex-wrap shrink-0">
            <button onClick={() => setSource('')}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors
                ${!source ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300'}`}>
              all ({data.total})
            </button>
            {data.sources.map((s) => (
              <button key={s.source} onClick={() => setSource(s.source === source ? '' : s.source)}
                className={`px-2.5 py-1 rounded text-xs font-medium transition-colors
                  ${source === s.source ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300'}`}>
                {s.source} ({s.n})
              </button>
            ))}
          </div>
        )}

        {/* list */}
        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="text-sm text-zinc-600 px-4 py-6">loading…</div>
          )}
          {!loading && data?.articles?.length === 0 && (
            <div className="text-sm text-zinc-600 px-4 py-6">no articles in this window</div>
          )}
          {!loading && data?.articles?.map((art) => (
            <ArticleRow key={art.id} art={art} />
          ))}
          {!loading && data && data.articles.length < data.total && (
            <div className="px-4 py-4 flex justify-center">
              <button onClick={loadMore}
                className="text-xs text-zinc-500 hover:text-zinc-300 border border-zinc-700
                           hover:border-zinc-600 px-4 py-1.5 rounded transition-colors">
                load more ({data.total - data.articles.length} remaining)
              </button>
            </div>
          )}
        </div>

        {/* footer count */}
        {!loading && data && (
          <div className="px-4 py-2.5 border-t border-zinc-800 shrink-0
                          text-[11px] text-zinc-600 flex justify-between">
            <span>showing {data.articles.length} of {data.total}</span>
            <span>{source ? `filtered: ${source}` : 'all sources'}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────────────
export default function MissionControl() {
  const [days, setDays] = useState(1);
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);

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
              <div key={s.stage} className="group relative">
                <FunnelBar stage={s.stage} n={s.n} maxN={maxN} desc={s.desc} />
                {s.stage === 'ingested' && s.n > 0 && (
                  <button
                    onClick={() => setDrawerOpen(true)}
                    className="absolute right-0 top-0 text-[11px] text-zinc-600
                               hover:text-amber-400 transition-colors opacity-0 group-hover:opacity-100
                               border border-zinc-700 hover:border-amber-500/50 px-2 py-0.5 rounded">
                    view all →
                  </button>
                )}
              </div>
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

          <Card title="Source health" icon={Rss} desc="is every watcher delivering?"
            actions={
              data.sources.length > 0 && (
                <button onClick={() => setDrawerOpen(true)}
                  className="text-[11px] text-zinc-500 hover:text-amber-400 transition-colors
                             border border-zinc-700 hover:border-amber-500/50 px-2 py-1 rounded">
                  browse all
                </button>
              )
            }>
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

      {drawerOpen && (
        <ArticlesDrawer days={days} onClose={() => setDrawerOpen(false)} />
      )}
    </div>
  );
}
