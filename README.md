# Employee Attendance & Analytics API

A robust backend service built with **FastAPI** and **MongoDB** for managing employee profiles, tracking daily attendance lifecycles, and running high-performance HR analytics aggregations.

## Tech Stack
- **Python 3.11+**
- **FastAPI**
- **PyMongo (MongoDB 6.0+)**

---

## Prerequisites & Installation

1. **Clone the Repository:**
   ```bash
   git clone <your-repository-url>
   cd <repository-folder>
   ```

2. **Create and Activate a Virtual Environment:**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Configuration & Environment Variables
The application reads database configuration directly from environment variables, prioritizing real environment variables over local configurations. Create a `.env` file in the root directory for local testing:

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

## Running the Application
Start the server using uvicorn from the repository root:

```bash
uvicorn app.main:app --port 8000 --reload
```

- **Interactive API Docs (Swagger UI):** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/health

## Repository Structure
- `app/main.py`: Core application code, route definitions, and idempotent index creation on startup.
- `requirements.txt`: Project dependencies.
- `openapi.yaml`: Official contract specification.
- `REVIEW.md`: Starter code review, identified defects, and fixes (Part A).
- `DECISIONS.md`: Architectural decisions and design answers (Part C).
