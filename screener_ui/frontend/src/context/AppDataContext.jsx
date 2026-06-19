import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";

const AppDataContext = createContext(null);
const SESSION_PREFIX = "nse_screener_app_cache:";
const CORE_CACHE_KEYS = ["dashboard", "reports", "watchlist", "holdings", "settings"];
const CACHE_TTL_MS = 5 * 60 * 1000;

function hasWarmCache(cache) {
  return CORE_CACHE_KEYS.every((key) => cache[key]?.loaded);
}

function todayInputValue() {
  const now = new Date();
  const tzOffsetMs = now.getTimezoneOffset() * 60 * 1000;
  return new Date(now.getTime() - tzOffsetMs).toISOString().slice(0, 10);
}

function monthStartValue() {
  const today = todayInputValue();
  return `${today.slice(0, 8)}01`;
}

export function profitLossCacheKey(fromDate = monthStartValue(), toDate = todayInputValue()) {
  return `profitLoss:${fromDate}:${toDate}`;
}

function sessionKey(user) {
  return `${SESSION_PREFIX}${user?.email || "guest"}`;
}

function cacheEntry(data) {
  return { data, error: "", loading: false, loaded: true };
}

function applyBootstrap(payload) {
  const next = {
    dashboard: cacheEntry(payload.dashboard || null),
    reports: cacheEntry(payload.reports || []),
    watchlist: cacheEntry(payload.watchlist || []),
    holdings: cacheEntry(payload.holdings || []),
    settings: cacheEntry(payload.settings || null),
  };
  if (payload.profitLoss?.from_date && payload.profitLoss?.to_date) {
    next[profitLossCacheKey(payload.profitLoss.from_date, payload.profitLoss.to_date)] = cacheEntry(payload.profitLoss.data || null);
  }
  if (payload.users) {
    next.users = cacheEntry(payload.users);
  }
  return next;
}

function loadSessionCache(user) {
  try {
    const raw = sessionStorage.getItem(sessionKey(user));
    if (!raw) return { cache: {}, fresh: false };
    const parsed = JSON.parse(raw);
    const savedAt = Number(parsed.__meta?.savedAt || 0);
    delete parsed.__meta;
    return {
      cache: parsed,
      fresh: Boolean(savedAt && Date.now() - savedAt < CACHE_TTL_MS),
    };
  } catch {
    return { cache: {}, fresh: false };
  }
}

function saveSessionCache(user, cache) {
  try {
    const persistable = {};
    for (const [key, value] of Object.entries(cache)) {
      if (key.startsWith("reportHtml:")) {
        continue;
      }
      if (value?.loaded) {
        persistable[key] = { ...value, loading: false };
      }
    }
    persistable.__meta = { savedAt: Date.now() };
    sessionStorage.setItem(sessionKey(user), JSON.stringify(persistable));
  } catch {
    // Browser storage can be unavailable; in-memory cache still works.
  }
}

export function AppDataProvider({ user, children }) {
  const initialSessionRef = useRef(null);
  if (!initialSessionRef.current) {
    initialSessionRef.current = loadSessionCache(user);
  }
  const [cache, setCache] = useState(() => initialSessionRef.current.cache);
  const [bootstrapped, setBootstrapped] = useState(() => (
    initialSessionRef.current.fresh && hasWarmCache(initialSessionRef.current.cache)
  ));
  const cacheRef = useRef(cache);

  const updateCache = useCallback((updater) => {
    setCache((current) => {
      const next = typeof updater === "function" ? updater(current) : updater;
      cacheRef.current = next;
      return next;
    });
  }, []);

  const setCachedData = useCallback((key, data) => {
    updateCache((current) => ({
      ...current,
      [key]: cacheEntry(data)
    }));
  }, [updateCache]);

  const loadKey = useCallback(async (key, loader, options = {}) => {
    const force = Boolean(options.force);
    const existing = cacheRef.current[key];
    const shouldLoad = force || !existing?.loaded;
    if (!shouldLoad) return existing?.data ?? null;

    updateCache((current) => {
      const currentEntry = current[key];
      return {
        ...current,
        [key]: {
          data: currentEntry?.data ?? null,
          error: "",
          loading: true,
          loaded: Boolean(currentEntry?.loaded)
        }
      };
    });

    try {
      const data = await loader();
      updateCache((current) => ({
        ...current,
        [key]: { data, error: "", loading: false, loaded: true }
      }));
      return data;
    } catch (err) {
      updateCache((current) => ({
        ...current,
        [key]: {
          data: current[key]?.data ?? null,
          error: err.message || "Request failed",
          loading: false,
          loaded: Boolean(current[key]?.loaded)
        }
      }));
      throw err;
    }
  }, [updateCache]);

  const refreshKey = useCallback((key, loader) => {
    return loadKey(key, loader, { force: true });
  }, [loadKey]);

  useEffect(() => {
    const session = loadSessionCache(user);
    cacheRef.current = session.cache;
    setCache(session.cache);
    const hasFreshWarmCache = session.fresh && hasWarmCache(session.cache);
    setBootstrapped(hasFreshWarmCache);
    if (!user) return;
    if (hasFreshWarmCache) return;
    api("/api/bootstrap")
      .then((payload) => {
        updateCache((current) => ({ ...current, ...applyBootstrap(payload) }));
      })
      .catch(() => {
        // Individual pages can still refresh their own endpoint if bootstrap fails.
      })
      .finally(() => setBootstrapped(true));
  }, [user?.email, user?.is_admin, updateCache]);

  useEffect(() => {
    if (!user) return;
    const timer = window.setTimeout(() => saveSessionCache(user, cache), 250);
    return () => window.clearTimeout(timer);
  }, [user?.email, cache]);

  const value = useMemo(() => ({
    cache,
    bootstrapped,
    loadKey,
    refreshKey,
    setCachedData
  }), [cache, bootstrapped, loadKey, refreshKey, setCachedData]);

  return <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>;
}

export function useAppData() {
  const context = useContext(AppDataContext);
  if (!context) {
    throw new Error("useAppData must be used inside AppDataProvider");
  }
  return context;
}
