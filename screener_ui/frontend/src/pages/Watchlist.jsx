import { useEffect, useState } from "react";
import { Edit3, ExternalLink, Plus, Save, Trash2, X } from "lucide-react";
import { api } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { DbRefreshButton } from "../components/RefreshButton.jsx";
import { Toast } from "../components/Toast.jsx";
import { useAppData } from "../context/AppDataContext.jsx";
import { useCachedLoad } from "../hooks/useCachedLoad.js";
import { money, shortDateTime } from "../utils/format.js";
import { openTradingView } from "../utils/tradingview.js";

function todayInputValue() {
  const now = new Date();
  const tzOffsetMs = now.getTimezoneOffset() * 60 * 1000;
  return new Date(now.getTime() - tzOffsetMs).toISOString().slice(0, 10);
}

function isAutoReportNote(notes) {
  return /^Added from report \d{4}-\d{2}-\d{2}$/.test(String(notes || "").trim());
}

function gainLossText(item) {
  if (item.profit_loss === null || item.profit_loss === undefined) return "-";
  const pct = item.profit_loss_pct === null || item.profit_loss_pct === undefined
    ? ""
    : ` (${item.profit_loss_pct}%)`;
  return `${money(item.profit_loss)}${pct}`;
}

function shortText(value, max = 34) {
  const text = String(value || "").trim();
  if (!text) return "-";
  return text.length > max ? `${text.slice(0, max - 1).trim()}...` : text;
}

export function Watchlist() {
  const watchlistLoader = () => api("/api/watchlist");
  const settingsLoader = () => api("/api/settings");
  const { cache, refreshKey, setCachedData } = useAppData();
  const { data, error, refresh } = useCachedLoad("watchlist", watchlistLoader, []);
  const { data: settings } = useCachedLoad("settings", settingsLoader, []);
  const [form, setForm] = useState({ symbol: "", target_price: "", notes: "" });
  const [edits, setEdits] = useState({});
  const [editingId, setEditingId] = useState(null);
  const [holdingDraft, setHoldingDraft] = useState(null);
  const [message, setMessage] = useState("");
  const [busyAction, setBusyAction] = useState("");

  useEffect(() => {
    const next = {};
    for (const item of data || []) {
      next[item.id] = {
        target_price: item.target_price ?? "",
        notes: isAutoReportNote(item.notes) ? "" : item.notes || ""
      };
    }
    setEdits(next);
  }, [data]);

  async function save(event) {
    event.preventDefault();
    setBusyAction("add");
    try {
      const saved = await api("/api/watchlist", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          target_price: form.target_price ? Number(form.target_price) : null
        })
      });
      if (saved?.created !== false) {
        const current = Array.isArray(cache.watchlist?.data) ? cache.watchlist.data : [];
        setCachedData("watchlist", [saved, ...current.filter((item) => item.id !== saved.id)]);
      }
      setForm({ symbol: "", target_price: "", notes: "" });
      setMessage(saved.created === false ? `${saved.symbol} already exists in Watchlist.` : "Watchlist item added.");
      refresh().catch(() => {});
      refreshKey("dashboard", () => api("/api/dashboard")).catch(() => {});
    } finally {
      setBusyAction("");
    }
  }

  async function saveRow(item) {
    const edit = edits[item.id] || {};
    const actionKey = `edit:${item.id}`;
    setBusyAction(actionKey);
    try {
      const updated = await api(`/api/watchlist/${item.id}`, {
        method: "PUT",
        body: JSON.stringify({
          symbol: item.symbol,
          target_price: edit.target_price === "" ? null : Number(edit.target_price),
          notes: edit.notes || ""
        })
      });
      const current = Array.isArray(cache.watchlist?.data) ? cache.watchlist.data : [];
      setCachedData("watchlist", current.map((row) => (row.id === item.id ? updated : row)));
      setMessage(`${item.symbol} updated.`);
      setEditingId(null);
      refresh().catch(() => {});
    } finally {
      setBusyAction("");
    }
  }

  function startEdit(item) {
    setEdits((current) => ({
      ...current,
      [item.id]: {
        target_price: item.target_price ?? "",
        notes: isAutoReportNote(item.notes) ? "" : item.notes || ""
      }
    }));
    setEditingId(item.id);
  }

  function cancelEdit(item) {
    setEdits((current) => ({
      ...current,
      [item.id]: {
        target_price: item.target_price ?? "",
        notes: isAutoReportNote(item.notes) ? "" : item.notes || ""
      }
    }));
    setEditingId(null);
  }

  function updateEdit(id, patch) {
    setEdits((current) => ({
      ...current,
      [id]: { ...(current[id] || {}), ...patch }
    }));
  }

  async function remove(id) {
    const actionKey = `delete:${id}`;
    setBusyAction(actionKey);
    try {
      await api(`/api/watchlist/${id}`, { method: "DELETE" });
      const current = Array.isArray(cache.watchlist?.data) ? cache.watchlist.data : [];
      setCachedData("watchlist", current.filter((item) => item.id !== id));
      setMessage("Watchlist item removed.");
      refresh().catch(() => {});
      refreshKey("dashboard", () => api("/api/dashboard")).catch(() => {});
    } finally {
      setBusyAction("");
    }
  }

  async function clearAll() {
    if (!window.confirm("Clear all watchlist items?")) return;
    setBusyAction("clear");
    try {
      await api("/api/watchlist", { method: "DELETE" });
      setCachedData("watchlist", []);
      setMessage("Watchlist cleared.");
      refresh().catch(() => {});
      refreshKey("dashboard", () => api("/api/dashboard")).catch(() => {});
    } finally {
      setBusyAction("");
    }
  }

  function startHolding(item) {
    setHoldingDraft({
      item_id: item.id,
      symbol: item.symbol,
      added_price: item.added_price,
      added_price_date: item.added_price_date,
      current_price: item.current_price,
      price_date: item.price_date,
      profit_loss: item.profit_loss,
      profit_loss_pct: item.profit_loss_pct,
      target_price: item.target_price,
      source_notes: item.notes,
      buy_date: todayInputValue(),
      quantity: "",
      buy_price: "",
      notes: ""
    });
  }

  async function addHolding(event) {
    event.preventDefault();
    setBusyAction("addHolding");
    try {
      const saved = await api("/api/holdings", {
        method: "POST",
        body: JSON.stringify({
          symbol: holdingDraft.symbol,
          buy_date: holdingDraft.buy_date,
          quantity: Number(holdingDraft.quantity),
          buy_price: Number(holdingDraft.buy_price),
          notes: holdingDraft.notes || ""
        })
      });
      const currentHoldings = Array.isArray(cache.holdings?.data) ? cache.holdings.data : [];
      setCachedData("holdings", [saved, ...currentHoldings.filter((item) => item.id !== saved.id)]);
      setMessage(`${holdingDraft.symbol} added to Holdings.`);
      setHoldingDraft(null);
      refreshKey("holdings", () => api("/api/holdings")).catch(() => {});
      refreshKey("dashboard", () => api("/api/dashboard")).catch(() => {});
    } finally {
      setBusyAction("");
    }
  }

  const editingItem = (data || []).find((item) => item.id === editingId);

  return (
    <section>
      <PageTitle
        title="Watchlist"
        action={
          <div className="titleActions">
            <DbRefreshButton
              cacheKey="watchlist"
              endpoint="/api/watchlist"
              disabled={Boolean(busyAction)}
              beforeRefresh={() => setMessage("")}
              onSuccess={() => setMessage("Watchlist refreshed.")}
              onError={(err) => setMessage(err.message || "Unable to refresh Watchlist.")}
            />
            <button className="iconDanger" onClick={clearAll} disabled={Boolean(busyAction)}>
              <Trash2 size={16} />{busyAction === "clear" ? "Clearing..." : "Clear"}
            </button>
          </div>
        }
      />
      {error && <Notice tone="danger">{error}</Notice>}
      <Toast message={message} onClose={() => setMessage("")} />
      <div className="panel">
        <form className="inlineForm" onSubmit={save}>
          <input placeholder="Symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} required />
          <input placeholder="Target price" type="number" value={form.target_price} onChange={(e) => setForm({ ...form, target_price: e.target.value })} />
          <input placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <button type="submit" disabled={busyAction === "add"}><Plus size={16} />{busyAction === "add" ? "Adding..." : "Add"}</button>
        </form>
        <div className="tableWrap watchlistWrap">
          <table className="watchlistTable">
            <thead>
              <tr>
                <th className="slCol">SL</th>
                <th>Symbol</th>
                <th>Added Price</th>
                <th>Latest Price</th>
                <th>Gain/Loss</th>
                <th>Target</th>
                <th>Notes</th>
                <th>Created</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {(data || []).length ? (data || []).map((item, index) => (
                <tr key={item.id}>
                  <td className="slCol hoverActionCell">
                    <span className="slNo">{index + 1}</span>
                    <button
                      className="slAddBtn"
                      type="button"
                      title={`Add ${item.symbol} to Holdings`}
                      onClick={() => startHolding(item)}
                      disabled={Boolean(busyAction)}
                    >
                      <Plus size={15} strokeWidth={2.8} />
                    </button>
                  </td>
                  <td>
                    <button
                      className="symbolLink"
                      type="button"
                      onClick={() => openTradingView(item.symbol, settings?.tradingview_chart_id)}
                      title={`Open ${item.symbol} in TradingView`}
                    >
                      <strong>{item.symbol}</strong>
                      <ExternalLink size={13} />
                    </button>
                  </td>
                  <td title={item.added_price_date ? `Added price date: ${item.added_price_date}` : ""}>
                    {money(item.added_price)}
                  </td>
                  <td title={item.price_date ? `Latest price date: ${item.price_date}` : ""}>
                    {money(item.current_price)}
                  </td>
                  <td>
                    <span className={(item.profit_loss || 0) >= 0 ? "gain" : "loss"}>
                      {gainLossText(item)}
                    </span>
                  </td>
                  <td>{money(item.target_price)}</td>
                  <td title={item.notes || ""}>
                    {isAutoReportNote(item.notes)
                      ? <span className="mutedText">{shortText(item.notes, 26)}</span>
                      : shortText(item.notes, 30)}
                  </td>
                  <td title={item.created_at || ""}>{shortDateTime(item.created_at)}</td>
                  <td>
                    <div className="rowActions">
                      <button
                        type="button"
                        className="iconActionBtn actionBtn"
                        onClick={() => startEdit(item)}
                        disabled={Boolean(busyAction)}
                        title={`Edit ${item.symbol}`}
                        aria-label={`Edit ${item.symbol}`}
                      >
                        <Edit3 size={15} />
                      </button>
                      <button className="iconDanger" type="button" onClick={() => remove(item.id)} disabled={busyAction === `delete:${item.id}`}>
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              )) : (
                <tr><td colSpan="9">No records.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {holdingDraft && (
        <div className="modalOverlay" onClick={() => setHoldingDraft(null)}>
          <form className="appModal holdingModal addHoldingModal" onSubmit={addHolding} onClick={(event) => event.stopPropagation()}>
            <div className="modalHeader">
              <div>
                <h2>Add {holdingDraft.symbol} to Holdings</h2>
                <p>Enter the actual buy details for this position.</p>
              </div>
              <button type="button" className="modalClose" onClick={() => setHoldingDraft(null)} title="Close">
                <X size={18} />
              </button>
            </div>
            <div className="modalFormGrid">
              <div className="modalReadOnlyGrid modalWide">
                <div className="modalReadOnlyItem">
                  <span>Symbol</span>
                  <strong>{holdingDraft.symbol}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Added Price</span>
                  <strong>{money(holdingDraft.added_price)}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Latest Price</span>
                  <strong>{money(holdingDraft.current_price)}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Gain/Loss</span>
                  <strong className={(holdingDraft.profit_loss || 0) >= 0 ? "gain" : "loss"}>
                    {gainLossText(holdingDraft)}
                  </strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Target</span>
                  <strong>{holdingDraft.target_price ? money(holdingDraft.target_price) : "-"}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Price Date</span>
                  <strong>{holdingDraft.price_date || holdingDraft.added_price_date || "-"}</strong>
                </div>
                <div className="modalReadOnlyItem modalReadOnlyWide">
                  <span>Watchlist Notes</span>
                  <strong>{isAutoReportNote(holdingDraft.source_notes) ? holdingDraft.source_notes : holdingDraft.source_notes || "-"}</strong>
                </div>
              </div>
              <label>
                Buy date
                <input type="date" value={holdingDraft.buy_date} onChange={(e) => setHoldingDraft({ ...holdingDraft, buy_date: e.target.value })} required />
              </label>
              <label>
                Quantity
                <input placeholder="Quantity" type="number" value={holdingDraft.quantity} onChange={(e) => setHoldingDraft({ ...holdingDraft, quantity: e.target.value })} required />
              </label>
              <label>
                Buy price
                <input placeholder="Buy price" type="number" value={holdingDraft.buy_price} onChange={(e) => setHoldingDraft({ ...holdingDraft, buy_price: e.target.value })} required />
              </label>
              <label className="modalWide">
                Notes
                <input placeholder="Notes" value={holdingDraft.notes} onChange={(e) => setHoldingDraft({ ...holdingDraft, notes: e.target.value })} />
              </label>
            </div>
            <div className="modalActions">
              <button type="submit" disabled={busyAction === "addHolding"}><Plus size={16} />{busyAction === "addHolding" ? "Adding..." : "Add to Holdings"}</button>
              <button type="button" className="secondaryBtn" onClick={() => setHoldingDraft(null)} disabled={busyAction === "addHolding"}>Cancel</button>
            </div>
          </form>
        </div>
      )}
      {editingItem && (
        <div className="modalOverlay" onClick={() => cancelEdit(editingItem)}>
          <form className="appModal holdingModal" onSubmit={(event) => { event.preventDefault(); saveRow(editingItem); }} onClick={(event) => event.stopPropagation()}>
            <div className="modalHeader">
              <div>
                <h2>Edit {editingItem.symbol}</h2>
                <p>Update target price and notes for this watchlist item.</p>
              </div>
              <button type="button" className="modalClose" onClick={() => cancelEdit(editingItem)} title="Close">
                <X size={18} />
              </button>
            </div>
            <div className="modalFormGrid">
              <div className="modalReadOnlyGrid modalWide">
                <div className="modalReadOnlyItem">
                  <span>Symbol</span>
                  <strong>{editingItem.symbol}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Added Price</span>
                  <strong>{money(editingItem.added_price)}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Latest Price</span>
                  <strong>{money(editingItem.current_price)}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Gain/Loss</span>
                  <strong className={(editingItem.profit_loss || 0) >= 0 ? "gain" : "loss"}>
                    {gainLossText(editingItem)}
                  </strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Created</span>
                  <strong>{editingItem.created_at || "-"}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Price Date</span>
                  <strong>{editingItem.price_date || "-"}</strong>
                </div>
              </div>
              <label>
                Target price
                <input
                  type="number"
                  value={edits[editingItem.id]?.target_price ?? ""}
                  onChange={(e) => updateEdit(editingItem.id, { target_price: e.target.value })}
                  placeholder="Target"
                />
              </label>
              <label className="modalWide">
                Notes
                <input
                  value={edits[editingItem.id]?.notes ?? ""}
                  onChange={(e) => updateEdit(editingItem.id, { notes: e.target.value })}
                  placeholder={isAutoReportNote(editingItem.notes) ? editingItem.notes : "Notes"}
                />
              </label>
            </div>
            <div className="modalActions">
              <button type="submit" disabled={busyAction === `edit:${editingItem.id}`}><Save size={16} />{busyAction === `edit:${editingItem.id}` ? "Saving..." : "Save"}</button>
              <button type="button" className="secondaryBtn" onClick={() => cancelEdit(editingItem)} disabled={busyAction === `edit:${editingItem.id}`}>Cancel</button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}
