export function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `₹${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function number(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export function shortDateTime(value) {
  if (!value) return "-";
  const text = String(value);
  const normalized = text.includes("T") ? text : text.replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return text.slice(0, 16);
  }
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
