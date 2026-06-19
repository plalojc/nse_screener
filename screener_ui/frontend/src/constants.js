import { BarChart3, CalendarClock, FileText, ReceiptText, Settings, Users, WalletCards } from "lucide-react";

export const tabs = [
  { id: "dashboard", label: "Dashboard", icon: BarChart3 },
  { id: "reports", label: "Reports", icon: FileText },
  { id: "watchlist", label: "Watchlist", icon: CalendarClock },
  { id: "holdings", label: "Holdings", icon: WalletCards },
  { id: "profitLoss", label: "P/L Report", icon: ReceiptText },
  { id: "settings", label: "Settings", icon: Settings },
  { id: "users", label: "Users", icon: Users, adminOnly: true }
];
