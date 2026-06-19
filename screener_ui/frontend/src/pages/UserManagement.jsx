import { useState } from "react";
import { KeyRound, Plus, Trash2 } from "lucide-react";
import { api } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { Toast } from "../components/Toast.jsx";
import { useCachedLoad } from "../hooks/useCachedLoad.js";

export function UserManagement() {
  const usersLoader = () => api("/api/auth/users");
  const { data, error, refresh } = useCachedLoad("users", usersLoader, []);
  const [form, setForm] = useState({ email: "", password: "" });
  const [passwords, setPasswords] = useState({});
  const [message, setMessage] = useState("");

  async function addUser(event) {
    event.preventDefault();
    const user = await api("/api/auth/users", {
      method: "POST",
      body: JSON.stringify(form)
    });
    setForm({ email: "", password: "" });
    setMessage(`${user.email} added.`);
    refresh();
  }

  async function deleteUser(email) {
    if (!window.confirm(`Delete user ${email}?`)) return;
    await api(`/api/auth/users/${encodeURIComponent(email)}`, { method: "DELETE" });
    setMessage(`${email} deleted.`);
    refresh();
  }

  async function resetPassword(email) {
    const password = passwords[email] || "";
    if (!password) return;
    await api(`/api/auth/users/${encodeURIComponent(email)}/password`, {
      method: "PUT",
      body: JSON.stringify({ password })
    });
    setPasswords((current) => ({ ...current, [email]: "" }));
    setMessage(`${email} password updated.`);
  }

  return (
    <section>
      <PageTitle title="User Management" />
      {error && <Notice tone="danger">{error}</Notice>}
      <Toast message={message} onClose={() => setMessage("")} />
      <div className="panel">
        <form className="inlineForm userForm" onSubmit={addUser}>
          <input
            type="email"
            placeholder="Email"
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
            required
          />
          <input
            type="password"
            placeholder="Password"
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            required
          />
          <button type="submit"><Plus size={16} />Add User</button>
        </form>
        <table className="holdingsTable userTable">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>New Password</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((user) => (
              <tr key={user.email}>
                <td><strong>{user.email}</strong></td>
                <td>{user.is_admin ? "Admin" : "User"}</td>
                <td>
                  <input
                    className="tableInput"
                    type="password"
                    placeholder="New password"
                    value={passwords[user.email] || ""}
                    onChange={(event) => setPasswords({ ...passwords, [user.email]: event.target.value })}
                  />
                </td>
                <td>
                  <div className="rowActions">
                    <button
                      type="button"
                      className="smallBtn actionBtn"
                      onClick={() => resetPassword(user.email)}
                      disabled={!passwords[user.email]}
                    >
                      <KeyRound size={14} />Set
                    </button>
                    {!user.is_admin && (
                      <button type="button" className="iconDanger" onClick={() => deleteUser(user.email)}>
                        <Trash2 size={16} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
