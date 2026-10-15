"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def startup_db_indices():
    """Create all required indexes idempotently at startup."""
    db.employees.create_index("emp_code", unique=True)
    db.attendance_logs.create_index([("emp_code", 1), ("date", 1)], unique=True)
    db.attendance_logs.create_index("date")
    db.attendance_logs.create_index("status")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(hour=h, minute=m, second=0, microsecond=0)
    minutes = int((punch_in - start).total_seconds() / 60)
    return minutes if minutes > 10 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round((punch_out - punch_in).total_seconds() / 3600, 2)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None


class AttendanceUpdateIn(BaseModel):
    punch_in: Optional[int] = None   # Epoch timestamp in milliseconds
    punch_out: Optional[int] = None  # Epoch timestamp in milliseconds
    status: Optional[str] = None     # e.g., PRESENT, ABSENT, ON_LEAVE, LATE

# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="MongoDB is unavailable")

@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
    q = {}
    if department:
        q["department"] = department
    skip = (page - 1) * page_size  # Fixed pagination offset bug
    total = db.employees.count_documents(q)
    items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    ts = datetime.fromtimestamp(body.punched_at / 1000) if body.punched_at else datetime.now()
    d = ts.date().isoformat()
    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    res = db.attendance_logs.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    docs = list(db.attendance_logs.find(q))
    docs.sort(key=lambda d: d["date"], reverse=True)
    total = len(docs)
    page_docs = docs[(page - 1) * page_size : page * page_size]
    for d in page_docs:
        d["id"] = str(d.pop("_id"))
    return {"items": page_docs, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    # 1. Get employee for shift details
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    # 2. Determine punch-out timestamp (IST conversion)
    ts = datetime.fromtimestamp(body.punched_at / 1000, tz=timezone.utc) if body.punched_at else datetime.now(timezone.utc)
    
    # 3. Find active (unclosed) attendance record for this employee
    log = db.attendance_logs.find_one({"emp_code": body.emp_code, "punch_out": None})
    if not log:
        raise HTTPException(status_code=404, detail="No active punch-in found for punch-out")

    punch_in_time = log["punch_in"]
    record_date = log["date"]

    # 4. Compute Work Hours (R4: rounded to 2 decimals half-up)
    duration_seconds = (ts - punch_in_time).total_seconds()
    work_hours = round(duration_seconds / 3600, 2)

    # 5. Compute Overtime (R3: floor minutes from shift_end, min 30 mins)
    h, m = map(int, emp["shift_end"].split(":"))
    # Handle overnight shift end if shift_end <= shift_start
    shift_end_dt = datetime.fromisoformat(record_date).replace(hour=h, minute=m, second=0, tzinfo=IST)
    if emp["shift_end"] <= emp["shift_start"]:
        shift_end_dt += timedelta(days=1)
    
    overtime_diff = int((ts - shift_end_dt).total_seconds() / 60)
    overtime_minutes = overtime_diff if overtime_diff >= 30 else 0

    # 6. Compute Half Day (R5: true if work_hours < 4.50)
    half_day = work_hours < 4.50

    # 7. Update the document in MongoDB
    db.attendance_logs.update_one(
        {"_id": log["_id"]},
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day
            }
        }
    )

    # Return updated document
    updated_log = db.attendance_logs.find_one({"_id": log["_id"]})
    updated_log["id"] = str(updated_log.pop("_id"))
    return updated_log


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, body: AttendanceUpdateIn):
    # 1. Verify employee exists
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    # 2. Find existing attendance record for this date
    log = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not log:
        raise HTTPException(status_code=404, detail="Attendance record not found for this date")

    update_data = {}

    # 3. Handle punch_in update
    if body.punch_in is not None:
        new_punch_in = datetime.fromtimestamp(body.punch_in / 1000, tz=timezone.utc)
        update_data["punch_in"] = new_punch_in
        
        h, m = map(int, emp["shift_start"].split(":"))
        start_dt = new_punch_in.astimezone(IST).replace(hour=h, minute=m, second=0, microsecond=0)
        diff_secs = (new_punch_in.astimezone(IST) - start_dt).total_seconds()
        update_data["late_minutes"] = int(diff_secs // 60) if diff_secs > 600 else 0

    # 4. Handle punch_out update
    current_punch_in = update_data.get("punch_in", log["punch_in"])
    if body.punch_out is not None:
        new_punch_out = datetime.fromtimestamp(body.punch_out / 1000, tz=timezone.utc)
        update_data["punch_out"] = new_punch_out
        
        duration_secs = (new_punch_out - current_punch_in).total_seconds()
        work_hours = round(duration_secs / 3600, 2)
        update_data["work_hours"] = work_hours
        update_data["half_day"] = work_hours < 4.50

        # Overtime calculation
        h_end, m_end = map(int, emp["shift_end"].split(":"))
        shift_end_dt = datetime.fromisoformat(date).replace(hour=h_end, minute=m_end, second=0, tzinfo=IST)
        if emp["shift_end"] <= emp["shift_start"]:
            shift_end_dt += timedelta(days=1)
        
        ot_diff = int((new_punch_out.astimezone(IST) - shift_end_dt).total_seconds() / 60)
        update_data["overtime_minutes"] = ot_diff if ot_diff >= 30 else 0

    # 5. Handle status update
    if body.status is not None:
        update_data["status"] = body.status

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    # 6. Update MongoDB
    db.attendance_logs.update_one(
        {"_id": log["_id"]},
        {"$set": update_data}
    )

    updated_log = db.attendance_logs.find_one({"_id": log["_id"]})
    updated_log["id"] = str(updated_log.pop("_id"))
    return updated_log


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(emp_code: str, month: Optional[str] = None):
    # 1. Verify employee exists
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    # 2. Build match query (e.g., matching YYYY-MM prefix on date string)
    match_query = {"emp_code": emp_code}
    if month:
        match_query["date"] = {"$regex": f"^{month}"}

    # 3. Aggregation pipeline
    pipeline = [
        {"$match": match_query},
        {
            "$group": {
                "_id": "$emp_code",
                "total_days_logged": {"$sum": 1},
                "total_late_arrivals": {
                    "$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}
                },
                "total_overtime_minutes": {"$sum": "$overtime_minutes"},
                "total_half_days": {
                    "$sum": {"$cond": ["$half_day", 1, 0]}
                },
                "avg_work_hours": {"$avg": "$work_hours"}
            }
        },
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "total_days_logged": 1,
                "total_late_arrivals": 1,
                "total_overtime_minutes": 1,
                "total_half_days": 1,
                "avg_work_hours": {"$round": ["$avg_work_hours", 2]}
            }
        }
    ]

    result = list(db.attendance_logs.aggregate(pipeline))
    
    if not result:
        return {
            "emp_code": emp_code,
            "total_days_logged": 0,
            "total_late_arrivals": 0,
            "total_overtime_minutes": 0,
            "total_half_days": 0,
            "avg_work_hours": 0.0
        }
        
    return result[0]


@app.get("/analytics/departments/summary")
def department_analytics(department: Optional[str] = None):
    # Pipeline stages
    pipeline = []
    
    # Stage 1: Join attendance_logs with employees collection to get department info
    pipeline.append({
        "$lookup": {
            "from": "employees",
            "localField": "emp_code",
            "foreignField": "emp_code",
            "as": "employee_info"
        }
    })
    
    # Stage 2: Unpack the employee array
    pipeline.append({"$unwind": "$employee_info"})
    
    # Stage 3: Filter by department if provided in query params
    if department:
        pipeline.append({"$match": {"employee_info.department": department}})
        
    # Stage 4: Group by department and calculate metrics
    pipeline.append({
        "$group": {
            "_id": "$employee_info.department",
            "total_logs": {"$sum": 1},
            "avg_work_hours": {"$avg": "$work_hours"},
            "total_overtime_minutes": {"$sum": "$overtime_minutes"},
            "total_late_arrivals": {
                "$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}
            }
        }
    })
    
    # Stage 5: Clean up the output structure
    pipeline.append({
        "$project": {
            "_id": 0,
            "department": "$_id",
            "total_logs": 1,
            "avg_work_hours": {"$round": ["$avg_work_hours", 2]},
            "total_overtime_minutes": 1,
            "total_late_arrivals": 1
        }
    })

    # Run the aggregation pipeline against MongoDB
    results = list(db.attendance_logs.aggregate(pipeline)) 
    return {"department_summary": results}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(limit: int = 10):
    pipeline = [
        {"$match": {"late_minutes": {"$gt": 0}}},
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1}
            }
        },
        {"$sort": {"total_late_minutes": -1}},
        {"$limit": limit},
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee_info"
            }
        },
        {"$unwind": "$employee_info"},
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$employee_info.name",
                "department": "$employee_info.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        }
    ]
    results = list(db.attendance_logs.aggregate(pipeline))
    return {"leaderboard": results}


@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str):
    pipeline = [
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee_info"
            }
        },
        {"$unwind": "$employee_info"},
        {"$match": {"employee_info.department": department}},
        {
            "$group": {
                "_id": "$date",
                "total_present": {"$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}},
                "total_late": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}},
                "avg_work_hours": {"$avg": "$work_hours"}
            }
        },
        {"$sort": {"_id": 1}},
        {
            "$project": {
                "_id": 0,
                "date": "$_id",
                "total_present": 1,
                "total_late": 1,
                "avg_work_hours": {"$round": ["$avg_work_hours", 2]}
            }
        }
    ]
    results = list(db.attendance_logs.aggregate(pipeline))
    return {"department": department, "trend": results}


@app.get("/admin/explain/{endpoint:path}")
def admin_explain(endpoint: str):
    explanations = {
        "analytics/leaderboard/late": "Aggregates late arrivals across all employees, sorted by total late minutes descending.",
        "analytics/departments/summary": "Performs a department-level aggregation joining attendance logs with employees to compute total logs, average work hours, overtime, and late arrivals.",
        "attendance": "Fetches attendance logs with dynamic filtering (emp_code, date, status) and pagination support."
    }
    clean_path = endpoint.lstrip("/")
    explanation = explanations.get(clean_path, "No detailed explanation available for this endpoint.")
    return {
        "endpoint": f"/{clean_path}",
        "explanation": explanation
    }

# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
