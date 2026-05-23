export function DataTable({ headers, rows }) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length ? rows.map((row, index) => (
            <tr key={index}>{row.map((cell, i) => <td key={i}>{cell}</td>)}</tr>
          )) : (
            <tr><td colSpan={headers.length}>No records.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
