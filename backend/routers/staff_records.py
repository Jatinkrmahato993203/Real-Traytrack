"""
routers/staff_records.py — inspections (submit, photos, history, schedule),
compliance records, notification log, protected photos, and the live
activity feed.
"""

import asyncio
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import alert_engine
import db
import photos
from broadcaster import Subscriber, broadcaster
from deps import (current_staff, page, require, require_mess_in_scope, scoped_college, scoped_mess,
                  session_token, staff_for_token)
import auth
from permissions import ACTIVITY_PREFIXES, can

router = APIRouter(prefix="/staff", tags=["staff"])


# ---------- Inspections ----------

class InspectionRequest(BaseModel):
    mess_id: int
    responses: dict                       # {item_key: {"result": "pass|fail|na", "note": "..."}}
    general_notes: Optional[str] = Field(None, max_length=2000)
    kitchen_code: Optional[str] = None    # from the QR/sign in the kitchen — proves the visit
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    client_ref: Optional[str] = Field(None, max_length=64)  # makes offline retries safe


@router.post("/inspections")
def submit_inspection(payload: InspectionRequest, staff=Depends(current_staff)):
    """Recorded under the signed-in account. Every checklist item must be
    answered Pass, Fail or N/A — nothing is assumed to pass."""
    require(staff, "inspect")
    require_mess_in_scope(staff, payload.mess_id)
    existing = db.find_by_client_ref(payload.client_ref)
    if existing:
        return {"inspection_id": existing["id"], "duplicate": True}
    try:
        inspection_id, alert_id, level, score, reason, verified = alert_engine.create_inspection(
            payload.mess_id, staff, payload.responses, (payload.general_notes or "").strip() or None,
            payload.kitchen_code, payload.latitude, payload.longitude, payload.client_ref,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"message": "Answer every checklist item (Pass, Fail or N/A).",
                                                     "missing": e.args[0]})
    return {"inspection_id": inspection_id, "alert_id": alert_id, "level": level, "score": score,
            "reason": reason, "verified_onsite": verified}


@router.post("/inspections/{inspection_id}/photos")
async def add_inspection_photo(inspection_id: int, item_key: Optional[str] = Form(None),
                               photo: UploadFile = File(...), staff=Depends(current_staff)):
    require(staff, "inspect")
    insp = db.get_inspection(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    require_mess_in_scope(staff, insp["mess_id"])
    if insp["inspector_id"] != staff["id"] and staff["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only the inspector who did this inspection can add photos.")
    path = await photos.save_upload(photo, "inspections")
    photo_id = db.add_inspection_photo(inspection_id, item_key, path)
    return {"ok": True, "id": photo_id}


def _can_see_inspections(staff):
    if not (can(staff, "view") or can(staff, "inspect")):
        raise HTTPException(status_code=403, detail="Your role doesn't allow this.")


@router.get("/inspections")
def list_inspections(college_id: Optional[int] = None, mess_id: Optional[int] = None, mine: bool = False,
                     offset: int = 0, limit: int = 50, staff=Depends(current_staff)):
    _can_see_inspections(staff)
    offset, limit = page(offset, limit)
    rows, total = db.list_inspections(scoped_college(staff, college_id), scoped_mess(staff, mess_id),
                                      staff["id"] if mine else None, offset, limit)
    return {"items": rows, "total": total, "offset": offset, "limit": limit}


@router.get("/inspections/{inspection_id}")
def inspection_detail(inspection_id: int, staff=Depends(current_staff)):
    _can_see_inspections(staff)
    insp = db.get_inspection(inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    require_mess_in_scope(staff, insp["mess_id"])
    insp["photos"] = [{"id": p["id"], "item_key": p["item_key"], "photo_url": db.complaint_photo_url(p["photo_path"])}
                      for p in insp["photos"]]
    return insp


@router.get("/inspection-overview")
def inspection_overview(college_id: Optional[int] = None, staff=Depends(current_staff)):
    """Every hall in scope with last inspection and when the next is due —
    overdue first. Scheduled visits assigned to the caller are flagged."""
    _can_see_inspections(staff)
    today = date.today()
    rows = db.overview(scoped_college(staff, college_id), scoped_mess(staff, None))
    schedule = db.list_schedule(scoped_college(staff, college_id), scoped_mess(staff, None))
    for r in rows:
        r["never_inspected"] = r["last_inspected_at"] is None
        # Earliest of a scheduled date and the regular interval; a hall never
        # inspected is due today.
        candidates = [d for d in (r["scheduled_due"], r["interval_due"]) if d] or [today]
        r["next_due"] = min(candidates)
        r["overdue"] = r["next_due"] < today or r["never_inspected"]
        r["assigned_to_me"] = any(s["mess_id"] == r["mess_id"] and s["assigned_staff_id"] == staff["id"] for s in schedule)
    rows.sort(key=lambda r: (not r["overdue"], not r["assigned_to_me"], r["next_due"] or today))
    return {"halls": rows, "schedule": schedule}


class ScheduleRequest(BaseModel):
    mess_id: int
    due_date: date
    assigned_staff_id: Optional[int] = None
    notes: Optional[str] = Field(None, max_length=500)


@router.post("/schedule")
def add_schedule(payload: ScheduleRequest, staff=Depends(current_staff)):
    require(staff, "schedule")
    mess = require_mess_in_scope(staff, payload.mess_id)
    if payload.assigned_staff_id:
        inspector = db.get_staff(payload.assigned_staff_id)
        if (not inspector or not inspector["active"] or not can(inspector, "inspect")
                or (inspector["college_id"] and inspector["college_id"] != mess["college_id"])):
            raise HTTPException(status_code=400, detail="Assign an active inspector from this college.")
    schedule_id = db.add_schedule(payload.mess_id, payload.due_date, payload.assigned_staff_id, payload.notes, staff)
    return {"ok": True, "id": schedule_id}


@router.delete("/schedule/{schedule_id}")
def delete_schedule(schedule_id: int, staff=Depends(current_staff)):
    require(staff, "schedule")
    item = db.get_schedule(schedule_id)
    if not item:
        raise HTTPException(status_code=404, detail="Not found.")
    scoped_college(staff, item["college_id"])
    if not db.delete_schedule(schedule_id):
        raise HTTPException(status_code=400, detail="Completed inspections can't be unscheduled.")
    return {"ok": True}


# ---------- Compliance ----------

@router.get("/compliance/types")
def compliance_types(staff=Depends(current_staff)):
    return [{"type": k, "label": v} for k, v in db.compliance.DOC_TYPES.items()]


@router.get("/compliance")
def list_compliance(college_id: Optional[int] = None, mess_id: Optional[int] = None,
                    expiring_within_days: Optional[int] = None, staff=Depends(current_staff)):
    require(staff, "view")
    docs = db.compliance.list_documents(scoped_college(staff, college_id), scoped_mess(staff, mess_id),
                                        expiring_within_days)
    for d in docs:
        d["file_url"] = db.complaint_photo_url(d.pop("file_path"))
    return docs


@router.post("/compliance")
async def add_compliance(college_id: int = Form(...), doc_type: str = Form(...), title: str = Form(...),
                         mess_id: Optional[int] = Form(None), person_name: Optional[str] = Form(None),
                         reference_no: Optional[str] = Form(None), issued_on: Optional[date] = Form(None),
                         expires_on: Optional[date] = Form(None), notes: Optional[str] = Form(None),
                         scan: Optional[UploadFile] = File(None), staff=Depends(current_staff)):
    """`scan` is a photo of the certificate (images only — re-encoded like
    every other upload)."""
    require(staff, "compliance_edit")
    scoped_college(staff, college_id)
    if mess_id:
        mess = require_mess_in_scope(staff, mess_id)
        if mess["college_id"] != college_id:
            raise HTTPException(status_code=400, detail="That mess hall belongs to a different college.")
    elif staff.get("mess_id"):
        mess_id = staff["mess_id"]
    if doc_type not in db.compliance.DOC_TYPES:
        raise HTTPException(status_code=400, detail="Unknown document type.")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Give the record a title.")
    if issued_on and expires_on and expires_on < issued_on:
        raise HTTPException(status_code=400, detail="Expiry date is before the issue date.")
    path = await photos.save_upload(scan, "compliance") if scan else None
    doc_id = db.compliance.add_document(college_id, mess_id, doc_type, title, (person_name or "").strip() or None,
                                        (reference_no or "").strip() or None, issued_on, expires_on,
                                        (notes or "").strip()[:500] or None, path, staff)
    return {"ok": True, "id": doc_id}


@router.delete("/compliance/{doc_id}")
def delete_compliance(doc_id: int, staff=Depends(current_staff)):
    require(staff, "compliance_edit")
    doc = db.compliance.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Not found.")
    scoped_college(staff, doc["college_id"])
    if doc["mess_id"]:
        scoped_mess(staff, doc["mess_id"])
    db.compliance.delete_document(doc_id, staff)
    return {"ok": True}


# ---------- Notifications ----------

@router.get("/notifications")
def list_notifications(college_id: Optional[int] = None, status: Optional[str] = None, offset: int = 0,
                       limit: int = 50, staff=Depends(current_staff)):
    require(staff, "view")
    offset, limit = page(offset, limit)
    rows, total = db.notifications.list_notifications(scoped_college(staff, college_id), None, status, offset, limit)
    return {"items": rows, "total": total, "offset": offset, "limit": limit}


# ---------- Protected photos ----------

def _photo_scope(kind, filename):
    """(college_id, mess_id) a stored photo belongs to."""
    lookup = {
        "complaints": db.get_complaint_by_photo,
        "inspections": db.get_inspection_by_photo,
        "evidence": db.get_evidence_by_photo,
        "compliance": db.compliance.get_document_by_file,
    }[kind]
    row = lookup(filename)
    return (row["college_id"], row["mess_id"]) if row else (None, None)


@router.get("/photos/{filename}")
def get_photo(filename: str, staff=Depends(current_staff)):
    """Photos for signed-in staff only, and only within their scope. The
    content type comes from the server, and nosniff + a sandboxing CSP stop
    a browser from ever treating the bytes as a page."""
    kind, path = photos.find(filename)
    college_id, mess_id = _photo_scope(kind, filename) if kind else (None, None)
    if not path or college_id is None:
        raise HTTPException(status_code=404, detail="Photo not found.")
    scoped_college(staff, college_id)
    if staff.get("mess_id") and mess_id and staff["mess_id"] != mess_id:
        raise HTTPException(status_code=403, detail="Your account is limited to another mess hall.")
    return FileResponse(path, media_type=photos.media_type(filename), headers={
        "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline",
        "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; sandbox",
    })


# ---------- Live activity ----------

def _activity_scope(staff, college_id, mess_id):
    if not (can(staff, "view") or can(staff, "view_complaints")):
        raise HTTPException(status_code=403, detail="Your role doesn't allow this.")
    return scoped_college(staff, college_id), scoped_mess(staff, mess_id), ACTIVITY_PREFIXES.get(staff["role"])


@router.get("/activity")
def activity(college_id: Optional[int] = None, mess_id: Optional[int] = None, event_type: Optional[str] = None,
             before_id: Optional[int] = None, limit: int = 100, staff=Depends(current_staff)):
    college_id, mess_id, prefixes = _activity_scope(staff, college_id, mess_id)
    return db.get_activity(before_id=before_id, college_id=college_id, mess_id=mess_id, event_type=event_type,
                           limit=max(1, min(limit, 500)), only_prefixes=prefixes)


AUTH_RECHECK_SECONDS = 15


@router.get("/activity/stream")
async def activity_stream(request: Request, after_id: int = 0, college_id: Optional[int] = None,
                          mess_id: Optional[int] = None):
    """Server-Sent Events. Auth is the normal Bearer header (the frontend
    streams with fetch, so the token never goes in a URL). The account is
    re-checked every few seconds, so revoking access ends the stream."""
    token = session_token(request, auth.STAFF_COOKIE)
    staff = staff_for_token(token)
    college_id, mess_id, prefixes = _activity_scope(staff, college_id, mess_id)
    backlog = await asyncio.to_thread(db.get_activity, after_id=after_id, college_id=college_id, mess_id=mess_id,
                                      limit=500, only_prefixes=prefixes)
    sub = Subscriber(college_id, mess_id, prefixes)
    broadcaster.subscribe(sub, backlog, after_id)

    async def events():
        loop = asyncio.get_event_loop()
        last_check = loop.time()
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                if loop.time() - last_check > AUTH_RECHECK_SECONDS:
                    last_check = loop.time()
                    try:
                        await asyncio.to_thread(staff_for_token, token)
                    except HTTPException:
                        yield "event: expired\ndata: {}\n\n"
                        return
                try:
                    row = await asyncio.wait_for(sub.queue.get(), timeout=15)
                    yield f"id: {row['id']}\nevent: activity\ndata: {json.dumps(row, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broadcaster.unsubscribe(sub)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
