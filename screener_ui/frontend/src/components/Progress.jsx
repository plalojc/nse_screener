export function Progress({ job }) {
  const progress = job?.progress || 0;
  return (
    <div className="progressBox">
      <div className="progressMeta">
        <span>{job?.status || "idle"}</span>
        <strong>{progress}%</strong>
      </div>
      <div className="bar"><span style={{ width: `${progress}%` }} /></div>
      <div className="progressMessage">
        {job?.message || "No scan running."}
      </div>
    </div>
  );
}
