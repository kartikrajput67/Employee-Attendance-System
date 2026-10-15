# REVIEW.md


## Summary of Defects & Fixes Found

1. **Time Zone and UTC/IST Mismatch**
   - **Where:** Helper functions handling timestamps.
   - **What was wrong:** The starter code treated naive datetimes or UTC datetimes inconsistently when matching calendar dates, causing off-by-date errors for evening shifts.
   - **Fix:** Explicitly converted all incoming epoch milliseconds to UTC, then converted to IST (`UTC+05:30`) for calendar date extraction (`%Y-%m-%d`).

2. **Missing Database Indexes**
   - **Where:** Database initialization startup event.
   - **What was wrong:** No indexes were created on startup, leading to severe performance degradation (`COLLSCAN`) when queried against 100,000+ attendance records.
   - **Fix:** Implemented idempotent index creation on startup for `emp_code`, `date`, and compound indexes `(emp_code, date)`.

3. **Pagination Offsets and Defaults**
   - **Where:** `GET /employees` and `GET /attendance` endpoints.
   - **What was wrong:** Pagination calculations lacked upper bounds on `page_size`, risking memory overload, and projection issues leaked MongoDB internal `_id` fields.
   - **Fix:** Added strict page size limiting (max 100) and projected away `_id` cleanly in query options.

4. **Race Conditions on Duplicate Punch-In**
   - **Where:** `POST /attendance/punch-in`
   - **What was wrong:** Checking for an existing record and inserting a new one was not atomic, allowing duplicate concurrent requests to slip through.
   - **Fix:** Relied on a unique compound index on `(emp_code, date)` and handled MongoDB duplicate key exceptions to safely return a `409 Conflict`.
