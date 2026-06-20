import { useEffect, useMemo, useState } from "react";
import { Download, FileSearch, RefreshCw, Trash2, X } from "lucide-react";
import { api, getAccessToken, reportContentUrl, reportDownloadUrl } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { useAppData } from "../context/AppDataContext.jsx";
import { useCachedLoad } from "../hooks/useCachedLoad.js";

function reportHtmlCacheKey(report) {
  return report ? `reportHtml:${report.kind}:${report.date}` : "";
}

export function Reports({ user }) {
  const reportsLoader = () => api("/api/reports");
  const { cache, loadKey, refreshKey } = useAppData();
  const { data, error, loading, refresh } = useCachedLoad("reports", reportsLoader, []);
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
    await refresh();
    refreshKey("dashboard", () => api("/api/dashboard")).catch(() => {});
  }

  function loadSelectedReport() {
    setMessage("");
    setLoadedDate(selectedDate);
  }

  async function downloadSelectedReport() {
    if (!selected || !user?.is_admin) return;
    setMessage("");
    const response = await fetch(reportDownloadUrl(selected));
    if (!response.ok) {
      let detail = response.statusText || "Download failed";
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        // keep HTTP status text
      }
      throw new Error(detail);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `NSE-Breakout-${selected.date}.html`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  const selectedHtmlKey = reportHtmlCacheKey(selected);
  const selectedHtml = selectedHtmlKey ? cache[selectedHtmlKey]?.data : "";
  const selectedHtmlLoading = selectedHtmlKey ? cache[selectedHtmlKey]?.loading : false;

  useEffect(() => {
    if (!selected) return;
    const key = reportHtmlCacheKey(selected);
    loadKey(key, async () => {
      const response = await fetch(reportContentUrl(selected));
      if (!response.ok) {
        throw new Error("Unable to load report content");
      }
      const html = await response.text();
      const token = JSON.stringify(getAccessToken());
      return html.replace(
        'new URLSearchParams(window.location.search).get("token") || ""',
        token
      );
    }).catch(() => {});
  }, [selected?.date, selected?.kind]);

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
          {selected && user?.is_admin && (
            <button
              type="button"
              className="downloadBtn"
              onClick={() => downloadSelectedReport().catch((err) => setMessage(err.message))}
            >
              <Download size={16} />Download HTML
            </button>
          )}
          {selected && user?.is_admin && (
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
        {selected && selectedHtmlLoading && !selectedHtml && <Notice>Loading report...</Notice>}
        {selected && selectedHtml && <iframe className="reportFrame" title="Report" srcDoc={selectedHtml} />}
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
