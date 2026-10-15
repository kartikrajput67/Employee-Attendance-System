# Architectural Decisions & Design Answers

### 1. Indexes Created and Why
We created compound and single-field indexes on startup idempotently:
- `{"emp_code": 1, "date": 1}` (Unique): Ensures race-safety against duplicate daily attendance entries and accelerates daily lookups.
- `{"emp_code": 1}`: Optimizes employee lookups and aggregation lookups.
- `{"date": 1}` and `{"employee_info.department": 1}`: Speeds up filtering for daily summaries, trends, and department aggregation pipelines over large volumes of logs.

### 2. Concurrent Identical Punch-Ins
When two identical punch-ins arrive simultaneously, MongoDB's unique compound index constraint `(emp_code, date)` guarantees atomicity at the database level. The first request successfully inserts the record, while the second request triggers a duplicate key error (`DuplicateKeyError`), which our code catches to safely return a `409 Conflict` response.

### 3. Leaderboard Ties at the Cutoff
For the late leaderboard aggregation, ties are handled using standard ranking where ties share a rank and the next rank is skipped (e.g., 1, 2, 2, 4), sorted deterministically by `emp_code`. The `limit` stage is strictly applied *after* sorting and ranking so that all tied employees at the boundary are included correctly.

### 4. Department Summary Headcount for Employees with No Logs
The department summary aggregation uses a left-outer join (`$lookup` from `employees` to `attendance_logs`) combined with date/headcount matching rules. This ensures that employees who have joined on or before the period end are properly counted in the headcount metrics, even if they have zero attendance logs for that period.

### 5. Changes for 100x Data Scale
To scale the system to 100 times the data volume (millions of records):
- Implement time-series collections or partitioned sharding on `date` and `emp_code`.
- Add an asynchronous worker queue (such as Celery or Redis RQ) for heavy analytics pipelines to offload heavy aggregation computations from blocking request threads.
- Introduce Redis caching layer for frequently accessed read-heavy endpoints like department summaries and leaderboards.