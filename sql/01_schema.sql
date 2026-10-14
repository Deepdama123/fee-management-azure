/* =====================================================================
   01_schema.sql  -  Fee Management System (Azure SQL Database)

   Tables
     dbo.Students        fee record per student (brief: StudentID, Name,
                         Course, TotalFee, PaidAmount, DueDate) + Email
     dbo.Administrators  admin profile (brief: AdminID, Name, Role) + Email
     dbo.FeeAudit        who changed which fee record, when, old -> new

   Safe to re-run (drops and recreates). No GO separators, so it runs as-is
   in the Azure portal Query editor.
   ===================================================================== */

SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.FeeAudit', N'U') IS NOT NULL       DROP TABLE dbo.FeeAudit;
IF OBJECT_ID(N'dbo.Students', N'U') IS NOT NULL       DROP TABLE dbo.Students;
IF OBJECT_ID(N'dbo.Administrators', N'U') IS NOT NULL DROP TABLE dbo.Administrators;

CREATE TABLE dbo.Students
(
    StudentID   INT            IDENTITY(1001, 1) NOT NULL,
    Name        NVARCHAR(100)  NOT NULL,
    Course      NVARCHAR(100)  NOT NULL,
    TotalFee    DECIMAL(12,2)  NOT NULL,
    PaidAmount  DECIMAL(12,2)  NOT NULL CONSTRAINT DF_Students_PaidAmount DEFAULT (0),
    DueDate     DATE           NOT NULL,
    -- Not in the brief's column list, but reminders cannot be emailed without it.
    Email       NVARCHAR(255)  NOT NULL,
    UpdatedAt   DATETIME2(0)   NOT NULL CONSTRAINT DF_Students_UpdatedAt DEFAULT (SYSUTCDATETIME()),

    CONSTRAINT PK_Students PRIMARY KEY (StudentID),
    CONSTRAINT CK_Students_TotalFee   CHECK (TotalFee >= 0),
    -- A student can never have paid less than 0 or more than the fee.
    CONSTRAINT CK_Students_PaidAmount CHECK (PaidAmount >= 0 AND PaidAmount <= TotalFee)
);

-- Supports the daily overdue scan (DueDate < today AND PaidAmount < TotalFee)
-- without touching the base table: every column the query needs is included.
CREATE INDEX IX_Students_DueDate
    ON dbo.Students (DueDate)
    INCLUDE (Name, Course, TotalFee, PaidAmount, Email);

-- Supports the admin "filter by course" query.
CREATE INDEX IX_Students_Course
    ON dbo.Students (Course)
    INCLUDE (Name, TotalFee, PaidAmount, DueDate);

CREATE TABLE dbo.Administrators
(
    AdminID   INT            IDENTITY(1, 1) NOT NULL,
    Name      NVARCHAR(100)  NOT NULL,
    Role      NVARCHAR(20)   NOT NULL,
    -- Links the row to the signed-in Entra ID user (token 'preferred_username').
    Email     NVARCHAR(255)  NOT NULL,
    IsActive  BIT            NOT NULL CONSTRAINT DF_Administrators_IsActive DEFAULT (1),

    CONSTRAINT PK_Administrators PRIMARY KEY (AdminID),
    CONSTRAINT UQ_Administrators_Email UNIQUE (Email),
    CONSTRAINT CK_Administrators_Role CHECK (Role IN (N'FeeAdmin', N'FeeViewer'))
);

CREATE TABLE dbo.FeeAudit
(
    AuditID        BIGINT         IDENTITY(1, 1) NOT NULL,
    StudentID      INT            NOT NULL,
    Action         NVARCHAR(30)   NOT NULL,      -- PAYMENT_RECORDED | FEE_UPDATED
    OldTotalFee    DECIMAL(12,2)  NULL,
    NewTotalFee    DECIMAL(12,2)  NULL,
    OldPaidAmount  DECIMAL(12,2)  NULL,
    NewPaidAmount  DECIMAL(12,2)  NULL,
    OldDueDate     DATE           NULL,
    NewDueDate     DATE           NULL,
    ChangedBy      NVARCHAR(255)  NOT NULL,
    ChangedAt      DATETIME2(0)   NOT NULL,

    CONSTRAINT PK_FeeAudit PRIMARY KEY (AuditID),
    CONSTRAINT FK_FeeAudit_Students FOREIGN KEY (StudentID) REFERENCES dbo.Students (StudentID)
);

CREATE INDEX IX_FeeAudit_StudentID ON dbo.FeeAudit (StudentID, ChangedAt DESC);
