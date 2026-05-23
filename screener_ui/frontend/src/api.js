export const API_BASE = import.meta.env.VITE_API_BASE || "";

export async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {
      // keep default message
    }
    throw new Error(message);
  }
  return response.json();
}

export function reportContentUrl(report) {
  return `${API_BASE}/api/reports/${report.date}/content?kind=${report.kind}`;
}

export function reportDownloadUrl(report) {
  return `${API_BASE}/api/reports/${report.date}/download?kind=${report.kind}`;
}
