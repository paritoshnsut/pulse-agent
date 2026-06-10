// Login screen. Two variants depending on the server's auth mode:
//   supabase — email + password, with sign-in AND create-account, via
//              @supabase/supabase-js (sessions auto-refresh; we never see
//              the password).
//   password — the single shared family password (POST /api/login).

import { useState } from 'react';
import { Btn, Input } from '../components/ui.jsx';

export default function Login({ config, supabase, onPasswordToken }) {
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [mode, setMode] = useState('signin'); // signin | signup
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const supabaseAuth = async () => {
    setBusy(true); setMsg('');
    try {
      if (mode === 'signup') {
        const { data, error } = await supabase.auth.signUp({ email, password: pw });
        if (error) throw error;
        if (!data.session) setMsg('Check your email to confirm, then sign in.');
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password: pw });
        if (error) throw error;
      }
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  const passwordAuth = async () => {
    setBusy(true); setMsg('');
    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw }),
      });
      if (!res.ok) throw new Error('Wrong password');
      onPasswordToken((await res.json()).token);
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  const isSupabase = config.auth_mode === 'supabase';
  const go = isSupabase ? supabaseAuth : passwordAuth;

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="w-80 space-y-4 text-center">
        <div className="text-3xl font-bold">⚡ Pulse</div>
        <div className="text-zinc-400 text-sm">
          {isSupabase
            ? (mode === 'signup' ? 'Create your account' : 'Sign in to your copilot')
            : 'Enter the family password'}
        </div>
        {isSupabase && (
          <Input type="email" placeholder="email" value={email}
                 onInput={(e) => setEmail(e.target.value)} />
        )}
        <Input type="password" placeholder="password" value={pw}
               onInput={(e) => setPw(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && go()} />
        {msg && <div className="text-rose-400 text-sm">{msg}</div>}
        <Btn color="blue" disabled={busy} onClick={go}>
          {busy ? '…' : mode === 'signup' ? 'Create account' : 'Sign in'}
        </Btn>
        {isSupabase && (
          <div className="text-xs text-zinc-500">
            {mode === 'signin' ? (
              <>New here?{' '}
                <button className="text-sky-400" onClick={() => setMode('signup')}>
                  Create an account
                </button></>
            ) : (
              <>Already set up?{' '}
                <button className="text-sky-400" onClick={() => setMode('signin')}>
                  Sign in
                </button></>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
