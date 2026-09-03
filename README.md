# Coaching Center Student Analytics Dashboard

An end-to-end data analytics project built on a coaching center's student data — tracking
enrollment, attendance, and fee collection across courses. Built with SQL Server for data
modeling and analysis, and Power BI for an interactive dashboard.

## What it does

- Models student enrollment, course, attendance, and fee data into a relational SQL Server database
- Surfaces business insights through T-SQL queries: revenue by course, at-risk students (low attendance),
  outstanding fees, and month-over-month enrollment trends
- Automates at-risk student reporting with a parameterized stored procedure
- Visualizes everything in an interactive Power BI dashboard with a custom DAX measure

## Tech Stack

SQL Server, T-SQL, Power BI, DAX, Python (Pandas, for data prep)

## Database Schema

| Table | Description |
|---|---|
| `Students` | Student ID, name, contact info, enrolled course, enrollment date |
| `Courses` | Course ID, name, subject, instructor, batch timing, schedule |
| `Attendance` | Per-class attendance record (Present/Absent) per student |
| `Fees` | Amount due, amount paid, payment status per student |

## Key Queries

- Revenue & enrollment by course (joins across Students, Courses, Fees)
- At-risk students (subquery + window function ranking by lowest attendance %)
- Pending fees (outstanding balance, sorted by amount owed)
- Monthly enrollment trend (running total window function)
- Course attendance ranking (`RANK()` window function)

## Stored Procedure

`dbo.GetAtRiskStudents` — takes a course ID and attendance threshold, returns every student
below the threshold along with outstanding fees.

```sql
EXEC dbo.GetAtRiskStudents @CourseID = 'CRS-001', @AttendanceThreshold = 75.00;
```

## Power BI Dashboard

- KPI cards: Total Fees Collected, Total Students, Total Courses, Overall Attendance Rate
- Revenue trend line chart, enrollment by course column chart
- Interactive course slicer, student attendance detail table
- Custom DAX measure:

```dax
Attendance Rate % =
DIVIDE(
    CALCULATE(COUNTROWS('Attendance'), 'Attendance'[Status] = "Present"),
    COUNTROWS('Attendance')
)
```

## Results

- Modeled and analyzed data across 150 students, 5 courses, and 5,400+ attendance records
- Identified at-risk students with attendance below 75% for proactive follow-up
- Flagged outstanding fee balances across the student base

## Data Privacy Note

This project uses sample/anonymized data. No real student names or personal information are included.
