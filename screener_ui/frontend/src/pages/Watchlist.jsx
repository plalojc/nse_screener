import { useEffect, useState } from "react";
import { Edit3, ExternalLink, Plus, Save, Trash2, X } from "lucide-react";
import { api } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { Toast } from "../components/Toast.jsx";
import { useLoad } from "../hooks/useLoad.js";
import { money } from "../utils/format.js";
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

export function Watchlist() {
  const { data, error, refresh } = useLoad(() => api("/api/watchlist"), []);
  const { data: settings } = useLoad(() => api("/api/settings"), []);
  const [form, setForm] = useState({ symbol: "", target_price: "", notes: "" });
  const [edits, setEdits] = useState({});
  const [editingId, setEditingId] = useState(null);
  const [holdingDraft, setHoldingDraft] = useState(null);
  const [message, setMessage] = useState("");

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
    const saved = await api("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({
        ...form,
        target_price: form.target_price ? Number(form.target_price) : null
      })
    });
    setForm({ symbol: "", target_price: "", notes: "" });
    setMessage(saved.created === false ? `${saved.symbol} already exists in Watchlist.` : "Watchlist item added.");
    refresh();
  }

  async function saveRow(item) {
    const edit = edits[item.id] || {};
    await api(`/api/watchlist/${item.id}`, {
      method: "PUT",
      body: JSON.stringify({
        symbol: item.symbol,
        target_price: edit.target_price === "" ? null : Number(edit.target_price),
        notes: edit.notes || ""
      })
    });
    setMessage(`${item.symbol} updated.`);
    setEditingId(null);
    refresh();
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
    await api(`/api/watchlist/${id}`, { method: "DELETE" });
    setMessage("Watchlist item removed.");
    refresh();
  }

  async function clearAll() {
    if (!window.confirm("Clear all watchlist items?")) return;
    await api("/api/watchlist", { method: "DELETE" });
    setMessage("Watchlist cleared.");
    refresh();
  }

  function startHolding(item) {
    setHoldingDraft({
      item_id: item.id,
      symbol: item.symbol,
      buy_date: todayInputValue(),
      quantity: "",
      buy_price: "",
      notes: ""
    });
  }

  async function addHolding(event) {
    event.preventDefault();
    await api("/api/holdings", {
      method: "POST",
      body: JSON.stringify({
        symbol: holdingDraft.symbol,
        buy_date: holdingDraft.buy_date,
        quantity: Number(holdingDraft.quantity),
        buy_price: Number(holdingDraft.buy_price),
        notes: holdingDraft.notes || ""
      })
    });
    setMessage(`${holdingDraft.symbol} added to Holdings.`);
    setHoldingDraft(null);
  }

  const editingItem = (data || []).find((item) => item.id === editingId);

  return (
    <section>
      <PageTitle
        title="Watchlist"
        action={<button className="iconDanger" onClick={clearAll}><Trash2 size={16} />Clear</button>}
      />
      {error && <Notice tone="danger">{error}</Notice>}
      <Toast message={message} onClose={() => setMessage("")} />
      <div className="panel">
        <form className="inlineForm" onSubmit={save}>
          <input placeholder="Symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} required />
          <input placeholder="Target price" type="number" value={form.target_price} onChange={(e) => setForm({ ...form, target_price: e.target.value })} />
          <input placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <button type="submit"><Plus size={16} />Add</button>
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
                  <td>{isAutoReportNote(item.notes) ? <span className="mutedText">{item.notes}</span> : (item.notes || "-")}</td>
                  <td>{item.created_at || "-"}</td>
                  <td>
                    <div className="rowActions">
                      <button
                        type="button"
                        className="iconActionBtn actionBtn"
                        onClick={() => startEdit(item)}
                        title={`Edit ${item.symbol}`}
                        aria-label={`Edit ${item.symbol}`}
                      >
                        <Edit3 size={15} />
                      </button>
                      <button className="iconDanger" type="button" onClick={() => remove(item.id)}>
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
          <form className="appModal holdingModal" onSubmit={addHolding} onClick={(event) => event.stopPropagation()}>
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
              <button type="submit"><Plus size={16} />Add to Holdings</button>
              <button type="button" className="secondaryBtn" onClick={() => setHoldingDraft(null)}>Cancel</button>
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
              <button type="submit"><Save size={16} />Save</button>
              <button type="button" className="secondaryBtn" onClick={() => cancelEdit(editingItem)}>Cancel</button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}
