import { NavLink } from "react-router-dom";

const items = [
  { to: "/",             label: "Overview",      icon: "▣" },
  { to: "/agents",       label: "Agents",        icon: "◎" },
  { to: "/dossiers",     label: "Dossiers",      icon: "▤" },
  { to: "/runs",         label: "Runs / Traces", icon: "↻" },
  { to: "/improvements", label: "Improvements",  icon: "▲" },
  { to: "/cost",         label: "Cost / Tokens", icon: "$" },
  { to: "/hephaestus",   label: "Hephaestus",    icon: "⚒" },
  { to: "/console",      label: "Console",       icon: "❯" },
  { to: "/settings",     label: "Settings",      icon: "⚙" },
];

export default function Sidebar() {
  return (
    <aside className="w-56 shrink-0 border-r border-line bg-panel">
      <div className="border-b border-line px-4 py-4">
        <div className="text-lg font-bold tracking-wide text-text">⚙ STRIKECORE</div>
        <div className="text-[10px] uppercase tracking-wider text-muted">Intel Dashboard · v0.3</div>
      </div>
      <nav className="px-2 py-3 flex flex-col gap-1">
        {items.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded px-3 py-2 text-sm transition ` +
              (isActive
                ? "bg-accent/15 text-accent"
                : "text-text/80 hover:bg-line hover:text-text")
            }
          >
            <span className="w-4 text-center text-muted">{icon}</span>
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
