export function Notice({ children, tone }) {
  return <div className={`notice ${tone || ""}`}>{children}</div>;
}
