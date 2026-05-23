export function Progress({ job, lines }) {
  const progress = job?.progress || 0;
  return (
    <div className="progressBox">
      <div className="progressMeta">
        <span>{job?.status || "idle"}</span>
        <strong>{progress}%</strong>
      </div>
      <div className="bar"><span style={{ width: `${progress}%` }} /></div>
      <pre>{(lines || []).slice(-120).join("\n") || "No scan output yet."}</pre>
    </div>
  );
}
