# Clinic booking API

FastAPI service and patient booking page are deployed as separate services with separate URLs.

## Run locally

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:API_KEY = "KOYA0APITHECAPSTONE"
uvicorn main:app --reload --port 8000
```

In a second terminal, serve the website separately:

```powershell
py -m http.server 8081 --directory static
```

Copy `.env.example` to `.env` and set your local values there. The application loads `.env` at startup; actual process environment variables take precedence, so hosting providers can inject their own values. Open `http://127.0.0.1:8081` for the website. The API is at `http://127.0.0.1:8000` and its documentation is at `http://127.0.0.1:8000/docs`. Enter the API URL and API key in the page before connecting.

The API stores state in SQLite at `clinic_booking.sqlite3`. Set `DATABASE_PATH` to use another file. Rate limiting defaults to five booking attempts per email in a 60-second rolling window; `RATE_LIMIT_ATTEMPTS` and `RATE_LIMIT_WINDOW_SECONDS` configure those values.

## Test

```powershell
pip install -r requirements.txt
pytest -q
```

## Deploy

The included `render.yaml` defines two Render services: the API at `https://koya-clinic-booking-api.onrender.com` and the website at `https://koya-clinic-booking-web.onrender.com`. Create a Blueprint from this repository and provide `API_KEY` when prompted. `.env` is intentionally excluded from the Docker image and version control; Render’s service environment variables override dotenv configuration. Update `ALLOWED_ORIGINS` in the API service settings if you use a custom website domain. API documentation is at `https://koya-clinic-booking-api.onrender.com/docs`.

SQLite is appropriate for this single-instance assessment deployment. For multiple app instances, use a shared transactional database such as PostgreSQL so slot uniqueness and rate limits are coordinated across instances.
