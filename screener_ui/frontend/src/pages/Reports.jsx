import { useEffect, useMemo, useState } from "react";
import { Download, RefreshCw, Trash2, X } from "lucide-react";
import { api, reportContentUrl, reportDownloadUrl } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { useLoad } from "../hooks/useLoad.js";

export function Reports() {
  const { data, error, loading, refresh } = useLoad(() => api("/api/reports"), []);
  const [selectedKey, setSelectedKey] = useState("");
  const [message, setMessage] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const reports = data || [];
  const selected = useMemo(() => {
    if (!reports.length) return null;
    return reports.find((item) => `${item.kind}:${item.date}` === selectedKey) || reports[0];
  }, [reports, selectedKey]);

  useEffect(() => {
    if (!selectedKey && reports[0]) setSelectedKey(`${reports[0].kind}:${reports[0].date}`);
  }, [reports, selectedKey]);

  async function deleteSelected() {
    if (!deleteTarget) return;
    await api(`/api/reports/${deleteTarget.date}?kind=${deleteTarget.kind}`, { method: "DELETE" });
    setMessage(`Report ${deleteTarget.date} deleted.`);
    setDeleteTarget(null);
    setSelectedKey("");
    refresh();
  }

  return (
    <section>
      <PageTitle title="Reports" action={<button onClick={refresh}><RefreshCw size={16} />Refresh</button>} />
      {error && <Notice tone="danger">{error}</Notice>}
      {message && <Notice>{message}</Notice>}
      <div className="panel">
        <div className="reportToolbar">
          <select
            value={selected ? `${selected.kind}:${selected.date}` : ""}
            onChange={(e) => setSelectedKey(e.target.value)}
          >
            {reports.map((report) => (
              <option key={`${report.kind}:${report.filename}`} value={`${report.kind}:${report.date}`}>
                {report.date} - {report.kind}
              </option>
            ))}
          </select>
          {selected && (
            <a className="downloadBtn" href={reportDownloadUrl(selected)}>
              <Download size={16} />Download HTML
            </a>
          )}
          {selected && (
            <button className="iconDanger reportDeleteBtn" onClick={() => setDeleteTarget(selected)}>
              <Trash2 size={16} />Delete Report
            </button>
          )}
        </div>
        {loading && <Notice>Loading reports...</Notice>}
        {!loading && !reports.length && <Notice>No reports available.</Notice>}
        {selected && <iframe className="reportFrame" title="Report" src={reportContentUrl(selected)} />}
      </div>
      {deleteTarget && (
        <div className="modalOverlay" onClick={() => setDeleteTarget(null)}>
          <div className="appModal confirmModal" onClick={(event) => event.stopPropagation()}>
            <div className="modalHeader">
              <div>
                <h2>Delete Report</h2>
                <p>This will remove the report for {deleteTarget.date} and allow that date to be scanned again.</p>
              </div>
              <button type="button" className="modalClose" onClick={() => setDeleteTarget(null)} title="Close">
                <X size={18} />
              </button>
            </div>
            <div className="confirmBody">
              <strong>NSE-Breakout-{deleteTarget.date}.html</strong>
              <span>Related saved scan rows and LLM evaluations for this date will be deleted.</span>
            </div>
            <div className="modalActions">
              <button type="button" className="sellBtn" onClick={deleteSelected}>
                <Trash2 size={16} />Delete Report
              </button>
              <button type="button" className="secondaryBtn" onClick={() => setDeleteTarget(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
