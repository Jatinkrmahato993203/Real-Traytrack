"""
routers/staff_cases.py — the day-to-day work: student complaints (search,
reply), alerts (workflow, owner, due date, evidence, reopen), and CSV
exports for audits.
"""

import csv
import io
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import alert_engine
import auth
import db
import notify
import photos
from deps import current_staff, page, require, require_alert_in_scope, scoped_college, scoped_mess
from permissions import can

router = APIRouter(prefix="/staff", tags=["staff"])


def _since(days):
    return db.to_db(db.utcnow() - timedelta(days=days)) if days else None


# ---------- Complaints ----------

def complaint_view(c):
    anonymous = bool(c.get("anonymous"))
    return {
        "id": c["id"], "college_id": c["college_id"], "college_name": c.get("college_name"),
        "mess_id": c["mess_id"], "mess_name": c.get("mess_name"), "category": c["category"],
        "description": c["description"], "meal": c.get("meal"), "dish": c.get("dish"),
        "anonymous": anonymous,
        # Anonymous reports show no identity at all, not even a masked email.
        "reporter": "Anonymous student" if anonymous else auth.mask_email(c["student_email"]),
        "status": c.get("status"), "staff_response": c.get("staff_response"), "responded_at": c.get("responded_at"),
        "created_at": c["created_at"], "photo_url": db.complaint_photo_url(c.get("photo_path")),
        "hidden_reason": c.get("hidden_reason") if c.get("hidden_at") else None,
    }


def _complaint_filters(staff, college_id, mess_id):
    if not can(staff, "view_complaints"):
        raise HTTPException(status_code=403, detail="Your role doesn't allow this.")
    return scoped_college(staff, college_id), scoped_mess(staff, mess_id)


@router.get("/complaints")
def search_complaints(college_id: Optional[int] = None, mess_id: Optional[int] = None, days: Optional[int] = 30,
                      category: Optional[str] = None, status: Optional[str] = None, meal: Optional[str] = None,
                      q: Optional[str] = None, offset: int = 0, limit: int = 50, staff=Depends(current_staff)):
    college_id, mess_id = _complaint_filters(staff, college_id, mess_id)
    offset, limit = page(offset, limit)
    rows, total = db.search_complaints(college_id, mess_id, _since(days), None, category, status, meal,
                                       (q or "").strip() or None, offset, limit)
    return {"items": [complaint_view(c) for c in rows], "total": total, "offset": offset, "limit": limit}


class RespondRequest(BaseModel):
    status: str
    response: Optional[str] = None


@router.post("/complaints/{complaint_id}/respond")
def respond(complaint_id: int, payload: RespondRequest, staff=Depends(current_staff)):
    """The student sees this in My Reports (and by email if configured)."""
    require(staff, "respond")
    c = db.get_complaint(complaint_id)
    if not c:
        raise HTTPException(status_code=404, detail="Complaint not found.")
    scoped_college(staff, c["college_id"])
    scoped_mess(staff, c["mess_id"])
    if payload.status not in db.COMPLAINT_STATUSES or payload.status == "received":
        raise HTTPException(status_code=400, detail="Choose acknowledged, action taken, closed or dismissed.")
    response = (payload.response or "").strip()
    if payload.status in ("action_taken", "dismissed") and not response:
        raise HTTPException(status_code=400, detail="Tell the student what was done (or why it was dismissed).")
    db.respond_to_complaint(complaint_id, payload.status, response[:2000] or None, staff)
    notify.complaint_update(c, payload.status, response)
    return {"ok": True}


class HideRequest(BaseModel):
    reason: str


@router.post("/complaints/{complaint_id}/hide")
def hide_complaint(complaint_id: int, payload: HideRequest, staff=Depends(current_staff)):
    """For abusive text or text that names/identifies someone. Admins and
    principals only — the person handling the complaint can't hide it."""
    require(staff, "alert_verify")
    c = db.get_complaint(complaint_id)
    if not c:
        raise HTTPException(status_code=404, detail="Complaint not found.")
    scoped_college(staff, c["college_id"])
    if not payload.reason.strip():
        raise HTTPException(status_code=400, detail="Give a reason (recorded in the activity log).")
    db.hide_complaint_text(complaint_id, payload.reason.strip()[:255], staff)
    return {"ok": True}


# ---------- Alerts ----------

def alert_view(a, delivered=None):
    return {
        **{k: a.get(k) for k in ("id", "mess_id", "mess_name", "college_id", "college_name", "source", "source_id",
                                  "level", "status", "reason", "fssai_reference", "created_at", "last_escalated_at",
                                  "resolved", "resolved_at", "resolution_notes", "owner_staff_id", "owner_name",
                                  "due_date", "reopened_count")},
        "authority_notified": (delivered or {}).get(a["id"], False),
        "overdue": bool(a.get("due_date") and a["due_date"] < date.today() and not a["resolved"]),
    }


@router.get("/alerts")
def search_alerts(college_id: Optional[int] = None, mess_id: Optional[int] = None, status: Optional[str] = None,
                  level: Optional[str] = None, offset: int = 0, limit: int = 50, staff=Depends(current_staff)):
    """status: one status, "active" (anything not resolved), or omitted for all."""
    require(staff, "view")
    college_id, mess_id = scoped_college(staff, college_id), scoped_mess(staff, mess_id)
    statuses = list(db.OPEN_STATUSES) if status == "active" else ([status] if status else None)
    offset, limit = page(offset, limit)
    rows, total = db.search_alerts(college_id=college_id, mess_id=mess_id, statuses=statuses, level=level,
                                   offset=offset, limit=limit)
    delivered = db.notifications.delivery_by_alert([a["id"] for a in rows])
    return {"items": [alert_view(a, delivered) for a in rows], "total": total, "offset": offset, "limit": limit}


@router.get("/alerts/{alert_id}")
def alert_detail(alert_id: int, staff=Depends(current_staff)):
    require(staff, "view")
    alert = require_alert_in_scope(staff, alert_id)
    delivered = db.notifications.delivery_by_alert([alert_id])
    source = None
    if alert["source"] == "complaint_pattern" and alert["source_id"]:
        c = db.get_complaint(alert["source_id"])
        source = complaint_view(c) if c else None
    elif alert["source"] == "inspection" and alert["source_id"]:
        i = db.get_inspection(alert["source_id"])
        if i:
            source = {"inspection_id": i["id"], "inspector_name": i["inspector_name"], "score": i["score"],
                      "failed": [r for r in i["responses"].values() if r["result"] == "fail"]}
    evidence = [{**e, "photo_url": db.complaint_photo_url(e["photo_path"]), "photo_path": None}
                for e in db.list_evidence(alert_id)]
    notifications, _ = db.notifications.list_notifications(alert_id=alert_id, limit=50)
    return {
        "alert": alert_view(alert, delivered), "source": source, "history": db.history(alert_id),
        "evidence": evidence, "notifications": notifications,
        "allowed_actions": [a for a, (frm, _, cap) in alert_engine.TRANSITIONS.items()
                            if alert["status"] in frm and can(staff, cap)],
        "can_reopen": alert["status"] == "resolved" and can(staff, "alert_verify"),
        "can_assign": can(staff, "alert_work") and alert["status"] != "resolved",
    }


class ActionRequest(BaseModel):
    action: str
    note: Optional[str] = None


@router.post("/alerts/{alert_id}/action")
def alert_action(alert_id: int, payload: ActionRequest, staff=Depends(current_staff)):
    alert = require_alert_in_scope(staff, alert_id)
    if payload.action not in alert_engine.TRANSITIONS:
        raise HTTPException(status_code=400, detail="Unknown action.")
    require(staff, alert_engine.TRANSITIONS[payload.action][2])
    try:
        alert_engine.transition(alert, payload.action, payload.note or "", staff)
    except alert_engine.WorkflowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


class ReopenRequest(BaseModel):
    note: str


@router.post("/alerts/{alert_id}/reopen")
def reopen_alert(alert_id: int, payload: ReopenRequest, staff=Depends(current_staff)):
    require(staff, "alert_verify")
    require_alert_in_scope(staff, alert_id)
    if not payload.note.strip():
        raise HTTPException(status_code=400, detail="Say why the alert is being reopened.")
    if not db.reopen(alert_id, payload.note.strip(), staff):
        raise HTTPException(status_code=400, detail="Only resolved alerts can be reopened.")
    notify.alert_raised(alert_id, kind="alert_created", extra=f"Reopened by {staff['name']}: {payload.note.strip()}")
    return {"ok": True}


class AssignRequest(BaseModel):
    owner_staff_id: Optional[int] = None
    due_date: Optional[date] = None


@router.post("/alerts/{alert_id}/assign")
def assign_alert(alert_id: int, payload: AssignRequest, staff=Depends(current_staff)):
    require(staff, "alert_work")
    alert = require_alert_in_scope(staff, alert_id)
    if payload.owner_staff_id:
        owner = db.get_staff(payload.owner_staff_id)
        if not owner or not owner["active"] or (owner["college_id"] and owner["college_id"] != alert["college_id"]):
            raise HTTPException(status_code=400, detail="Choose an active staff member from this college.")
    db.assign(alert_id, payload.owner_staff_id, payload.due_date, staff)
    return {"ok": True}


@router.post("/alerts/{alert_id}/evidence")
async def add_evidence(alert_id: int, note: str = Form(""), inspection_id: Optional[int] = Form(None),
                       photo: Optional[UploadFile] = File(None), staff=Depends(current_staff)):
    """Proof of a fix: a photo, a follow-up inspection, or both (with a note)."""
    require(staff, "alert_work")
    alert = require_alert_in_scope(staff, alert_id)
    if inspection_id:
        insp = db.get_inspection(inspection_id)
        if not insp or insp["mess_id"] != alert["mess_id"]:
            raise HTTPException(status_code=400, detail="That inspection isn't for this mess hall.")
    if not photo and not inspection_id and not note.strip():
        raise HTTPException(status_code=400, detail="Add a photo, a follow-up inspection, or a note.")
    photo_path = await photos.save_upload(photo, "evidence") if photo else None
    kind = "photo" if photo_path else ("inspection" if inspection_id else "note")
    evidence_id = db.add_evidence(alert_id, kind, note.strip() or None, staff, photo_path, inspection_id)
    db.log_activity("alert_evidence", f"{staff['name']} added {kind} evidence to alert #{alert_id}",
                    mess_id=alert["mess_id"], ref_id=alert_id, details={"actor": staff["name"], "note": note.strip()})
    return {"ok": True, "id": evidence_id}


# ---------- Exports ----------

def _csv(filename, header, rows):
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel opens UTF-8 (₹, Hindi, emoji) correctly
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/complaints.csv")
def export_complaints(college_id: Optional[int] = None, mess_id: Optional[int] = None, days: Optional[int] = 90,
                      staff=Depends(current_staff)):
    require(staff, "export")
    college_id, mess_id = scoped_college(staff, college_id), scoped_mess(staff, mess_id)
    rows, _ = db.search_complaints(college_id, mess_id, _since(days), limit=100000)
    return _csv("complaints.csv",
                ["id", "created_at_utc", "college", "mess_hall", "category", "meal", "dish", "status", "reporter",
                 "description", "staff_response"],
                [[c["id"], c["created_at"], c["college_name"], c["mess_name"], c["category"], c["meal"], c["dish"],
                  c["status"], complaint_view(c)["reporter"], c["description"], c["staff_response"]] for c in rows])


@router.get("/export/alerts.csv")
def export_alerts(college_id: Optional[int] = None, staff=Depends(current_staff)):
    require(staff, "export")
    college_id = scoped_college(staff, college_id)
    rows, _ = db.search_alerts(college_id=college_id, mess_id=scoped_mess(staff, None))
    return _csv("alerts.csv",
                ["id", "created_at_utc", "college", "mess_hall", "source", "level", "status", "owner", "due_date",
                 "reason", "resolved_at_utc", "resolution_notes", "reopened_count"],
                [[a["id"], a["created_at"], a["college_name"], a["mess_name"], a["source"], a["level"], a["status"],
                  a["owner_name"], a["due_date"], a["reason"], a["resolved_at"], a["resolution_notes"],
                  a["reopened_count"]] for a in rows])


@router.get("/export/inspections.csv")
def export_inspections(college_id: Optional[int] = None, staff=Depends(current_staff)):
    require(staff, "export")
    college_id = scoped_college(staff, college_id)
    rows, _ = db.list_inspections(college_id=college_id, mess_id=scoped_mess(staff, None), limit=100000)
    return _csv("inspections.csv",
                ["id", "created_at_utc", "mess_hall", "inspector", "score", "verified_onsite", "failed_items",
                 "general_notes"],
                [[i["id"], i["created_at"], i["mess_name"], i["inspector_name"], i["score"], bool(i["verified_onsite"]),
                  "; ".join(f["text"] for f in i["summary"]["failed_items"]), i["general_notes"]] for i in rows])


# ---------- In-app "my work" counts ----------

@router.get("/my-work")
def my_work(staff=Depends(current_staff)):
    """What needs this person's attention right now — shown as badges in the
    staff app, so nobody depends on email to know there's work waiting."""
    college_id, mess_id = scoped_college(staff, None), scoped_mess(staff, None)
    out = {}

    def scope_sql(college_col, mess_col):
        clauses, params = "", []
        if college_id:
            clauses += f" AND {college_col} = %s"
            params.append(college_id)
        if mess_id:
            clauses += f" AND {mess_col} = %s"
            params.append(mess_id)
        return clauses, params

    if can(staff, "alert_work"):
        out["alerts_assigned_to_me"] = db.fetch_one(
            "SELECT COUNT(*) AS n FROM alerts WHERE owner_staff_id = %s AND resolved = 0", (staff["id"],))["n"]
        where, params = scope_sql("m.college_id", "a.mess_id")
        out["alerts_untouched"] = db.fetch_one(
            "SELECT COUNT(*) AS n FROM alerts a JOIN mess_halls m ON a.mess_id = m.id WHERE a.status = 'open'" + where,
            params)["n"]
    if can(staff, "alert_verify"):
        where, params = scope_sql("m.college_id", "a.mess_id")
        out["fixes_to_verify"] = db.fetch_one(
            "SELECT COUNT(*) AS n FROM alerts a JOIN mess_halls m ON a.mess_id = m.id WHERE a.status = 'fixed'" + where,
            params)["n"]
    if can(staff, "respond"):
        where, params = scope_sql("c.college_id", "c.mess_id")
        out["complaints_unanswered"] = db.fetch_one(
            "SELECT COUNT(*) AS n FROM complaints c WHERE c.status = 'received' "
            "AND c.created_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY" + where, params)["n"]
    if can(staff, "inspect"):
        today = date.today()
        rows = db.overview(college_id, mess_id)
        schedule = db.list_schedule(college_id, mess_id, assigned_staff_id=staff["id"])
        out["inspections_due"] = sum(
            1 for r in rows
            if r["last_inspected_at"] is None
            or min(d for d in (r["scheduled_due"], r["interval_due"]) if d) <= today
        )
        out["inspections_assigned"] = len(schedule)
    if can(staff, "compliance_edit"):
        out["compliance_expiring"] = len(db.compliance.list_documents(college_id, mess_id, expiring_within_days=30))
    return out
