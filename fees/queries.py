"""All SQL text. Every value is a bound '?' parameter; nothing from a request
is ever concatenated into SQL. Column lists and status predicates come only
from constants in code."""

STUDENT_COLUMNS = """
    s.StudentID, s.Name, s.Course, s.TotalFee, s.PaidAmount, s.DueDate, s.Email, s.UpdatedAt"""

GET_STUDENT = f"SELECT {STUDENT_COLUMNS} FROM dbo.Students AS s WHERE s.StudentID = ?;"

LIST_STUDENTS = "SELECT {columns} FROM dbo.Students AS s WHERE {where} {page};"

COUNT_STUDENTS = "SELECT COUNT(*) FROM dbo.Students AS s WHERE {where};"

# Atomic: the balance check and the increment happen in ONE statement, so two
# admins recording payments at the same moment can never overpay a student.
RECORD_PAYMENT = """
UPDATE dbo.Students
SET    PaidAmount = PaidAmount + ?,
       UpdatedAt  = ?
WHERE  StudentID = ?
  AND  PaidAmount + ? <= TotalFee;
"""

UPDATE_FEES = "UPDATE dbo.Students SET {assignments}, UpdatedAt = ? WHERE StudentID = ?;"

INSERT_AUDIT = """
INSERT INTO dbo.FeeAudit
    (StudentID, Action, OldTotalFee, NewTotalFee, OldPaidAmount, NewPaidAmount,
     OldDueDate, NewDueDate, ChangedBy, ChangedAt)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

LIST_AUDIT = """
SELECT a.AuditID, a.Action, a.OldTotalFee, a.NewTotalFee, a.OldPaidAmount, a.NewPaidAmount,
       a.OldDueDate, a.NewDueDate, a.ChangedBy, a.ChangedAt
FROM dbo.FeeAudit AS a
WHERE a.StudentID = ?
{page};
"""

GET_ADMIN_BY_EMAIL = """
SELECT AdminID, Name, Role, Email, IsActive
FROM dbo.Administrators
WHERE LOWER(Email) = ?;
"""

HEALTH_CHECK = "SELECT 1;"
