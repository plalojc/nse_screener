import { useEffect, useState } from "react";
import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { api, clearSession, getAccessToken, getCurrentUser } from "./api.js";
import { Sidebar } from "./components/Sidebar.jsx";
import { AppDataProvider } from "./context/AppDataContext.jsx";
import { Dashboard } from "./pages/Dashboard.jsx";
import { Holdings } from "./pages/Holdings.jsx";
import { Login } from "./pages/Login.jsx";
import { ProfitLossReport } from "./pages/ProfitLossReport.jsx";
import { Reports } from "./pages/Reports.jsx";
import { Settings } from "./pages/Settings.jsx";
import { UserManagement } from "./pages/UserManagement.jsx";
import { Watchlist } from "./pages/Watchlist.jsx";

export default function App() {
  const [active, setActive] = useState("dashboard");
  const [mountedTabs, setMountedTabs] = useState(() => new Set(["dashboard"]));
  const [sidebarHidden, setSidebarHidden] = useState(false);
  const [user, setUser] = useState(getCurrentUser());
  const [checkingAuth, setCheckingAuth] = useState(Boolean(getAccessToken()));

  useEffect(() => {
    if (!getAccessToken()) return;
    api("/api/auth/me")
      .then(setUser)
      .catch(() => {
        clearSession();
        setUser(null);
      })
      .finally(() => setCheckingAuth(false));
  }, []);

  function logout() {
    clearSession();
    setUser(null);
    setActive("dashboard");
    setMountedTabs(new Set(["dashboard"]));
  }

  const visibleActive = active === "users" && !user?.is_admin ? "dashboard" : active;

  function changeActive(nextActive) {
    const nextVisible = nextActive === "users" && !user?.is_admin ? "dashboard" : nextActive;
    setMountedTabs((current) => {
      if (current.has(nextVisible)) return current;
      const next = new Set(current);
      next.add(nextVisible);
      return next;
    });
    setActive(nextActive);
  }

  useEffect(() => {
    setMountedTabs((current) => {
      if (current.has(visibleActive)) return current;
      const next = new Set(current);
      next.add(visibleActive);
      return next;
    });
  }, [visibleActive]);

  if (checkingAuth) {
    return <main className="loginShell"><div className="loginCard">Checking login...</div></main>;
  }

  if (!user) {
    return <Login onLogin={setUser} />;
  }

  return (
    <div className={`appShell ${sidebarHidden ? "sidebarHidden" : ""}`}>
      <Sidebar active={visibleActive} onChange={changeActive} hidden={sidebarHidden} user={user} onLogout={logout} />
      <button
        className="sidebarToggle"
        onClick={() => setSidebarHidden((current) => !current)}
        title={sidebarHidden ? "Show menu" : "Hide menu"}
        aria-label={sidebarHidden ? "Show menu" : "Hide menu"}
      >
        {sidebarHidden ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
      </button>
      <AppDataProvider user={user}>
        <main className="content">
          {mountedTabs.has("dashboard") && (
            <div className={`viewPane ${visibleActive === "dashboard" ? "active" : ""}`} aria-hidden={visibleActive !== "dashboard"}>
              <Dashboard user={user} />
            </div>
          )}
          {mountedTabs.has("reports") && (
            <div className={`viewPane ${visibleActive === "reports" ? "active" : ""}`} aria-hidden={visibleActive !== "reports"}>
              <Reports user={user} />
            </div>
          )}
          {mountedTabs.has("watchlist") && (
            <div className={`viewPane ${visibleActive === "watchlist" ? "active" : ""}`} aria-hidden={visibleActive !== "watchlist"}>
              <Watchlist />
            </div>
          )}
          {mountedTabs.has("holdings") && (
            <div className={`viewPane ${visibleActive === "holdings" ? "active" : ""}`} aria-hidden={visibleActive !== "holdings"}>
              <Holdings />
            </div>
          )}
          {mountedTabs.has("profitLoss") && (
            <div className={`viewPane ${visibleActive === "profitLoss" ? "active" : ""}`} aria-hidden={visibleActive !== "profitLoss"}>
              <ProfitLossReport />
            </div>
          )}
          {mountedTabs.has("settings") && (
            <div className={`viewPane ${visibleActive === "settings" ? "active" : ""}`} aria-hidden={visibleActive !== "settings"}>
              <Settings />
            </div>
          )}
          {user.is_admin && mountedTabs.has("users") && (
            <div className={`viewPane ${visibleActive === "users" ? "active" : ""}`} aria-hidden={visibleActive !== "users"}>
              <UserManagement />
            </div>
          )}
        </main>
      </AppDataProvider>
    </div>
  );
}
