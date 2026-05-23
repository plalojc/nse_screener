import { useState } from "react";
import { Sidebar } from "./components/Sidebar.jsx";
import { Bought } from "./pages/Bought.jsx";
import { Dashboard } from "./pages/Dashboard.jsx";
import { Reports } from "./pages/Reports.jsx";
import { Watchlist } from "./pages/Watchlist.jsx";

export default function App() {
  const [active, setActive] = useState("dashboard");

  return (
    <div className="appShell">
      <Sidebar active={active} onChange={setActive} />
      <main className="content">
        {active === "dashboard" && <Dashboard />}
        {active === "reports" && <Reports />}
        {active === "watchlist" && <Watchlist />}
        {active === "bought" && <Bought />}
      </main>
    </div>
  );
}
