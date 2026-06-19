import { useEffect, useState } from "react";
import { Download, KeyRound, Save } from "lucide-react";
import { api, backupDownloadUrl } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { useCachedLoad } from "../hooks/useCachedLoad.js";

export function Settings() {
  const settingsLoader = () => api("/api/settings");
  const { data, error, refresh } = useCachedLoad("settings", settingsLoader, []);
  const [message, setMessage] = useState("");
  const [passwordForm, setPasswordForm] = useState({ current_password: "", new_password: "" });
  const [form, setForm] = useState({
    tradingview_chart_id: "IMppZ0T",
    llm_validation_limit: 100,
    report_include_weak: false
  });

  useEffect(() => {
    if (data) {
      setForm({
        tradingview_chart_id: data.tradingview_chart_id || "IMppZ0T",
        llm_validation_limit: data.llm_validation_limit ?? 100,
        report_include_weak: Boolean(data.report_include_weak),
        is_admin: Boolean(data.is_admin)
      });
    }
  }, [data]);

  async function save(event) {
    event.preventDefault();
    const next = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        tradingview_chart_id: form.tradingview_chart_id,
        llm_validation_limit: Number(form.llm_validation_limit),
        report_include_weak: Boolean(form.report_include_weak)
      })
    });
    setForm(next);
    setMessage("Settings saved.");
    refresh();
  }

  async function changePassword(event) {
    event.preventDefault();
    await api("/api/auth/password", {
      method: "PUT",
      body: JSON.stringify(passwordForm)
    });
    setPasswordForm({ current_password: "", new_password: "" });
    setMessage("Password changed.");
  }

  return (
    <section>
      <PageTitle title="Settings" />
      {error && <Notice tone="danger">{error}</Notice>}
      {message && <Notice>{message}</Notice>}
      <div className="panel settingsPanel">
        <form className="settingsForm" onSubmit={save}>
          <label>
            TradingView chart id
            <input
              value={form.tradingview_chart_id || ""}
              onChange={(e) => setForm({ ...form, tradingview_chart_id: e.target.value })}
              placeholder="IMppZ0T"
            />
          </label>
          {form.is_admin && (
            <>
              <label>
                Stocks to review with AI
                <input
                  type="number"
                  min="0"
                  max="1000"
                  value={form.llm_validation_limit ?? 100}
                  onChange={(e) => setForm({ ...form, llm_validation_limit: e.target.value })}
                />
                <span className="fieldHint">
                  Maximum top-ranked stocks sent to AI.
                </span>
              </label>
              <label className="checkLine">
                <input
                  type="checkbox"
                  checked={Boolean(form.report_include_weak)}
                  onChange={(e) => setForm({ ...form, report_include_weak: e.target.checked })}
                />
                Include WEAK verdicts in reports
              </label>
            </>
          )}
          <button type="submit"><Save size={16} />Save Settings</button>
        </form>
      </div>
      {form.is_admin && (
        <div className="panel settingsPanel">
          <div className="settingsBackup">
            <div>
              <h2>Backup</h2>
              <p>Download a zip backup of the local SQLite data and user file.</p>
            </div>
            <a className="downloadBtn" href={backupDownloadUrl()}>
              <Download size={16} />Download Backup
            </a>
          </div>
        </div>
      )}
      <div className="panel settingsPanel">
        <form className="settingsForm" onSubmit={changePassword}>
          <label>
            Current password
            <input
              type="password"
              value={passwordForm.current_password}
              onChange={(e) => setPasswordForm({ ...passwordForm, current_password: e.target.value })}
              required
            />
          </label>
          <label>
            New password
            <input
              type="password"
              value={passwordForm.new_password}
              onChange={(e) => setPasswordForm({ ...passwordForm, new_password: e.target.value })}
              required
            />
          </label>
          <button type="submit"><KeyRound size={16} />Change Password</button>
        </form>
      </div>
    </section>
  );
}
