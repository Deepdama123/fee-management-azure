/* =====================================================================
   03_load_test_5000.sql  -  OPTIONAL scalability check

   Adds 5,000 synthetic students in one set-based INSERT (no loops), so
   the API can be shown paging and filtering over 5,000+ rows.

   Safety: every synthetic student is NOT overdue (due date in the future,
   or fully paid), so the reminder workflow never emails these fake
   addresses. Remove them again with 04_remove_load_test.sql.
   ===================================================================== */

SET NOCOUNT ON;

DECLARE @Today DATE = CAST(SYSUTCDATETIME() AS DATE);

WITH Numbers AS (
    SELECT TOP (5000) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS n
    FROM sys.all_objects AS a
    CROSS JOIN sys.all_objects AS b
)
INSERT INTO dbo.Students (Name, Course, TotalFee, PaidAmount, DueDate, Email)
SELECT
    CONCAT(N'Load Test Student ', n),
    CHOOSE(n % 5 + 1, N'B.Tech CSE', N'MBA', N'B.Com', N'M.Sc Data Science', N'BBA'),
    100000.00,
    CASE WHEN n % 3 = 0 THEN 100000.00 ELSE (n % 10) * 9000.00 END,  -- 1/3 paid in full
    DATEADD(DAY, 1 + n % 90, @Today),                                   -- always in the future
    CONCAT(N'loadtest+', n, N'@example.invalid')
FROM Numbers;

SELECT COUNT(*) AS TotalStudents FROM dbo.Students;
