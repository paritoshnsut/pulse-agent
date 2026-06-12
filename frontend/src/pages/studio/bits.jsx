// Shared Studio primitives: score bars, tier chips, tiny formatters.
// The Studio's job is to make numbers legible at a glance — bars over tables.

import { Chip } from '../../components/ui.jsx';

export const TIER_TONE = { FIRE: 'red', WARM: 'amber', COOL: 'indigo', SKIP: 'zinc' };

export function TierChip({ tier }) {
  return <Chip tone={TIER_TONE[tier] || 'zinc'}>{tier}</Chip>;
}

// A 0-10 subscore as a labelled horizontal bar.
export function ScoreBar({ label, value, max = 10, tone = 'indigo' }) {
  const pct = Math.max(0, Math.min(100, ((value || 0) / max) * 100));
  const tones = { indigo: 'bg-indigo-500', amber: 'bg-amber-500',
                  green: 'bg-emerald-500', zinc: 'bg-zinc-600' };
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-32 shrink-0 text-zinc-500 truncate">{label}</span>
      <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${tones[tone] || tones.indigo}`}
          style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-right text-zinc-400 tabular-nums">
        {value == null ? '—' : Number(value).toFixed(1)}
      </span>
    </div>
  );
}

// A funnel stage: count bar scaled against the widest stage.
export function FunnelBar({ stage, n, maxN, desc }) {
  const pct = maxN ? Math.max(2, (n / maxN) * 100) : 2;
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium capitalize">{stage}</span>
        <span className="text-zinc-300 font-bold tabular-nums">{n}</span>
      </div>
      <div className="h-2.5 bg-zinc-800/80 rounded-full mt-1 overflow-hidden">
        <div className="h-full rounded-full bg-gradient-to-r from-amber-500 to-orange-500"
          style={{ width: `${pct}%` }} />
      </div>
      <div className="text-[11px] text-zinc-600 mt-0.5">{desc}</div>
    </div>
  );
}

export function fmtWhen(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

// genome values arrive as strings, numbers, booleans, arrays — render anything.
export function renderVal(v) {
  if (v == null) return '—';
  if (Array.isArray(v)) return v.join(' · ');
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

// key/value grid for genome traits and learned rules
export function KV({ obj, skip = [] }) {
  const entries = Object.entries(obj || {}).filter(([k]) => !skip.includes(k));
  if (!entries.length) return <div className="text-sm text-zinc-600">nothing yet</div>;
  return (
    <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2 text-[13px] min-w-0">
          <span className="text-zinc-500 shrink-0">{k.replaceAll('_', ' ')}:</span>
          <span className="text-zinc-300 truncate" title={renderVal(v)}>{renderVal(v)}</span>
        </div>
      ))}
    </div>
  );
}
