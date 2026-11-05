import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("API_KEY", "KOYA0APITHECAPSTONE")
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "clinic_booking.sqlite3")))
RATE_LIMIT_ATTEMPTS = int(os.getenv("RATE_LIMIT_ATTEMPTS", "5"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
ALLOWED_ORIGINS = [
	origin.strip()
	for origin in os.getenv(
		"ALLOWED_ORIGINS",
		"http://127.0.0.1:5173,http://localhost:5173,https://koya-clinic-booking-web.onrender.com",
	).split(",")
	if origin.strip()
]