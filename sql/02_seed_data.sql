/* =====================================================================
   02_seed_data.sql  -  20 sample students + administrators

   BEFORE RUNNING, edit the three variables below:
     @InboxUser / @InboxDomain  your own mailbox. Every student gets a
                                "plus address" (you+s1@gmail.com ...), so
                                all reminder emails land in YOUR inbox and
                                no real person is ever emailed.
     @MyAdminEmail              the exact username you sign in to Azure
                                with (the token's preferred_username).

   Due dates are relative to the day you run the script, so the mix of
   statuses is always the same:
     6 Paid  |  7 Partially Paid (not yet due)  |  7 Overdue
   ===================================================================== */

SET NOCOUNT ON;

DECLARE @InboxUser    NVARCHAR(100) = N'deepbhanushali30';          -- <-- edit
DECLARE @InboxDomain  NVARCHAR(100) = N'gmail.com';                 -- <-- edit
DECLARE @MyAdminEmail NVARCHAR(255) = N'deep.nb@somaiya.edu'; -- <-- edit

DECLARE @Today DATE = CAST(SYSUTCDATETIME() AS DATE);

DELETE FROM dbo.FeeAudit;
DELETE FROM dbo.Students;
DELETE FROM dbo.Administrators;
-- Restart StudentIDs at 1001. (A brand-new table already starts at 1001; a
-- reseed there would make the first id 1000, so only reseed a used table.)
IF EXISTS (SELECT 1 FROM sys.identity_columns
           WHERE object_id = OBJECT_ID(N'dbo.Students') AND last_value IS NOT NULL)
    DBCC CHECKIDENT ('dbo.Students', RESEED, 1000);

INSERT INTO dbo.Students (Name, Course, TotalFee, PaidAmount, DueDate, Email)
SELECT v.Name, v.Course, v.TotalFee, v.PaidAmount,
       DATEADD(DAY, v.DueOffsetDays, @Today),
       CONCAT(@InboxUser, N'+s', v.Tag, N'@', @InboxDomain)
FROM (VALUES
    -- Paid (PaidAmount = TotalFee)
    (1,  N'Aarav Sharma',    N'B.Tech CSE',        150000.00, 150000.00, -20),
    (2,  N'Diya Patel',      N'MBA',               220000.00, 220000.00,  15),
    (3,  N'Kabir Mehta',     N'B.Com',              60000.00,  60000.00, -60),
    (4,  N'Ananya Iyer',     N'M.Sc Data Science', 180000.00, 180000.00,  30),
    (5,  N'Vihaan Reddy',    N'BBA',                90000.00,  90000.00, -10),
    (6,  N'Isha Nair',       N'B.Tech CSE',        150000.00, 150000.00,  45),
    -- Partially Paid (balance due, due date still ahead)
    (7,  N'Arjun Singh',     N'MBA',               220000.00, 110000.00,   5),
    (8,  N'Saanvi Gupta',    N'B.Com',              60000.00,  30000.00,  12),
    (9,  N'Reyansh Joshi',   N'M.Sc Data Science', 180000.00,  90000.00,  20),
    (10, N'Myra Kulkarni',   N'BBA',                90000.00,  45000.00,  25),
    (11, N'Aditya Rao',      N'B.Tech CSE',        150000.00, 100000.00,  10),
    (12, N'Kiara Desai',     N'MBA',               220000.00,  50000.00,  40),
    (13, N'Rohan Bhatt',     N'B.Com',              60000.00,  10000.00,   1),
    -- Overdue (balance due, due date passed)
    (14, N'Neha Verma',      N'BBA',                90000.00,  60000.00,  -3),
    (15, N'Siddharth Menon', N'M.Sc Data Science', 180000.00,      0.00,  -7),
    (16, N'Pooja Shah',      N'B.Tech CSE',        150000.00,  75000.00, -15),
    (17, N'Rahul Kapoor',    N'MBA',               220000.00, 200000.00, -21),
    (18, N'Tanvi Pillai',    N'B.Com',              60000.00,      0.00, -30),
    (19, N'Yash Malhotra',   N'BBA',                90000.00,  20000.00, -45),
    (20, N'Meera Chopra',    N'M.Sc Data Science', 180000.00, 120000.00,  -1)
) AS v (Tag, Name, Course, TotalFee, PaidAmount, DueOffsetDays)
ORDER BY v.Tag;

INSERT INTO dbo.Administrators (Name, Role, Email, IsActive) VALUES
    (N'Deep Bhanushali', N'FeeAdmin',  @MyAdminEmail,                         1),
    (N'Finance Viewer',  N'FeeViewer', N'viewer@yourtenant.onmicrosoft.com',  1),
    (N'Former Admin',    N'FeeAdmin',  N'former.admin@yourtenant.onmicrosoft.com', 0);

-- Quick check
SELECT COUNT(*) AS Students FROM dbo.Students;
SELECT * FROM dbo.Administrators;
