import { useEffect, useState } from "react";
import { Search, Trash2, X } from "lucide-react";
import { api } from "../api.js";
import { Metric } from "../components/Metric.jsx";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { money, number } from "../utils/format.js";

function todayInputValue() {
  const now = new Date();
  const tzOffsetMs = now.getTimezoneOffset() * 60 * 1000;
  return new Date(now.getTime() - tzOffsetMs).toISOString().slice(0, 10);
}

function monthStartValue() {
  const today = todayInputValue();
  return `${today.slice(0, 8)}01`;
}

function pnlClass(value) {
  return Number(value || 0) >= 0 ? "gain" : "loss";
}

function pnlPercent(profitLoss, buyAmount) {
  const base = Number(buyAmount || 0);
  if (!base) return null;
  return (Number(profitLoss || 0) / base) * 100;
}

function pnlDisplay(profitLoss, buyAmount) {
  if (profitLoss === null || profitLoss === undefined) return "-";
  const pct = pnlPercent(profitLoss, buyAmount);
  return {
    amount: money(profitLoss),
    percent: pct === null ? "" : `${pct.toFixed(1)}%`
  };
}

export function ProfitLossReport() {
  const [fromDate, setFromDate] = useState(monthStartValue());
  const [toDate, setToDate] = useState(todayInputValue());
  const [data, setData] = useState(null);
  const [deleteRow, setDeleteRow] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadReport(event) {
    event?.preventDefault();
    setLoading(true);
    setError("");
    try {
      setData(await api(`/api/profit-loss?from_date=${fromDate}&to_date=${toDate}`));
    } catch (err) {
      setError(err.message || "Unable to load P/L report");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadReport();
  }, []);

  async function confirmDelete() {
    if (!deleteRow) return;
    setLoading(true);
    setError("");
    try {
      await api(`/api/profit-loss/${deleteRow.id}`, { method: "DELETE" });
      setDeleteRow(null);
      await loadReport();
    } catch (err) {
      setError(err.message || "Unable to delete P/L row");
    } finally {
      setLoading(false);
    }
  }

  const rows = data?.rows || [];
  const summary = data?.summary || {};
  const summaryPnl = pnlDisplay(summary.profit_loss, summary.total_buy_amount);

  return (
    <section>
      <PageTitle title="P/L Report" />
      {error && <Notice tone="danger">{error}</Notice>}
      <div className="panel">
        <form className="plFilterForm" onSubmit={loadReport}>
          <label>
            From date
            <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} required />
          </label>
          <label>
            To date
            <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} required />
          </label>
          <button type="submit" disabled={loading}>
            <Search size={16} />Get Report
          </button>
        </form>

        <div className="metricGrid plMetricGrid">
          <Metric label="Total Buy" value={money(summary.total_buy_amount)} />
          <Metric label="Total Sell" value={money(summary.total_sell_amount)} />
          <Metric label="Profit / Loss" value={money(summary.profit_loss)} tone={pnlClass(summary.profit_loss)} />
        </div>

        <div>
          <table className="holdingsTable plTable">
            <thead>
              <tr>
                <th className="slCol">SL</th>
                <th>Symbol</th>
                <th>Quantity</th>
                <th className="buyCol">Buy Date</th>
                <th className="buyCol">Buy Price</th>
                <th className="buyCol">Buy Amount</th>
                <th className="sellCol">Sell Date</th>
                <th className="sellCol">Sell Price</th>
                <th className="sellCol">Sell Amount</th>
                <th>P/L</th>
              </tr>
            </thead>
            <tbody>
              {rows.length ? rows.map((row, index) => (
                (() => {
                  const pnl = pnlDisplay(row.profit_loss, row.buy_amount);
                  return (
                    <tr key={row.id || `${row.symbol}-${row.sell_date}-${index}`}>
                      <td className="slCol">{index + 1}</td>
                      <td><strong>{row.symbol}</strong></td>
                      <td>{number(row.quantity)}</td>
                      <td className="buyCol">{row.buy_date || "-"}</td>
                      <td className="buyCol">{money(row.buy_price)}</td>
                      <td className="buyCol">{money(row.buy_amount)}</td>
                      <td className="sellCol">{row.sell_date || "-"}</td>
                      <td className="sellCol">{money(row.sell_price)}</td>
                      <td className="sellCol">{money(row.sell_amount)}</td>
                      <td className={`pnlCol ${pnlClass(row.profit_loss)}`}>
                        <div className="pnlCell">
                          <span className="pnlText">
                            <span className="pnlAmount">{pnl.amount || pnl}</span>
                            {pnl.percent && <span className="pnlPct">({pnl.percent})</span>}
                          </span>
                          {row.id && (
                            <button
                              className="plDeleteBtn"
                              type="button"
                              title={`Delete ${row.symbol} sale row`}
                              aria-label={`Delete ${row.symbol} sale row`}
                              onClick={() => setDeleteRow(row)}
                            >
                              <Trash2 size={14} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })()
              )) : (
                <tr><td colSpan="10">{loading ? "Loading..." : "No sold shares in this date range."}</td></tr>
              )}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan="5"><strong>Total</strong></td>
                <td><strong>{money(summary.total_buy_amount)}</strong></td>
                <td colSpan="2" />
                <td><strong>{money(summary.total_sell_amount)}</strong></td>
                <td className={`pnlCol ${pnlClass(summary.profit_loss)}`}>
                  <div className="pnlCell">
                    <strong className="pnlText">
                      <span className="pnlAmount">{summaryPnl.amount || summaryPnl}</span>
                      {summaryPnl.percent && <span className="pnlPct">({summaryPnl.percent})</span>}
                    </strong>
                  </div>
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
      {deleteRow && (
        <div className="modalOverlay" onClick={() => setDeleteRow(null)}>
          <div className="appModal confirmModal" onClick={(event) => event.stopPropagation()}>
            <div className="modalHeader">
              <div>
                <h2>Delete P/L Row</h2>
                <p>Delete the sold transaction for {deleteRow.symbol} on {deleteRow.sell_date}?</p>
              </div>
              <button type="button" className="modalClose" onClick={() => setDeleteRow(null)} title="Close">
                <X size={18} />
              </button>
            </div>
            <div className="modalActions">
              <button type="button" className="dangerBtn" onClick={confirmDelete} disabled={loading}>
                <Trash2 size={16} />Delete
              </button>
              <button type="button" className="secondaryBtn" onClick={() => setDeleteRow(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
