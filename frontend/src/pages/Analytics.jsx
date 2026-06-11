// Approval / format / emotion performance, learned posting windows.

import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { AccountPicker, Card, PageHeader } from '../components/ui.jsx';

function Rates({ title, rates }) {
  const entries = Object.entries(rates || {});
  if (!entries.length) return null;
  return (
    <Card>
      <div className="font-medium mb-2">{title}</div>
      {entries.map(([k, v]) => (
        <div key={k} className="flex justify-between text-sm py-0.5">
          <span className="text-zinc-400">{k}</span>
          <span>
            {v?.rate != null ? `${Math.round(v.rate * 100)}%` : '—'}
            {v?.approved != null && (
              <span className="text-zinc-500"> ({v.approved}✓ {v.rejected}✗)</span>
            )}
          </span>
        </div>
      ))}
    </Card>
  );
}

export default function Analytics({ accounts }) {
  const [acct, setAcct] = useState(null);
  const [a, setA] = useState(null);
  const id = acct ?? accounts[0]?.id;

  useEffect(() => { if (id) api(`/api/analytics/${id}`).then(setA).catch(() => {}); }, [id]);

  if (!id) return <Card><div className="text-zinc-400">Create an account in Settings first.</div></Card>;
  if (!a) return <AccountPicker accounts={accounts} value={id} onChange={setAcct} />;

  const s = a.stats;
  const tiles = [
    ['reviewed', s.total_reviewed],
    ['approval', s.approval_rate != null ? `${Math.round(s.approval_rate * 100)}%` : '—'],
    ['news sense (0-10)', a.historical_perf.overall],
    ['open predictions', a.open_predictions],
  ];
  return (
    <div className="space-y-4">
      <PageHeader title="Analytics"
        desc="What the learning loops know so far: approval rates, which formats and emotions land, and your best posting windows." />
      <AccountPicker accounts={accounts} value={id} onChange={setAcct} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {tiles.map(([k, v]) => (
          <Card key={k}>
            <div className="text-2xl font-bold">{v}</div>
            <div className="text-xs text-zinc-400">{k}</div>
          </Card>
        ))}
      </div>
      <Card>
        <div className="font-medium mb-1">⏰ Best posting windows ({a.timing.label})</div>
        <div className="text-sm">
          {a.timing.windows
            .map((w) => `${String(w[0]).padStart(2, '0')}:00–${String(w[1]).padStart(2, '0')}:00`)
            .join(', ')}
        </div>
        <div className="text-xs text-zinc-500 mt-1">
          {a.timing.learned
            ? `learned from ${a.timing.samples} posts`
            : 'defaults — log engagement on 8+ posts to personalize'}
        </div>
      </Card>
      <div className="grid md:grid-cols-2 gap-4">
        <Rates title="By format" rates={s.by_format} />
        <Rates title="By emotion" rates={s.by_emotion} />
      </div>
    </div>
  );
}
