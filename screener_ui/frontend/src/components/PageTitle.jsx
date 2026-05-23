export function PageTitle({ title, action }) {
  return (
    <div className="pageTitle">
      <h1>{title}</h1>
      {action}
    </div>
  );
}
