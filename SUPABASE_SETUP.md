# Supabase Postgres Setup

This project uses a Python/FastAPI backend, so database access should use the Supabase Postgres connection string in `DATABASE_URL`.

The `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` values are for browser Supabase clients. They are not enough for this backend to create tables or write scan data.

## 1. Get The Connection String

In Supabase:

1. Open your project.
2. Go to `Project Settings` -> `Database`.
3. Copy the pooled connection string.
4. Replace the password placeholder with your database password.

Use a value like:

```env
DATABASE_URL=postgresql://postgres.<project-ref>:<db-password>@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require
DB_SYSTEM_SCHEMA=system
DB_USER_SCHEMA=app_user
```

Your direct Supabase connection string format is:

```env
DATABASE_URL=postgresql://postgres:<db-password>@db.tzqbefennicpfeljlier.supabase.co:5432/postgres?sslmode=require
```

If your password contains special characters such as `@`, `#`, `%`, `/`, or `:`, URL-encode the password before putting it in `DATABASE_URL`.

Keep this value secret. Do not put it in React code.

## 2. Install Python Dependencies

```powershell
pip install -r requirements.txt
pip install -r screener_ui/backend/requirements.txt
```

`psycopg[binary]` is already listed in both requirement files.

## 3. Initialize And Migrate Existing SQLite Data

After setting `DATABASE_URL`, run:

```powershell
python tools/migrate_sqlite_to_postgres.py
```

This creates the required schemas/tables and copies local SQLite data into Supabase.

To clear target tables before copying, run:

```powershell
python tools/migrate_sqlite_to_postgres.py --replace
```

## 4. Run The App

Start the backend normally after `DATABASE_URL` is set:

```powershell
.\run_screener.bat start
```

The scanner, reports, watchlist, holdings, settings, and P/L data will use Supabase Postgres.

## Notes

- Supabase free tier can sleep or throttle. First query after idle may be slower.
- Keep `screener_ui/backend/users.json` backed up; app login users are still file-based.
- The admin `Download Backup` button uses SQLite snapshots in local mode.
- In Supabase/Postgres mode, the admin `Download Backup` button runs `pg_dump` and downloads a `.dump` file.
- For Postgres backup from the app, install PostgreSQL client tools on the server so `pg_dump` is available, or set `PG_DUMP_PATH` to the full `pg_dump` executable path.

Example:

```env
PG_DUMP_PATH=C:\Program Files\PostgreSQL\16\bin\pg_dump.exe
```
