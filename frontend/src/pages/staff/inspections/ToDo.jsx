import { useNavigate } from "react-router-dom";
import { inspectionOverview } from "../../../lib/api";
import { useStaff } from "../../../lib/session";
import { formatDate } from "../../../lib/time";
import { ErrorBanner, Loading, useAsync, When } from "../../../components/ui";

export default function ToDo() {
  const { can } = useStaff();
  const overview = useAsync(() => inspectionOverview(), []);
  const navigate = useNavigate();
  if (overview.error) return <ErrorBanner error={overview.error} onRetry={overview.reload} />;
  if (!overview.data) return <Loading />;
  return (
    <>
      <p className="hint">Halls are due every 30 days, or by the date an admin scheduled. Overdue first.</p>
      <table className="data-table responsive clickable">
        <thead><tr><th>Hall</th><th>Last inspected</th><th>Last score</th><th>Next due</th><th></th></tr></thead>
        <tbody>
          {overview.data.halls.map((h) => (
            <tr key={h.mess_id}>
              <td data-label="Hall">{h.mess_name}<span className="hint block">{h.college_name}</span></td>
              <td data-label="Last inspected">{h.last_inspected_at ? <When value={h.last_inspected_at} /> : <span className="warn-text">Never</span>}</td>
              <td data-label="Last score">{h.last_score != null ? `${h.last_score}%` : "—"}</td>
              <td data-label="Next due">
                <span className={h.overdue ? "warn-text" : ""}>
                  {h.never_inspected ? "Due now — never inspected" : `${formatDate(h.next_due)}${h.overdue ? " — overdue" : ""}`}
                </span>
                {h.assigned_to_me && <span className="pill pill-acknowledged block">assigned to you</span>}
              </td>
              <td>{can("inspect") && <button type="button" className="secondary-btn" onClick={() => navigate(`/admin/inspections/new?mess=${h.mess_id}`)}>Inspect</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
