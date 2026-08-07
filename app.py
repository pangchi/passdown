"""
Daily shift passdown app.

No login — pick your name and shift from a dropdown and log a structured
entry (Problem Statement / Action Item(s) / Current Status / Follow up).
Entries are stored in Postgres. See README.md for setup.
"""
import csv
import difflib
import io
import logging
import mimetypes
import os
import threading
import time
import uuid
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timezone

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, abort, Response
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from docx import Document
from docx.shared import Pt, Inches

import config
from db import (
    get_cursor,
    record_db_health,
    init_db,
    get_tool_list,
    get_tool_locations,
    get_names,
    add_name,
    delete_name,
    get_categories,
    add_category,
    delete_category,
    extract_hashtags,
    record_hashtags,
    get_hashtags,
    extract_mentions,
    pg_regex_escape,
    log_entry_edit,
    get_entry_edits,
    soft_delete_entry,
    add_attachment,
    get_attachments_for_entries,
    get_attachment,
    purge_oldest_attachments_over_disk_threshold,
)

app = Flask(__name__)
app.secret_key = "passdown-local-secret"  # local-network tool, no auth — fine as a static key
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024

# Lets the app run correctly behind a reverse proxy (e.g. Apache) that
# mounts it under a subfolder (e.g. https://host/passdown/) rather than
# at the domain root. Apache needs to set X-Forwarded-Prefix (and the
# usual X-Forwarded-Proto/Host/For) — see README.md ("Deploying behind
# Apache") for the exact Apache config. Harmless no-op if those headers
# aren't sent, e.g. when just running `python3 app.py` directly.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

UPLOAD_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), config.UPLOAD_FOLDER))
os.makedirs(UPLOAD_DIR, exist_ok=True)
UPLOAD_ACCEPT = ",".join("." + ext for ext in sorted(config.ALLOWED_EXTENSIONS))

# --- Logging -----------------------------------------------------------
# One log file per day (rotated at midnight), kept for
# config.LOG_RETENTION_DAYS days — TimedRotatingFileHandler's backupCount
# deletes anything older than that automatically as part of rotation, so
# there's no separate purge job to maintain. Attached to the ROOT logger
# (not just app.py's own logger) so events logged from db.py — the
# attachment auto-purge warnings, for instance — land in the same file
# without needing their own handler.
LOG_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), config.LOG_FOLDER))
os.makedirs(LOG_DIR, exist_ok=True)

_log_handler = TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "passdown.log"),
    when="midnight",
    backupCount=config.LOG_RETENTION_DAYS,
    encoding="utf-8",
)
_log_handler.suffix = "%Y-%m-%d"  # ISO 8601 date — explicit rather than relying on the (matching) default


def _iso_date_log_namer(default_name):
    """TimedRotatingFileHandler's own default rotated-file naming is
    "passdown.log.2026-08-05" — the ISO 8601 date is there, but tacked
    on after the extension rather than before it, which reads oddly and
    doesn't sort well next to non-log files. Renames it to
    "passdown-2026-08-05.log" instead — same date, same file, just a
    cleaner name. Only affects files once they've rotated (a completed
    day); the currently-active file stays plain "passdown.log" until
    then, which is the standard convention for this kind of handler —
    not a bug, just "this is the one still being written to right now."
    """
    dir_name, file_name = os.path.split(default_name)
    stem, ext, date_str = file_name.split(".", 2)  # "passdown.log.2026-08-05" -> [stem, ext, date]
    return os.path.join(dir_name, f"{stem}-{date_str}.{ext}")


_log_handler.namer = _iso_date_log_namer
_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(_log_handler)
logging.getLogger().setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# Separate logger (still lands in the same passdown.log file, via the
# same root-logger handler set up above) specifically for usage/traffic
# — which pages get visited, how often, by roughly whom — as opposed to
# the "logger" above, which is for business events (entry added, name
# removed, etc.). Kept as its own logger name ("usage") so the two kinds
# of log lines are easy to tell apart or filter separately, e.g.
# `grep '] usage:' passdown.log` for just traffic, `grep -v '] usage:'`
# for everything else.
usage_logger = logging.getLogger("usage")

# Captured once when this process starts (i.e. whenever the app was last
# started/restarted — the closest thing to a "build date" without a real
# CI/build pipeline). Shown in the page footer so it's easy to tell
# whether a deployed change actually took effect. Timezone-aware (UTC) so
# the footer can render it correctly in the viewer's own local time, same
# as every other timestamp in this app.
APP_STARTED_AT = datetime.now(timezone.utc)


@app.context_processor
def _inject_app_started_at():
    """Makes app_started_at (and app_version) available in every template
    without having to pass them explicitly from each render_template call
    — the footer lives in base.html, which every page extends."""
    return {"app_started_at": APP_STARTED_AT.isoformat(), "app_version": config.APP_VERSION}

# Create the table (and indexes) automatically on first launch if they
# don't exist yet. Safe to run on every startup. If the database isn't
# reachable yet (e.g. Postgres is still starting up, or a network blip),
# retry with a warning instead of crashing — see
# config.STARTUP_DB_RETRY_SECONDS / STARTUP_DB_MAX_RETRIES.
#
# This runs in a background thread rather than blocking here directly:
# code at module level runs during gunicorn's worker boot, before the
# worker can accept any connections at all — retrying here synchronously
# would mean the app doesn't even start listening until the database is
# reachable (or retries are exhausted), which defeats the point of
# "retry instead of quit." Running it in the background lets the app
# bind and start serving requests immediately; any request that comes in
# before the database is ready just hits the existing per-request health
# check (db.record_db_health(), see "Database connection health") and
# gets the same degraded-state page a request would get if the database
# went down after a successful startup — one code path handles both.
def _startup_db_retry():
    for attempt in range(1, config.STARTUP_DB_MAX_RETRIES + 1):
        try:
            init_db()
            if attempt > 1:
                logger.info("Database became reachable on startup attempt %d.", attempt)
            break
        except Exception as exc:
            if attempt < config.STARTUP_DB_MAX_RETRIES:
                logger.warning(
                    "Database not reachable on startup (attempt %d/%d): %s — retrying in %ds.",
                    attempt, config.STARTUP_DB_MAX_RETRIES, exc, config.STARTUP_DB_RETRY_SECONDS,
                )
                time.sleep(config.STARTUP_DB_RETRY_SECONDS)
            else:
                logger.error(
                    "Database still not reachable after %d attempts: %s — the app is serving "
                    "requests, but the log page will show a warning until this recovers.",
                    config.STARTUP_DB_MAX_RETRIES, exc,
                )
                return

    # If disk usage is already over threshold, purge oldest attachments —
    # only reachable here once init_db() above actually succeeded.
    try:
        purge_oldest_attachments_over_disk_threshold(UPLOAD_DIR)
    except Exception as exc:
        logger.warning("Startup attachment purge failed: %s", exc)


threading.Thread(target=_startup_db_retry, daemon=True, name="startup-db-retry").start()


def _allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in config.ALLOWED_EXTENSIONS


def _opens_inline(filename):
    """True if this (non-image) attachment should open in a new tab
    instead of forcing a download — see config.INLINE_VIEW_EXTENSIONS."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in config.INLINE_VIEW_EXTENSIONS


app.jinja_env.globals["opens_inline"] = _opens_inline


# Endpoints deliberately excluded from usage logging: static assets (not
# a "page view" — logged every time the browser fetches CSS/JS, which
# would just be noise), and health_json specifically because it's polled
# every 10 seconds for as long as anyone has the page open (see
# index.html) — logging that would dwarf every other usage line in the
# file within minutes and drown out anything actually useful.
_USAGE_LOG_EXCLUDED_ENDPOINTS = {"static", "health_json"}


@app.before_request
def _log_page_view():
    """Log each real page view/action — endpoint, method, and (if the
    request came through Apache with X-Forwarded-For set — see
    deploy/apache-eqpassdown.conf.example) the originating client
    address — to usage_logger, separate from the business-event logging
    elsewhere in this file (entry added, name removed, etc.). This is
    raw traffic data, not aggregated statistics on its own; see the
    README ("Logging") for example commands to derive actual counts
    (busiest page, requests per day, etc.) from it.
    """
    if request.endpoint in _USAGE_LOG_EXCLUDED_ENDPOINTS:
        return
    usage_logger.info("%s %s (endpoint=%s) from %s", request.method, request.path, request.endpoint, request.remote_addr)


def _save_attachments(entry_id, files):
    """Validate, save to disk, and record each uploaded file against entry_id.

    Silently skips empty file inputs and files with disallowed extensions
    (the browser's accept filter already discourages the latter, but
    someone could bypass it, so this is the real enforcement point).
    """
    for f in files:
        if not f or not f.filename:
            continue
        original_filename = secure_filename(f.filename)
        if not original_filename or not _allowed_file(original_filename):
            flash(f'Skipped "{f.filename}" — file type not allowed.', "error")
            logger.warning("Attachment upload for entry #%d rejected (disallowed type): %r", entry_id, f.filename)
            continue

        ext = original_filename.rsplit(".", 1)[-1].lower()
        stored_filename = f"{uuid.uuid4().hex}.{ext}"
        dest_path = os.path.join(UPLOAD_DIR, stored_filename)
        f.save(dest_path)

        mime_type = f.mimetype or mimetypes.guess_type(original_filename)[0]
        file_size = os.path.getsize(dest_path)
        add_attachment(entry_id, stored_filename, original_filename, mime_type, file_size)
        logger.info("Attachment saved for entry #%d: %r (%d bytes)", entry_id, original_filename, file_size)

    # Newly-saved files may have just pushed disk usage over the line —
    # check now rather than waiting for the next app restart.
    purge_oldest_attachments_over_disk_threshold(UPLOAD_DIR)


def _parse_datetime_local(value):
    """Parse an HTML datetime-local field ('YYYY-MM-DDTHH:MM') to a datetime, or None if blank."""
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


def _datetime_local_str(value):
    """Format a value for a datetime-local input's value attribute.

    Accepts a real datetime (from the DB) or a plain string (a raw,
    possibly-invalid resubmission being redisplayed after a validation
    error) — either way returns a string, '' for None/empty.
    """
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%dT%H:%M")


@app.errorhandler(413)
def _file_too_large(_error):
    flash(f"Attachment too large — max {config.MAX_UPLOAD_SIZE_MB} MB per file.", "error")
    return redirect(request.referrer or url_for("index"))


def _new_entry_defaults():
    """Default values for the New Entry form on a plain page load.

    shift/task_start here use the server's own local time (Python
    datetime.now(), i.e. the server OS clock) — if the server runs in a
    different timezone than the people using the app (e.g. server on
    UTC, shop floor on UTC+8), these come out wrong on their own. The
    page's script (index.html) recomputes both from the viewer's actual
    browser clock on a fresh load and overwrites these, so in practice
    this only matters as the no-JS fallback.
    """
    current_hour = datetime.now().hour
    if config.DAY_SHIFT_START_HOUR <= current_hour < config.DAY_SHIFT_END_HOUR:
        default_shift = "Day"
    else:
        default_shift = "Night"
    return {
        "author": "",
        "shift": default_shift,
        "tool_entity": "",
        "chamber": "",
        "category": "",
        "task_start": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "task_end": "",
        "problem_statement": "",
        "action_items": "",
        "current_status": "",
        "follow_up": "",
    }


def _degraded_index_context(new_entry_overrides, db_warning, db_entry_disabled):
    """Context for index.html when the database can't be queried right
    now — empty log, no filter option lists, New Entry form still shown
    (disabled if this has persisted a while). Used both when the
    reachability check itself fails, and as a fallback if a query fails
    for some other reason (e.g. the schema hasn't finished being created
    yet by the startup retry thread — see threading.Thread(...) near the
    top of this file) even though the reachability check passed.
    """
    new_entry = _new_entry_defaults()
    if new_entry_overrides:
        new_entry.update(new_entry_overrides)
    return {
        "entries": [],
        "names": [],
        "shifts": config.SHIFTS,
        "tools": [],
        "categories": [],
        "hashtags": [],
        "shift_filter": "",
        "author_filters": [],
        "tool_filter": "",
        "category_filter": "",
        "tag_filters": [],
        "location_filter": "",
        "locations": [],
        "search_query": "",
        "days_back": config.DEFAULT_DAYS_BACK,
        "new_entry": new_entry,
        "is_fresh_new_entry": new_entry_overrides is None,
        "day_shift_start_hour": config.DAY_SHIFT_START_HOUR,
        "day_shift_end_hour": config.DAY_SHIFT_END_HOUR,
        "upload_accept": UPLOAD_ACCEPT,
        "db_warning": db_warning,
        "db_entry_disabled": db_entry_disabled,
        "db_warning_persist_seconds": config.DB_WARNING_PERSIST_MINUTES * 60,
    }


def _build_index_context(new_entry_overrides=None):
    """Build the full context for index.html: log query results plus filter
    and New Entry form state. Shared by the GET / route and by add_entry()'s
    validation-error path, so a failed submission can be redisplayed with
    everything the person typed still in place instead of a fresh/empty form.
    """
    db_health = record_db_health()
    db_warning = not db_health["ok"]
    db_entry_disabled = db_warning and db_health["down_seconds"] >= config.DB_WARNING_PERSIST_MINUTES * 60

    if not db_health["ok"]:
        # DB is unreachable right now — none of the queries below would
        # succeed, so don't attempt them.
        return _degraded_index_context(new_entry_overrides, db_warning, db_entry_disabled)

    shift_filter = request.args.get("shift", "")
    author_filters = request.args.getlist("author")
    tool_filter = request.args.get("tool_entity", "")
    category_filter = request.args.get("category", "")
    tag_filters = request.args.getlist("tag")
    location_filter = request.args.get("location", "")
    search_query = request.args.get("q", "").strip()
    days_param = request.args.get("days", str(config.DEFAULT_DAYS_BACK))
    if days_param == "all":
        days_back = None  # no lower time bound — show everything
    else:
        try:
            days_back = int(days_param)
        except ValueError:
            days_back = config.DEFAULT_DAYS_BACK

    query = "SELECT * FROM passdown_entries WHERE is_deleted = FALSE"
    params = []
    if days_back is not None:
        query += " AND created_at >= NOW() - (%s * INTERVAL '1 day')"
        params.append(days_back)

    if shift_filter:
        query += " AND shift = %s"
        params.append(shift_filter)
    if author_filters:
        # An entry matches if ANY selected name is either in its author
        # list OR @mentioned in one of its 4 text fields — mention bubbles
        # reuse this same "author" filter (see index.html), so the query
        # needs to actually match both, not just the author column, or
        # clicking a mention bubble would filter the very entry it came
        # from right out of the results.
        name_conditions = []
        for name in author_filters:
            mention_pattern = "@" + pg_regex_escape(name) + r"([^A-Za-z0-9_-]|$)"
            name_conditions.append(
                "(author ILIKE %s OR problem_statement ~* %s OR action_items ~* %s "
                "OR current_status ~* %s OR follow_up ~* %s)"
            )
            params.extend([f"%{name}%", mention_pattern, mention_pattern, mention_pattern, mention_pattern])
        query += " AND (" + " OR ".join(name_conditions) + ")"
    if tool_filter:
        query += " AND tool_entity = %s"
        params.append(tool_filter)
    if category_filter:
        query += " AND category = %s"
        params.append(category_filter)
    if tag_filters:
        # An entry matches if ANY selected tag appears as a complete #tag
        # token in any of the 4 text fields (word-boundary regex, not a
        # plain substring match, so filtering by "#urgent" doesn't also
        # match "#urgent-followup").
        tag_conditions = []
        for tag in tag_filters:
            tag_conditions.append(
                "(problem_statement ~* %s OR action_items ~* %s "
                "OR current_status ~* %s OR follow_up ~* %s)"
            )
            pattern = "#" + tag + r"([^A-Za-z0-9_-]|$)"
            params.extend([pattern, pattern, pattern, pattern])
        query += " AND (" + " OR ".join(tag_conditions) + ")"
    if search_query:
        # Plain substring search across all 4 free-text fields (not
        # word-boundary like the tag filter — this is a general text
        # search, so "urgent" should also match "#urgent" or "urgently").
        query += (
            " AND (problem_statement ILIKE %s OR action_items ILIKE %s "
            "OR current_status ILIKE %s OR follow_up ILIKE %s)"
        )
        search_pattern = f"%{search_query}%"
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

    # Sort by task start when the entry has one, falling back to created_at —
    # keeps the client-side day grouping (which uses the same effective
    # date) contiguous instead of fragmenting into repeated day headers.
    query += " ORDER BY COALESCE(task_start, created_at) DESC"

    try:
        with get_cursor() as cur:
            cur.execute(query, params)
            entries = cur.fetchall()
    except Exception as exc:
        # The reachability check above passed (a plain connection is
        # fine), but this query still failed — most likely the schema
        # hasn't finished being created yet by the startup retry thread.
        # Treat it the same as an unreachable database rather than
        # raising a raw error page. Caught outside the "with" block (not
        # inside) so get_cursor()'s own rollback still runs before the
        # connection goes back to the pool — catching it inside would
        # skip that and risk returning a connection stuck mid-transaction.
        logger.warning("Log query failed even though the DB connection check passed: %s", exc)
        return _degraded_index_context(new_entry_overrides, True, False)

    attachments_by_entry = get_attachments_for_entries([e["id"] for e in entries])
    tool_locations = get_tool_locations()
    team_names = [m["name"] for m in get_names()]
    for e in entries:
        e["attachments"] = attachments_by_entry.get(e["id"], [])
        e["hashtags"] = sorted(
            extract_hashtags(e["problem_statement"], e["action_items"], e["current_status"], e["follow_up"])
        )
        e["location"] = tool_locations.get(e["tool_entity"], "")
        e["mentions"] = sorted(
            extract_mentions(
                team_names, e["problem_statement"], e["action_items"], e["current_status"], e["follow_up"]
            )
        )

    if location_filter:
        # Applied in Python rather than as a SQL join against mestoollist:
        # that view depends on a live FDW connection to the MES database,
        # and get_tool_locations() already degrades gracefully (empty
        # dict) if that's down — a SQL-side join wouldn't degrade as
        # nicely, it'd just fail the whole page's query.
        entries = [e for e in entries if e["location"] == location_filter]

    # Day-grouping and all displayed times are done client-side (see the
    # script in index.html) so they reflect the viewer's own browser
    # timezone rather than the server's — the server only sorts by the
    # absolute instant (created_at DESC above).

    new_entry = _new_entry_defaults()
    # Tool/Entity defaults to the active filter, since selecting a tool in
    # the New Entry form also sets that filter (see the page's script) —
    # this keeps the field showing what triggered it rather than going blank.
    new_entry["tool_entity"] = tool_filter
    if new_entry_overrides:
        new_entry.update(new_entry_overrides)

    return {
        "entries": entries,
        "names": team_names,
        "shifts": config.SHIFTS,
        "tools": get_tool_list(),
        "categories": [c["name"] for c in get_categories()],
        "hashtags": get_hashtags(),
        "shift_filter": shift_filter,
        "author_filters": author_filters,
        "tool_filter": tool_filter,
        "category_filter": category_filter,
        "tag_filters": tag_filters,
        "location_filter": location_filter,
        "search_query": search_query,
        "locations": sorted(set(tool_locations.values())),
        "days_back": days_back,
        "new_entry": new_entry,
        # True on a plain page load (shift/task_start are server-computed
        # defaults, using the server's own local time — see the note by
        # DAY_SHIFT_START_HOUR in config.py). False when new_entry instead
        # holds a person's actual submitted values after a validation
        # error. The page's script uses this to know when it's safe to
        # overwrite shift/task_start with values computed from the
        # viewer's own browser clock instead — see index.html.
        "is_fresh_new_entry": new_entry_overrides is None,
        "day_shift_start_hour": config.DAY_SHIFT_START_HOUR,
        "day_shift_end_hour": config.DAY_SHIFT_END_HOUR,
        "upload_accept": UPLOAD_ACCEPT,
        "db_warning": False,
        "db_entry_disabled": False,
        "db_warning_persist_seconds": config.DB_WARNING_PERSIST_MINUTES * 60,
    }


@app.route("/")
def index():
    return render_template("index.html", **_build_index_context())


@app.route("/health.json")
def health_json():
    """Lightweight DB reachability check as JSON — used by the page's own
    script to detect when the database has come back without requiring a
    manual refresh (see the polling script in index.html, only active
    while the warning banner is showing). Deliberately cheap: just the
    same record_db_health() the rest of the app already uses, no other
    queries.
    """
    return record_db_health()


def _fmt_export_dt(dt):
    """Plain YYYY-MM-DD HH:MM (no timezone offset) — friendlier for
    spreadsheet/Word auto-recognition than raw ISO8601, and consistent
    across all three export formats."""
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def _export_filename(extension):
    return "passdown_export_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "." + extension


def _get_export_entries():
    """Entries for the current filters, oldest first — the opposite order
    from the log page itself (which is newest-first), since a downloaded
    report reads more naturally chronologically."""
    entries = _build_index_context()["entries"]
    return list(reversed(entries))


@app.route("/export.csv")
def export_csv():
    """Download the currently-filtered log as CSV — reuses the exact same
    filtering logic as the log page itself (same query params: shift,
    author, tool_entity, category, tag, location, q, days), so whatever
    filters are active on the page you clicked "Download CSV" from are
    exactly what ends up in the file.
    """
    entries = _get_export_entries()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Logged At", "Task Start", "Task End", "Name(s)", "Shift", "Tool/Entity",
            "Chamber", "Category", "Location", "Problem Statement", "Action Item(s)",
            "Current Status", "Follow up", "Tags", "Mentions",
        ]
    )

    for e in entries:
        writer.writerow(
            [
                _fmt_export_dt(e["created_at"]),
                _fmt_export_dt(e["task_start"]),
                _fmt_export_dt(e["task_end"]),
                e["author"],
                e["shift"],
                e["tool_entity"],
                e["chamber"] or "",
                e["category"] if e["category"] != "unspecified" else "",
                e.get("location", ""),
                e["problem_statement"],
                e["action_items"] or "",
                e["current_status"] or "",
                e["follow_up"] or "",
                ", ".join("#" + t for t in e.get("hashtags", [])),
                ", ".join("@" + m for m in e.get("mentions", [])),
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{_export_filename("csv")}"'},
    )


@app.route("/export.docx")
def export_docx():
    """Download the currently-filtered log as a Word document — one
    section per entry, same filtering as export_csv()/the log page.
    Image attachments are embedded directly in the document (not just
    linked/listed) as long as they're under config.EXPORT_INLINE_IMAGE_MAX_MB;
    larger images and non-image files are listed by name instead, since
    there's no lightweight way to embed an arbitrary file inline in a
    Word document the way an image can be.
    """
    entries = _get_export_entries()

    doc = Document()
    doc.add_heading("Shift Passdown Log", level=1)
    meta = doc.add_paragraph(
        f"Exported {datetime.now().strftime('%Y-%m-%d %H:%M')} \u2014 {len(entries)} "
        f"{'entry' if len(entries) == 1 else 'entries'}"
    )
    meta.runs[0].italic = True
    meta.runs[0].font.size = Pt(9)

    def add_labeled_line(label, value):
        p = doc.add_paragraph()
        p.add_run(label + ": ").bold = True
        p.add_run(value)

    inline_max_bytes = config.EXPORT_INLINE_IMAGE_MAX_MB * 1024 * 1024

    if not entries:
        doc.add_paragraph("No entries match the current filters.")

    for e in entries:
        doc.add_heading(
            f"{_fmt_export_dt(e['created_at'])} \u2014 {e['author']} ({e['shift']})", level=2
        )

        meta_bits = [f"Tool/Entity: {e['tool_entity']}"] if e["tool_entity"] else []
        if e.get("location"):
            meta_bits.append(f"Location: {e['location']}")
        if e["chamber"]:
            meta_bits.append(f"Chamber: {e['chamber']}")
        if e["category"] and e["category"] != "unspecified":
            meta_bits.append(f"Category: {e['category']}")
        if meta_bits:
            doc.add_paragraph(" | ".join(meta_bits))

        if e["task_start"] or e["task_end"]:
            add_labeled_line(
                "Task", f"{_fmt_export_dt(e['task_start'])} \u2013 {_fmt_export_dt(e['task_end'])}"
            )

        add_labeled_line("Problem Statement", e["problem_statement"])
        if e["action_items"]:
            add_labeled_line("Action Item(s)", e["action_items"])
        if e["current_status"]:
            add_labeled_line("Current Status", e["current_status"])
        if e["follow_up"]:
            add_labeled_line("Follow up", e["follow_up"])

        if e.get("hashtags"):
            add_labeled_line("Tags", ", ".join("#" + t for t in e["hashtags"]))
        if e.get("mentions"):
            add_labeled_line("Mentions", ", ".join("@" + m for m in e["mentions"]))

        if e.get("attachments"):
            p = doc.add_paragraph()
            p.add_run("Attachments:").bold = True
            for a in e["attachments"]:
                is_image = a["mime_type"] and a["mime_type"].startswith("image/")
                file_path = os.path.join(UPLOAD_DIR, a["stored_filename"])
                if is_image and a["file_size"] and a["file_size"] <= inline_max_bytes and os.path.isfile(file_path):
                    try:
                        doc.add_picture(file_path, width=Inches(4))
                        doc.paragraphs[-1].add_run(a["original_filename"]).italic = True
                        continue
                    except Exception:
                        pass  # corrupt/unreadable image file — fall through to listing it by name below
                size_mb = (a["file_size"] / (1024 * 1024)) if a["file_size"] else 0
                doc.add_paragraph(f"\u2022 {a['original_filename']} ({size_mb:.1f} MB, not embedded)")

        doc.add_paragraph()  # spacer between entries

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    return Response(
        buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{_export_filename("docx")}"'},
    )


@app.route("/export.html")
def export_html():
    """Download the currently-filtered log as a standalone HTML file —
    same filtering as export_csv()/export_docx()/the log page, but
    self-contained (inline styles, no dependency on the app's own
    static files) so it still looks right opened later, offline, from
    wherever it was saved. The one thing that still needs the app
    reachable is attachments — those link back to the live server (there's
    no lightweight way to embed arbitrary files, including large images,
    directly in an HTML file without risking a huge/unwieldy export), so
    they only work while opened from a device that can reach this server.
    """
    entries = _get_export_entries()
    html = render_template(
        "export.html",
        entries=entries,
        fmt=_fmt_export_dt,
        exported_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    return Response(
        html,
        mimetype="text/html",
        headers={"Content-Disposition": f'attachment; filename="{_export_filename("html")}"'},
    )


@app.route("/add", methods=["POST"])
def add_entry():
    db_health = record_db_health()
    if not db_health["ok"] and db_health["down_seconds"] >= config.DB_WARNING_PERSIST_MINUTES * 60:
        flash(
            "Can't save right now — the database connection has been down "
            "for a while. Try again once it's back.",
            "error",
        )
        return redirect(url_for("index"))

    author = request.form.get("author", "").strip()
    shift = request.form.get("shift", "").strip()
    tool_entity = request.form.get("tool_entity", "").strip()
    chamber = request.form.get("chamber", "").strip()
    category = request.form.get("category", "").strip()
    problem_statement = request.form.get("problem_statement", "").strip()
    action_items = request.form.get("action_items", "").strip()
    current_status = request.form.get("current_status", "").strip()
    follow_up = request.form.get("follow_up", "").strip()
    task_start_raw = request.form.get("task_start", "").strip()
    task_end_raw = request.form.get("task_end", "").strip()

    # Everything typed so far, kept around so a validation error can
    # redisplay the form with it all still in place instead of clearing it.
    submitted = {
        "author": author,
        "shift": shift or _new_entry_defaults()["shift"],
        "tool_entity": tool_entity,
        "chamber": chamber,
        "category": category,
        "task_start": task_start_raw,
        "task_end": task_end_raw,
        "problem_statement": problem_statement,
        "action_items": action_items,
        "current_status": current_status,
        "follow_up": follow_up,
    }

    def _redisplay_with_error(message):
        flash(message, "error")
        context = _build_index_context(new_entry_overrides=submitted)
        return render_template("index.html", **context), 400

    try:
        task_start = _parse_datetime_local(task_start_raw)
        task_end = _parse_datetime_local(task_end_raw)
    except ValueError:
        return _redisplay_with_error("Task start/end date-time is invalid.")

    if not author or not shift or not tool_entity or not category or not problem_statement:
        return _redisplay_with_error("Name, shift, tool/entity, category, and problem statement are all required.")

    if task_start and task_end and task_end < task_start:
        return _redisplay_with_error("Task end can't be before task start.")

    # A transient DB failure that hasn't persisted long enough to trip the
    # guard at the top of this route (or one that starts mid-request) can
    # still land here — catch it so the person gets a clear flash message
    # instead of a raw error page.
    try:
        valid_categories = [c["name"] for c in get_categories()]
        if category not in valid_categories:
            return _redisplay_with_error("Category must be one of: " + ", ".join(valid_categories) + ".")

        with get_cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO passdown_entries
                   (author, shift, tool_entity, chamber, category, task_start, task_end,
                    problem_statement, action_items, current_status, follow_up)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    author, shift, tool_entity, chamber or None, category, task_start, task_end,
                    problem_statement, action_items or None, current_status or None, follow_up or None,
                ),
            )
            new_id = cur.fetchone()["id"]
    except Exception:
        flash("Couldn't save the entry — a database error occurred. Please try again.", "error")
        return redirect(url_for("index"))

    record_hashtags(extract_hashtags(problem_statement, action_items, current_status, follow_up))
    _save_attachments(new_id, request.files.getlist("attachments"))

    logger.info("Entry #%d added by %r (shift=%s, tool=%s, category=%s)", new_id, author, shift, tool_entity, category)
    flash("Entry added.", "success")
    return redirect(url_for("index"))


_EDIT_HISTORY_FIELD_LABELS = [
    ("author", "Name(s)"),
    ("problem_statement", "Problem Statement"),
    ("action_items", "Action Item(s)"),
    ("current_status", "Current Status"),
    ("follow_up", "Follow up"),
]


def _word_diff_html(old_text, new_text):
    """Word-level diff from old_text to new_text, rendered as HTML with
    removed words wrapped in <del> and added words in <ins>. Returns None
    if the two are identical, so callers can skip fields that didn't
    change. Each word is HTML-escaped individually before being wrapped,
    so this is safe to render with Jinja's |safe (there's no way for
    entry text to inject markup here).
    """
    old_text = old_text or ""
    new_text = new_text or ""
    if old_text == new_text:
        return None

    old_words = old_text.split()
    new_words = new_text.split()
    matcher = difflib.SequenceMatcher(None, old_words, new_words)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(str(escape(" ".join(old_words[i1:i2]))))
        elif tag == "delete":
            parts.append("<del>" + str(escape(" ".join(old_words[i1:i2]))) + "</del>")
        elif tag == "insert":
            parts.append("<ins>" + str(escape(" ".join(new_words[j1:j2]))) + "</ins>")
        elif tag == "replace":
            parts.append("<del>" + str(escape(" ".join(old_words[i1:i2]))) + "</del>")
            parts.append("<ins>" + str(escape(" ".join(new_words[j1:j2]))) + "</ins>")
    return Markup(" ".join(parts))


def _build_edit_history_with_diffs(entry, edit_history):
    """Turn raw edit-history rows (newest first, each holding the field
    values right before that edit) into what actually changed at each
    edit — highlighted word-diffs, with unchanged fields left out
    entirely rather than repeating text nobody touched.

    "What changed" for a given historical snapshot means: compare its
    previous_* values against whatever those fields became next — either
    the *next* snapshot in the list (chronologically newer), or the
    entry's current live value for the most recent snapshot, since
    there's nothing newer than that to compare against.
    """
    diffs = []
    for i, edit in enumerate(edit_history):
        after = edit_history[i - 1] if i > 0 else entry

        changed_fields = []
        for field, label in _EDIT_HISTORY_FIELD_LABELS:
            after_value = after["previous_" + field] if i > 0 else after[field]
            diff_html = _word_diff_html(edit["previous_" + field], after_value)
            if diff_html is not None:
                changed_fields.append((label, diff_html))

        task_start_after = after["previous_task_start"] if i > 0 else after["task_start"]
        task_end_after = after["previous_task_end"] if i > 0 else after["task_end"]
        task_changed = (
            edit["previous_task_start"] != task_start_after
            or edit["previous_task_end"] != task_end_after
        )

        diffs.append(
            {
                "edited_at": edit["edited_at"],
                "changed_fields": changed_fields,
                "task_changed": task_changed,
                "previous_task_start": edit["previous_task_start"],
                "previous_task_end": edit["previous_task_end"],
                "task_start_after": task_start_after,
                "task_end_after": task_end_after,
            }
        )
    return diffs


def _build_edit_display(current, overrides=None):
    """Build the entry dict edit_entry.html renders from: a copy of the DB
    row with task_start/task_end pre-formatted as datetime-local strings,
    optionally overridden with a failed resubmission's raw values so the
    edit form can be redisplayed with everything still in place.
    """
    display = dict(current)
    display["task_start"] = _datetime_local_str(display.get("task_start"))
    display["task_end"] = _datetime_local_str(display.get("task_end"))
    if overrides:
        display.update(overrides)
    return display


@app.route("/edit/<int:entry_id>", methods=["GET", "POST"])
def edit_entry(entry_id):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM passdown_entries WHERE id = %s AND is_deleted = FALSE", (entry_id,))
        current = cur.fetchone()

    if current is None:
        flash("Entry not found.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        author = request.form.get("author", "").strip()
        problem_statement = request.form.get("problem_statement", "").strip()
        action_items = request.form.get("action_items", "").strip()
        current_status = request.form.get("current_status", "").strip()
        follow_up = request.form.get("follow_up", "").strip()
        task_start_raw = request.form.get("task_start", "").strip()
        task_end_raw = request.form.get("task_end", "").strip()

        submitted = {
            "author": author,
            "problem_statement": problem_statement,
            "action_items": action_items,
            "current_status": current_status,
            "follow_up": follow_up,
            "task_start": task_start_raw,
            "task_end": task_end_raw,
        }

        def _redisplay_with_error(message):
            flash(message, "error")
            return render_template(
                "edit_entry.html",
                entry=_build_edit_display(current, submitted),
                edit_history=_build_edit_history_with_diffs(current, get_entry_edits(entry_id)),
                attachments=get_attachments_for_entries([entry_id]).get(entry_id, []),
                names=[m["name"] for m in get_names()],
                hashtags=get_hashtags(),
                upload_accept=UPLOAD_ACCEPT,
            ), 400

        try:
            task_start = _parse_datetime_local(task_start_raw)
            task_end = _parse_datetime_local(task_end_raw)
        except ValueError:
            return _redisplay_with_error("Task start/end date-time is invalid.")

        if not author:
            return _redisplay_with_error("At least one name is required.")

        if not problem_statement:
            return _redisplay_with_error("Problem statement can't be empty.")

        if task_start and task_end and task_end < task_start:
            return _redisplay_with_error("Task end can't be before task start.")

        # Snapshot the pre-edit version before changing anything, so the
        # previous field values are never lost — only added to.
        log_entry_edit(
            entry_id,
            current["author"],
            current["problem_statement"],
            current["action_items"],
            current["current_status"],
            current["follow_up"],
            current["task_start"],
            current["task_end"],
        )

        with get_cursor(commit=True) as cur:
            cur.execute(
                """UPDATE passdown_entries
                   SET author = %s, problem_statement = %s, action_items = %s, current_status = %s,
                       follow_up = %s, task_start = %s, task_end = %s, updated_at = NOW()
                   WHERE id = %s""",
                (
                    author, problem_statement, action_items or None, current_status or None,
                    follow_up or None, task_start, task_end, entry_id,
                ),
            )

        record_hashtags(extract_hashtags(problem_statement, action_items, current_status, follow_up))
        _save_attachments(entry_id, request.files.getlist("attachments"))

        logger.info("Entry #%d edited (author now %r)", entry_id, author)
        flash("Entry updated.", "success")
        return redirect(url_for("index"))

    return render_template(
        "edit_entry.html",
        entry=_build_edit_display(current),
        edit_history=_build_edit_history_with_diffs(current, get_entry_edits(entry_id)),
        attachments=get_attachments_for_entries([entry_id]).get(entry_id, []),
        names=[m["name"] for m in get_names()],
        hashtags=get_hashtags(),
        upload_accept=UPLOAD_ACCEPT,
    )


@app.route("/delete/<int:entry_id>", methods=["POST"])
def delete_entry(entry_id):
    soft_delete_entry(entry_id)
    logger.info("Entry #%d removed from log (soft delete)", entry_id)
    flash("Entry removed from the log (kept in the database for the record).", "success")
    return redirect(url_for("index"))


@app.route("/uploads/<int:attachment_id>")
def download_attachment(attachment_id):
    attachment = get_attachment(attachment_id)
    if attachment is None:
        abort(404)
    return send_from_directory(
        UPLOAD_DIR,
        attachment["stored_filename"],
        as_attachment=False,
        download_name=attachment["original_filename"],
        mimetype=attachment["mime_type"],
    )


@app.route("/guide")
def user_guide():
    return render_template("guide.html")


@app.route("/names")
def manage_names():
    return render_template("manage_names.html", members=get_names())


@app.route("/names/add", methods=["POST"])
def add_name_route():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Enter a name.", "error")
    else:
        add_name(name)
        logger.info("Team member added: %r", name)
        flash(f'Added "{name}".', "success")
    return redirect(url_for("manage_names"))


@app.route("/names/delete/<int:member_id>", methods=["POST"])
def delete_name_route(member_id):
    delete_name(member_id)
    logger.info("Team member #%d removed", member_id)
    flash("Removed.", "success")
    return redirect(url_for("manage_names"))


@app.route("/categories")
def manage_categories():
    return render_template("manage_categories.html", categories=get_categories())


@app.route("/categories/add", methods=["POST"])
def add_category_route():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Enter a category.", "error")
    else:
        add_category(name)
        logger.info("Category added: %r", name)
        flash(f'Added "{name}".', "success")
    return redirect(url_for("manage_categories"))


@app.route("/categories/delete/<int:category_id>", methods=["POST"])
def delete_category_route(category_id):
    delete_category(category_id)
    logger.info("Category #%d removed", category_id)
    flash("Removed.", "success")
    return redirect(url_for("manage_categories"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.APP_PORT, debug=False)
