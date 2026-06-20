import { useEffect, useRef, useState } from "react";
import { Ban, CheckCircle2, KeyRound, Plus, Trash2 } from "lucide-react";
import { api } from "../api.js";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { Toast } from "../components/Toast.jsx";
import { useAppData } from "../context/AppDataContext.jsx";
import { useCachedLoad } from "../hooks/useCachedLoad.js";

export function UserManagement() {
  const usersLoader = () => api("/api/auth/users");
  const { cache, setCachedData } = useAppData();
  const { data, error, refresh } = useCachedLoad("users", usersLoader, []);
  const [form, setForm] = useState({ email: "", password: "" });
  const [passwords, setPasswords] = useState({});
  const [message, setMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const addFormRef = useRef(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setForm({ email: "", password: "" });
      addFormRef.current?.reset();
    }, 150);
    return () => window.clearTimeout(timer);
  }, []);

  async function addUser(event) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const email = String(formData.get("new-user-email") || form.email).trim().toLowerCase();
    const password = String(formData.get("new-user-password") || form.password);
    if (!email || !password) return;
    setBusyAction("add");
    setActionError("");
    try {
      const user = await api("/api/auth/users", {
        method: "POST",
        body: JSON.stringify({ email, password })
      });
      const current = Array.isArray(cache.users?.data) ? cache.users.data : [];
      setCachedData("users", [user, ...current.filter((item) => item.email !== user.email)]);
      setForm({ email: "", password: "" });
      setMessage(`${user.email} added.`);
      refresh().catch(() => {});
    } catch (err) {
      setActionError(err.message || "Could not add user.");
    } finally {
      setBusyAction("");
    }
  }

  async function deleteUser(email) {
    if (!window.confirm(`Delete user ${email}?`)) return;
    const actionKey = `delete:${email}`;
    setBusyAction(actionKey);
    setActionError("");
    try {
      await api(`/api/auth/users/${encodeURIComponent(email)}`, { method: "DELETE" });
      const current = Array.isArray(cache.users?.data) ? cache.users.data : [];
      setCachedData("users", current.filter((user) => user.email !== email));
      setMessage(`${email} deleted.`);
      refresh().catch(() => {});
    } catch (err) {
      setActionError(err.message || "Could not delete user.");
    } finally {
      setBusyAction("");
    }
  }

  async function toggleUser(user) {
    const disabled = !user.disabled;
    const actionKey = `toggle:${user.email}`;
    setBusyAction(actionKey);
    setActionError("");
    try {
      await api(`/api/auth/users/${encodeURIComponent(user.email)}/disabled`, {
        method: "PUT",
        body: JSON.stringify({ disabled })
      });
      const current = Array.isArray(cache.users?.data) ? cache.users.data : [];
      setCachedData("users", current.map((item) => (item.email === user.email ? { ...item, disabled } : item)));
      setMessage(`${user.email} ${disabled ? "disabled" : "enabled"}.`);
      refresh().catch(() => {});
    } catch (err) {
      setActionError(err.message || "Could not update user.");
    } finally {
      setBusyAction("");
    }
  }

  async function resetPassword(email) {
    const password = passwords[email] || "";
    if (!password) return;
    const actionKey = `password:${email}`;
    setBusyAction(actionKey);
    setActionError("");
    try {
      await api(`/api/auth/users/${encodeURIComponent(email)}/password`, {
        method: "PUT",
        body: JSON.stringify({ password })
      });
      setPasswords((current) => ({ ...current, [email]: "" }));
      setMessage(`${email} password updated.`);
    } catch (err) {
      setActionError(err.message || "Could not update password.");
    } finally {
      setBusyAction("");
    }
  }

  return (
    <section>
      <PageTitle title="User Management" />
      {error && <Notice tone="danger">{error}</Notice>}
      {actionError && <Notice tone="danger">{actionError}</Notice>}
      <Toast message={message} onClose={() => setMessage("")} />
      <div className="panel">
        <form ref={addFormRef} className="inlineForm userForm" onSubmit={addUser} autoComplete="off">
          <input type="text" name="fake-login-email" autoComplete="username" tabIndex="-1" aria-hidden="true" className="hiddenAutofillField" />
          <input type="password" name="fake-login-password" autoComplete="current-password" tabIndex="-1" aria-hidden="true" className="hiddenAutofillField" />
          <input
            type="email"
            name="new-user-email"
            placeholder="Email"
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
            autoComplete="section-add-user off"
            data-lpignore="true"
            data-1p-ignore="true"
            required
          />
          <input
            type="password"
            name="new-user-password"
            placeholder="Password"
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            autoComplete="section-add-user new-password"
            data-lpignore="true"
            data-1p-ignore="true"
            required
          />
          <button type="submit" disabled={busyAction === "add"}>
            <Plus size={16} />{busyAction === "add" ? "Adding..." : "Add User"}
          </button>
        </form>
        <table className="holdingsTable userTable">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>New Password</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((user) => (
              <tr key={user.email}>
                <td><strong>{user.email}</strong></td>
                <td>{user.is_admin ? "Admin" : "User"}</td>
                <td>{user.disabled ? "Disabled" : "Active"}</td>
                <td>
                  <input
                    className="tableInput"
                    type="password"
                    name={`reset-password-${user.email}`}
                    placeholder="New password"
                    value={passwords[user.email] || ""}
                    onChange={(event) => setPasswords({ ...passwords, [user.email]: event.target.value })}
                    autoComplete="new-password"
                  />
                </td>
                <td>
                  <div className="rowActions">
                    <button
                      type="button"
                      className="smallBtn actionBtn"
                      onClick={() => resetPassword(user.email)}
                      disabled={!passwords[user.email] || busyAction === `password:${user.email}`}
                    >
                      <KeyRound size={14} />Set
                    </button>
                    {!user.is_admin && (
                      <>
                        <button
                          type="button"
                          className="smallBtn actionBtn"
                          onClick={() => toggleUser(user)}
                          disabled={busyAction === `toggle:${user.email}`}
                        >
                          {user.disabled ? <CheckCircle2 size={14} /> : <Ban size={14} />}
                          {user.disabled ? "Enable" : "Disable"}
                        </button>
                        <button
                          type="button"
                          className="iconDanger"
                          onClick={() => deleteUser(user.email)}
                          disabled={busyAction === `delete:${user.email}`}
                        >
                          <Trash2 size={16} />
                        </button>
                      </>
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
