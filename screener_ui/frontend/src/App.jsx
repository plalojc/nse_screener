import { useState } from "react";
import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { Sidebar } from "./components/Sidebar.jsx";
import { Dashboard } from "./pages/Dashboard.jsx";
import { Holdings } from "./pages/Holdings.jsx";
import { Reports } from "./pages/Reports.jsx";
import { Settings } from "./pages/Settings.jsx";
import { Watchlist } from "./pages/Watchlist.jsx";

export default function App() {
  const [active, setActive] = useState("dashboard");
  const [sidebarHidden, setSidebarHidden] = useState(false);

  return (
    <div className={`appShell ${sidebarHidden ? "sidebarHidden" : ""}`}>
      <Sidebar active={active} onChange={setActive} hidden={sidebarHidden} />
      <button
        className="sidebarToggle"
        onClick={() => setSidebarHidden((current) => !current)}
        title={sidebarHidden ? "Show menu" : "Hide menu"}
        aria-label={sidebarHidden ? "Show menu" : "Hide menu"}
      >
        {sidebarHidden ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
      </button>
      <main className="content">
        {active === "dashboard" && <Dashboard />}
        {active === "reports" && <Reports />}
        {active === "watchlist" && <Watchlist />}
        {active === "holdings" && <Holdings />}
        {active === "settings" && <Settings />}
      </main>
    </div>
  );
}
