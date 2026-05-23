import { useEffect, useMemo, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { api, reportContentUrl, reportDownloadUrl } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { useLoad } from "../hooks/useLoad.js";

export function Reports() {
  const { data, error, loading, refresh } = useLoad(() => api("/api/reports"), []);
  const [selectedKey, setSelectedKey] = useState("");
  const reports = data || [];
  const selected = useMemo(() => {
    if (!reports.length) return null;
    return reports.find((item) => `${item.kind}:${item.date}` === selectedKey) || reports[0];
  }, [reports, selectedKey]);

  useEffect(() => {
    if (!selectedKey && reports[0]) setSelectedKey(`${reports[0].kind}:${reports[0].date}`);
  }, [reports, selectedKey]);

  return (
    <section>
      <PageTitle title="Reports" action={<button onClick={refresh}><RefreshCw size={16} />Refresh</button>} />
      {error && <Notice tone="danger">{error}</Notice>}
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
        </div>
        {loading && <Notice>Loading reports...</Notice>}
        {!loading && !reports.length && <Notice>No reports available.</Notice>}
        {selected && <iframe className="reportFrame" title="Report" src={reportContentUrl(selected)} />}
      </div>
    </section>
  );
}
