"""
Database connection settings for the shift passdown app.

Values are read from environment variables (see .env.example), so
credentials don't need to live in source code. Edit the defaults below
only for local/dev convenience.
"""
import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.environ.get("PASSDOWN_DB_HOST", "localhost")
DB_PORT = os.environ.get("PASSDOWN_DB_PORT", "5432")
DB_NAME = os.environ.get("PASSDOWN_DB_NAME", "passdown")
DB_USER = os.environ.get("PASSDOWN_DB_USER", "passdown")
DB_PASSWORD = os.environ.get("PASSDOWN_DB_PASSWORD", "")

# Timezone used for displaying and interpreting all timestamps (task
# start/end, entry created/edited times). Must be a valid IANA name
# (e.g. "Asia/Singapore", "America/New_York", "Europe/London"). Applied
# to every Postgres session this app opens, so all TIMESTAMPTZ
# read/write goes through this zone regardless of the DB server's own
# default timezone.
APP_TIMEZONE = os.environ.get("PASSDOWN_TIMEZONE", "Asia/Singapore")
