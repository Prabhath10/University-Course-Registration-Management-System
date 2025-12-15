# 🏛️ University Course Management System

A comprehensive web application for university course registration with **AI-powered database queries using the Gemini API**.

## 🌟 Features

* **User Management**: Role-based authentication (**Admin, Teacher, Student**).
* **Course Enrollment**: Automated enrollment with **credit limits** and **schedule conflict detection**.
* **AI Assistant**: Natural language queries about university data using **Gemini API + Custom Logic**.
* **Admin Dashboard**: User approval, system overview, and complete CRUD operations.
* **Modern UI**: Streamlit-based interface.



## 🏗️ Architecture and Technology Stack

| Component | Technology | Description |
| :--- | :--- | :--- |
| **Backend/API** | **FastAPI** | Provides robust, fast API endpoints for data access and business logic. |
| **Database** | **SQLite** | Simple, file-based relational database for data persistence. |
| **Frontend/UI** | **Streamlit** | Creates the interactive, modern user interface. |
| **AI Integration** | **Gemini API** | Handles natural language processing for database queries. |
| **Security** | **Bcrypt** | Used for secure password hashing. |



## 🚀 Quick Start

### Prerequisites

* **Python 3.9+**
* **Gemini API Key** (Required for the AI Assistant feature)

### 1. Installation

1.  **Clone and setup**: Ensure your Python virtual environment is active.
    ```bash
    pip install -r requirements.txt
    ```

2.  **Initialize Database**: This creates `university.db` and populates it with sample data, including the necessary `capacity` column.
    ```bash
    python setup.py
    ```

### 2. Configure API Key

Create a file named **`.env`** in your project's root directory:

```bash
# .env file

# API Key for the AI Assistant feature.
# Replace YOUR_GEMINI_API_KEY_HERE with your actual key.
GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE"
```
### 3.  Start the Application
- You need two separate terminal windows for the backend and frontend.
    - Start the backend (Terminal 1): This serves the API endpoints.
    ```bash
      uvicorn main:app --reload
    ```
    - Start the frontend (Terminal 2): This runs the web interface
    ```bash
    streamlit run frontend.py
    ```
- The application will open in your browser at http://localhost:8501.

## 🔒 Default Credentials

| Role | Username | Password | Approval Status |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin` | `admin123` | Pre-approved |
| **Student (Example)** | `S001` | `pass1` | Pending Approval |
| **Teacher (Example)** | `T001` | `tpass1` | Pending Approval |

*(Note: New users are created with pending approval and must be approved via the Admin Dashboard.)*


