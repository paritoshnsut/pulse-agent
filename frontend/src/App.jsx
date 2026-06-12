// App shell: fetches /api/config, runs the right auth flow (Supabase session
// / family password / dev), then renders the sidebar app. The Supabase client
// is created at runtime from server config, so one build works on any
// deployment — no rebuild to change projects.
//
// Two zones, one build:
//   Pulse App    — the customer product. Answers "what should I post?"
//   Pulse Studio — the internal glass wall. Answers "what is the machine
//                  doing and why?" — every signal's subscores, every draft's
//                  trace, the memory, the voice, the learned rules.
// The zone toggle lives at the top of the sidebar and persists locally.

import { useCallback, useEffect, useState } from 'react';
import { createClient } from '@supabase/supabase-js';
import {
  Activity, BarChart3, Brain, FlaskConical, GitBranch, Inbox, LayoutDashboard,
  Lightbulb, LogOut, Mic2, Radar, Recycle, SearchCode, Settings as SettingsIcon,
  TrendingUp, Zap,
} from 'lucide-react';
import { api, setOnUnauthorized, setTokenProvider } from './api.js';
import Login from './auth/Login.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Review from './pages/Review.jsx';
import Repurpose from './pages/Repurpose.jsx';
import Ideas from './pages/Ideas.jsx';
import Analytics from './pages/Analytics.jsx';
import Settings from './pages/Settings.jsx';
import MissionControl from './pages/studio/MissionControl.jsx';
import Signals from './pages/studio/Signals.jsx';
import Memory from './pages/studio/Memory.jsx';
import Voice from './pages/studio/Voice.jsx';
import Learning from './pages/studio/Learning.jsx';
import Inspector from './pages/studio/Inspector.jsx';
import Graph from './pages/studio/Graph.jsx';
import { Chip, Dot } from './components/ui.jsx';

const NAV = {
  app: [
    { id: 'Home', icon: LayoutDashboard },
    { id: 'Review', icon: Inbox },
    { id: 'Repurpose', icon: Recycle },
    { id: 'Ideas', icon: Lightbulb },
    { id: 'Analytics', icon: BarChart3 },
    { id: 'Settings', icon: SettingsIcon },
  ],
  studio: [
    { id: 'Mission Control', icon: Activity },
    { id: 'Signals', icon: Radar },
    { id: 'Memory', icon: Brain },
    { id: 'Voice', icon: Mic2 },
    { id: 'Learning', icon: TrendingUp },
    { id: 'Inspector', icon: SearchCode },
    { id: 'Graph', icon: GitBranch },
  ],
};

export default function App() {
  const [config, setConfig] = useState(null);
  const [supabase, setSupabase] = useState(null);
  const [authed, setAuthed] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      const cfg = await fetch('/api/config').then((r) => r.json());
      setConfig(cfg);

      if (cfg.auth_mode === 'supabase') {
        const sb = createClient(cfg.supabase_url, cfg.supabase_anon_key);
        setSupabase(sb);
        setTokenProvider(async () =>
          (await sb.auth.getSession()).data.session?.access_token || null);
        setOnUnauthorized(() => sb.auth.signOut());
        const { data } = await sb.auth.getSession();
        setAuthed(!!data.session);
        sb.auth.onAuthStateChange((_e, session) => setAuthed(!!session));
      } else if (cfg.auth_mode === 'password') {
        setTokenProvider(() => localStorage.getItem('pulse_token'));
        setOnUnauthorized(() => {
          localStorage.removeItem('pulse_token');
          setAuthed(false);
        });
        setAuthed(!!localStorage.getItem('pulse_token'));
      } else {
        setTokenProvider(() => 'dev');
        setAuthed(true);
      }
      setReady(true);
    })();
  }, []);

  if (!ready) return <div className="p-8 text-zinc-600 text-sm">loading…</div>;
  if (!authed) {
    return (
      <Login
        config={config}
        supabase={supabase}
        onPasswordToken={(t) => {
          localStorage.setItem('pulse_token', t);
          setAuthed(true);
        }}
      />
    );
  }
  return <Shell config={config} supabase={supabase} setAuthed={setAuthed} />;
}

function Shell({ config, supabase, setAuthed }) {
  const [zone, setZone] = useState(() => localStorage.getItem('pulse_zone') || 'app');
  const [tab, setTab] = useState(() =>
    localStorage.getItem('pulse_zone') === 'studio' ? 'Mission Control' : 'Home');
  const [accounts, setAccounts] = useState(null);
  const [status, setStatus] = useState({});

  const refreshAccounts = useCallback(
    () => api('/api/accounts').then(setAccounts),
    []
  );

  useEffect(() => {
    refreshAccounts().catch(() => {});
    const loadStatus = () => api('/api/status').then(setStatus).catch(() => {});
    loadStatus();
    const t = setInterval(loadStatus, 60000);
    return () => clearInterval(t);
  }, [refreshAccounts]);

  const switchZone = (z) => {
    setZone(z);
    setTab(NAV[z][0].id);
    localStorage.setItem('pulse_zone', z);
  };

  const logout = async () => {
    if (config.auth_mode === 'supabase' && supabase) await supabase.auth.signOut();
    localStorage.removeItem('pulse_token');
    setAuthed(false);
  };

  if (accounts === null) return <div className="p-8 text-zinc-600 text-sm">loading…</div>;

  const studio = zone === 'studio';
  const nav = NAV[zone];
  const badge = { Review: status.pending_drafts || 0 };
  const accent = studio
    ? 'bg-amber-500/15 text-amber-300 border border-amber-500/20'
    : 'bg-indigo-500/15 text-indigo-300 border border-indigo-500/20';

  return (
    <div className="flex min-h-screen">
      {/* ───────────── sidebar (desktop) ───────────── */}
      <aside className="hidden md:flex flex-col w-60 shrink-0 border-r border-zinc-800/70
        bg-zinc-950 px-3 py-5 sticky top-0 h-screen">
        <div className="flex items-center gap-2 px-3 mb-4">
          <div className={`h-8 w-8 rounded-xl flex items-center justify-center shadow-lg
            ${studio
              ? 'bg-gradient-to-br from-amber-500 to-orange-600 shadow-amber-950'
              : 'bg-gradient-to-br from-indigo-500 to-sky-500 shadow-indigo-950'}`}>
            {studio ? <FlaskConical size={17} className="text-white" />
                    : <Zap size={17} className="text-white" fill="currentColor" />}
          </div>
          <div>
            <div className="font-bold tracking-tight leading-none">
              Pulse{studio && <span className="text-amber-400"> Studio</span>}
            </div>
            <div className="text-[10px] text-zinc-500 mt-0.5">
              {studio ? 'mission control · internal' : 'content copilot'}
            </div>
          </div>
        </div>

        {/* zone toggle */}
        <div className="flex gap-1 mb-5 px-1 bg-zinc-900/80 border border-zinc-800/70
          rounded-xl p-1">
          {['app', 'studio'].map((z) => (
            <button key={z} onClick={() => switchZone(z)}
              className={`flex-1 text-xs font-semibold py-1.5 rounded-lg transition-colors
                ${zone === z
                  ? (z === 'studio' ? 'bg-amber-500/20 text-amber-300' : 'bg-indigo-500/20 text-indigo-300')
                  : 'text-zinc-500 hover:text-zinc-300'}`}>
              {z === 'app' ? 'App' : 'Studio'}
            </button>
          ))}
        </div>

        <nav className="space-y-1 flex-1">
          {nav.map(({ id, icon: Icon }) => (
            <button key={id} onClick={() => setTab(id)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl text-sm
                font-medium transition-colors
                ${tab === id ? accent
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900 border border-transparent'}`}>
              <Icon size={17} />
              <span className="flex-1 text-left">{id}</span>
              {badge[id] > 0 && (
                <span className="text-[11px] font-bold bg-indigo-500 text-white
                  rounded-full px-1.5 py-0.5 min-w-[20px] text-center">{badge[id]}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="border-t border-zinc-800/70 pt-3 px-2 space-y-2">
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <Dot on={!!status.scheduler_in_app} />
            {status.scheduler_in_app ? 'agent running' : 'agent paused'}
          </div>
          {status.user_email && (
            <div className="text-xs text-zinc-600 truncate">{status.user_email}</div>
          )}
          <button onClick={logout}
            className="flex items-center gap-2 text-xs text-zinc-500 hover:text-zinc-300">
            <LogOut size={13} /> sign out
          </button>
        </div>
      </aside>

      {/* ───────────── main column ───────────── */}
      <div className="flex-1 min-w-0">
        {/* mobile top nav */}
        <div className="md:hidden sticky top-0 z-20 bg-zinc-950/90 backdrop-blur
          border-b border-zinc-800/70 px-3 py-2 flex items-center gap-1 overflow-x-auto">
          <button onClick={() => switchZone(studio ? 'app' : 'studio')} className="shrink-0 mr-1">
            {studio ? <FlaskConical size={18} className="text-amber-400" />
                    : <Zap size={18} className="text-indigo-400" fill="currentColor" />}
          </button>
          {nav.map(({ id, icon: Icon }) => (
            <button key={id} onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs
                font-medium whitespace-nowrap
                ${tab === id
                  ? (studio ? 'bg-amber-500/15 text-amber-300' : 'bg-indigo-500/15 text-indigo-300')
                  : 'text-zinc-400'}`}>
              <Icon size={14} />{id}
              {badge[id] > 0 && <span className="text-[10px] font-bold text-indigo-300">({badge[id]})</span>}
            </button>
          ))}
        </div>

        {/* topbar (desktop) */}
        <div className="hidden md:flex items-center justify-end gap-2 px-8 pt-5">
          {studio && <Chip tone="amber">🔬 internal — customers never see this</Chip>}
          {status.spend_today_usd !== undefined && (
            <Chip tone={status.spend_today_usd >= (status.daily_budget_usd || Infinity) ? 'red' : 'zinc'}>
              💰 ${Number(status.spend_today_usd).toFixed(2)}
              {status.daily_budget_usd ? ` / $${Number(status.daily_budget_usd).toFixed(0)}` : ''} today
            </Chip>
          )}
          {status.outbox > 0 && <Chip tone="amber">📤 {status.outbox} to post</Chip>}
          {!!status.telegram_configured && <Chip tone="green">📱 telegram</Chip>}
        </div>

        <main className="px-4 md:px-8 py-5 md:py-6 max-w-6xl mx-auto">
          {tab === 'Home' && <Dashboard accounts={accounts} go={setTab} />}
          {tab === 'Review' && <Review accounts={accounts} />}
          {tab === 'Repurpose' && <Repurpose accounts={accounts} />}
          {tab === 'Ideas' && <Ideas accounts={accounts} />}
          {tab === 'Analytics' && <Analytics accounts={accounts} />}
          {tab === 'Settings' && <Settings accounts={accounts} refreshAccounts={refreshAccounts} />}
          {tab === 'Mission Control' && <MissionControl />}
          {tab === 'Signals' && <Signals accounts={accounts} />}
          {tab === 'Memory' && <Memory accounts={accounts} />}
          {tab === 'Voice' && <Voice accounts={accounts} />}
          {tab === 'Learning' && <Learning accounts={accounts} />}
          {tab === 'Inspector' && <Inspector accounts={accounts} />}
          {tab === 'Graph' && <Graph accounts={accounts} />}
        </main>
      </div>
    </div>
  );
}
