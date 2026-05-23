import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../api.js";
import { DataTable } from "../components/DataTable.jsx";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { useLoad } from "../hooks/useLoad.js";
import { money } from "../utils/format.js";

export function Watchlist() {
  const { data, error, refresh } = useLoad(() => api("/api/watchlist"), []);
  const [form, setForm] = useState({ symbol: "", target_price: "", notes: "" });

  async function save(event) {
    event.preventDefault();
    await api("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({
        ...form,
        target_price: form.target_price ? Number(form.target_price) : null
      })
    });
    setForm({ symbol: "", target_price: "", notes: "" });
    refresh();
  }

  async function remove(id) {
    await api(`/api/watchlist/${id}`, { method: "DELETE" });
    refresh();
  }

  return (
    <section>
      <PageTitle title="Watchlist" />
      {error && <Notice tone="danger">{error}</Notice>}
      <div className="panel">
        <form className="inlineForm" onSubmit={save}>
          <input placeholder="Symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} required />
          <input placeholder="Target price" type="number" value={form.target_price} onChange={(e) => setForm({ ...form, target_price: e.target.value })} />
          <input placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <button type="submit"><Plus size={16} />Add</button>
        </form>
        <DataTable
          headers={["Symbol", "Target", "Notes", "Updated", ""]}
          rows={(data || []).map((item) => [
            <strong>{item.symbol}</strong>,
            money(item.target_price),
            item.notes || "-",
            item.updated_at,
            <button className="iconDanger" onClick={() => remove(item.id)}><Trash2 size={16} /></button>
          ])}
        />
      </div>
    </section>
  );
}
