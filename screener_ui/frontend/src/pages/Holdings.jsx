import { useEffect, useState } from "react";
import { Check, Edit3, ExternalLink, Plus, Save, X } from "lucide-react";
import { api } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { Toast } from "../components/Toast.jsx";
import { useAppData } from "../context/AppDataContext.jsx";
import { profitLossCacheKey } from "../context/AppDataContext.jsx";
import { useCachedLoad } from "../hooks/useCachedLoad.js";
import { money, number } from "../utils/format.js";
import { openTradingView } from "../utils/tradingview.js";

function todayInputValue() {
  const now = new Date();
  const tzOffsetMs = now.getTimezoneOffset() * 60 * 1000;
  return new Date(now.getTime() - tzOffsetMs).toISOString().slice(0, 10);
}

export function Holdings() {
  const holdingsLoader = () => api("/api/holdings");
  const settingsLoader = () => api("/api/settings");
  const { refreshKey } = useAppData();
  const { data, error, refresh } = useCachedLoad("holdings", holdingsLoader, []);
  const { data: settings } = useCachedLoad("settings", settingsLoader, []);
  const [form, setForm] = useState({
    symbol: "",
    buy_date: todayInputValue(),
    quantity: "",
    buy_price: "",
    notes: ""
  });
  const [sellingId, setSellingId] = useState(null);
  const [sellingSymbol, setSellingSymbol] = useState("");
  const [sellForm, setSellForm] = useState({
    sell_date: todayInputValue(),
    quantity: "",
    sell_price: "",
    notes: ""
  });
  const [editingId, setEditingId] = useState(null);
  const [edits, setEdits] = useState({});
  const [message, setMessage] = useState("");

  useEffect(() => {
    const next = {};
    for (const item of data || []) {
      next[item.id] = {
        symbol: item.symbol || "",
        buy_date: item.buy_date || todayInputValue(),
        quantity: item.quantity ?? "",
        buy_price: item.buy_price ?? "",
        notes: item.notes || ""
      };
    }
    setEdits(next);
  }, [data]);

  async function save(event) {
    event.preventDefault();
    await api("/api/holdings", {
      method: "POST",
      body: JSON.stringify({
        ...form,
        quantity: Number(form.quantity),
        buy_price: Number(form.buy_price)
      })
    });
    setForm({ ...form, symbol: "", quantity: "", buy_price: "", notes: "" });
    setMessage("Holding added.");
    await refresh();
    refreshKey("dashboard", () => api("/api/dashboard")).catch(() => {});
  }

  function startEdit(item) {
    setEdits((current) => ({
      ...current,
      [item.id]: {
        symbol: item.symbol || "",
        buy_date: item.buy_date || todayInputValue(),
        quantity: item.quantity ?? "",
        buy_price: item.buy_price ?? "",
        notes: item.notes || ""
      }
    }));
    setEditingId(item.id);
  }

  function cancelEdit(item) {
    setEdits((current) => ({
      ...current,
      [item.id]: {
        symbol: item.symbol || "",
        buy_date: item.buy_date || todayInputValue(),
        quantity: item.quantity ?? "",
        buy_price: item.buy_price ?? "",
        notes: item.notes || ""
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

  async function saveEdit(item) {
    const edit = edits[item.id] || {};
    await api(`/api/holdings/${item.id}`, {
      method: "PUT",
      body: JSON.stringify({
        symbol: edit.symbol || item.symbol,
        buy_date: edit.buy_date || item.buy_date,
        quantity: Number(edit.quantity),
        buy_price: Number(edit.buy_price),
        notes: edit.notes || ""
      })
    });
    setEditingId(null);
    setMessage(`${edit.symbol || item.symbol} updated.`);
    await refresh();
    refreshKey("dashboard", () => api("/api/dashboard")).catch(() => {});
  }

  function startSell(item) {
    setSellingId(item.id);
    setSellingSymbol(item.symbol);
    setSellForm({
      sell_date: todayInputValue(),
      quantity: item.quantity || "",
      sell_price: item.current_price || "",
      notes: ""
    });
  }

  async function sell(event) {
    event.preventDefault();
    await api(`/api/holdings/${sellingId}/sell`, {
      method: "POST",
      body: JSON.stringify({
        ...sellForm,
        quantity: Number(sellForm.quantity),
        sell_price: Number(sellForm.sell_price)
      })
    });
    setSellingId(null);
    setSellingSymbol("");
    setMessage("Holding sale recorded.");
    await refresh();
    refreshKey("dashboard", () => api("/api/dashboard")).catch(() => {});
    const fromDate = todayInputValue().slice(0, 8) + "01";
    const toDate = todayInputValue();
    refreshKey(profitLossCacheKey(fromDate, toDate), () => api(`/api/profit-loss?from_date=${fromDate}&to_date=${toDate}`)).catch(() => {});
  }

  const editingItem = (data || []).find((item) => item.id === editingId);

  return (
    <section>
      <PageTitle title="Holdings" />
      {error && <Notice tone="danger">{error}</Notice>}
      <Toast message={message} onClose={() => setMessage("")} />
      <div className="panel">
        <form className="holdingForm" onSubmit={save}>
          <input placeholder="Symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} required />
          <input type="date" value={form.buy_date} onChange={(e) => setForm({ ...form, buy_date: e.target.value })} required />
          <input placeholder="Quantity" type="number" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} required />
          <input placeholder="Buy price" type="number" value={form.buy_price} onChange={(e) => setForm({ ...form, buy_price: e.target.value })} required />
          <input placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <button type="submit"><Plus size={16} />Add</button>
        </form>

        <div className="tableWrap">
          <table className="holdingsTable">
            <thead>
              <tr>
                <th className="slCol">SL</th>
                <th>Symbol</th>
                <th>Date</th>
                <th>Quantity</th>
                <th>Buy</th>
                <th>Invested</th>
                <th>Current / Share</th>
                <th>Total P/L</th>
                <th>P/L %</th>
                <th>Notes</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {(data || []).length ? (data || []).map((item, index) => (
                <tr key={item.id}>
                  <td className="slCol">{index + 1}</td>
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
                  <td>{item.buy_date}</td>
                  <td>{number(item.quantity)}</td>
                  <td>{money(item.buy_price)}</td>
                  <td>{money(item.invested_amount)}</td>
                  <td>{money(item.current_price)}</td>
                  <td><span className={(item.profit_loss || 0) >= 0 ? "gain" : "loss"}>{money(item.profit_loss)}</span></td>
                  <td>{item.profit_loss_pct === null || item.profit_loss_pct === undefined ? "-" : `${item.profit_loss_pct}%`}</td>
                  <td>{item.notes || "-"}</td>
                  <td>
                    <div className="rowActions">
                      <button type="button" className="smallBtn actionBtn" onClick={() => startEdit(item)}>
                        <Edit3 size={14} />Edit
                      </button>
                      <button type="button" className="smallBtn sellBtn" onClick={() => startSell(item)}>Sell</button>
                    </div>
                  </td>
                </tr>
              )) : (
                <tr><td colSpan="11">No records.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {sellingId && (
        <div className="modalOverlay" onClick={() => { setSellingId(null); setSellingSymbol(""); }}>
          <form className="appModal holdingModal" onSubmit={sell} onClick={(event) => event.stopPropagation()}>
            <div className="modalHeader">
              <div>
                <h2>Sell {sellingSymbol}</h2>
                <p>Record sell quantity, price, and date for this holding.</p>
              </div>
              <button type="button" className="modalClose" onClick={() => { setSellingId(null); setSellingSymbol(""); }} title="Close">
                <X size={18} />
              </button>
            </div>
            <div className="modalFormGrid">
              <label>
                Sell date
                <input type="date" value={sellForm.sell_date} onChange={(e) => setSellForm({ ...sellForm, sell_date: e.target.value })} required />
              </label>
              <label>
                Quantity
                <input placeholder="Sell quantity" type="number" value={sellForm.quantity} onChange={(e) => setSellForm({ ...sellForm, quantity: e.target.value })} required />
              </label>
              <label>
                Sell price
                <input placeholder="Sell price" type="number" value={sellForm.sell_price} onChange={(e) => setSellForm({ ...sellForm, sell_price: e.target.value })} required />
              </label>
              <label className="modalWide">
                Notes
                <input placeholder="Notes" value={sellForm.notes} onChange={(e) => setSellForm({ ...sellForm, notes: e.target.value })} />
              </label>
            </div>
            <div className="modalActions">
              <button type="submit" className="sellBtn"><Check size={16} />Confirm Sell</button>
              <button type="button" className="secondaryBtn" onClick={() => { setSellingId(null); setSellingSymbol(""); }}>Cancel</button>
            </div>
          </form>
        </div>
      )}
      {editingItem && (
        <div className="modalOverlay" onClick={() => cancelEdit(editingItem)}>
          <form className="appModal holdingModal holdingEditModal" onSubmit={(event) => { event.preventDefault(); saveEdit(editingItem); }} onClick={(event) => event.stopPropagation()}>
            <div className="modalHeader">
              <div>
                <h2>Edit {editingItem.symbol}</h2>
                <p>Update holding details for this position.</p>
              </div>
              <button type="button" className="modalClose" onClick={() => cancelEdit(editingItem)} title="Close">
                <X size={18} />
              </button>
            </div>
            <div className="modalFormGrid">
              <div className="modalReadOnlyGrid modalWide">
                <div className="modalReadOnlyItem">
                  <span>Current Symbol</span>
                  <strong>{editingItem.symbol}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Buy Date</span>
                  <strong>{editingItem.buy_date || "-"}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Quantity</span>
                  <strong>{number(editingItem.quantity)}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Buy Price</span>
                  <strong>{money(editingItem.buy_price)}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Invested</span>
                  <strong>{money(editingItem.invested_amount)}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Current / Share</span>
                  <strong>{money(editingItem.current_price)}</strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>Total P/L</span>
                  <strong className={(editingItem.profit_loss || 0) >= 0 ? "gain" : "loss"}>
                    {money(editingItem.profit_loss)}
                  </strong>
                </div>
                <div className="modalReadOnlyItem">
                  <span>P/L %</span>
                  <strong>{editingItem.profit_loss_pct === null || editingItem.profit_loss_pct === undefined ? "-" : `${editingItem.profit_loss_pct}%`}</strong>
                </div>
                <div className="modalReadOnlyItem modalReadOnlyWide">
                  <span>Current Notes</span>
                  <strong>{editingItem.notes || "-"}</strong>
                </div>
              </div>
              <label>
                Symbol
                <input
                  value={edits[editingItem.id]?.symbol ?? ""}
                  onChange={(e) => updateEdit(editingItem.id, { symbol: e.target.value.toUpperCase() })}
                />
              </label>
              <label>
                Buy date
                <input
                  type="date"
                  value={edits[editingItem.id]?.buy_date ?? ""}
                  onChange={(e) => updateEdit(editingItem.id, { buy_date: e.target.value })}
                />
              </label>
              <label>
                Quantity
                <input
                  type="number"
                  value={edits[editingItem.id]?.quantity ?? ""}
                  onChange={(e) => updateEdit(editingItem.id, { quantity: e.target.value })}
                />
              </label>
              <label>
                Buy price
                <input
                  type="number"
                  value={edits[editingItem.id]?.buy_price ?? ""}
                  onChange={(e) => updateEdit(editingItem.id, { buy_price: e.target.value })}
                />
              </label>
              <label className="modalWide">
                Notes
                <input
                  value={edits[editingItem.id]?.notes ?? ""}
                  onChange={(e) => updateEdit(editingItem.id, { notes: e.target.value })}
                  placeholder="Notes"
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
