import os
import sqlite3
import logging
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv
from passlib.context import CryptContext

# --- Imports for Gemini AI Integration ---
from google import genai
from google.genai import types
from google.genai.errors import APIError

import re  # for SQL pattern checks

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_FILE = os.getenv("DATABASE_FILE", "university.db")

# --- Password Hashing Setup (NOT USED FOR AUTH) ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- AI / Gemini initialization ---
client: Optional[genai.Client] = None
GEMINI_MODEL = "gemini-2.5-flash-lite"

try:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        pass

    client = genai.Client(api_key=GEMINI_API_KEY)
    print(f"✅ INFO: Gemini AI integration initialized with model: {GEMINI_MODEL}.")

except (ValueError, APIError) as e:
    print(f"⚠️ WARNING: Gemini AI integration disabled. Error: {e}")
    client = None
# conn = sqlite3.connect(DATABASE_FILE)
# time = conn.execute("SELECT * from time_slot")
# print(time)
# --- FastAPI setup ---
app = FastAPI(
    title="University Registration System API",
    description="A comprehensive API for university course registration, user management, and AI-powered database queries.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
#  Read-only AI SQL Guard (from your friend, merged in)
# -------------------------------------------------------------------
def ai_sql_guard(sql: str):
    """
    Extra protection on the *generated SQL*:
    - Only allow SELECT
    - Block DML / DDL keywords
    - Block multi-statement tricks with ';'
    """
    sql_clean = sql.lower().strip()

    # If not SELECT → block
    if not sql_clean.startswith("select"):
        return {
        "blocked": True,
        "message": (
            "❌ The AI Assistant is **read-only**.\n"
            "Only SELECT queries are allowed. Please use the admin interface for INSERT / UPDATE / DELETE."
        ),
        "sql": sql,
        }

    # Block harmful keywords anywhere
    forbidden = ["insert", "update", "delete", "create", "drop", "alter", "truncate"]
    for word in forbidden:
        if word in sql_clean:
            return {
                "blocked": True,
                "message": (
                    f"❌ The AI Assistant cannot run `{word.upper()}` commands.\n"
                    "Use the admin dashboard for write or schema operations."
                ),
                "sql": sql,
            }

    # Block multi-statement (semicolon misuse, except optional trailing ;)
    if ";" in sql_clean.strip(";"):
        return {
            "blocked": True,
            "message": "❌ Multiple SQL statements are not allowed in the AI Assistant.",
            "sql": sql,
        }

    return {"blocked": False}


@contextmanager
def get_db_connection():
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        logger.debug("Database connection established")
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")
    finally:
        if conn:
            conn.close()
            logger.debug("Database connection closed")


# --- AI SQL Safety & Row-Level Access Helpers ---

SENSITIVE_TABLES = {"login_credentials"}
SENSITIVE_COLUMNS_ALWAYS = {"password"}

# Column-level rules (can be extended later)
SENSITIVE_COLUMNS_BY_ROLE = {
    "student": {"salary"},   # students cannot see any salary info
    "teacher": set(),        # teachers can see their own salary (row-level filtered below)
    "admin": set(),          # admins see everything except DML & passwords table
}


def is_sql_safe_for_role(sql: str, role: str, username: str) -> Optional[str]:
    """
    Static checks *before* executing the generated SQL.
    Returns an error message if disallowed, or None if OK.
    """
    sql_upper = sql.upper()
    role_lower = role.lower()

    # Helper for student-specific message
    def student_denied_message() -> str:
        return (
            "❌ Access Denied: As a student, you are not authorized to view this information. "
            "You can only ask about your own courses, grades, schedule, credits, or advisor."
        )

    # 1. Block access to sensitive tables (like login_credentials)
    for tbl in SENSITIVE_TABLES:
        if re.search(rf"\b{tbl}\b", sql, flags=re.IGNORECASE):
            if role_lower == "student":
                return student_denied_message()
            return f"Access to table '{tbl}' is not allowed through the AI assistant."

    # 2. Block always-sensitive columns (like password)
    for col in SENSITIVE_COLUMNS_ALWAYS:
        if re.search(rf"\b{col}\b", sql, flags=re.IGNORECASE):
            if role_lower == "student":
                return student_denied_message()
            return f"Access to column '{col}' is not allowed through the AI assistant."

    # 3. Role-based sensitive columns (e.g., students can't see salary)
    blocked_cols = SENSITIVE_COLUMNS_BY_ROLE.get(role_lower, set())
    for col in blocked_cols:
        if re.search(rf"\b{col}\b", sql, flags=re.IGNORECASE):
            if role_lower == "student":
                return student_denied_message()
            return f"Users with role '{role}' are not allowed to query column '{col}'."

    return None


def post_filter_results_for_role(
    results: List[Dict[str, Any]], role: str, username: str
) -> List[Dict[str, Any]]:
    """
    Row-level filtering *after* executing the SQL.
    - Admin: no filtering.
    - Teacher: can see all students; only themselves from instructor-related rows.
    - Student: can only see their own student-related rows.
    """

    role_l = role.lower()
    if role_l == "admin":
        return results

    filtered: List[Dict[str, Any]] = []

    for row in results:
        r = dict(row)  # make sure it's mutable
        keep = True

        if role_l == "student":
            # If there's a generic ID, only allow if it's their own ID
            if "ID" in r:
                val = r["ID"]
                if isinstance(val, str) and val != username:
                    keep = False

            # For advisor table: s_ID is the student
            if "s_ID" in r and r["s_ID"] != username:
                keep = False

        elif role_l == "teacher":
            # Teachers can see all students, but only themselves as instructor
            if "ID" in r:
                val = r["ID"]
                if isinstance(val, str) and val.startswith("T") and val != username:
                    keep = False

            # For advisor table: i_ID is the instructor
            if "i_ID" in r:
                val = r["i_ID"]
                if isinstance(val, str) and val.startswith("T") and val != username:
                    keep = False

        if keep:
            filtered.append(r)

    return filtered


# --- Helper Functions ---

def check_section_conflicts(conn, course_id, sec_id, semester, year, building, room_number, time_slot_id, teacher_id):
    """Checks for room and teacher time conflicts before adding a section."""
    if not time_slot_id:
        return None  # No time slot, no time conflict possible

    # 1. Room Conflict Check (Same room, same time slot)
    room_conflict = conn.execute("""
        SELECT course_id, sec_id FROM section
        WHERE semester=? AND year=? AND building=? AND room_number=? AND time_slot_id=?
          AND course_id != ? AND sec_id != ?
    """, (semester, year, building, room_number, time_slot_id, course_id, sec_id)).fetchone()
    if room_conflict:
        return f"Room Conflict: {building} {room_number} is already booked for {room_conflict['course_id']}-{room_conflict['sec_id']}."

    # 2. Teacher Schedule Conflict Check (Same teacher, same time slot)
    if teacher_id:
        teacher_conflict = conn.execute("""
            SELECT T.course_id, T.sec_id FROM teaches T
            JOIN section S ON T.course_id=S.course_id AND T.sec_id=S.sec_id AND T.semester=S.semester AND T.year=S.year
            WHERE T.ID=? AND S.semester=? AND S.year=? AND S.time_slot_id=?
              AND T.course_id != ? AND T.sec_id != ?
        """, (teacher_id, semester, year, time_slot_id, course_id, sec_id)).fetchone()
        if teacher_conflict:
            return f"Teacher Schedule Conflict: Teacher {teacher_id} is already assigned to teach {teacher_conflict['course_id']}-{teacher_conflict['sec_id']} at this time."

    return None


# --- Pydantic Schemas ---

class LoginSchema(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)


class RegisterSchema(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    full_name: str = Field(..., min_length=2, max_length=120)

    password: str = Field(..., min_length=6, max_length=100)
    email: str = Field(..., min_length=3, max_length=200)
    phone: str = Field(..., min_length=3, max_length=50)
    city: str = Field(..., min_length=1, max_length=100)
    zip: str = Field(..., min_length=1, max_length=20)

    role: str = Field(default="student")  # student / teacher

    # student-only
    major: Optional[str] = None
    level_of_study: Optional[str] = None  # grad / undergrad

    # teacher-only
    ssn: Optional[str] = None
    experience: Optional[int] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str):
        if v not in ("student", "teacher"):
            raise ValueError("role must be student or teacher")
        return v

    @field_validator("level_of_study")
    @classmethod
    def validate_level(cls, v: Optional[str]):
        if v is None:
            return v
        if v not in ("grad", "undergrad"):
            raise ValueError("level_of_study must be grad or undergrad")
        return v


class ApproveSchema(BaseModel):

    username: str = Field(..., min_length=1, max_length=50)


class UpdatePasswordSchema(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=100)


class AIQuerySchema(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    role: str = Field(...)
    query: str = Field(..., min_length=1, max_length=1000)


class EnrollSchema(BaseModel):
    student_id: str = Field(..., min_length=1, max_length=20)
    course_id: str = Field(..., min_length=1, max_length=20)
    sec_id: str = Field(..., min_length=1, max_length=10)
    semester: str = Field(default="Fall")
    year: int = Field(default=2025, ge=2000, le=2100)


@field_validator('semester')
@classmethod
def validate_semester(cls, v):
    allowed = ("Fall", "Winter", "Spring", "Summer")
    if v not in allowed:
        raise ValueError(f"Semester must be one of: {', '.join(allowed)}")
    return v


class DropSchema(BaseModel):
    student_id: str = Field(...)
    course_id: str = Field(...)
    sec_id: str = Field(...)
    semester: str = Field(default="Fall")
    year: int = Field(default=2025)


class RemoveAccessSchema(BaseModel):
    username: str = Field(...)


class CourseSchema(BaseModel):
    course_id: str = Field(..., max_length=10)
    title: str = Field(..., max_length=50)
    dept_name: str = Field(..., max_length=20)
    credits: int = Field(..., ge=1, le=4)


class CourseUpdateSchema(BaseModel):  # NEW
    course_id: str
    title: str = Field(..., max_length=50)
    dept_name: str = Field(..., max_length=20)
    credits: int = Field(..., ge=1, le=4)


class SectionSchema(BaseModel):
    course_id: str = Field(..., max_length=10)
    sec_id: str = Field(..., max_length=10)
    semester: str = Field(default="Fall")
    year: int = Field(default=2025)
    building: str = Field(..., max_length=15)
    room_number: str = Field(..., max_length=7)
    capacity: int = Field(default=30, ge=1)
    time_slot_id: Optional[str] = Field(None)
    teacher_id: Optional[str] = Field(None)


class StudentUpdateSchema(BaseModel):  # NEW
    id: str
    name: str = Field(..., max_length=100)
    dept_name: str = Field(..., max_length=20)
    tot_cred: int = Field(..., ge=0)


class InstructorUpdateSchema(BaseModel):  # NEW
    id: str
    name: str = Field(..., max_length=100)
    dept_name: str = Field(..., max_length=20)
    salary: float = Field(..., ge=29000)


# --- Endpoints (login / register / etc.) ---

@app.post("/login", summary="User Login")
def login(credentials: LoginSchema):
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT username, role, approved, password FROM login_credentials WHERE username=?",
                (credentials.username,)
            )
            user = cursor.fetchone()

            if not user:
                return {"status": "fail", "message": "Invalid credentials"}

            if credentials.password != user["password"]:
                return {"status": "fail", "message": "Invalid credentials"}

            if user["role"] == "admin" or user["approved"] == 1:
                return {"status": "success", "role": user["role"]}
            else:
                return {"status": "fail", "message": "User not approved yet"}
    except Exception:
        raise HTTPException(status_code=500, detail="Login failed due to server error")

@app.get("/departments")
async def get_departments():
    conn = sqlite3.connect(DATABASE_FILE)
    rows = conn.execute("SELECT dept_name FROM department")
    return {
        "status": "success",
        "departments": [r[0] for r in rows]   # <-- FIXED
    }



@app.post("/register", summary="User Registration")
def register_user(data: RegisterSchema):
    # Student registers -> can login immediately
    # Teacher registers -> pending until admin approval
    approved_status = 1 if data.role == "student" else 0

    with get_db_connection() as conn:
        conn.execute("BEGIN")
        try:
            # username exists?
            exists = conn.execute(
                "SELECT 1 FROM login_credentials WHERE username=?",
                (data.username,)
            ).fetchone()
            if exists:
                raise HTTPException(status_code=400, detail="Username already exists")

            # store login
            conn.execute(
                "INSERT INTO login_credentials(username, password, role, approved) VALUES (?,?,?,?)",
                (data.username, data.password, data.role, approved_status)
            )

            # store extended registration profile
            conn.execute(
                """
                INSERT INTO users(
                    username, role, full_name, email, phone, city, zip,
                    major, level_of_study, ssn, experience
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    data.username, data.role, data.full_name, data.email, data.phone,
                    data.city, data.zip, data.major, data.level_of_study, data.ssn, data.experience
                )
            )

            # If student: create academic record now (simple default dept = major or 'CS')
            if data.role == "student":
                dept = (data.major or "CS").strip() or "CS"
                conn.execute(
                    "INSERT OR IGNORE INTO student(ID, name, dept_name, tot_cred) VALUES (?,?,?,0)",
                    (data.username, data.full_name, dept)
                )

            # If teacher: do NOT create instructor row until approval

            conn.commit()

            if data.role == "student":
                return {"status": "success", "message": "Student registered successfully. You can login now."}
            return {"status": "success", "message": "Instructor registration submitted. Waiting for admin approval."}

        except HTTPException:
            conn.execute("ROLLBACK")
            raise
        except sqlite3.Error as e:
            conn.execute("ROLLBACK")
            logger.error(f"Registration DB error: {e}")
            raise HTTPException(status_code=500, detail="Registration failed due to server error")


@app.post("/approve", summary="Approve User")
def approve_user(data: ApproveSchema):
    """Admin approves a pending teacher (and can approve students too)."""
    with get_db_connection() as conn:
        conn.execute("BEGIN")
        try:
            login_user = conn.execute(
                "SELECT username, role, approved FROM login_credentials WHERE username=?",
                (data.username,)
            ).fetchone()

            if not login_user:
                raise HTTPException(status_code=404, detail="User not found")

            if login_user["approved"] == 1:
                return {"status": "fail", "message": "User already approved"}

            profile = conn.execute(
                "SELECT role, full_name, major, level_of_study, ssn, experience "
                "FROM users WHERE username=?",
                (data.username,),
            ).fetchone()

            if not profile:
                raise HTTPException(status_code=404, detail="User registration record missing")

            # Only insert into academic tables on approval for teachers
            if login_user["role"] == "teacher":
                dept = (profile["major"] or "CS").strip() or "CS"
                conn.execute(
                    "INSERT OR IGNORE INTO instructor(ID, name, dept_name, salary) VALUES (?,?,?,30000)",
                    (data.username, profile["full_name"], dept),
                )

            # Mark approved
            conn.execute(
                "UPDATE login_credentials SET approved=1 WHERE username=?",
                (data.username,),
            )

            conn.commit()
            return {"status": "success", "message": f"User {data.username} approved successfully"}

        except HTTPException:
            conn.execute("ROLLBACK")
            raise
        except sqlite3.Error as e:
            conn.execute("ROLLBACK")
            logger.error(f"Approve DB error: {e}")
            raise HTTPException(status_code=500, detail="Approval failed due to server error")


@app.post("/reject", summary="Reject User")
def reject_user(data: ApproveSchema):
    with get_db_connection() as conn:
        conn.execute("BEGIN")
        try:
            cursor = conn.execute(
                "SELECT username, approved FROM login_credentials WHERE username=?",
                (data.username,)
            )
            user = cursor.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            if user["approved"] == -1:
                return {"status": "fail", "message": "User already rejected"}

            # Set approved = -1 for rejected status
            conn.execute(
                "UPDATE login_credentials SET approved=-1 WHERE username=?",
                (data.username,)
            )
            conn.commit()

            return {
                "status": "success",
                "message": f"User {data.username} rejected"
            }

        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(f"Error rejecting {data.username}: {e}")
            raise HTTPException(status_code=500, detail="Reject failed")


@app.post("/update_password")
def update_password(data: UpdatePasswordSchema):
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT password FROM login_credentials WHERE username=?",
            (data.username,)
        )
        user = cursor.fetchone()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if data.old_password != user["password"]:
            raise HTTPException(
                status_code=400,
                detail="Old password does not match"
            )

        new_password_plaintext = data.new_password

        conn.execute(
            "UPDATE login_credentials SET password=? WHERE username=?",
            (new_password_plaintext, data.username)
        )
        conn.commit()
    return {"status": "success", "message": "Password updated"}


@app.post("/user/remove", summary="Remove User Access")
def remove_user_access(data: RemoveAccessSchema):
    username = data.username
    with get_db_connection() as conn:
        conn.execute("BEGIN")
        try:
            cursor = conn.execute(
                "SELECT role FROM login_credentials WHERE username=?",
                (username,)
            )
            user = cursor.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="User not found.")

            role = user['role']

            conn.execute(
                "UPDATE login_credentials SET approved=0 WHERE username=?",
                (username,)
            )

            table_name = None
            if role == 'student':
                conn.execute("DELETE FROM student WHERE ID=?", (username,))
                table_name = "student"
            elif role == 'teacher':
                conn.execute("DELETE FROM instructor WHERE ID=?", (username,))
                table_name = "instructor"
            else:
                table_name = "admin (login credentials only)"

            conn.commit()
            logger.info(
                f"User {username} ({role}) access removed and primary record deleted."
            )
            return {
                "status": "success",
                "message": f"Access for {username} ({role}) removed and data deleted from {table_name}."
            }

        except sqlite3.Error as e:
            conn.execute("ROLLBACK")
            logger.error(f"Error removing user {username}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Database error during removal: {e}"
            )
        except HTTPException:
            conn.execute("ROLLBACK")
            raise


@app.get("/users")
def get_all_users():
    with get_db_connection() as conn:
        users = conn.execute(
            "SELECT username, role, approved FROM login_credentials"
        ).fetchall()
        return [dict(u) for u in users]


@app.get("/data/summary")
def get_system_summary():
    with get_db_connection() as conn:
        total_students = conn.execute(
            "SELECT COUNT(ID) FROM student"
        ).fetchone()[0] or 0
        total_teachers = conn.execute(
            "SELECT COUNT(ID) FROM instructor"
        ).fetchone()[0] or 0
        pending = conn.execute(
            "SELECT COUNT(username) FROM login_credentials WHERE approved=0 AND role != 'admin'"
        ).fetchone()[0] or 0
        total_courses_offered = conn.execute(
            "SELECT COUNT(DISTINCT course_id) FROM section WHERE semester='Fall' AND year=2025 AND time_slot_id IS NOT NULL"
        ).fetchone()[0] or 0
    return {
        "total_students": total_students,
        "total_teachers": total_teachers,
        "pending_approvals": pending,
        "total_courses_offered": total_courses_offered
    }


@app.get("/data/students", summary="Get All Students")
def get_all_students():
    with get_db_connection() as conn:
        students = conn.execute(
            "SELECT ID, name, dept_name, tot_cred FROM student"
        ).fetchall()
        login_map = {
            row['username']: dict(row)
            for row in conn.execute(
                "SELECT username, role, approved FROM login_credentials WHERE role='student'"
            ).fetchall()
        }

        results = []
        for s in students:
            s_dict = dict(s)
            login_info = login_map.get(
                s_dict['ID'],
                {'approved': 0, 'role': 'student'}
            )
            s_dict['approved'] = login_info['approved']
            results.append(s_dict)

        return results


@app.get("/data/instructors", summary="Get All Instructors")
def get_all_instructors():
    with get_db_connection() as conn:
        instructors = conn.execute(
            "SELECT ID, name, dept_name, salary FROM instructor"
        ).fetchall()
        login_map = {
            row['username']: dict(row)
            for row in conn.execute(
                "SELECT username, role, approved FROM login_credentials WHERE role='teacher'"
            ).fetchall()
        }

        results = []
        for i in instructors:
            i_dict = dict(i)
            login_info = login_map.get(
                i_dict['ID'],
                {'approved': 0, 'role': 'teacher'}
            )
            i_dict['approved'] = login_info['approved']
            results.append(i_dict)

        return results


# --- Admin CRUD: Courses / Students / Instructors ---

@app.post("/admin/course/add", summary="Admin: Add New Course (C)")
def add_new_course(data: CourseSchema):
    with get_db_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO course (course_id, title, dept_name, credits) VALUES (?, ?, ?, ?)",
                (data.course_id, data.title, data.dept_name, data.credits)
            )
            conn.commit()
            return {
                "status": "success",
                "message": f"Course {data.course_id} added successfully."
            }
        except sqlite3.IntegrityError as e:
            if "course.course_id" in str(e):
                raise HTTPException(
                    status_code=400,
                    detail="Course ID already exists."
                )
            if "course.dept_name" in str(e):
                raise HTTPException(
                    status_code=400,
                    detail="Department does not exist."
                )
            raise HTTPException(
                status_code=400,
                detail=f"Data integrity error: {e}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {e}"
            )


@app.post("/admin/course/update", summary="Admin: Update Course Details (U)")
def update_course_details(data: CourseUpdateSchema):
    with get_db_connection() as conn:
        try:
            cursor = conn.execute(
                "UPDATE course SET title=?, dept_name=?, credits=? WHERE course_id=?",
                (data.title, data.dept_name, data.credits, data.course_id)
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Course ID not found."
                )
            return {
                "status": "success",
                "message": f"Course {data.course_id} updated successfully."
            }
        except sqlite3.IntegrityError as e:
            if "course.dept_name" in str(e):
                raise HTTPException(
                    status_code=400,
                    detail="Department does not exist."
                )
            raise HTTPException(
                status_code=400,
                detail=f"Data integrity error: {e}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {e}"
            )


@app.post("/admin/course/delete", summary="Admin: Delete Course (D)")
def delete_course(data: CourseSchema):
    with get_db_connection() as conn:
        try:
            cursor = conn.execute(
                "DELETE FROM course WHERE course_id=?",
                (data.course_id,)
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Course ID not found."
                )
            return {
                "status": "success",
                "message": (
                    f"Course {data.course_id} deleted successfully. "
                    "All related sections and enrollments were removed."
                )
            }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {e}"
            )


@app.post("/admin/student/update", summary="Admin: Update Student Details (U)")
def update_student_details(data: StudentUpdateSchema):
    with get_db_connection() as conn:
        try:
            cursor = conn.execute(
                "UPDATE student SET name=?, dept_name=?, tot_cred=? WHERE ID=?",
                (data.name, data.dept_name, data.tot_cred, data.id)
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Student ID not found."
                )
            return {
                "status": "success",
                "message": f"Student {data.id} updated successfully."
            }
        except sqlite3.IntegrityError as e:
            if "student.dept_name" in str(e):
                raise HTTPException(
                    status_code=400,
                    detail="Department does not exist."
                )
            raise HTTPException(
                status_code=400,
                detail=f"Data integrity error: {e}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {e}"
            )


@app.post("/admin/student/delete", summary="Admin: Delete Student (D)")
def delete_student(data: RemoveAccessSchema):
    with get_db_connection() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "DELETE FROM login_credentials WHERE username=? AND role='student'",
                (data.username,)
            )
            cursor = conn.execute(
                "DELETE FROM student WHERE ID=?",
                (data.username,)
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Student ID not found."
                )
            return {
                "status": "success",
                "message": (
                    f"Student {data.username} and all related data "
                    "deleted successfully."
                )
            }
        except Exception as e:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {e}"
            )


@app.post("/admin/instructor/update", summary="Admin: Update Instructor Details (U)")
def update_instructor_details(data: InstructorUpdateSchema):
    with get_db_connection() as conn:
        try:
            cursor = conn.execute(
                "UPDATE instructor SET name=?, dept_name=?, salary=? WHERE ID=?",
                (data.name, data.dept_name, data.salary, data.id)
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Instructor ID not found."
                )
            return {
                "status": "success",
                "message": f"Instructor {data.id} updated successfully."
            }
        except sqlite3.IntegrityError as e:
            if "instructor.dept_name" in str(e):
                raise HTTPException(
                    status_code=400,
                    detail="Department does not exist."
                )
            raise HTTPException(
                status_code=400,
                detail=f"Data integrity error: {e}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {e}"
            )


@app.post("/admin/instructor/delete", summary="Admin: Delete Instructor (D)")
def delete_instructor(data: RemoveAccessSchema):
    with get_db_connection() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "DELETE FROM login_credentials WHERE username=? AND role='teacher'",
                (data.username,)
            )
            cursor = conn.execute(
                "DELETE FROM instructor WHERE ID=?",
                (data.username,)
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Instructor ID not found."
                )
            return {
                "status": "success",
                "message": (
                    f"Instructor {data.username} and all related data "
                    "deleted successfully."
                )
            }
        except Exception as e:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {e}"
            )


# --- Existing Data Endpoints ---

@app.get("/data/courses", summary="Get All Courses")
def get_all_courses():
    with get_db_connection() as conn:
        courses = conn.execute(
            "SELECT course_id, title, dept_name, credits FROM course"
        ).fetchall()
        return [dict(c) for c in courses]


@app.get("/data/sections", summary="Get All Sections (Fall 2025)")
def get_all_sections():
    with get_db_connection() as conn:
        sections = conn.execute("""
            SELECT S.course_id, S.sec_id, S.semester, S.year, S.building, S.room_number,
                   S.capacity, S.time_slot_id,
                   T.ID AS teacher_id, I.name AS teacher_name,
                   C.title, C.credits
            FROM section S
            LEFT JOIN teaches T ON 
                S.course_id = T.course_id AND
                S.sec_id = T.sec_id AND
                S.semester = T.semester AND
                S.year = T.year
            LEFT JOIN instructor I ON T.ID = I.ID
            JOIN course C ON S.course_id = C.course_id
            WHERE S.semester='Fall' AND S.year=2025
            ORDER BY S.course_id, S.sec_id
        """).fetchall()
        return [dict(s) for s in sections]


@app.post("/admin/section/add", summary="Admin: Add New Section")
def add_new_section(data: SectionSchema):
    if data.semester != 'Fall' or data.year != 2025:
        raise HTTPException(
            status_code=400,
            detail="Only 'Fall 2025' scheduling is currently supported."
        )

    with get_db_connection() as conn:
        conn.execute("BEGIN")
        try:
            conflict = check_section_conflicts(
                conn,
                data.course_id, data.sec_id,
                data.semester, data.year,
                data.building, data.room_number,
                data.time_slot_id, data.teacher_id
            )
            if conflict:
                raise HTTPException(status_code=409, detail=conflict)

            conn.execute("""
                INSERT INTO section (
                    course_id, sec_id, semester, year,
                    building, room_number, capacity, time_slot_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.course_id, data.sec_id,
                data.semester, data.year,
                data.building, data.room_number,
                data.capacity, data.time_slot_id
            ))
            teacher_id = data.teacher_id.split("-")[0]
            
            if teacher_id:
                teacher_check = conn.execute(
                    "SELECT ID FROM instructor WHERE ID=?",
                    (teacher_id,)
                ).fetchone()
                if not teacher_check:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Instructor ID {teacher_id} not found."
                    )

                conn.execute("""
                    INSERT INTO teaches (ID, course_id, sec_id, semester, year)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    teacher_id,
                    data.course_id, data.sec_id,
                    data.semester, data.year
                ))

            conn.commit()
            return {
                "status": "success",
                "message": f"Section {data.course_id}-{data.sec_id} scheduled successfully."
            }

        except sqlite3.IntegrityError as e:
            conn.execute("ROLLBACK")
            if "UNIQUE constraint failed" in str(e):
                raise HTTPException(
                    status_code=400,
                    detail="Section already exists for this semester/year."
                )
            raise HTTPException(
                status_code=400,
                detail=(
                    "Data integrity error (e.g., Course, Building, "
                    f"or Time Slot ID not found): {e}"
                )
            )
        except HTTPException:
            conn.execute("ROLLBACK")
            raise
        except Exception as e:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=500,
                detail=f"Internal database error: {e}"
            )


@app.get("/teacher/{teacher_id}/summary")
def get_teacher_summary(teacher_id: str):
    with get_db_connection() as conn:
        sections = conn.execute(
            "SELECT COUNT(*) FROM teaches WHERE ID=? AND semester='Fall' AND year=2025",
            (teacher_id,)
        ).fetchone()[0] or 0
        students = conn.execute("""
            SELECT COUNT(DISTINCT t.ID) FROM takes t
            JOIN teaches ts ON
                t.course_id=ts.course_id AND t.sec_id=ts.sec_id AND
                t.semester=ts.semester AND t.year=ts.year
            WHERE ts.ID=? AND ts.semester='Fall' AND ts.year=2025
        """, (teacher_id,)).fetchone()[0] or 0
    return {
        "sections_taught_fall_2025": sections,
        "total_students_taught_fall_2025": students
    }

@app.get("/teacher/{teacher_id}/schedule", summary="Teacher: View My Schedule (Fall 2025)")
def get_teacher_schedule(teacher_id: str):
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT
                S.course_id,
                S.sec_id,
                C.title,
                S.semester,
                S.year,
                S.building,
                S.room_number,
                S.time_slot_id,
                TS.day,
                TS.start_hr, TS.start_min,
                TS.end_hr, TS.end_min
            FROM teaches T
            JOIN section S ON
                T.course_id = S.course_id AND
                T.sec_id    = S.sec_id AND
                T.semester  = S.semester AND
                T.year      = S.year
            JOIN course C ON C.course_id = S.course_id
            LEFT JOIN time_slot TS ON TS.time_slot_id = S.time_slot_id
            WHERE T.ID = ?
              AND S.semester='Fall' AND S.year=2025
            ORDER BY
                CASE TS.day
                    WHEN 'Mon' THEN 1 WHEN 'Tue' THEN 2 WHEN 'Wed' THEN 3
                    WHEN 'Thu' THEN 4 WHEN 'Fri' THEN 5 WHEN 'Sat' THEN 6
                    WHEN 'Sun' THEN 7 ELSE 99
                END,
                TS.start_hr, TS.start_min,
                S.course_id, S.sec_id
        """, (teacher_id,)).fetchall()

        result = []
        for r in rows:
            start_time = None
            end_time = None
            if r["start_hr"] is not None:
                start_time = f"{int(r['start_hr']):02d}:{int(r['start_min']):02d}"
                end_time   = f"{int(r['end_hr']):02d}:{int(r['end_min']):02d}"

            result.append({
                "course_id": r["course_id"],
                "sec_id": r["sec_id"],
                "title": r["title"],
                "semester": r["semester"],
                "year": r["year"],
                "building": r["building"],
                "room_number": r["room_number"],
                "day": r["day"],
                "start_time": start_time,
                "end_time": end_time,
                "time_slot_id": r["time_slot_id"],
            })

        return result


@app.get("/student/{student_id}")
def get_student_info(student_id: str):
    with get_db_connection() as conn:
        info = conn.execute(
            "SELECT name, tot_cred, dept_name FROM student WHERE ID=?",
            (student_id,)
        ).fetchone()
        if not info:
            raise HTTPException(status_code=404, detail="Student ID not found")
        return dict(info)


@app.get("/student/{student_id}/courses")
def get_student_courses(student_id: str):
    with get_db_connection() as conn:
        courses = conn.execute("""
            SELECT
                t.course_id, c.title, c.credits, t.sec_id, t.semester, t.year, t.grade,
                s.building, s.room_number,
                ts.day, ts.start_hr, ts.start_min, ts.end_hr, ts.end_min
            FROM takes t
            JOIN course c ON t.course_id=c.course_id
            JOIN section s ON
                t.course_id=s.course_id AND
                t.sec_id=s.sec_id AND
                t.semester=s.semester AND
                t.year=s.year
            LEFT JOIN time_slot ts ON s.time_slot_id=ts.time_slot_id
            WHERE t.ID=?
            ORDER BY t.year DESC, t.semester DESC
        """, (student_id,)).fetchall()
        return [dict(row) for row in courses]


@app.post("/enroll", summary="Enroll Student")
def enroll_student(data: EnrollSchema):
    logger.info(
        f"Enrollment attempt: Student {data.student_id} "
        f"for course {data.course_id}-{data.sec_id} ({data.semester} {data.year})"
    )
    with get_db_connection() as conn:
        conn.execute("BEGIN")
        try:
            student = conn.execute(
                "SELECT ID, tot_cred FROM student WHERE ID=?",
                (data.student_id,)
            ).fetchone()
            if not student:
                raise HTTPException(
                    status_code=404,
                    detail="Student not found or not registered/approved."
                )

            already = conn.execute(
                "SELECT * FROM takes WHERE ID=? AND course_id=? "
                "AND sec_id=? AND semester=? AND year=?",
                (
                    data.student_id, data.course_id, data.sec_id,
                    data.semester, data.year
                )
            ).fetchone()
            if already:
                raise HTTPException(
                    status_code=400,
                    detail="Already enrolled in this section"
                )

            sec = conn.execute("""
                SELECT c.credits, s.time_slot_id, s.building, s.capacity,
                       (SELECT COUNT(*) FROM takes
                        WHERE course_id=s.course_id AND sec_id=s.sec_id
                          AND semester=s.semester AND year=s.year
                       ) AS enrollment_count
                FROM course c
                JOIN section s ON c.course_id=s.course_id
                WHERE s.course_id=? AND s.sec_id=? AND
                      s.semester=? AND s.year=?
            """, (
                data.course_id, data.sec_id,
                data.semester, data.year
            )).fetchone()
            if not sec:
                raise HTTPException(
                    status_code=404,
                    detail="Course or Section not found for the specified semester/year."
                )

            course_cred = sec["credits"]

            if sec['enrollment_count'] >= sec['capacity']:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Section is full. Current enrollment: "
                        f"{sec['enrollment_count']}/{sec['capacity']}."
                    )
                )

            current = conn.execute("""
                SELECT IFNULL(SUM(c.credits), 0)
                FROM takes t
                JOIN course c ON t.course_id=c.course_id
                WHERE t.ID=? AND t.semester=? AND t.year=? AND t.grade IS NULL
            """, (
                data.student_id, data.semester, data.year
            )).fetchone()[0]

            if current + course_cred > 12:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Credit limit exceeded. Currently registered: {current}, Max: 12."
                    )
                )

            existing = conn.execute("""
                SELECT s.time_slot_id, s.building
                FROM takes t
                JOIN section s ON
                    t.course_id=s.course_id AND
                    t.sec_id=s.sec_id AND
                    t.semester=s.semester AND
                    t.year=s.year
                WHERE t.ID=? AND t.semester=? AND t.year=? AND s.time_slot_id IS NOT NULL
            """, (
                data.student_id, data.semester, data.year
            )).fetchall()

            if sec["time_slot_id"]:
                for es in existing:
                    if (
                        es["time_slot_id"] == sec["time_slot_id"]
                        and es["building"] == sec["building"]
                    ):
                        raise HTTPException(
                            status_code=400,
                            detail="Schedule conflict detected (Same time/location)."
                        )

            conn.execute(
                "INSERT INTO takes (ID,course_id,sec_id,semester,year,grade) "
                "VALUES (?,?,?,?,?,NULL)",
                (
                    data.student_id, data.course_id, data.sec_id,
                    data.semester, data.year
                )
            )

            conn.commit()
            logger.info(
                f"Enrollment successful: Student {data.student_id} "
                f"enrolled in {data.course_id}-{data.sec_id}"
            )
            return {"status": "success", "message": "Enrollment successful"}

        except HTTPException:
            conn.execute("ROLLBACK")
            raise
        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(
                f"Enrollment error for student {data.student_id}: {e}"
            )
            raise HTTPException(
                status_code=500,
                detail="Enrollment failed: An internal error occurred."
            )


@app.post("/drop", summary="Drop Course")
def drop_course(data: DropSchema):
    logger.info(
        f"Drop attempt: Student {data.student_id} dropping "
        f"course {data.course_id}-{data.sec_id}"
    )
    with get_db_connection() as conn:
        conn.execute("BEGIN")
        try:
            takes_record = conn.execute(
                "SELECT * FROM takes WHERE ID=? AND course_id=? AND sec_id=? "
                "AND semester=? AND year=? AND grade IS NULL",
                (
                    data.student_id, data.course_id, data.sec_id,
                    data.semester, data.year
                )
            ).fetchone()

            if not takes_record:
                raise HTTPException(
                    status_code=404,
                    detail="Enrollment not found or course already graded."
                )

            conn.execute(
                "DELETE FROM takes WHERE ID=? AND course_id=? AND sec_id=? "
                "AND semester=? AND year=?",
                (
                    data.student_id, data.course_id, data.sec_id,
                    data.semester, data.year
                )
            )

            conn.commit()
            logger.info(
                f"Drop successful: Student {data.student_id} "
                f"dropped {data.course_id}-{data.sec_id}"
            )
            return {
                "status": "success",
                "message": (
                    f"Successfully dropped {data.course_id} section {data.sec_id}. "
                    "Your schedule is updated in real-time."
                )
            }

        except HTTPException:
            conn.execute("ROLLBACK")
            raise
        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(
                f"Drop error for student {data.student_id}: {e}"
            )
            raise HTTPException(
                status_code=500,
                detail="Drop failed due to server error."
            )


# -------------------------------------------------------------------
#   AI Endpoint – Read-only guard + role restrictions + custom empty
# -------------------------------------------------------------------
@app.post("/ai_query", summary="AI Database Query")
async def ai_query(data: AIQuerySchema):
    logger.info(
        f"AI query from user {data.username} ({data.role}): "
        f"{data.query[:100]}..."
    )

    # Basic DML keyword block on the natural language question
    dangerous_keywords = ['drop', 'delete', 'update', 'insert', 'alter', 'create', 'truncate']
    query_lower = data.query.lower()
    if any(keyword in query_lower for keyword in dangerous_keywords):
        logger.warning(
            f"AI query blocked: Potentially dangerous query from user {data.username}"
        )
        return {
            "status": "fail",
            "response": (
                "❌ AI Assistant is limited to **read-only** access.\n"
                "Write operations such as CREATE, UPDATE, DELETE, or ALTER "
                "are not allowed.\n"
                "Please use the admin dashboard for changes."
            ),
            "sql_query": "N/A"
        }

    if not client:
        logger.warning("AI query failed: Gemini client not initialized")
        return {
            "status": "fail",
            "response": "AI is currently disabled due to missing API key or connection error.",
            "sql_query": "N/A"
        }

    try:
        # 1. Get database schema for context (hide sensitive tables)
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table';"
            )
            tables = cursor.fetchall()
            visible_tables = [
                t for t in tables if t["name"] not in SENSITIVE_TABLES
            ]
            schema_info = "\n".join(
                [f"Table: {t['name']}\nSchema: {t['sql']}" for t in visible_tables]
            )

        # 2. First LLM call: Generate SQL
        sql_generation_prompt = f"""
You are an expert SQLite writer. Translate the user's natural-language question into a single, valid SQLite SELECT query.

User role: {data.role}
Username: {data.username}

SECURITY / ACCESS RULES (you MUST obey these):
- Only generate SELECT queries.
- Never query the table 'login_credentials'.
- Never select any column named 'password'.
- Admin can query about all teachers and all students.
- Teachers can query about ALL students, but ONLY about themselves from instructor-related tables.
- Students can only query about themselves:
  * When using tables with student IDs (student.ID, takes.ID, advisor.s_ID),
    always filter to the current student's ID = '{data.username}'.

If the user's question would violate these rules, generate a harmless SELECT that returns no rows, like:
  SELECT 'Access denied by AI policy' AS message WHERE 1=0;

Do not add any text, explanations, or markdown formatting (e.g., ```sql). Only output the SQL query itself.

Available tables and their schemas:
{schema_info}

User Question: {data.query}

SQL Query:
"""

        sql_response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=sql_generation_prompt,
            config=types.GenerateContentConfig(temperature=0.0)
        )

        sql = sql_response.text.strip()

        # --- Read-only guard from your friend ---
        guard = ai_sql_guard(sql)
        if guard["blocked"]:
            logger.warning(
                f"AI SQL guard blocked query for user {data.username}: {guard['message']}"
            )
            return {
                "status": "fail",
                "response": guard["message"],
                "sql_query": guard["sql"],
            }

        normalized_sql = sql.upper().strip()
        if not normalized_sql.startswith("SELECT"):
            logger.warning(
                f"AI query blocked: LLM generated non-SELECT query: {sql}"
            )
            return {
                "status": "fail",
                "response": "I can only execute SELECT queries for data retrieval.",
                "sql_query": sql,
            }

        # Static safety checks: tables/columns based on role
        error_msg = is_sql_safe_for_role(sql, data.role, data.username)
        if error_msg:
            logger.warning(
                f"AI query blocked for user {data.username} ({data.role}): {error_msg}"
            )
            return {
                "status": "fail",
                "response": error_msg,
                "sql_query": sql,
            }
        print(schema_info)
        # 3. Execute query
        with get_db_connection() as conn:
            cursor = conn.execute(sql)
            raw_results = [dict(row) for row in cursor.fetchall()]

        # 3b. Row-level filtering based on role and username
        results = post_filter_results_for_role(
            raw_results, data.role, data.username
        )

        result_str = "\n".join([str(row) for row in results])

        # 4. Second LLM call: Natural Language Response
        answer_synthesis_prompt = f"""
You are a helpful university assistant. Based ONLY on the SQL Query and the raw SQL Result provided below,
provide a concise, natural language answer to the user's Question.

If the result is empty, say '🚫 No matching records found — or you may not have permission to view this information.'

Question: {data.query}
SQL Query: {sql}
SQL Result: {result_str}
Answer:
"""

        answer_response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=answer_synthesis_prompt,
            config=types.GenerateContentConfig(temperature=0.2)
        )

        answer = answer_response.text.strip()

        logger.info(f"AI query successful for user {data.username}")
        return {
            "status": "success",
            "response": answer,
            "sql_query": sql
        }

    except sqlite3.Error as e:
        logger.error(f"SQL Execution error for user {data.username}: {e}")
        return {
            "status": "fail",
            "response": f"Database error during query execution: {e}",
            "sql_query": sql if 'sql' in locals() else 'N/A'
        }
    except APIError as e:
        logger.error(f"Gemini API error for user {data.username}: {e}")
        return {
            "status": "fail",
            "response": (
                "AI error: Failed to process query due to API issue. "
                f"Details: {e}"
            ),
            "sql_query": "N/A"
        }
    except Exception as e:
        logger.error(f"AI query error for user {data.username}: {e}")
        return {
            "status": "fail",
            "response": f"AI error: An internal error occurred. Details: {e}",
            "sql_query": "N/A"
        }


@app.get("/")
def root():
    return {"message": "University Registration System Backend Running."}
