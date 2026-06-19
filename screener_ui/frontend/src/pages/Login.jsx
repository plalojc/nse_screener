import { useState } from "react";
import { LogIn } from "lucide-react";
import { login } from "../api.js";
import { Notice } from "../components/Notice.jsx";

export function Login({ onLogin }) {
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const user = await login(form.username, form.password);
      onLogin(user);
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="loginShell">
      <form className="loginCard" onSubmit={submit}>
        <div className="loginMark">N</div>
        <h1>NSE Screener</h1>
        <p>Login to your breakout workspace.</p>
        {error && <Notice tone="danger">{error}</Notice>}
        <label>
          Username / email
          <input
            value={form.username}
            onChange={(event) => setForm({ ...form, username: event.target.value })}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            autoComplete="current-password"
            required
          />
        </label>
        <button type="submit" disabled={loading}>
          <LogIn size={17} />Login
        </button>
      </form>
    </main>
  );
}
