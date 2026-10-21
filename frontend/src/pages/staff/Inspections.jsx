import { NavLink, Route, Routes } from "react-router-dom";
import { useStaff } from "../../lib/session";
import ToDo from "./inspections/ToDo";
import NewInspection from "./inspections/NewInspection";
import { History, InspectionDetail } from "./inspections/History";
import Schedule from "./inspections/Schedule";

export default function Inspections() {
  const { can } = useStaff();
  const sub = [["", "To do", true], ["new", "New inspection", can("inspect")], ["history", "History", true], ["schedule", "Schedule", true]]
    .filter(([, , show]) => show);
  return (
    <>
      <nav className="sub-tabs" aria-label="Inspections">
        {sub.map(([path, label]) => (
          <NavLink key={path} end to={`/admin/inspections${path ? `/${path}` : ""}`} className={({ isActive }) => (isActive ? "active" : "")}>{label}</NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<ToDo />} />
        <Route path="new" element={<NewInspection />} />
        <Route path="history" element={<History />} />
        <Route path="history/:id" element={<InspectionDetail />} />
        <Route path="schedule" element={<Schedule />} />
      </Routes>
    </>
  );
}
