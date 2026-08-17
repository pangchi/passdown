-- Shift passdown schema.
-- This is a reference copy — the app creates/updates this automatically
-- via db.init_db() on startup. Run manually only if you'd rather set it
-- up yourself, e.g.:
--   psql -U passdown -d passdown -f schema.sql

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
    updated_at          TIMESTAMPTZ,
    is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ
);

ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS tool_entity VARCHAR(150);
-- author holds a comma-separated list of names now — widen it from the
-- old VARCHAR(100) if this table predates that change.
ALTER TABLE passdown_entries ALTER COLUMN author TYPE TEXT;
UPDATE passdown_entries SET tool_entity = 'unspecified' WHERE tool_entity IS NULL;
ALTER TABLE passdown_entries ALTER COLUMN tool_entity SET NOT NULL;

ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS task_start TIMESTAMPTZ;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS task_end TIMESTAMPTZ;

ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS chamber VARCHAR(100);
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS category VARCHAR(20);
UPDATE passdown_entries SET category = 'unspecified' WHERE category IS NULL;
ALTER TABLE passdown_entries ALTER COLUMN category SET NOT NULL;
ALTER TABLE passdown_entries ALTER COLUMN category SET DEFAULT 'unspecified';

-- The single free-text "note" field was replaced by 4 structured fields.
ALTER TABLE passdown_entries DROP COLUMN IF EXISTS note;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS problem_statement TEXT;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS action_items TEXT;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS current_status TEXT;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS follow_up TEXT;
UPDATE passdown_entries SET problem_statement = 'unspecified' WHERE problem_statement IS NULL;
ALTER TABLE passdown_entries ALTER COLUMN problem_statement SET NOT NULL;

ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE passdown_entries ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_passdown_created_at ON passdown_entries (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_passdown_shift ON passdown_entries (shift);
CREATE INDEX IF NOT EXISTS idx_passdown_author ON passdown_entries (author);
CREATE INDEX IF NOT EXISTS idx_passdown_tool_entity ON passdown_entries (tool_entity);
CREATE INDEX IF NOT EXISTS idx_passdown_category ON passdown_entries (category);
CREATE INDEX IF NOT EXISTS idx_passdown_is_deleted ON passdown_entries (is_deleted);

-- Snapshot of an entry's editable fields taken right before each edit —
-- edits never overwrite history, they only add to it.
CREATE TABLE IF NOT EXISTS passdown_entry_edits (
    id                          SERIAL PRIMARY KEY,
    entry_id                    INTEGER NOT NULL REFERENCES passdown_entries(id),
    previous_author              TEXT,
    previous_problem_statement  TEXT,
    previous_action_items       TEXT,
    previous_current_status     TEXT,
    previous_follow_up          TEXT,
    previous_task_start         TIMESTAMPTZ,
    previous_task_end           TIMESTAMPTZ,
    edited_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE passdown_entry_edits DROP COLUMN IF EXISTS previous_note;
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_problem_statement TEXT;
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_action_items TEXT;
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_current_status TEXT;
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_follow_up TEXT;
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_author TEXT;
ALTER TABLE passdown_entry_edits ADD COLUMN IF NOT EXISTS previous_tool_entity VARCHAR(150);

CREATE INDEX IF NOT EXISTS idx_passdown_edits_entry_id ON passdown_entry_edits (entry_id);

-- Team member names shown in the "Name" dropdown. Managed from the app
-- itself at /names (add/remove) — config.NAMES is only used to seed this
-- table the very first time it's empty.
CREATE TABLE IF NOT EXISTS team_members (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Category options shown in the "Category" dropdown. Managed from the
-- app itself at /categories (add/remove) — config.CATEGORIES is only
-- used to seed this table the very first time it's empty.
CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Hashtags used in free-text fields (#tag). No manual management page —
-- learned automatically whenever an entry with #tags is saved.
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
-- entry — the row (and the file on disk) stay put, just hidden.
ALTER TABLE passdown_attachments ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE passdown_attachments ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_passdown_attachments_entry_id ON passdown_attachments (entry_id);

-- The Tool / Entity dropdown on the add-entry form is populated live from
-- a "mestoollist" view (see config.py: MESTOOLLIST_VIEW / MESTOOLLIST_COLUMN)
-- rather than a column in this table. That view is expected to already
-- exist in your database — this file doesn't create it.
