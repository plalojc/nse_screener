import { useCallback, useEffect, useRef } from "react";
import { useAppData } from "../context/AppDataContext.jsx";

export function useCachedLoad(key, loader, deps = []) {
  const { bootstrapped, cache, loadKey, refreshKey, setCachedData } = useAppData();
  const entry = cache[key];
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    if (!bootstrapped && !entry?.loaded) return;
    loadKey(key, () => loaderRef.current()).catch(() => {
      // The hook returns the error through cache state.
    });
  }, [bootstrapped, key, entry?.loaded, loadKey, ...deps]);

  const refresh = useCallback(() => refreshKey(key, () => loaderRef.current()), [key, refreshKey]);
  const setData = useCallback((data) => setCachedData(key, data), [key, setCachedData]);

  return {
    data: entry?.data ?? null,
    error: entry?.error || "",
    loading: entry ? entry.loading && !entry.loaded : true,
    refresh,
    setData
  };
}
