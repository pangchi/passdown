"""
App/team configuration for the shift passdown app.

Edit NAMES and SHIFTS below to match your team/site.
Database connection settings live separately in db_config.py.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Seed value for the "Name" dropdown — only used to populate the
# team_members table the very first time the app runs (when that table
# is empty). After that, manage names from the app itself at /names
# (add/remove) rather than editing this list. Leave empty to start with
# no names — add them via the "+" link next to the Name dropdown.
NAMES = []

# Shift labels shown in the "Shift" dropdown. The add-entry form
# auto-selects based on time of day — see DAY_SHIFT_START_HOUR /
# DAY_SHIFT_END_HOUR below.
SHIFTS = [
    "Day",
    "Night",
]

# Hours (24h, local server time) during which "Day" is auto-selected on
# the add-entry form; outside this range "Night" is auto-selected.
DAY_SHIFT_START_HOUR = 8   # 08:00
DAY_SHIFT_END_HOUR = 21    # 21:00

# Tool/entity dropdown — sourced live from a database view (e.g. from
# your MES) rather than a static list here. Update these two to match
# the actual view/column names in your database.
MESTOOLLIST_VIEW = "mestoollist"
MESTOOLLIST_COLUMN = "mestoolname"

# Seed values for the "Category" dropdown — only used to populate the
# categories table the very first time it's empty. After that, manage
# categories from the app itself at /categories (add/remove) rather than
# editing this list.
CATEGORIES = [
    "PM",   # Preventive Maintenance
    "CM",   # Corrective Maintenance
    "SPC",  # Statistical Process Control
]

# How many days of history to show on the main page by default.
DEFAULT_DAYS_BACK = 14

# --- Attachments ---------------------------------------------------------
# Folder files are saved to, relative to app.py (created automatically).
# Deliberately outside the app's own folder (a sibling directory) so it
# survives a redeploy that replaces the passdown/ folder wholesale (e.g.
# re-cloning/re-extracting the app), and so it's a separate, obvious
# target for backups.
UPLOAD_FOLDER = "../eqpassdown_uploads"

# Max size per individual attachment, in megabytes.
MAX_UPLOAD_SIZE_MB = 200

# File extensions accepted for upload (lowercase, no dot). Images in this
# list are shown inline in the log; videos are shown inline too (a
# playable <video> element, not just a download link) — e.g. a phone's
# WhatsApp-exported clip; everything else shows as a download link.
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
VIDEO_EXTENSIONS = {"mp4", "mov", "webm"}
OTHER_ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | OTHER_ALLOWED_EXTENSIONS

# Auto-purge: if the disk holding UPLOAD_FOLDER is at or above this
# fraction full, the oldest attachments are permanently deleted (file +
# database row) — oldest first — until usage drops back below it or
# there's nothing left to purge. Unlike everything else in this app,
# this IS destructive: a purged attachment cannot be recovered. Checked
# at app startup and after every upload. Set to 1.0 (or higher) to
# effectively disable it.
ATTACHMENT_PURGE_DISK_THRESHOLD = 0.8

# Safety valve: purge at most this many attachments in a single check,
# even if usage is still over threshold afterward — prevents one bad
# check (e.g. a full disk from something unrelated) from wiping out the
# entire attachment history in one pass.
ATTACHMENT_PURGE_BATCH_LIMIT = 100

# Image attachments up to this size are embedded directly in DOCX exports
# (see /export.docx). Since MAX_UPLOAD_SIZE_MB can be much larger (200 MB
# by default), embedding every image regardless of size could make an
# export with several large photos huge and slow to generate — larger
# images just get listed by filename instead, same as non-image files.
EXPORT_INLINE_IMAGE_MAX_MB = 10

# --- Database connection health -------------------------------------------
# Every load of the log page does a cheap reachability check (SELECT 1).
# A failing check shows a warning banner immediately. If it keeps failing
# continuously for at least this many minutes, the New Entry form is also
# disabled (submit button grayed out client-side, server also rejects
# submissions) rather than letting people type entries that can't
# actually be saved. A brief blip shows the warning but doesn't block
# entry — it has to persist to actually disable anything.
DB_WARNING_PERSIST_MINUTES = 5

# --- Bounding how long a hung database can block a request ------------------
# Without these, a database that's silently unreachable (packets dropped,
# no TCP reset ever received — not the same as a fast "connection
# refused") can make a query hang far longer than you'd expect, tying up
# a whole gunicorn worker for the duration. This app doesn't use asyncio
# (a genuine non-blocking rewrite was tried and rolled back — see git
# history/README notes — as too large/risky a change), so these are the
# practical alternative: bound the *worst case* instead.
#
# DB_CONNECT_TIMEOUT_SECONDS: passed to psycopg2 as connect_timeout —
# bounds how long establishing a brand new connection can take.
#
# DB_KEEPALIVE_SECONDS: TCP keepalive probing on every pooled connection,
# so a connection whose peer silently vanished (network partition, DB
# host crashed without closing sockets cleanly) gets detected and killed
# within roughly this many seconds, instead of the OS default (often
# effectively hours) — this is what actually protects a long-running
# QUERY, not just the initial connect, from hanging indefinitely.
#
# DB_HEALTH_CHECK_TIMEOUT_SECONDS: the health check specifically (used by
# /health.json and every page load) additionally runs in a background
# thread with this as a hard ceiling — belt-and-suspenders on top of the
# above, since it's the one DB call polled most frequently (every 10s per
# open browser tab — see index.html).
DB_CONNECT_TIMEOUT_SECONDS = 3
DB_KEEPALIVE_SECONDS = 3
DB_HEALTH_CHECK_TIMEOUT_SECONDS = 3

# --- Startup database retry -------------------------------------------------
# If the database isn't reachable when the app process starts, retry
# instead of crashing outright — waits STARTUP_DB_RETRY_SECONDS between
# attempts, logging a warning each time, for up to STARTUP_DB_MAX_RETRIES
# attempts. If it's still not reachable after that, the app keeps serving
# requests in a degraded state (see DB_WARNING_PERSIST_MINUTES above)
# rather than refusing to start at all — the ongoing per-request health
# check will pick things up once the database comes back.
#
# This retry runs in a background thread (see threading.Thread(...) in
# app.py), not blocking startup itself — the app binds and starts
# accepting requests immediately regardless of database state, so these
# values aren't constrained by gunicorn's worker boot timeout the way a
# blocking retry would be. Raise them freely if your database sometimes
# takes a while to come up.
STARTUP_DB_RETRY_SECONDS = 5
STARTUP_DB_MAX_RETRIES = 6  # worst case ~30s of background retrying

# --- Logging -----------------------------------------------------------------
# Folder log files are written to, relative to app.py (created
# automatically). Deliberately outside the app's own folder — same
# reasoning as UPLOAD_FOLDER: survives a redeploy that replaces the app
# folder wholesale, and is an obvious separate target for backups.
LOG_FOLDER = "../passdown_logs"

# Log files rotate at midnight and the last this-many days are kept —
# anything older is deleted automatically by the rotation itself
# (Python's TimedRotatingFileHandler backupCount), no separate cleanup
# job needed.
LOG_RETENTION_DAYS = 90

# --- Version -----------------------------------------------------------------
# Shown in the page footer (next to the build date) and referenced in
# README.md's Version section. Bump this when you make a meaningful
# change, so "what version is actually running" and "what does the
# README say the latest version is" can be compared at a glance.
APP_VERSION = "1.1.0"

# Non-image extensions that open in a new tab instead of forcing a download.
# Honest caveat: browsers only have a genuine built-in viewer for PDF —
# for Word/Excel this just omits the "download" attribute and lets the
# browser/OS decide what to do with it, which in practice often still
# means it downloads or opens in a desktop app rather than rendering
# inline. It's still useful (no forced "Save As" prompt on file types the
# OS already knows how to open), just not the same guarantee as PDF.
INLINE_VIEW_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx"}

# Port the Flask dev/prod server listens on.
APP_PORT = int(os.environ.get("PASSDOWN_APP_PORT", "5050"))
