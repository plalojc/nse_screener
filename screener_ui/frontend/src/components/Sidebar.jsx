import { tabs } from "../constants.js";
import { LogOut } from "lucide-react";

export function Sidebar({ active, onChange, hidden = false, user, onLogout }) {
  return (
    <aside className={`sidebar ${hidden ? "hidden" : ""}`}>
      <div className="brand">
        <div className="brandIdentity">
          <div className="brandMark">N</div>
          <div className="brandText">
            <strong>NSE Screener</strong>
            <span>Breakout workspace</span>
          </div>
        </div>
        <div className="sidebarAccount mobileAccount">
          <span title={user?.email}>{user?.email}</span>
          <button className="secondaryBtn" type="button" onClick={onLogout} title="Logout">
            <LogOut size={15} /><span className="accountLogoutText">Logout</span>
          </button>
        </div>
      </div>
      <nav>
        {tabs.filter((tab) => !tab.adminOnly || user?.is_admin).map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              className={active === tab.id ? "active" : ""}
              onClick={() => onChange(tab.id)}
            >
              <Icon size={18} />
              <span className="navLabel">{tab.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="sidebarAccount desktopAccount">
        <span title={user?.email}>{user?.email}</span>
        <button className="secondaryBtn" type="button" onClick={onLogout}>
          <LogOut size={15} /><span className="accountLogoutText">Logout</span>
        </button>
      </div>
    </aside>
  );
}
