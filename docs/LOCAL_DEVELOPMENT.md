# Local Development

This is the current source of truth for running BizonVR locally.

## Requirements

- Python 3.12+
- PostgreSQL
- Node.js and npm
- Git
- A local `.env` copied from `.env.example`

Do not commit `.env`, database dumps, local logs, or generated secrets.

## First Run

```bash
createdb bizon
cp .env.example .env
make install-local
make migrate-local
make superuser-local
make run-local
```

Open:

- Public site: `http://127.0.0.1:8000/`
- Django admin: `http://127.0.0.1:8000/admin/`

If `make` is not available on Windows, use the equivalent commands:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

## Minimal Local `.env`

Use local values only. Never copy production secrets into local docs.

```env
DEBUG=True
SITE_URL=http://127.0.0.1:8000
ALLOWED_HOSTS=127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000

DB_NAME=bizon
DB_USER=postgres
DB_PASSWORD=replace-with-local-password
DB_HOST=localhost
DB_PORT=5432
```

## Common Commands

```bash
make run-local
make migrate-local
make load-data-local
make load-data-clear-local
make clear-cache
make check-single-db
```

CSS source lives in `static_src/input.css`. The compiled file is `static/css/tailwind.css`.

```bash
npm run build:css
```

On Windows, if `npm run build:css` cannot find the Tailwind shim, run the CLI directly:

```powershell
node node_modules\tailwindcss\lib\cli.js -i static_src\input.css -o static\css\tailwind.css --minify
```

## Validation

Run before reporting a public-site change:

```bash
python manage.py check
python manage.py test --keepdb --noinput
npm run build:css
```

If the full test suite is too slow for the current task, run the relevant app subset and state that in the report.
