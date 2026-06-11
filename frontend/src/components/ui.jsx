// Design system primitives — one consistent visual language everywhere.

const BTN = {
  primary: 'bg-indigo-500 hover:bg-indigo-400 text-white shadow-sm shadow-indigo-950',
  green: 'bg-emerald-600 hover:bg-emerald-500 text-white',
  red: 'bg-rose-600/90 hover:bg-rose-500 text-white',
  blue: 'bg-sky-600 hover:bg-sky-500 text-white',
  zinc: 'bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700/60',
};

export function Btn({ onClick, color = 'zinc', disabled, children, className = '' }) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-colors
        focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60
        ${disabled ? 'opacity-40 cursor-not-allowed' : ''} ${BTN[color] || BTN.zinc} ${className}`}
    >
      {children}
    </button>
  );
}

export function Chip({ children, tone = 'zinc' }) {
  const tones = {
    zinc: 'bg-zinc-800/80 text-zinc-300 border-zinc-700/50',
    green: 'bg-emerald-950/60 text-emerald-300 border-emerald-800/50',
    amber: 'bg-amber-950/60 text-amber-300 border-amber-800/50',
    red: 'bg-rose-950/60 text-rose-300 border-rose-800/50',
    indigo: 'bg-indigo-950/60 text-indigo-300 border-indigo-800/50',
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full
      text-xs font-medium border ${tones[tone] || tones.zinc}`}>
      {children}
    </span>
  );
}

export function Dot({ on = true, className = '' }) {
  return (
    <span className={`inline-block h-2 w-2 rounded-full ${className}
      ${on ? 'bg-emerald-400 shadow-[0_0_6px] shadow-emerald-500/60' : 'bg-amber-400'}`} />
  );
}

export function Card({ title, icon: Icon, desc, actions, children, className = '' }) {
  return (
    <div className={`bg-zinc-900/60 border border-zinc-800/70 rounded-2xl ${className}`}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-1">
          <div>
            <div className="flex items-center gap-2 font-semibold text-[15px]">
              {Icon && <Icon size={17} className="text-indigo-400" />}
              {title}
            </div>
            {desc && <div className="text-[13px] text-zinc-500 mt-0.5 leading-relaxed">{desc}</div>}
          </div>
          {actions}
        </div>
      )}
      <div className="px-5 pb-5 pt-3">{children}</div>
    </div>
  );
}

export function Stat({ label, value, sub, icon: Icon, tone = 'zinc' }) {
  const tones = { zinc: 'text-zinc-100', green: 'text-emerald-400',
                  amber: 'text-amber-400', indigo: 'text-indigo-400',
                  red: 'text-rose-400' };
  return (
    <div className="bg-zinc-900/60 border border-zinc-800/70 rounded-2xl px-4 py-3.5 flex-1 min-w-[140px]">
      <div className="flex items-center gap-1.5 text-[12px] text-zinc-500 font-medium">
        {Icon && <Icon size={13} />} {label}
      </div>
      <div className={`text-2xl font-bold mt-1 tracking-tight ${tones[tone]}`}>{value}</div>
      {sub && <div className="text-[12px] text-zinc-500 mt-0.5">{sub}</div>}
    </div>
  );
}

export function PageHeader({ title, desc, actions }) {
  return (
    <div className="flex items-end justify-between gap-4 flex-wrap">
      <div>
        <h1 className="text-xl font-bold tracking-tight">{title}</h1>
        {desc && <p className="text-sm text-zinc-500 mt-1 max-w-2xl leading-relaxed">{desc}</p>}
      </div>
      {actions}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, body, action }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-12 px-6">
      {Icon && (
        <div className="h-12 w-12 rounded-2xl bg-indigo-500/10 border border-indigo-500/20
          flex items-center justify-center mb-4">
          <Icon size={22} className="text-indigo-400" />
        </div>
      )}
      <div className="font-semibold">{title}</div>
      {body && <div className="text-sm text-zinc-500 mt-1.5 max-w-sm leading-relaxed">{body}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Input(props) {
  return (
    <input
      {...props}
      className={`bg-zinc-900 border border-zinc-700/70 rounded-lg px-3 py-2
        text-sm w-full placeholder-zinc-600 focus:outline-none
        focus:border-indigo-500/60 focus:ring-1 focus:ring-indigo-500/30
        transition-colors ${props.className || ''}`}
    />
  );
}

export function Select({ value, onChange, children, className = '' }) {
  return (
    <select value={value} onChange={onChange}
      className={`bg-zinc-900 border border-zinc-700/70 rounded-lg px-3 py-2 text-sm
        focus:outline-none focus:border-indigo-500/60 ${className}`}>
      {children}
    </select>
  );
}

export function Textarea(props) {
  return (
    <textarea
      {...props}
      className={`w-full bg-zinc-900 border border-zinc-700/70 rounded-lg p-3 text-sm
        placeholder-zinc-600 focus:outline-none focus:border-indigo-500/60
        focus:ring-1 focus:ring-indigo-500/30 transition-colors ${props.className || ''}`}
    />
  );
}

export function AccountPicker({ accounts, value, onChange }) {
  if (accounts.length <= 1) return null;
  return (
    <Select value={value} onChange={(e) => onChange(+e.target.value)}>
      {accounts.map((a) => (
        <option key={a.id} value={a.id}>@{a.handle}</option>
      ))}
    </Select>
  );
}

export function copyText(text) {
  return navigator.clipboard.writeText(text);
}
