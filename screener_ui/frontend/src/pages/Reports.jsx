import { useEffect, useMemo, useState } from "react";
import { Download, FileSearch, RefreshCw, Trash2, X } from "lucide-react";
import { api, reportContentUrl, reportDownloadUrl } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { useLoad } from "../hooks/useLoad.js";

export function Reports() {
  const { data, error, loading, refresh } = useLoad(() => api("/api/reports"), []);
  const [selectedDate, setSelectedDate] = useState("");
  const [loadedDate, setLoadedDate] = useState("");
  const [message, setMessage] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const reports = data || [];
  const selected = useMemo(() => {
    if (!loadedDate) return null;
    return reports.find((item) => item.kind === "scan" && item.date === loadedDate) || null;
  }, [reports, loadedDate]);

  useEffect(() => {
    if (!selectedDate && reports[0]) {
      setSelectedDate(reports[0].date);
      setLoadedDate(reports[0].date);
    }
  }, [reports, selectedDate]);

  async function deleteSelected() {
    if (!deleteTarget) return;
    await api(`/api/reports/${deleteTarget.date}?kind=${deleteTarget.kind}`, { method: "DELETE" });
    setMessage(`Report ${deleteTarget.date} deleted.`);
    setDeleteTarget(null);
    setSelectedDate("");
    setLoadedDate("");
    refresh();
  }

  function loadSelectedReport() {
    setMessage("");
    setLoadedDate(selectedDate);
  }

  return (
    <section className="reportsPage">
      <PageTitle title="Reports" action={<button onClick={refresh}><RefreshCw size={16} />Refresh</button>} />
      {error && <Notice tone="danger">{error}</Notice>}
      {message && <Notice>{message}</Notice>}
      <div className="panel reportsPanel">
        <div className="reportToolbar">
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
          />
          <button onClick={loadSelectedReport} disabled={!selectedDate}>
            <FileSearch size={16} />Get Report
          </button>
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
        {!loading && reports.length > 0 && loadedDate && !selected && (
          <Notice tone="danger">Report not available for {loadedDate}.</Notice>
        )}
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
