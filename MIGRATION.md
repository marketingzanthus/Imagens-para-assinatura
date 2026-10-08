# PostgreSQL migration

Render must have DATABASE_URL set to the internal URL of the PostgreSQL instance
in the same workspace and region. No fallback to SQLite is allowed on Render.
Set SECRET_KEY and ADMIN_PASSWORD securely in the service environment; the latter
is used only if no user exists. Existing users and password hashes are retained
when a recovered SQLite snapshot is imported before starting the application.

## Preserve data before cutover

Do not restart, upgrade, deploy, or push to the production branch before examining
recovery options. On paid instances, use SQLite's backup API on the running
instance and download the resulting file AND uploads. A raw copy of an active
SQLite file can omit WAL transactions. Free instances have no shell or SSH.
If the application exposes only XLSX export, this is a partial export, not a full
database backup. Do not claim that lost rows or password hashes were recovered.

After freezing writes, import a recovered database into an empty target:

    python migrate_sqlite.py recovered.db --backup verified-copy.db

The tool uses DATABASE_URL from the environment, checks source integrity, imports
all five tables in one transaction, compares every imported value, and repairs ID
sequences. It refuses nonempty targets. It does not seed default campaigns.

## Images

Images need a separate private S3-compatible bucket. Set S3_BUCKET, S3_REGION,
optional S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY securely.
Use a dedicated credential limited to the bucket's sorteador/ prefix with
GetObject and PutObject. Copy recovered uploads to that prefix with the same
filenames. Downloads use short lived signed URLs. No bucket ACLs are changed.
Until configured, Render uploads are disabled to prevent silent data loss.
Local images are not durable. PostgreSQL stores image filenames, not image bytes.

## Validation and rollback

Validate registration, duplicate email rejection, login/roles, campaign creation
(RETURNING id), draw history, participant flags, and XLSX export against an
isolated PostgreSQL schema. /health checks the actual database and returns 503 on
failure. Preserve a PostgreSQL dump before future migrations. Do not roll back to
the old SQLite version after cutover: it would create an empty ephemeral database.
Rollback code must retain PostgreSQL compatibility.

Free Render PostgreSQL expires 30 days after creation and does not include
backups. Upgrade before expiry or export and migrate to a permanent instance.
