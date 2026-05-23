import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { api } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { useLoad } from "../hooks/useLoad.js";

export function Settings() {
  const { data, error, refresh } = useLoad(() => api("/api/settings"), []);
  const [message, setMessage] = useState("");
  const [form, setForm] = useState({
    tradingview_chart_id: "IMppZ0T",
    llm_validation_limit: 100,
    report_include_weak: false
  });

  useEffect(() => {
    if (data) setForm(data);
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
          <button type="submit"><Save size={16} />Save Settings</button>
        </form>
      </div>
    </section>
  );
}
