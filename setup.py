# setup.py (Corrected Version)

import sqlite3

DB_FILE = "university.db"

def create_tables(conn):
    cursor = conn.cursor()

    # Classroom
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS classroom(
        building TEXT,
        room_number TEXT,
        capacity INTEGER,
        PRIMARY KEY(building, room_number)
    )
    """)

    # Department
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS department(
        dept_name TEXT PRIMARY KEY,
        building TEXT,
        budget REAL CHECK(budget > 0)
    )
    """)

    # Course
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS course(
        course_id TEXT PRIMARY KEY,
        title TEXT,
        dept_name TEXT,
        credits INTEGER CHECK(credits > 0),
        FOREIGN KEY(dept_name) REFERENCES department(dept_name) ON DELETE SET NULL
    )
    """)

    # Instructor
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS instructor(
        ID TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dept_name TEXT,
        salary REAL CHECK(salary > 29000),
        FOREIGN KEY(dept_name) REFERENCES department(dept_name) ON DELETE SET NULL
    )
    """)

    # Section
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS section(
        course_id TEXT,
        sec_id TEXT,
        semester TEXT CHECK(semester IN ('Fall','Winter','Spring','Summer')),
        year INTEGER CHECK(year > 1701 AND year < 2100),
        building TEXT,
        room_number TEXT,
        capacity INTEGER DEFAULT 30,  -- <<< ADDED CAPACITY COLUMN HERE
        time_slot_id TEXT,
        PRIMARY KEY(course_id, sec_id, semester, year),
        FOREIGN KEY(course_id) REFERENCES course(course_id) ON DELETE CASCADE,
        FOREIGN KEY(building, room_number) REFERENCES classroom(building, room_number) ON DELETE SET NULL
    )
    """)

    # Teaches
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teaches(
        ID TEXT,
        course_id TEXT,
        sec_id TEXT,
        semester TEXT,
        year INTEGER,
        PRIMARY KEY(ID, course_id, sec_id, semester, year),
        FOREIGN KEY(course_id, sec_id, semester, year) REFERENCES section(course_id, sec_id, semester, year) ON DELETE CASCADE,
        FOREIGN KEY(ID) REFERENCES instructor(ID) ON DELETE CASCADE
    )
    """)

    # Student
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS student(
        ID TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dept_name TEXT,
        tot_cred INTEGER CHECK(tot_cred >=0),
        FOREIGN KEY(dept_name) REFERENCES department(dept_name) ON DELETE SET NULL
    )
    """)

    # Takes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS takes(
        ID TEXT,
        course_id TEXT,
        sec_id TEXT,
        semester TEXT,
        year INTEGER,
        grade TEXT,
        PRIMARY KEY(ID, course_id, sec_id, semester, year),
        FOREIGN KEY(course_id, sec_id, semester, year) REFERENCES section(course_id, sec_id, semester, year) ON DELETE CASCADE,
        FOREIGN KEY(ID) REFERENCES student(ID) ON DELETE CASCADE
    )
    """)

    # Advisor
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS advisor(
        s_ID TEXT PRIMARY KEY,
        i_ID TEXT,
        FOREIGN KEY(i_ID) REFERENCES instructor(ID) ON DELETE SET NULL,
        FOREIGN KEY(s_ID) REFERENCES student(ID) ON DELETE CASCADE
    )
    """)

    # Time Slot
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS time_slot(
        time_slot_id TEXT,
        day TEXT,
        start_hr INTEGER CHECK(start_hr>=0 AND start_hr<24),
        start_min INTEGER CHECK(start_min>=0 AND start_min<60),
        end_hr INTEGER CHECK(end_hr>=0 AND end_hr<24),
        end_min INTEGER CHECK(end_min>=0 AND end_min<60),
        PRIMARY KEY(time_slot_id, day, start_hr, start_min)
    )
    """)

    # Prerequisites
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS prereq(
        course_id TEXT,
        prereq_id TEXT,
        PRIMARY KEY(course_id, prereq_id),
        FOREIGN KEY(course_id) REFERENCES course(course_id) ON DELETE CASCADE,
        FOREIGN KEY(prereq_id) REFERENCES course(course_id)
    )
    """)

    # Login credentials table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS login_credentials(
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        role TEXT CHECK(role IN ('admin','student','teacher')),
        approved INTEGER DEFAULT 0
    )
    """)


    # User registration profile table (extended registration info)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        role TEXT CHECK(role IN ('student','teacher')) NOT NULL,
        full_name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT NOT NULL,
        city TEXT NOT NULL,
        zip TEXT NOT NULL,
        major TEXT,
        level_of_study TEXT CHECK(level_of_study IN ('grad','undergrad')),
        ssn TEXT,
        experience INTEGER CHECK(experience >= 0),
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(username) REFERENCES login_credentials(username) ON DELETE CASCADE
    )
    """)

    conn.commit()


def insert_sample_data(conn):
    cursor = conn.cursor()

    # ----------------- Departments -----------------
    departments = [
        ('CS', 'BldgA', 500000),
        ('EE', 'BldgB', 400000),
        ('ME', 'BldgC', 300000)
    ]
    cursor.executemany("INSERT OR IGNORE INTO department VALUES (?,?,?)", departments)

    # ----------------- Classrooms -----------------
    classrooms = [
        ('BldgA','101',30),('BldgA','102',30),('BldgA','103',30),('BldgA','104',30),('BldgA','105',30),
        ('BldgB','201',25),('BldgB','202',25),('BldgC','301',20),('BldgC','302',20),('BldgD','401',20),('BldgD','402',20)
    ]
    cursor.executemany("INSERT OR IGNORE INTO classroom VALUES (?,?,?)", classrooms)

    # ----------------- Instructors -----------------
    instructors = [
        ('T001','Alan Turing','CS',80000),('T002','Ada Lovelace','CS',75000),
        ('T003','Nikola Tesla','EE',78000),('T004','Marie Curie','ME',72000),
        ('T005','Grace Hopper','CS',77000),('T006','James Watt','ME',74000),
        ('T007','Rosalind Franklin','EE',73000),
        ('T008','Galileo Galilei','EE',85000) # New instructor
    ]
    cursor.executemany("INSERT OR IGNORE INTO instructor VALUES (?,?,?,?)", instructors)

    # ----------------- Students -----------------
    students = [
        ('S001','Alice Johnson','CS',12),('S002','Bob Smith','CS',8),('S003','Charlie Lee','EE',10),
        ('S004','Diana Patel','CS',6),('S005','Ethan Brown','ME',9),('S006','Fiona Wang','EE',7),
        ('S007','George Miller','CS',11),('S008','Hannah Davis','ME',6),('S009','Ian Thompson','CS',8),
        ('S010','Julia Garcia','EE',12),('S011','Kevin Martinez','CS',9),('S012','Laura Kim','ME',7),
        ('S013','Michael Clark','CS',6),('S014','Nina Rodriguez','EE',10),('S015','Oscar Lopez','CS',11),
        ('S016','Zoe Adams','CS',18), # New student: High credits, for testing enrollment limit
        ('S017','Yusuf Khan','EE',3) # New student: Low credits, for testing enrollment
    ]
    cursor.executemany("INSERT OR IGNORE INTO student VALUES (?,?,?,?)", students)

    # ----------------- Courses -----------------
    courses = [
        ('C001','Introduction to CS','CS',3),('C002','Data Structures','CS',3),('C003','Algorithms','CS',3),
        ('C004','Operating Systems','CS',3),('C005','Digital Electronics','EE',3),('C006','Circuit Analysis','EE',3),
        ('C007','Thermodynamics','ME',3),('C008','Fluid Mechanics','ME',3),('C009','Database Systems','CS',3),
        ('C010','Computer Networks','CS',3),
        ('C011','Intro to Logic','CS',4), # New course: 4 credits (to hit 12 credit limit easily)
        ('C012','Advanced Topics','CS',3) # New course: Requires C011
    ]
    cursor.executemany("INSERT OR IGNORE INTO course VALUES (?,?,?,?)", courses)

    # ----------------- Sections -----------------
    # NOTE: Added a default capacity (30) for all existing sections to match the new schema.
    sections = [
        # Existing Sections
        ('C001','01','Fall',2025,'BldgA','101',30,'TS01'), # M 9:00 - 10:00
        ('C001','02','Spring',2026,'BldgA','102',30,'TS02'),
        ('C002','01','Fall',2025,'BldgA','103',30,'TS03'), # W 11:00 - 12:00
        ('C003','01','Fall',2025,'BldgB','201',30,'TS04'), # R 12:00 - 13:00
        ('C004','01','Spring',2026,'BldgB','202',30,'TS05'),
        ('C005','01','Fall',2025,'BldgC','301',30,'TS06'),
        ('C006','01','Spring',2026,'BldgC','302',30,'TS07'),
        ('C007','01','Fall',2025,'BldgD','401',30,'TS08'),
        ('C008','01','Spring',2026,'BldgD','402',30,'TS09'),
        ('C009','01','Fall',2025,'BldgA','104',1,'TS10'), # F 8:00 - 9:00
        ('C010','01','Spring',2026,'BldgA','105',30,'TS11'),

        # New Sections for Edge Cases
        ('C011','01','Fall',2025,'BldgA','101',30,'TS01'), # Conflict: Same time/building as C001-01
        ('C012','01','Fall',2025,'BldgB','202',30,'TS05'), 
        ('C013','01','Fall',2025,'BldgC','302',30,None),   # No Time Slot
        ('C001','03','Fall',2025,'BldgA','105',30,'TS11') # M 10:00 - 11:00
    ]
    # Executing against 7 columns in your original, now 8 columns with capacity
    cursor.executemany("INSERT OR IGNORE INTO section VALUES (?,?,?,?,?,?,?,?)", sections)

    # ----------------- Teaches -----------------
    teaches = [
        ('T001','C001','01','Fall',2025),('T002','C002','01','Fall',2025),
        ('T001','C003','01','Fall',2025),('T003','C005','01','Fall',2025),
        ('T004','C007','01','Fall',2025),('T005','C009','01','Fall',2025),
        ('T006','C011','01','Fall',2025), # T006 teaches the conflict course
        ('T008','C012','01','Fall',2025), # T008 teaches the prereq course
        ('T001','C001','03','Fall',2025) # T001 teaches new section C001-03
    ]
    cursor.executemany("INSERT OR IGNORE INTO teaches VALUES (?,?,?,?,?)", teaches)

    # ----------------- Takes (Enrollment) -----------------
    takes = [
        # S001 history (Completed)
        ('S001','C001','01','Fall',2025,'A'),
        ('S001','C002','01','Spring',2024,'B+'),
        # S001 current enrollment (Should appear on dashboard)
        ('S001','C003','01','Fall',2025,None), # 3 credits, R 12:00
        ('S001','C009','01','Fall',2025,None), # 3 credits, F 8:00
        
        # S016 enrollment (4+4+3 = 11 credits. Near limit. Should successfully enroll in C001-03)
        ('S016','C011','01','Fall',2025,None), # 4 credits, M 9:00
        ('S016','C005','01','Fall',2025,None), # 3 credits, M 14:00
        ('S016','C007','01','Fall',2025,None), # 3 credits, W 16:00
        
        # S017 history (Completed prerequisite C011)
        ('S017','C011','01','Fall',2024,'A'),
        # S017 current enrollment (3 credits)
        ('S017','C001','01','Fall',2025,None), # 3 credits, M 9:00
    ]
    cursor.executemany("INSERT OR IGNORE INTO takes VALUES (?,?,?,?,?,?)", takes)

    # ----------------- Advisors -----------------
    advisors = [
        ('S001','T001'),('S002','T002'),('S003','T003'),('S004','T001'),('S005','T004'),
        ('S006','T003'),('S007','T005'),('S008','T004'),('S009','T001'),('S010','T003'),
        ('S011','T005'),('S012','T004'),('S013','T001'),('S014','T003'),('S015','T005'),
        ('S016','T002'),('S017','T003')
    ]
    cursor.executemany("INSERT OR IGNORE INTO advisor VALUES (?,?)", advisors)

    # ----------------- Time Slots -----------------
    timeslots = [
        ('TS01','Monday',9,0,10,0),('TS02','Tuesday',10,0,11,0),('TS03','Wednesday',11,0,12,0),('TS04','Thursday',12,0,13,0),
        ('TS05','Friday',13,0,14,0),('TS06','Monday',14,0,15,0),('TS07','Tuesday',15,0,16,0),('TS08','Wednesday',16,0,17,0),
        ('TS09','Thursday',17,0,18,0),('TS10','Friday',8,0,9,0),('TS11','Monday',10,0,11,0)
    ]
    cursor.executemany("INSERT OR IGNORE INTO time_slot VALUES (?,?,?,?,?,?)", timeslots)

    # ----------------- Prerequisites -----------------
    prereqs = [
        ('C002','C001'),('C003','C002'),('C009','C003'),
        ('C012','C011') # New Prereq: C012 requires C011
    ]
    cursor.executemany("INSERT OR IGNORE INTO prereq VALUES (?,?)", prereqs)

    # ----------------- Login credentials -----------------
    credentials = [
        ('admin','admin123','admin',1),  # admin approved by default
        ('S001','pass1','student',1),('S002','pass2','student',1),('S003','pass3','student',1),
        ('S004','pass4','student',1),('S005','pass5','student',1),('S006','pass6','student',1),
        ('S007','pass7','student',1),('S008','pass8','student',1),('S009','pass9','student',1),
        ('S010','pass10','student',1),('S011','pass11','student',1),('S012','pass12','student',1),
        ('S013','pass13','student',1),('S014','pass14','student',1),('S015','pass15','student',1),
        ('S016','pass16','student',1),('S017','pass17','student',1), # New student credentials
        ('T001','tpass1','teacher',1),('T002','tpass2','teacher',1),('T003','tpass3','teacher',1),
        ('T004','tpass4','teacher',1),('T005','tpass5','teacher',1),('T006','tpass6','teacher',1),
        ('T007','tpass7','teacher',1),('T008','tpass8','teacher',1) # New teacher credential
    ]
    cursor.executemany("INSERT OR IGNORE INTO login_credentials VALUES (?,?,?,?)", credentials)

    conn.commit()


if __name__ == "__main__":
    conn = sqlite3.connect(DB_FILE)
    
    # ⚠️ IMPORTANT: To apply the new schema, you must delete the old university.db file first 
    # and then run this script. If the file exists, the CREATE TABLE IF NOT EXISTS statements
    # will be skipped.
    
    create_tables(conn)
    insert_sample_data(conn)
    conn.close()
    print("Database initialized with test data successfully!")