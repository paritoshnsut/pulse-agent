// Tiny shared UI atoms — consistent dark theme everywhere.

const BTN_COLORS = {
  green: 'bg-emerald-600 hover:bg-emerald-500',
  red: 'bg-rose-700 hover:bg-rose-600',
  blue: 'bg-sky-600 hover:bg-sky-500',
  zinc: 'bg-zinc-700 hover:bg-zinc-600',
};

export function Btn({ onClick, color = 'zinc', disabled, children }) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition
        ${disabled ? 'opacity-40 cursor-not-allowed' : ''} ${BTN_COLORS[color]}`}
    >
      {children}
    </button>
  );
}

export function Chip({ children }) {
  return (
    <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-xs text-zinc-300">
      {children}
    </span>
  );
}

export function Card({ children }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
      {children}
    </div>
  );
}

export function Input(props) {
  return (
    <input
      {...props}
      className={`bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5
        text-sm w-full placeholder-zinc-500 ${props.className || ''}`}
    />
  );
}

export function AccountPicker({ accounts, value, onChange }) {
  if (accounts.length <= 1) return null;
  return (
    <select
      value={value}
      onChange={(e) => onChange(+e.target.value)}
      className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm"
    >
      {accounts.map((a) => (
        <option key={a.id} value={a.id}>@{a.handle}</option>
      ))}
    </select>
  );
}

export function copyText(text) {
  return navigator.clipboard.writeText(text);
}
