export const API_BASE = import.meta.env.VITE_API_BASE || "";
const ACCESS_KEY = "nse_screener_access_token";
const REFRESH_KEY = "nse_screener_refresh_token";
const USER_KEY = "nse_screener_user";
const CACHE_PREFIX = "nse_screener_app_cache:";

export function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY) || "";
}

export function getCurrentUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null");
  } catch {
    return null;
  }
}

export function setSession(payload) {
  localStorage.setItem(ACCESS_KEY, payload.access_token);
  localStorage.setItem(REFRESH_KEY, payload.refresh_token);
  localStorage.setItem(USER_KEY, JSON.stringify(payload.user));
}

export function clearSession() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
  for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
    const key = sessionStorage.key(index);
    if (key?.startsWith(CACHE_PREFIX)) {
      sessionStorage.removeItem(key);
    }
  }
}

async function refreshAccessToken() {
  const refreshToken = localStorage.getItem(REFRESH_KEY);
  if (!refreshToken) return false;
  const response = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken })
  });
  if (!response.ok) {
    clearSession();
    return false;
  }
  setSession(await response.json());
  return true;
}

export async function api(path, options = {}) {
  const token = getAccessToken();
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {})
    },
    ...options
  });
  if (response.status === 401 && !options.skipRefresh && await refreshAccessToken()) {
    return api(path, { ...options, skipRefresh: true });
  }
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

export async function downloadFile(path, fallbackName = "download") {
  const token = getAccessToken();
  let response = await fetch(`${API_BASE}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  });
  if (response.status === 401 && await refreshAccessToken()) {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { Authorization: `Bearer ${getAccessToken()}` }
    });
  }
  if (!response.ok) {
    let message = response.statusText || "Download failed";
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {
      // keep HTTP status text
    }
    throw new Error(message);
  }

  const disposition = response.headers.get("content-disposition") || "";
  const filenameMatch = disposition.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i);
  const filename = filenameMatch ? decodeURIComponent(filenameMatch[1].replace(/"/g, "")) : fallbackName;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function reportContentUrl(report) {
  return `${API_BASE}/api/reports/${report.date}/content?kind=${report.kind}&token=${encodeURIComponent(getAccessToken())}`;
}

export function reportDownloadUrl(report) {
  return `${API_BASE}/api/reports/${report.date}/download?kind=${report.kind}&token=${encodeURIComponent(getAccessToken())}`;
}

export async function login(username, password) {
  const payload = await api("/api/auth/login", {
    method: "POST",
    skipRefresh: true,
    body: JSON.stringify({ username, password })
  });
  setSession(payload);
  return payload.user;
}
