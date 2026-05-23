import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../api.js";
import { DataTable } from "../components/DataTable.jsx";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { useLoad } from "../hooks/useLoad.js";
import { money, number } from "../utils/format.js";

export function Bought() {
  const { data, error, refresh } = useLoad(() => api("/api/holdings"), []);
  const [form, setForm] = useState({
    symbol: "",
    buy_date: new Date().toISOString().slice(0, 10),
    quantity: "",
    buy_price: "",
    notes: ""
  });

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
    refresh();
  }

  async function remove(id) {
    await api(`/api/holdings/${id}`, { method: "DELETE" });
    refresh();
  }

  return (
    <section>
      <PageTitle title="Bought" />
      {error && <Notice tone="danger">{error}</Notice>}
      <div className="panel">
        <form className="holdingForm" onSubmit={save}>
          <input placeholder="Symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} required />
          <input type="date" value={form.buy_date} onChange={(e) => setForm({ ...form, buy_date: e.target.value })} required />
          <input placeholder="Quantity" type="number" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} required />
          <input placeholder="Buy price" type="number" value={form.buy_price} onChange={(e) => setForm({ ...form, buy_price: e.target.value })} required />
          <input placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <button type="submit"><Plus size={16} />Add</button>
        </form>
        <DataTable
          headers={["Symbol", "Date", "Quantity", "Buy", "Invested", "Current", "P/L", "P/L %", ""]}
          rows={(data || []).map((item) => [
            <strong>{item.symbol}</strong>,
            item.buy_date,
            number(item.quantity),
            money(item.buy_price),
            money(item.invested_amount),
            money(item.current_price),
            <span className={(item.profit_loss || 0) >= 0 ? "gain" : "loss"}>{money(item.profit_loss)}</span>,
            item.profit_loss_pct === null || item.profit_loss_pct === undefined ? "-" : `${item.profit_loss_pct}%`,
            <button className="iconDanger" onClick={() => remove(item.id)}><Trash2 size={16} /></button>
          ])}
        />
      </div>
    </section>
  );
}
