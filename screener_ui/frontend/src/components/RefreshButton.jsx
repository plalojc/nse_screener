import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "../api.js";
import { useAppData } from "../context/AppDataContext.jsx";

export function RefreshButton({ loading = false, onClick, label = "Refresh", className = "", disabled = false }) {
  return (
    <button
      className={`pageRefreshBtn ${className}`.trim()}
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
    >
      <RefreshCw size={16} />{loading ? "Refreshing..." : label}
    </button>
  );
}

export function DbRefreshButton({
  cacheKey,
  endpoint,
  label = "Refresh",
  className = "",
  disabled = false,
  beforeRefresh,
  onSuccess,
  onError,
}) {
  const { setCachedData } = useAppData();
  const [loading, setLoading] = useState(false);

  async function refreshFromDb() {
    setLoading(true);
    try {
      beforeRefresh?.();
      const resolvedEndpoint = typeof endpoint === "function" ? endpoint() : endpoint;
      const resolvedKey = typeof cacheKey === "function" ? cacheKey() : cacheKey;
      const latest = await api(resolvedEndpoint);
      setCachedData(resolvedKey, latest);
      onSuccess?.(latest);
    } catch (err) {
      onError?.(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <RefreshButton
      className={className}
      disabled={disabled}
      label={label}
      loading={loading}
      onClick={refreshFromDb}
    />
  );
}
