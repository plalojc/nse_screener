import { useCallback, useEffect } from "react";
import { useAppData } from "../context/AppDataContext.jsx";

export function useCachedLoad(key, loader, deps = []) {
  const { bootstrapped, cache, loadKey, refreshKey, setCachedData } = useAppData();
  const entry = cache[key];

  useEffect(() => {
    if (!bootstrapped && !entry?.loaded) return;
    loadKey(key, loader).catch(() => {
      // The hook returns the error through cache state.
    });
  }, [bootstrapped, key, entry?.loaded, ...deps]);

  const refresh = useCallback(() => refreshKey(key, loader), [key, loader, refreshKey]);
  const setData = useCallback((data) => setCachedData(key, data), [key, setCachedData]);

  return {
    data: entry?.data ?? null,
    error: entry?.error || "",
    loading: entry ? entry.loading && !entry.loaded : true,
    refresh,
    setData
  };
}
