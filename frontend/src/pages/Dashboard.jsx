// The home screen: what the agent is doing RIGHT NOW, setup progress, and
// the latest output — the "it's alive and working for you" view.

import { useEffect, useState } from 'react';
import {
  Activity, CheckCircle2, Circle, Eye, Flame, Inbox, MessageCircle,
  PackageOpen, Palette, Radio, Send, Sparkles, Wallet, Zap,
} from 'lucide-react';
import { api } from '../api.js';
import { Btn, Card, Chip, Dot, EmptyState, PageHeader, Stat } from '../components/ui.jsx';

const STATUS_TONE = { draft: 'amber', approved: 'indigo', posted: 'green',
                      rejected: 'red', edited: 'indigo' };

function SetupRow({ done, label, hint, action, go }) {
  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-zinc-800/60 last:border-0">
      {done
        ? <CheckCircle2 size={18} className="text-emerald-400 shrink-0" />
        : <Circle size={18} className="text-zinc-600 shrink-0" />}
      <div className="flex-1">
        <div className={`text-sm font-medium ${done ? 'text-zinc-400 line-through' : ''}`}>{label}</div>
        {!done && hint && <div className="text-xs text-zinc-500">{hint}</div>}
      </div>
      {!done && action && (
        <Btn color="zinc" onClick={() => go(action)} className="!py-1 !px-2.5 text-xs">
          {action} →
        </Btn>
      )}
    </div>
  );
}

export default function Dashboard({ accounts, go }) {
  const [d, setD] = useState(null);

  useEffect(() => {
    const load = () => api('/api/dashboard').then(setD).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  if (!d) return <div className="text-zinc-600 text-sm p-2">loading…</div>;

  const setup = d.setup || {};
  const setupDone = setup.account && setup.voice;
  const fire = d.signals_today?.FIRE || 0;
  const warm = d.signals_today?.WARM || 0;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Dashboard"
        desc="Your agent watches the news, scores what's worth saying, and drafts in your voice — around the clock."
        actions={
          <div className="flex items-center gap-2">
            <Chip tone={d.scheduler_in_app ? 'green' : 'amber'}>
              <Dot on={d.scheduler_in_app} />
              {d.scheduler_in_app ? 'agent running' : 'agent paused'}
            </Chip>
          </div>
        }
      />

      {!setupDone && (
        <Card
          title="Finish setting up"
          icon={Sparkles}
          desc="Two required steps, three boosters. The agent starts producing the moment voice training is done."
        >
          <SetupRow done={setup.account} label="Create your account"
            hint="Pick a template — politics, SaaS, D2C, creator, finance…" action="Settings" go={go} />
          <SetupRow done={setup.voice} label="Train your voice"
            hint="Paste 50–200 of your past posts — the single biggest quality lever" action="Settings" go={go} />
          <SetupRow done={setup.brand} label="Set your brand kit (recommended)"
            hint="Colors, banned words, CTA — applied to every draft & graphic" action="Settings" go={go} />
          <SetupRow done={setup.watching} label="Add sources to watch"
            hint="YouTube channels, subreddits — 65 news feeds are built in" action="Settings" go={go} />
          <SetupRow done={setup.telegram} label="Connect Telegram (optional)"
            hint="Drafts pushed to your phone; approve with /approve" />
        </Card>
      )}

      <div className="flex gap-3 flex-wrap">
        <Stat label="articles watched today" value={d.articles_today} icon={Eye} />
        <Stat label="hot signals today" value={`${fire} 🔥 ${warm} ⚡`}
              sub="FIRE · WARM" icon={Flame} tone={fire ? 'amber' : 'zinc'} />
        <Stat label="drafts waiting" value={d.pending_drafts} icon={Inbox}
              tone={d.pending_drafts ? 'indigo' : 'zinc'} />
        <Stat label="posted today" value={d.posted_today} icon={Send} tone="green" />
        <Stat label="Claude spend today" value={`$${(d.spend_today_usd ?? 0).toFixed(2)}`}
              sub={d.daily_budget_usd ? `of $${d.daily_budget_usd.toFixed(2)} budget` : 'no cap'}
              icon={Wallet} />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="Agent activity" icon={Activity}
              desc="What the always-on side is doing.">
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-2.5">
              <Radio size={15} className="text-indigo-400" />
              Watching <b>65 news feeds</b>
              {d.watch_sources > 0 && <> + <b>{d.watch_sources}</b> of your sources</>}
              <span className="text-zinc-500">(YouTube · Reddit · Trends · Wikipedia)</span>
            </div>
            <div className="flex items-center gap-2.5">
              <Zap size={15} className={d.scheduler_in_app ? 'text-emerald-400' : 'text-amber-400'} />
              {d.scheduler_in_app
                ? <>Scoring &amp; drafting every <b>10 minutes</b></>
                : <span className="text-amber-300">Scheduler is paused — set SCHEDULER_IN_APP=1 in your deploy variables</span>}
            </div>
            <div className="flex items-center gap-2.5">
              <MessageCircle size={15} className={d.telegram_configured ? 'text-emerald-400' : 'text-zinc-600'} />
              {d.telegram_configured
                ? <>Telegram connected — drafts push to your phone</>
                : <span className="text-zinc-500">Telegram not connected — drafts only appear here</span>}
            </div>
            {d.outbox > 0 && (
              <div className="flex items-center gap-2.5 text-amber-300">
                <PackageOpen size={15} />
                {d.outbox} approved draft{d.outbox > 1 ? 's' : ''} waiting for you to post
                <Btn color="zinc" onClick={() => go('Review')} className="!py-0.5 !px-2 text-xs">open</Btn>
              </div>
            )}
          </div>
        </Card>

        <Card title="Latest drafts" icon={Inbox}
              actions={<Btn color="zinc" onClick={() => go('Review')} className="!py-1 !px-2.5 text-xs">Review all →</Btn>}>
          {d.recent.length === 0 ? (
            <EmptyState icon={Sparkles} title="Nothing drafted yet"
              body={setupDone
                ? 'The agent drafts when a story scores FIRE or WARM for your niche — or make something now in Repurpose.'
                : 'Finish setup and drafts will start appearing here on their own.'}
              action={setupDone && <Btn color="primary" onClick={() => go('Repurpose')}>Repurpose something now</Btn>} />
          ) : (
            <div className="space-y-2.5">
              {d.recent.map((p) => (
                <div key={p.id} className="flex items-start gap-3 py-1.5">
                  <Chip tone={STATUS_TONE[p.status] || 'zinc'}>{p.status}</Chip>
                  <div className="text-sm text-zinc-300 leading-snug line-clamp-2 flex-1">{p.content}</div>
                  <span className="text-xs text-zinc-600 shrink-0">{p.format}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {accounts.length > 0 && (
        <Card title="Quick actions" icon={Palette}>
          <div className="flex gap-2.5 flex-wrap">
            <Btn color="primary" onClick={() => go('Repurpose')}>📦 Repurpose a blog/podcast</Btn>
            <Btn color="zinc" onClick={() => go('Ideas')}>💡 Ideas bank & evergreen</Btn>
            <Btn color="zinc" onClick={() => go('Analytics')}>📊 What's working</Btn>
            <Btn color="zinc" onClick={() => go('Settings')}>🎨 Brand & voice</Btn>
          </div>
        </Card>
      )}
    </div>
  );
}
