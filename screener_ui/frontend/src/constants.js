import { BarChart3, CalendarClock, FileText, ReceiptText, Settings, WalletCards } from "lucide-react";

export const tabs = [
  { id: "dashboard", label: "Dashboard", icon: BarChart3 },
  { id: "reports", label: "Reports", icon: FileText },
  { id: "watchlist", label: "Watchlist", icon: CalendarClock },
  { id: "holdings", label: "Holdings", icon: WalletCards },
  { id: "profitLoss", label: "P/L Report", icon: ReceiptText },
  { id: "settings", label: "Settings", icon: Settings }
];
