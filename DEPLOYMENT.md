# Deployment guide

Deploys the Fee Management System into one resource group. Use one Azure region for everything; on student subscriptions, pick one your subscription policy allows (for example, Central India).

| Resource | Example name | Tier |
|---|---|---|
| Resource group | `rg-feemgmt` | — |
| Azure SQL server and database | `feemgmt-sql-<you>` / `feemgmt-db` | Free offer (serverless) |
| Function App | `feemgmt-func-<you>` | Flex Consumption, Python 3.11 |
| Application Insights | `feemgmt-ai` | Workspace-based |
| API Management | `feemgmt-apim-<you>` | Consumption |
| Logic App | `la-fee-reminders` | Consumption |
| App registration (Entra ID) | `fee-management-api` | — |

Start API Management first, because it takes the longest to provision.

## 1. Entra ID app registration (authentication and RBAC)

1. **Entra ID → App registrations → New registration.** Name it `fee-management-api`, choose *Single tenant*, then **Register**. Note the **Application (client) ID** and the **Directory (tenant) ID**.
2. **App roles → Create app role**, twice:
   - Display name `Fee Admin`, value **`FeeAdmin`**, allowed member types *Users/Groups*, description "Read and update fee records".
   - Display name `Fee Viewer`, value **`FeeViewer`**, allowed member types *Users/Groups*, description "Read fee records".
3. **Expose an API.**
   - Set the Application ID URI to `api://<client-id>`.
   - **Add a scope** `access_as_user` (Admins and users can consent).
   - **Add a client application** `04b07795-8ddb-461a-bbee-02f9e1bf7b46`. That's the Azure CLI, so `az` can get tokens for this API. Tick the scope.
4. **Manifest:** set `"requestedAccessTokenVersion": 2` (inside `"api"` in the new manifest editor), then **Save**.
5. **Enterprise applications → fee-management-api → Users and groups → Add user/group.** Select yourself and the role **FeeAdmin**.

## 2. Azure SQL Database

1. Create the database with the **free offer** (`aka.ms/azuresqlhub` → Start free). Use SQL authentication.
2. On the server's **Networking** page, allow Azure services and add your client IP.
3. In the Query editor, run these scripts in order:
   - `sql/01_schema.sql`
   - `sql/02_seed_data.sql`. **First edit `@InboxUser`, `@InboxDomain` and `@MyAdminEmail`.** Set `@MyAdminEmail` to the username you sign in to Azure with.
   - `sql/03_load_test_5000.sql` (optional scalability demo). `sql/04_remove_load_test.sql` removes those rows again.

## 3. Application Insights

1. **Create → Application Insights**, workspace-based, in the same region. Copy its **Connection string**.

## 4. Function App

1. **Create → Function App → Flex Consumption**, Python **3.11**. Turn on Application Insights, or connect it to `feemgmt-ai` afterwards.
2. **Settings → Environment variables:**

   | Name | Value |
   |---|---|
   | `SqlConnectionString` | ODBC connection string (`Pwd={…}`) |
   | `AUTH_MODE` | `entra` |
   | `AUTH_TENANT_ID` | Directory (tenant) ID |
   | `AUTH_AUDIENCES` | `<client-id>,api://<client-id>` |
   | `FEE_TIMEZONE` | `Asia/Kolkata` |
   | `APPLICATIONINSIGHTS_CONNECTION_STRING` | from step 3 (if not already set) |

3. Package the Linux dependencies with the app. Run this in the project folder:
   ```
   pip install --target=".python_packages\lib\site-packages" --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.11 -r requirements.txt
   ```
   Then deploy: **VS Code → Azure → right-click the Function App → Deploy to Function App**.
4. Test the deployment:
   - `https://<func>.azurewebsites.net/api/health` should return `{"status":"healthy"}`.
   - Copy **App keys → Host keys → default**. You'll need it in APIM and the Logic App.

## 5. API Management

1. **Create → API Management**, **Consumption** tier.
2. **Named values → + Add:**
   - `func-host-key`, type **Secret**, value = the Function host key.
   - `tenant-id` = tenant ID.
   - `api-client-id` = client ID.
3. **APIs → + Add API → OpenAPI** → `apim/student-api.openapi.json`, API URL suffix **`student`**. Under **Settings**, set the Web service URL to `https://<func>.azurewebsites.net/api`.
4. **APIs → + Add API → OpenAPI** → `apim/admin-api.openapi.json`, API URL suffix **`admin`**. Set the Web service URL to `https://<func>.azurewebsites.net/api/manage`.
5. For each API, open **All operations → Inbound processing → code editor (`</>`)**. Paste `apim/policies/student-api-policy.xml` or `admin-api-policy.xml`, then **Save**. In the admin policy, replace `<your-function-app>` in `set-backend-service` with your Function App's default domain.
6. **Subscriptions → + Add subscription:**
   - `student-demo`, scope: Student API.
   - `admin-demo`, scope: Admin API.
   - Then use **Show/hide keys** to copy each primary key.

## 6. Logic App (fee reminders)

1. **Create → Logic App → Consumption**, named `la-fee-reminders`.
2. In the designer, build the workflow below. `logicapp/fee-reminder-workflow.json` is the exported code view.
   1. **Recurrence:** every 1 day, at 09:00, time zone (UTC+05:30) Chennai, Kolkata.
   2. **HTTP GET** `https://<func>.azurewebsites.net/api/reminders/overdue?limit=200`, with header `x-functions-key: <host key>`.
      - *Settings:* Retry policy **Exponential**, count 4, interval `PT10S`, minimum `PT5S`, maximum `PT1H`; **Secure inputs** on. Durations are ISO 8601 with no spaces.
   3. **Parse JSON** on the HTTP body. Use the schema from the workflow JSON.
   4. **For each** `items` (*Settings:* concurrency 5), containing **Office 365 Outlook (or Outlook.com) → Send an email (V2)**:
      - To `email`; the subject and body use `name`, `balance`, `dueDate` and `daysOverdue`.
      - *Settings:* Retry policy **Exponential**, count 3.
   5. Optionally, **Send an email** to the admin with the run summary.
3. **Save → Run trigger.** Each overdue student's plus-address receives a reminder.

## 7. Get an admin token and test

```
az login --tenant <tenant-id>
az account get-access-token --scope api://<client-id>/.default --query accessToken -o tsv
```

Paste the token into `requests.http` (REST Client `azure` environment) and run the requests through APIM. To check the token's `roles` claim, decode it at https://jwt.ms.

To demonstrate the 403 check, change your app-role assignment to **FeeViewer**, get a new token, and call `POST /admin/students/{id}/payments`.

## 8. Monitoring

Use **Application Insights → Transaction search / Failures / Logs**. For example:

```kusto
requests
| where timestamp > ago(1h)
| summarize count() by name, resultCode
| order by name asc
```

Logic App runs, with every retry attempt, appear under **Logic App → Run history**.

## Clean up

Delete the resource group `rg-feemgmt` once you've finished. That removes everything except the app registration, which you delete under Entra ID → App registrations.
