import { tabs } from "../constants.js";

export function Sidebar({ active, onChange }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brandMark">N</div>
        <div>
          <strong>NSE Screener</strong>
          <span>Breakout workspace</span>
        </div>
      </div>
      <nav>
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              className={active === tab.id ? "active" : ""}
              onClick={() => onChange(tab.id)}
            >
              <Icon size={18} />
              {tab.label}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
