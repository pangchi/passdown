"""Small Postgres connection pool wrapper used by app.py."""
import logging
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool

import db_config

_pool = None


def init_pool(minconn=1, maxconn=5):
    global _pool
    if _pool is None:
        import config

        _pool = SimpleConnectionPool(
            minconn,
            maxconn,
            host=db_config.DB_HOST,
            port=db_config.DB_PORT,
            dbname=db_config.DB_NAME,
            user=db_config.DB_USER,
            password=db_config.DB_PASSWORD,
            # Sets the session timezone on every connection this pool opens,
            # so all TIMESTAMPTZ values are read/written in local time
            # regardless of the Postgres server's own default timezone.
            options=f"-c timezone={db_config.APP_TIMEZONE}",
            # Bounds how long establishing a brand-new connection can take
            # (see config.DB_CONNECT_TIMEOUT_SECONDS for why).
            connect_timeout=config.DB_CONNECT_TIMEOUT_SECONDS,
            # TCP keepalive so a connection whose peer silently vanished
            # gets detected and killed within roughly
            # config.DB_KEEPALIVE_SECONDS, instead of hanging on it
            # indefinitely the next time something tries to use it.
            keepalives=1,
            keepalives_idle=config.DB_KEEPALIVE_SECONDS,
            keepalives_interval=config.DB_KEEPALIVE_SECONDS,
            keepalives_count=2,
        )
    return _pool


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS passdown_entries (
    id                  SERIAL PRIMARY KEY,
    author              TEXT         NOT NULL,
    shift               VARCHAR(50)  NOT NULL,
    tool_entity         VARCHAR(150) NOT NULL,
    chamber             VARCHAR(100),
    category            VARCHAR(20)  NOT NULL DEFAULT 'unspecified',
    task_start          TIMESTAMPTZ,
    task_end            TIMESTAMPTZ,
    problem_statement   TEXT         NOT NULL,
    action_items        TEXT,
    current_status      TEXT,
    follow_up           TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ
);

-- author holds a comma-separated list of names now (an entry can involve
-- more than one person) — widen it from the old VARCHAR(100) if needed.
ALTER TABLE passdown_entries ALTER COLUMN author TYPE TEXT;
-- Adds the column if this table already existed from before tool_entity was introduced.
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS tool_entity VARCHAR(150);

-- Backfill any existing rows saved back when the field was optional, so the
-- NOT NULL constraint below can be applied safely.
UPDATE passdown_entries SET tool_entity = 'unspecified' WHERE tool_entity IS NULL;

ALTER TABLE passdown_entries ALTER COLUMN tool_entity SET NOT NULL;

-- Adds task_start/task_end if this table existed before they were introduced.
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS task_start TIMESTAMPTZ;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS task_end TIMESTAMPTZ;

-- Adds chamber (free text, optional) and category (PM/CM/SPC, required)
-- if this table existed before they were introduced.
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS chamber VARCHAR(100);
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS category VARCHAR(20);
UPDATE passdown_entries SET category = 'unspecified' WHERE category IS NULL;
ALTER TABLE passdown_entries ALTER COLUMN category SET NOT NULL;
ALTER TABLE passdown_entries ALTER COLUMN category SET DEFAULT 'unspecified';

-- The single free-text "note" field was replaced by 4 structured fields.
-- No prior note data needed preserving, so the old column is just dropped.
ALTER TABLE passdown_entries DROP COLUMN IF EXISTS note;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS problem_statement TEXT;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS action_items TEXT;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS current_status TEXT;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS follow_up TEXT;
UPDATE passdown_entries SET problem_statement = 'unspecified' WHERE problem_statement IS NULL;
ALTER TABLE passdown_entries ALTER COLUMN problem_statement SET NOT NULL;

-- Soft delete: entries are marked, never removed. is_deleted defaults FALSE
-- so plain "ADD COLUMN" is safe on an existing table with rows.
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_passdown_created_at ON passdown_entries (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_passdown_shift ON passdown_entries (shift);
CREATE INDEX IF NOT EXISTS idx_passdown_author ON passdown_entries (author);
CREATE INDEX IF NOT EXISTS idx_passdown_tool_entity ON passdown_entries (tool_entity);
CREATE INDEX IF NOT EXISTS idx_passdown_category ON passdown_entries (category);
CREATE INDEX IF NOT EXISTS idx_passdown_is_deleted ON passdown_entries (is_deleted);

-- Snapshot of an entry's editable fields taken right before each edit, so
-- edits never overwrite history — they only add to it.
CREATE TABLE IF NOT EXISTS passdown_entry_edits (
    id                         SERIAL PRIMARY KEY,
    entry_id                   INTEGER NOT NULL REFERENCES passdown_entries(id),
    previous_author            TEXT,
    previous_problem_statement TEXT,
    previous_action_items      TEXT,
    previous_current_status    TEXT,
    previous_follow_up         TEXT,
    previous_task_start        TIMESTAMPTZ,
    previous_task_end          TIMESTAMPTZ,
    edited_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Same "note" -> 4-field split applied to the history table. No prior
-- edit-history data needed preserving, so the old column is just dropped.
ALTER TABLE passdown_entry_edits DROP COLUMN IF EXISTS previous_note;
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_problem_statement TEXT;
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_action_items TEXT;
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_current_status TEXT;
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_follow_up TEXT;

-- Name became editable too — track its prior value the same way.
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_author TEXT;

-- Tool/Entity became editable too — same reasoning.
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_tool_entity VARCHAR(150);

CREATE INDEX IF NOT EXISTS idx_passdown_edits_entry_id ON passdown_entry_edits (entry_id);

CREATE TABLE IF NOT EXISTS team_members (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Category options (PM/CM/SPC by default) for the "Category" dropdown.
-- Managed from the app itself at /categories, same pattern as team_members.
CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Hashtags used in free-text fields (#tag). No manual management page —
-- these are learned automatically: whenever an entry is saved, any
-- #tags found in its text fields are upserted here, bumping
-- last_used_at. Powers the "#" autocomplete in the free-text fields.
CREATE TABLE IF NOT EXISTS hashtags (
    id            SERIAL PRIMARY KEY,
    tag           VARCHAR(100) NOT NULL UNIQUE,
    last_used_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hashtags_last_used ON hashtags (last_used_at DESC);

-- Attachments uploaded with an entry. The file itself is saved to
-- config.UPLOAD_FOLDER on disk under stored_filename; this row is just
-- the metadata + pointer.
CREATE TABLE IF NOT EXISTS passdown_attachments (
    id                 SERIAL PRIMARY KEY,
    entry_id           INTEGER NOT NULL REFERENCES passdown_entries(id),
    stored_filename    VARCHAR(255) NOT NULL,
    original_filename  VARCHAR(255) NOT NULL,
    mime_type          VARCHAR(100),
    file_size          INTEGER,
    uploaded_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Removing an attachment from the edit page is soft, same as removing an
-- entry — the row (and the file on disk) stay put, just hidden. is_deleted
-- defaults FALSE so plain "ADD COLUMN" is safe on an existing table with rows.
ALTER TABLE passdown_attachments ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE passdown_attachments ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_passdown_attachments_entry_id ON passdown_attachments (entry_id);
"""


def init_db():
    """Create tables/indexes if they don't exist yet, and seed team_members
    and categories.

    Safe to call on every startup — CREATE TABLE/INDEX IF NOT EXISTS is a
    no-op once the schema is already there. Both tables are only seeded
    from config.NAMES / config.CATEGORIES the first time (i.e. when empty),
    so entries added/removed later through the app aren't overwritten on
    restart.
    """
    pool = init_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(SCHEMA_SQL)

        import config

        cur.execute("SELECT COUNT(*) FROM team_members")
        (count,) = cur.fetchone()
        if count == 0:
            for name in config.NAMES:
                cur.execute(
                    "INSERT INTO team_members (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                    (name,),
                )

        cur.execute("SELECT COUNT(*) FROM categories")
        (count,) = cur.fetchone()
        if count == 0:
            for name in config.CATEGORIES:
                cur.execute(
                    "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                    (name,),
                )

        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(commit=False):
    """Yield a dict-cursor from the pool, returning the connection when done."""
    pool = init_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        pool.putconn(conn)


_db_down_since = None  # epoch seconds since the DB started failing, or None if healthy


# A small dedicated pool just for check_connection() — kept tiny (2
# threads) since it's only ever running this one cheap check, even under
# concurrent polling from several open browser tabs. Separate from
# get_cursor()'s connection pool (which is about pooling actual Postgres
# connections, not threads).
_health_check_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="db-health-check")


def _health_check_timeout():
    import config

    return config.DB_HEALTH_CHECK_TIMEOUT_SECONDS


def check_connection():
    """Cheap DB reachability check (SELECT 1). Never raises — returns
    True/False so callers can treat "DB is down" as a normal condition
    to handle, not an exception to catch everywhere.

    Runs in a background thread with a hard timeout
    (config.DB_HEALTH_CHECK_TIMEOUT_SECONDS) — the connect_timeout and
    TCP keepalive settings on the pool (see init_pool()) already cover
    most "DB unreachable" cases, but this is the last line of defense:
    if the check somehow still hasn't returned by the deadline, give up
    and report "down" rather than let the calling request wait
    indefinitely. This app doesn't use asyncio, so "don't block on this"
    isn't free — the abandoned background thread does keep running until
    it eventually finishes or the connection's own keepalive kills it;
    this just stops the calling request from waiting on it.
    """

    def _select_one():
        with get_cursor() as cur:
            cur.execute("SELECT 1")
        return True

    try:
        future = _health_check_executor.submit(_select_one)
        return future.result(timeout=_health_check_timeout())
    except Exception:
        return False


def record_db_health():
    """Run check_connection() and track how long the DB has been
    continuously unreachable. Returns {"ok": bool, "down_seconds": float}
    — down_seconds is 0.0 whenever ok is True (it resets the moment a
    check succeeds again).

    CAVEAT: this state lives in a plain module-level variable, so it's
    per-process. Under gunicorn with multiple workers (see
    deploy/eqpassdown.service.example, --workers 3), each worker tracks
    this independently — a request landing on a worker that hasn't hit a
    failure yet won't show the warning even if other workers have. Fine
    for a small deployment where any given worker will notice a real
    outage within a request or two either way; a shared store (e.g. a
    status file, or Redis) would be needed for exact cross-worker
    consistency, which isn't worth the added complexity here.
    """
    global _db_down_since
    ok = check_connection()
    logger = logging.getLogger(__name__)
    if ok:
        if _db_down_since is not None:
            logger.info("Database reachable again after %.0fs down.", time.time() - _db_down_since)
        _db_down_since = None
        return {"ok": True, "down_seconds": 0.0}
    if _db_down_since is None:
        _db_down_since = time.time()
        logger.warning("Database unreachable.")
    return {"ok": False, "down_seconds": time.time() - _db_down_since}


def get_names():
    """Return the current list of team member names, alphabetical."""
    with get_cursor() as cur:
        cur.execute("SELECT id, name FROM team_members ORDER BY name")
        return cur.fetchall()


def add_name(name):
    """Add a team member. Silently ignores duplicates (case-sensitive)."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO team_members (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )


def delete_name(member_id):
    """Remove a team member by id. Existing passdown entries keep their author name."""
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM team_members WHERE id = %s", (member_id,))


def get_categories():
    """Return the current list of categories, alphabetical."""
    with get_cursor() as cur:
        cur.execute("SELECT id, name FROM categories ORDER BY name")
        return cur.fetchall()


def add_category(name):
    """Add a category. Silently ignores duplicates (case-sensitive)."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )


def delete_category(category_id):
    """Remove a category by id. Existing passdown entries keep their category value."""
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM categories WHERE id = %s", (category_id,))


_HASHTAG_RE = re.compile(r"#([A-Za-z0-9_][A-Za-z0-9_-]*)")


def extract_hashtags(*texts):
    """Return the distinct #tags (without the '#') found across the given
    text fields — e.g. extract_hashtags(problem_statement, follow_up)."""
    tags = set()
    for text in texts:
        if not text:
            continue
        tags.update(m.group(1) for m in _HASHTAG_RE.finditer(text))
    return tags


def extract_mentions(names, *texts):
    """Return the distinct team-member names (from `names`) @mentioned
    across the given text fields — e.g. extract_mentions(get_names_list,
    problem_statement, follow_up). Unlike hashtags, mentions aren't
    matched against an arbitrary word pattern: only text that names an
    actual, currently-known team member counts, so a stray "@" in text
    that doesn't match anyone just isn't a mention. Case-insensitive
    matching, but returns each hit using the name's own canonical
    casing from `names`. Longer names are matched first so "@John
    Smith" isn't mistakenly captured as just "@John" when both "John"
    and "John Smith" are on the roster.
    """
    if not names:
        return set()
    sorted_names = sorted(names, key=len, reverse=True)
    pattern = re.compile(
        r"@(" + "|".join(re.escape(n) for n in sorted_names) + r")\b",
        re.IGNORECASE,
    )
    lower_to_canonical = {n.lower(): n for n in names}
    found = set()
    for text in texts:
        if not text:
            continue
        for m in pattern.finditer(text):
            found.add(lower_to_canonical.get(m.group(1).lower(), m.group(1)))
    return found


def pg_regex_escape(text):
    """Escape a plain string for safe use inside a Postgres POSIX regex
    (the ~* operator) — e.g. a team member name that happens to contain
    regex-special characters like "O'Brien" or "Smith (Bay 2)". Used by
    the Name filter query so it can also match @mentions in free text,
    not just the author field.
    """
    return re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", text)


def record_hashtags(tags):
    """Upsert each tag into the hashtags table, bumping last_used_at.
    Called after saving/editing an entry so the '#' autocomplete picks up
    newly-used tags without any manual management."""
    if not tags:
        return
    with get_cursor(commit=True) as cur:
        for tag in tags:
            cur.execute(
                """INSERT INTO hashtags (tag) VALUES (%s)
                   ON CONFLICT (tag) DO UPDATE SET last_used_at = NOW()""",
                (tag,),
            )


def get_hashtags():
    """Return all known hashtags, most recently used first."""
    with get_cursor() as cur:
        cur.execute("SELECT tag FROM hashtags ORDER BY last_used_at DESC")
        return [row["tag"] for row in cur.fetchall()]


def log_entry_edit(
    entry_id,
    previous_author,
    previous_tool_entity,
    previous_problem_statement,
    previous_action_items,
    previous_current_status,
    previous_follow_up,
    previous_task_start,
    previous_task_end,
):
    """Snapshot an entry's pre-edit field values into passdown_entry_edits.

    Call this BEFORE applying an update, so the row being replaced is
    preserved rather than lost.
    """
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO passdown_entry_edits
               (entry_id, previous_author, previous_tool_entity, previous_problem_statement,
                previous_action_items, previous_current_status, previous_follow_up,
                previous_task_start, previous_task_end)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                entry_id,
                previous_author,
                previous_tool_entity,
                previous_problem_statement,
                previous_action_items,
                previous_current_status,
                previous_follow_up,
                previous_task_start,
                previous_task_end,
            ),
        )


def get_entry_edits(entry_id):
    """Return prior versions of an entry's note/task times, newest first."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM passdown_entry_edits WHERE entry_id = %s ORDER BY edited_at DESC",
            (entry_id,),
        )
        return cur.fetchall()


def soft_delete_entry(entry_id):
    """Mark an entry as deleted without removing the row."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE passdown_entries SET is_deleted = TRUE, deleted_at = NOW() WHERE id = %s",
            (entry_id,),
        )


def add_attachment(entry_id, stored_filename, original_filename, mime_type, file_size):
    """Record an uploaded file's metadata against an entry."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO passdown_attachments
               (entry_id, stored_filename, original_filename, mime_type, file_size)
               VALUES (%s, %s, %s, %s, %s)""",
            (entry_id, stored_filename, original_filename, mime_type, file_size),
        )


def get_attachments_for_entries(entry_ids):
    """Return {entry_id: [attachment, ...]} for a batch of entry ids.

    One query for the whole page rather than one per entry. Returns an
    empty dict if entry_ids is empty. Soft-deleted attachments (see
    soft_delete_attachment()) are excluded, same as soft-deleted entries
    are excluded from the log.
    """
    if not entry_ids:
        return {}
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM passdown_attachments WHERE entry_id = ANY(%s) AND is_deleted = FALSE ORDER BY uploaded_at",
            (list(entry_ids),),
        )
        rows = cur.fetchall()
    grouped = {}
    for row in rows:
        grouped.setdefault(row["entry_id"], []).append(row)
    return grouped


def get_attachment(attachment_id):
    """Return a single attachment's metadata, or None — including if it's
    been soft-deleted, same as soft-deleted entries aren't findable by id
    either. Used both to serve a download and to look up an attachment
    before removing it, so a stale/already-removed link 404s cleanly in
    both cases rather than serving or re-processing a removed file.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM passdown_attachments WHERE id = %s AND is_deleted = FALSE", (attachment_id,)
        )
        return cur.fetchone()


def soft_delete_attachment(attachment_id):
    """Mark an attachment as removed without deleting the row or the file
    on disk — matches the app's general non-destructive policy (compare
    soft_delete_entry() for entries). Recoverable by a DB admin the same
    way a soft-deleted entry is; the file itself is untouched, only
    config.ATTACHMENT_PURGE_DISK_THRESHOLD auto-purge and manual cleanup
    ever actually remove a file from disk.
    """
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE passdown_attachments SET is_deleted = TRUE, deleted_at = NOW() WHERE id = %s",
            (attachment_id,),
        )


def purge_oldest_attachments_over_disk_threshold(upload_dir):
    """Permanently delete the oldest attachments (file + DB row) while the
    disk holding upload_dir is at or above config.ATTACHMENT_PURGE_DISK_THRESHOLD
    full. Already soft-deleted attachments (see soft_delete_attachment())
    are purged first, regardless of age — recovering their disk space
    costs nothing since they're already invisible in the UI — then falls
    back to the oldest still-active ones if that's not enough. Rechecks
    disk usage after each purge, and stops when usage drops below
    threshold, there are no more attachments left, or
    config.ATTACHMENT_PURGE_BATCH_LIMIT deletions have happened in this
    call — whichever comes first.

    Unlike a soft-deleted attachment (row kept, file kept — see
    soft_delete_attachment()), this IS destructive: a purged attachment's
    file and metadata are both gone for good, whether it was already
    soft-deleted or not. Logs a warning for each one purged so there's at
    least a trace in the server logs.

    Returns the number of attachments purged (0 if none were needed).
    """
    import config

    logger = logging.getLogger(__name__)
    purged = 0

    while purged < config.ATTACHMENT_PURGE_BATCH_LIMIT:
        try:
            usage = shutil.disk_usage(upload_dir)
        except OSError as exc:
            logger.warning("Could not check disk usage for %s: %s", upload_dir, exc)
            break

        if usage.total == 0 or (usage.used / usage.total) < config.ATTACHMENT_PURGE_DISK_THRESHOLD:
            break

        with get_cursor() as cur:
            cur.execute(
                "SELECT id, entry_id, stored_filename, original_filename "
                "FROM passdown_attachments ORDER BY is_deleted DESC, uploaded_at ASC LIMIT 1"
            )
            oldest = cur.fetchone()

        if oldest is None:
            break  # disk still over threshold, but nothing left to purge

        file_path = os.path.join(upload_dir, oldest["stored_filename"])
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass  # already gone on disk; still clear the orphaned DB row below

        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM passdown_attachments WHERE id = %s", (oldest["id"],))

        logger.warning(
            "Disk usage over %.0f%% — auto-purged attachment %s (\"%s\", entry %s)",
            config.ATTACHMENT_PURGE_DISK_THRESHOLD * 100,
            oldest["id"],
            oldest["original_filename"],
            oldest["entry_id"],
        )
        purged += 1

    return purged


def get_tool_list():
    """Return the list of tool/entity names from the mestoollist view.

    Reads the view name and column name from config.py so this can be
    pointed at whatever your MES already exposes. Returns an empty list
    (rather than raising) if the view/column isn't there yet, so the app
    still starts even before that view exists — the dropdown just shows
    no options until it does.
    """
    import config

    query = f"SELECT DISTINCT {config.MESTOOLLIST_COLUMN} FROM {config.MESTOOLLIST_VIEW} ORDER BY {config.MESTOOLLIST_COLUMN}"
    try:
        with get_cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return [row[config.MESTOOLLIST_COLUMN] for row in rows if row[config.MESTOOLLIST_COLUMN]]
    except Exception as exc:
        app_logger = logging.getLogger(__name__)
        app_logger.warning("Could not read tool list from %s: %s", config.MESTOOLLIST_VIEW, exc)
        return []


def get_tool_locations():
    """Return {tool_name: location} from the mestoollist view's Location
    column, for showing/filtering entries by a tool's physical location.

    Same graceful-degradation approach as get_tool_list(): returns an
    empty dict rather than raising if the view isn't reachable, so a
    down MES connection doesn't take the whole log page with it — entries
    just show no location bubble until it's reachable again. "Location"
    is quoted in the query because that's the exact (capitalized) column
    name in the view as defined — see fdw/setup_mestoollist_fdw.sql.template.
    """
    import config

    query = f'SELECT {config.MESTOOLLIST_COLUMN}, "Location" FROM {config.MESTOOLLIST_VIEW}'
    try:
        with get_cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return {
            row[config.MESTOOLLIST_COLUMN]: row["Location"]
            for row in rows
            if row[config.MESTOOLLIST_COLUMN] and row["Location"]
        }
    except Exception as exc:
        app_logger = logging.getLogger(__name__)
        app_logger.warning("Could not read tool locations from %s: %s", config.MESTOOLLIST_VIEW, exc)
        return {}
