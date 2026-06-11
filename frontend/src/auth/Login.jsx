// Login screen. Two variants depending on the server's auth mode:
//   supabase — email + password with sign-in AND create-account
//   password — the single shared family password (POST /api/login)

import { useState } from 'react';
import { Zap } from 'lucide-react';
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
    <div className="min-h-screen flex items-center justify-center px-4
      bg-[radial-gradient(ellipse_at_top,rgba(99,102,241,0.12),transparent_55%)]">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="h-14 w-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-sky-500
            flex items-center justify-center shadow-xl shadow-indigo-950 mb-4">
            <Zap size={26} className="text-white" fill="currentColor" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Pulse</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Your always-on content copilot
          </p>
        </div>

        <div className="bg-zinc-900/70 border border-zinc-800/70 rounded-2xl p-6 space-y-3
          shadow-2xl shadow-black/40">
          <div className="text-sm font-medium text-zinc-300 mb-1">
            {isSupabase
              ? (mode === 'signup' ? 'Create your account' : 'Sign in')
              : 'Enter the password'}
          </div>
          {isSupabase && (
            <Input type="email" placeholder="email" value={email}
                   onInput={(e) => setEmail(e.target.value)} />
          )}
          <Input type="password" placeholder="password" value={pw}
                 onInput={(e) => setPw(e.target.value)}
                 onKeyDown={(e) => e.key === 'Enter' && go()} />
          {msg && <div className="text-rose-400 text-sm">{msg}</div>}
          <Btn color="primary" disabled={busy} onClick={go} className="w-full !py-2.5">
            {busy ? '…' : mode === 'signup' ? 'Create account' : 'Sign in'}
          </Btn>
          {isSupabase && (
            <div className="text-xs text-zinc-500 text-center pt-1">
              {mode === 'signin' ? (
                <>New here?{' '}
                  <button className="text-indigo-400 hover:text-indigo-300"
                          onClick={() => setMode('signup')}>Create an account</button></>
              ) : (
                <>Already set up?{' '}
                  <button className="text-indigo-400 hover:text-indigo-300"
                          onClick={() => setMode('signin')}>Sign in</button></>
              )}
            </div>
          )}
        </div>
        <p className="text-center text-xs text-zinc-600 mt-6">
          watches your world · drafts in your voice · you press post
        </p>
      </div>
    </div>
  );
}
