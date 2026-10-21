import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { addInspectionPhoto, downloadStaffFile, getInspection, listInspections } from "../../../lib/api";
import { useStaff } from "../../../lib/session";
import { formatDateTime } from "../../../lib/time";
import { ErrorBanner, Loading, Pager, StaffPhoto, useAsync, When } from "../../../components/ui";

export function History() {
  const { can } = useStaff();
  const [offset, setOffset] = useState(0);
  const [mine, setMine] = useState(false);
  const list = useAsync(() => listInspections({ offset, limit: 25, mine: mine || undefined }), [offset, mine]);
  const navigate = useNavigate();
  return (
    <>
      <div className="filters-row">
        {can("inspect") && <label className="checkbox-row"><input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); setOffset(0); }} /> Only mine</label>}
        {can("export") && <button type="button" className="secondary-btn" onClick={() => downloadStaffFile("/staff/export/inspections.csv", "inspections.csv")}>⬇ Export CSV</button>}
      </div>
      <ErrorBanner error={list.error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading />}
      {list.data?.items.length === 0 && <div className="banner info">No inspections yet.</div>}
      {list.data?.items.length > 0 && (
        <table className="data-table responsive clickable">
          <thead><tr><th>#</th><th>Hall</th><th>Inspector</th><th>Score</th><th>Failed</th><th>When</th></tr></thead>
          <tbody>
            {list.data.items.map((i) => (
              <tr key={i.id} tabIndex={0} onClick={() => navigate(`/admin/inspections/history/${i.id}`)} onKeyDown={(e) => e.key === "Enter" && navigate(`/admin/inspections/history/${i.id}`)}>
                <td data-label="#">{i.id}</td>
                <td data-label="Hall">{i.mess_name}</td>
                <td data-label="Inspector">{i.inspector_name}{i.verified_onsite ? " ✓" : ""}</td>
                <td data-label="Score">{i.score}%</td>
                <td data-label="Failed">{i.summary.failed_items.length}{i.summary.failed_items.some((f) => f.critical) && <span className="crit-badge">critical</span>}</td>
                <td data-label="When"><When value={i.created_at} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {list.data && <Pager offset={offset} limit={25} total={list.data.total} onChange={setOffset} />}
    </>
  );
}

export function InspectionDetail() {
  const { id } = useParams();
  const { staff } = useStaff();
  const insp = useAsync(() => getInspection(id), [id]);
  const [error, setError] = useState(null);
  const navigate = useNavigate();
  if (insp.error) return <ErrorBanner error={insp.error} />;
  if (!insp.data) return <Loading />;
  const d = insp.data;
  const canAddPhotos = d.inspector_id === staff.id || staff.role === "admin";
  return (
    <div className="detail">
      <button type="button" className="link-btn" onClick={() => navigate("/admin/inspections/history")}>← History</button>
      <h2>Inspection #{d.id} · {d.mess_name}</h2>
      <p>{d.inspector_name} · {formatDateTime(d.created_at)} · {d.score}% · {d.verified_onsite ? "✓ verified on site" : "not verified on site"}
        {d.latitude != null && <> · <a href={`https://www.openstreetmap.org/?mlat=${d.latitude}&mlon=${d.longitude}#map=18/${d.latitude}/${d.longitude}`} target="_blank" rel="noreferrer">location</a></>}</p>
      {d.general_notes && <p>{d.general_notes}</p>}
      <ul className="check-results">
        {Object.entries(d.responses).map(([key, r]) => (
          <li key={key} className={r.result}>
            <span className="result-tag">{r.result === "na" ? "N/A" : r.result.toUpperCase()}</span> {r.text}
            {r.critical && <span className="crit-badge">Critical</span>}
            {r.note && <span className="hint block">{r.note}</span>}
            {d.photos.filter((p) => p.item_key === key).map((p) => <StaffPhoto key={p.id} url={p.photo_url} />)}
          </li>
        ))}
      </ul>
      {d.photos.filter((p) => !p.item_key).map((p) => <StaffPhoto key={p.id} url={p.photo_url} />)}
      {canAddPhotos && (
        <label className="file-inline">📷 Add a photo
          <input type="file" accept="image/jpeg,image/png,image/webp" onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            try { await addInspectionPhoto(d.id, null, f); insp.reload(); } catch (err) { setError(err); }
          }} />
        </label>
      )}
      <ErrorBanner error={error} />
    </div>
  );
}
