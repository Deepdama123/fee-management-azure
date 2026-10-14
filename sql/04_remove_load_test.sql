/* Removes the synthetic rows added by 03_load_test_5000.sql. */
SET NOCOUNT ON;

DELETE a FROM dbo.FeeAudit AS a
JOIN dbo.Students AS s ON s.StudentID = a.StudentID
WHERE s.Email LIKE N'loadtest+%@example.invalid';

DELETE FROM dbo.Students WHERE Email LIKE N'loadtest+%@example.invalid';

SELECT COUNT(*) AS TotalStudents FROM dbo.Students;
