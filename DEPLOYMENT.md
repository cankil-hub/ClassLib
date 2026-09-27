# Vercel + Supabase deployment

Production uses:

- Vercel: Django web application
- Supabase Postgres: application database
- Supabase Storage bucket `classlib-private`: private file objects

Required Vercel environment variables:

```text
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<random-secret>
DJANGO_ALLOWED_HOSTS=<your-project>.vercel.app
DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-project>.vercel.app

DATABASE_URL=<Supabase pooled Postgres connection string>

STORAGE_BACKEND=supabase
SUPABASE_URL=https://hkhoasexmlwugiiclvcg.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<Supabase secret/service-role key>
SUPABASE_STORAGE_BUCKET=classlib-private
```

After the database variables are configured, run Django migrations once against the Supabase database:

```bash
python manage.py migrate
python manage.py createsuperuser
```

Local development keeps the existing defaults:

- SQLite database
- local private file storage
