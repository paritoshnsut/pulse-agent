// App shell: fetches /api/config, runs the right auth flow (Supabase session
// / family password / dev), then renders the four tabs. The Supabase client
// is created at runtime from server config, so one build works on any
// deployment — no rebuild to change projects.

import { useCallback, useEffect, useState } from 'react';
import { createClient } from '@supabase/supabase-js';
import { api, setOnUnauthorized, setTokenProvider } from './api.js';
import Login from './auth/Login.jsx';
import Review from './pages/Review.jsx';
import Repurpose from './pages/Repurpose.jsx';
import Ideas from './pages/Ideas.jsx';
import Analytics from './pages/Analytics.jsx';
import Settings from './pages/Settings.jsx';
import { Chip } from './components/ui.jsx';

const TABS = ['Review', 'Repurpose', 'Ideas', 'Analytics', 'Settings'];

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

  if (!ready) return <div className="p-8 text-zinc-500">loading…</div>;
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
  const [tab, setTab] = useState('Review');
  const [accounts, setAccounts] = useState(null);
  const [status, setStatus] = useState({});

  const refreshAccounts = useCallback(
    () =>
      api('/api/accounts').then((a) => {
        setAccounts(a);
        if (a.length === 0) setTab('Settings');
      }),
    []
  );

  useEffect(() => {
    refreshAccounts().catch(() => {});
    api('/api/status').then(setStatus).catch(() => {});
  }, [refreshAccounts]);

  const logout = async () => {
    if (config.auth_mode === 'supabase' && supabase) await supabase.auth.signOut();
    localStorage.removeItem('pulse_token');
    setAuthed(false);
  };

  if (accounts === null) return <div className="p-8 text-zinc-500">loading…</div>;

  return (
    <div className="max-w-3xl mx-auto p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="text-xl font-bold">⚡ Pulse</div>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          {status.pending_drafts > 0 && <Chip>📝 {status.pending_drafts} to review</Chip>}
          {status.outbox > 0 && <Chip>📤 {status.outbox} to post</Chip>}
          {status.user_email && <span>{status.user_email}</span>}
          <button onClick={logout} className="hover:text-zinc-300">logout</button>
        </div>
      </div>
      <div className="flex gap-1 mb-5 bg-zinc-900 rounded-xl p-1">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-1.5 rounded-lg text-sm font-medium
              ${tab === t ? 'bg-zinc-700' : 'text-zinc-400 hover:text-zinc-200'}`}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === 'Review' && <Review accounts={accounts} />}
      {tab === 'Repurpose' && <Repurpose accounts={accounts} />}
      {tab === 'Ideas' && <Ideas accounts={accounts} />}
      {tab === 'Analytics' && <Analytics accounts={accounts} />}
      {tab === 'Settings' && <Settings accounts={accounts} refreshAccounts={refreshAccounts} />}
    </div>
  );
}
