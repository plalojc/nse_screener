export function openTradingView(symbol, chartIdValue) {
  const rawId = chartIdValue || "IMppZ0T";
  const chartId = String(rawId).replace(/[^A-Za-z0-9_-]/g, "");
  const base = chartId
    ? `https://in.tradingview.com/chart/${chartId}/`
    : "https://in.tradingview.com/chart/";
  const left = (window.screen.width / 2) - 600;
  const top = (window.screen.height / 2) - 300;
  window.open(
    `${base}?symbol=NSE:${encodeURIComponent(symbol)}`,
    symbol,
    `height=600,width=1200,top=${top},left=${left}`
  );
}
