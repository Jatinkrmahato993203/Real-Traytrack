import { useState } from "react";
import { addSchedule, deleteSchedule, inspectionOverview, listStaff } from "../../../lib/api";
import { useStaff } from "../../../lib/session";
import { daysFromToday, formatDate } from "../../../lib/time";
import { ErrorBanner, Field, Loading, useAsync } from "../../../components/ui";

export default function Schedule() {
  const { can } = useStaff();
  const overview = useAsync(() => inspectionOverview(), []);
  const inspectors = useAsync(() => listStaff("inspector"), []);
  const [form, setForm] = useState({ mess_id: "", due_date: daysFromToday(7), assigned_staff_id: "", notes: "" });
  const [error, setError] = useState(null);
  if (!overview.data) return <Loading />;
  return (
    <>
      {can("schedule") && (
        <form className="form-card" onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await addSchedule({ ...form, mess_id: Number(form.mess_id), assigned_staff_id: form.assigned_staff_id ? Number(form.assigned_staff_id) : null });
            setForm({ ...form, notes: "" });
            overview.reload();
          } catch (err) { setError(err); }
        }}>
          <h3>Schedule an inspection</h3>
          <div className="filters-row">
            <label className="field inline-field"><span className="field-label">Hall</span>
              <select required value={form.mess_id} onChange={(e) => setForm({ ...form, mess_id: e.target.value })}>
                <option value="" disabled>Choose</option>
                {overview.data.halls.map((h) => <option key={h.mess_id} value={h.mess_id}>{h.mess_name} ({h.college_name})</option>)}
              </select>
            </label>
            <label className="field inline-field"><span className="field-label">Due by</span>
              <input type="date" required value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
            </label>
            <label className="field inline-field"><span className="field-label">Inspector</span>
              <select value={form.assigned_staff_id} onChange={(e) => setForm({ ...form, assigned_staff_id: e.target.value })}>
                <option value="">Anyone</option>
                {(inspectors.data || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
          </div>
          <Field label="Note for the inspector" optional><input value={form.notes} maxLength={500} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
          <p className="hint">For a surprise inspection, don't share the date with the mess team — only inspectors and admins see this schedule.</p>
          <ErrorBanner error={error} />
          <button type="submit" className="primary-btn">Add to schedule</button>
        </form>
      )}
      <h3>Upcoming</h3>
      {overview.data.schedule.length === 0 ? <p className="hint">Nothing scheduled.</p> : (
        <table className="data-table responsive">
          <thead><tr><th>Hall</th><th>Due</th><th>Inspector</th><th>Note</th><th></th></tr></thead>
          <tbody>
            {overview.data.schedule.map((s) => (
              <tr key={s.id}>
                <td data-label="Hall">{s.mess_name}</td>
                <td data-label="Due">{formatDate(s.due_date)}</td>
                <td data-label="Inspector">{s.assigned_name || "Anyone"}</td>
                <td data-label="Note">{s.notes || "—"}</td>
                <td>{can("schedule") && <button type="button" className="link-btn" onClick={async () => { try { await deleteSchedule(s.id); overview.reload(); } catch (e) { setError(e); } }}>Remove</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
