# Shift Passdown

A small Flask app for logging daily shift passdown notes to Postgres. No
login — pick your name and shift from a dropdown, write a note, done.
Built for running on a Raspberry Pi / local network alongside your other
tools.

## Version

**v1.1.0** — set in `config.APP_VERSION`, shown in the footer of every
page next to the build date (e.g. "v1.1.0 — Build: 05 Aug 2026 14:32").
Bump `APP_VERSION` when you make a meaningful change, so what's running
and what this README describes can be compared at a glance. There's no
enforced format — plain `MAJOR.MINOR.PATCH` is a reasonable default if
you don't already have your own convention.

## Features

- Add a passdown note (name + shift + tool/entity + chamber + category
  [PM/CM/SPC] + optional task start/end date-time + a structured note
  split into **Problem Statement** [required], **Action Item(s)**,
  **Current Status**, and **Follow up** [all three optional])
- Attach one or more files when adding (or later editing) an entry —
  drag and drop them onto the drop zone, or click it to browse; you can
  browse multiple times and each round adds to the pile rather than
  replacing it, with a "×" to remove a staged file before submitting.
  Images display inline in the log; PDF, Word (doc/docx), and Excel
  (xls/xlsx) attachments open in a new browser tab rather than forcing a
  download (configurable via `config.INLINE_VIEW_EXTENSIONS`) — note
  this is a genuine inline viewer only for PDF, since browsers don't
  render Office formats natively; for those it just skips the forced
  "Save As" and lets the browser/OS decide (often still a download or an
  open-in-desktop-app prompt, depending on the browser). CSV and plain
  text attachments still show as a download link. Files are saved to disk
  (`config.UPLOAD_FOLDER`), with only metadata + a pointer in Postgres.
- **Auto-purge**: if the disk holding `../eqpassdown_uploads` (see
  `config.UPLOAD_FOLDER`) reaches 80% full
  (`config.ATTACHMENT_PURGE_DISK_THRESHOLD`), the oldest attachments are
  automatically and **permanently** deleted — file and database row both
  — oldest first, until usage drops back below that line or there's
  nothing left to purge. This is the one destructive thing in the whole
  app; everything else (edits, deletes) is deliberately non-destructive,
  but unbounded attachment storage on a small disk needed a release
  valve. Checked at startup and after every upload; each purge is logged
  as a warning in the server log (see `journalctl -u eqpassdown` if running
  under the systemd unit) so there's at least a record of what was
  removed and when, even though the file/row itself is gone. Raise the
  threshold (or set it to `1.0`+) in `config.py` to disable it if you'd
  rather manage disk space manually.
- Name supports multiple people on one entry — type or pick a name and click Add (or press Enter) to add it as a chip; that explicit Add accepts free text same as before. If you submit with text still sitting in the box unstaged, it's committed automatically too, but only when it matches a real name from `/names` (case-insensitive) — an unmatched typo is left in the box rather than silently added or silently dropped. Stored as a comma-separated list; filtering by name matches if that name appears anywhere in the list. Editable later from the edit page the same way — add or remove names, with the previous list snapshotted into edit history first.
- Tool/Entity is searchable — type to filter, or pick from the list (native browser autocomplete, no JS framework)
- Team member names are stored in the database and managed from the app itself (add/remove at `/names`) — no code edits needed to update the roster
- Tool/entity dropdown is populated live from a `mestoollist` database view (e.g. your MES), not a static list
- Log view grouped by day, newest first
- On screens ≥900px wide, the page is two columns — New Entry on the left, the log on the right — each scrolling independently. The **divider between them is draggable**: drag it to resize either pane, drag it (or double-click it) all the way left to minimize the New Entry pane down to a thin strip with a small "›" button to bring it back, or use arrow keys/Enter after tabbing to the divider if you'd rather not use a mouse. The chosen width (and whether it's minimized) is remembered across visits via `localStorage`. Below 900px the columns stack and the divider disappears, since dragging doesn't make sense on a narrow/touch screen.
- **Database connection health**: every log page load does a cheap `SELECT 1` reachability check, immediately reflected as a warning banner and (if the outage persists past `config.DB_WARNING_PERSIST_MINUTES`, default 5) a disabled New Entry form — the server backs this up too, rejecting submissions server-side if that threshold is crossed, so it's not just a client-side visual state that could be bypassed. On top of that, a script polls a lightweight `/health.json` endpoint every 10 seconds for as long as the page stays open — so if the connection drops (or recovers) *while someone already has the page open*, the banner and form update live, straight in the DOM, with no page reload involved at all. That matters because a reload would interrupt someone mid-typing in the New Entry form; this way it can't. The **"Add entry" button specifically greys out the moment any outage is detected** — even a brief one, before it's persisted long enough to disable the rest of the form — since there's no point letting someone try to submit something that's already known not to save; the rest of the fields stay editable so they can keep writing while it's down. Separately, the button also **greys out immediately on submit** (before the page even navigates away) to prevent a double-click from submitting the same entry twice. See the caveat about the health-check state being per-worker-process in the code comments in `db.py` if running gunicorn with multiple workers.
  - **Bounding a hung database**: none of this waits on `asyncio` (a full non-blocking rewrite was tried and rolled back — too large/risky a change for what it bought). Instead, pooled connections use a short `connect_timeout` and TCP keepalive (`config.DB_CONNECT_TIMEOUT_SECONDS` / `DB_KEEPALIVE_SECONDS`) so a database that's gone silently unreachable (not a fast "connection refused," but a genuine network black hole) gets detected within seconds instead of the OS's much longer default. On top of that, the health check itself runs in a small background thread pool with a hard ceiling (`config.DB_HEALTH_CHECK_TIMEOUT_SECONDS`, default 3s) — belt-and-suspenders, since it's the DB call polled most often. One honest caveat: if a check does time out, the abandoned background thread keeps running until it finishes or the connection's own keepalive kills it — repeated hangs could occupy both of the health-check thread pool's workers, at which point *further* health checks queue behind them rather than failing instantly. Bounded and far less severe than the original problem (a hung query tying up a whole gunicorn worker, blocking real requests), but worth knowing.
- **The app starts and serves requests immediately, even if the database isn't reachable yet** — e.g. Postgres still starting up, or a brief network blip right as the app boots. Rather than blocking startup on it, a background thread retries (`config.STARTUP_DB_RETRY_SECONDS` / `STARTUP_DB_MAX_RETRIES`, default worst case ~30s) with a warning logged each attempt, while gunicorn's worker boots and starts accepting connections right away regardless. Any request that arrives before the database is reachable just gets the same degraded-state page (empty log, warning banner, New Entry form present) that a request would get if the database went down after a successful startup — one code path handles both, and no gunicorn timeout tuning is needed since nothing blocks worker boot.
- **Logging**: application events (entries added/edited/removed, attachments saved or rejected, team members and categories added/removed, database health transitions, startup retries) are logged to `../passdown_logs/` (see `config.LOG_FOLDER`), one file per day, automatically kept for `config.LOG_RETENTION_DAYS` days (default 90) and deleted beyond that — no separate cleanup job, it's built into the log rotation itself (Python's `TimedRotatingFileHandler`, `backupCount=90`). Today's log is `passdown.log` (the file actively being written to); once a day passes, it rotates into a dated file named `passdown-YYYY-MM-DD.log` (ISO 8601, e.g. `passdown-2026-08-05.log`) and a fresh `passdown.log` starts for the new day. This is separate from gunicorn's own access/error logs (`--access-logfile` / `--error-logfile` in the systemd unit, which go to `journalctl` by default) — this file is the application's own record of what happened, not raw HTTP traffic.
  - **Usage logging**: every real page view/action (not static assets, not the every-10-seconds health-check polling — both are filtered out as noise) is also logged, tagged with logger name `usage` so it's easy to tell apart from the business-event lines above. Raw traffic on its own isn't "statistics" yet — a few `grep`/`awk` one-liners turn it into some:
    ```bash
    # Requests per day this week
    grep '] usage:' passdown_logs/passdown*.log | awk '{print $1}' | sort | uniq -c

    # Busiest pages/endpoints
    grep '] usage:' passdown_logs/passdown.log | grep -oP 'endpoint=\K[^)]+' | sort | uniq -c | sort -rn

    # Which client IPs are hitting the app most
    grep '] usage:' passdown_logs/passdown.log | grep -oP 'from \K.+' | sort | uniq -c | sort -rn

    # Entries added per day (from the business-event log, not usage)
    grep 'Entry .* added by' passdown_logs/passdown.log | awk '{print $1}' | sort | uniq -c
    ```
- Filter by shift, tool/entity, category, and how many days back to show — options go up to 365 days, plus an "All time" option with no lower bound at all. Name filters as toggleable bubbles — click any number of names to show entries involving any of them (an entry matches if it lists at least one selected name). Every entry in the log also shows its name(s), shift, tool/entity, category (when set), and location (when known — see below) as clickable bubbles — clicking one toggles that filter directly from the log, without scrolling back up to the filter bar. Name works as an add-to-the-set toggle (multi-select); Shift/Tool/Category/Location toggle between that value and "All" since those filters are single-value. Names not in the `/names` roster (e.g. free text added via the explicit Add button) aren't clickable this way since there's no matching filter checkbox for them.
- **Location** shows and filters entries by a tool's physical location — pulled live from `mestoollist`'s `Location` column (see "Setting up mestoollist"), keyed off each entry's Tool/Entity value. Not something typed in — it's looked up automatically, so an entry only gets a location bubble if its tool has one in the MES data. The Location filter (in the filter bar and the log's own bubbles) only appears at all once at least one entry resolves to a location; if the MES/FDW connection is down, entries just show no location bubble rather than erroring the page.
- A **search box** at the top of the log searches Problem Statement, Action Item(s), Current Status, and Follow up for a plain substring match (case-insensitive) — combines with every other active filter (Name, Shift, Tool/Entity, Category, Tags, Location, Days back), narrowing the result set further rather than replacing the other filters. A 🔍 button submits it (Enter also works, same as any form field), and a ✕ button clears it — clearing only removes the search term, leaving every other active filter in place.
- **⬇ CSV / ⬇ DOCX / ⬇ HTML / ⬇ PDF** links next to the "Log" heading download exactly what's currently on screen — same filters, same search, same date range — in four formats (`/export.csv`, `/export.docx`, `/export.html`, `/export.pdf`), all sharing the same filtering logic as the log page itself. Each includes the same data: timestamps, name(s), shift, tool, chamber, category, location, all four text fields, tags, and mentions. Unlike the log page (newest first), all exports are sorted **oldest first** — reads more like a report that way.
  - **CSV**: one row per entry, for spreadsheets. Doesn't include attachments (no sensible way to represent a file in a table cell).
  - **DOCX**: one section per entry (heading + labeled fields), a real Word document via `python-docx`. Image attachments are **embedded directly in the document** (not linked) as long as they're under `config.EXPORT_INLINE_IMAGE_MAX_MB` (default 10 MB) — larger images and non-image files are listed by filename instead, since there's no lightweight way to embed an arbitrary file inline the way an image can be.
  - **HTML**: a self-contained page with inline styles — no dependency on the app's own stylesheet, so it still looks right opened later, offline. Attachments are the one exception to "self-contained": images show as thumbnails and other files as download links, but both point back to the live server (absolute URLs), so they only work while opened from a device that can still reach it. Embedding attachments directly (like DOCX does for images) risked making the HTML file huge for exports with many/large photos, so it links instead.
  - **PDF**: one section per entry, similar layout to DOCX, via `fpdf2`. Attachments are listed by filename only, not embedded (unlike DOCX's image handling) or linked (unlike HTML's). **Known limitation**: uses fpdf2's built-in core fonts, which only support latin-1 — no TrueType font was bundled with the app for full Unicode support, to avoid shipping/managing an extra font file. Text outside latin-1 (curly quotes, em dashes typed as literal Unicode, emoji, non-Latin scripts) renders as `?` rather than crashing the export — CSV/DOCX/HTML aren't affected by this, it's PDF-specific.
  - All four links carry over the page's own query string via a small script, so whatever's active when you click one is what's in the file.
- **Archive export**: a collapsed-by-default "Archive export" section below the filter bar (click to expand — a native `<details>` disclosure, no JS needed) with "From"/"To" date pickers, for pulling a clean date range to file away — e.g. "everything from March 2026." Deliberately **ignores every other active filter** (Name, Tag, Tool, Category, Location, search) — it's meant to be a complete record of that date range, not a filtered slice — so it's a separate small form rather than reusing the CSV/DOCX/HTML/PDF links above. Only offers PDF and CSV (the two most likely formats for handing off/filing away a record); leave either date blank for an open-ended range. Auto-expands if a date range is already set (e.g. arriving via a bookmarked/shared link with `date_from`/`date_to` in the URL), so those values aren't hidden behind a click. Internally this reuses the exact same query-building code as every other export and the log page itself — `date_from`/`date_to` query params simply take precedence over the "Days back" preset when present, rather than being a separate code path.
- Selecting a tool in the New Entry form's Tool/Entity field also auto-filters the log below to that tool (only for a real match from the tool list, not partial/half-typed text). Clicking any log/filter bubble does the same kind of reload. None of these lose what's already in the New Entry form — everything typed so far (including staged and not-yet-added name chips) is saved right before the reload and restored after, the same way scroll position is. The one thing that can't survive a reload is attachments, since browsers won't let JS repopulate a file input.
- Edit or remove an entry — both are non-destructive: deleting only marks
  an entry hidden (`is_deleted`), and editing snapshots the previous
  note/task times into a history table before applying the change, so
  nothing is ever overwritten or actually deleted. The entry's edit page
  shows this history as a **diff**, not a wall of repeated text — only
  the fields that actually changed at each edit are shown, with removed
  words struck through in red and added words highlighted in green
  (word-level, computed server-side with Python's `difflib`). Task
  start/end changes show as old range → new range. If an edit somehow
  touched nothing visible (e.g. only an attachment was added in that
  same save), that version just says so rather than showing an empty
  diff.
- Problem Statement, Action Item(s), Current Status, and Follow up
  support **@mentions** and **#hashtags** — type `@` to search team
  member names (same roster as the Name field), or `#` to search
  hashtags that have been used before. Arrow keys + Enter/Tab to pick,
  Escape to dismiss, or click an option. Hashtags aren't a managed
  list — any `#word` typed into a saved entry is automatically
  remembered for future autocomplete, most-recently-used first; nothing
  to set up.
- `@mentions` are also bubbled and filterable, reusing the existing Name
  filter: an `@mention` only becomes a bubble if it matches someone
  currently on the `/names` roster (case-insensitive) — a stray `@` or a
  mention of someone not on the roster stays as plain text, nothing is
  auto-added. Matching checks longer names first, so `@John Smith`
  correctly matches the two-word name "John Smith" rather than being cut
  off at `@John`, as long as "John Smith" is the name actually on the
  roster. Mention bubbles are styled distinctly (teal, `@Name`) from the
  entry's own author bubbles (indigo), but clicking either toggles the
  same Name filter — so filtering by a name surfaces every entry that
  person is either credited on *or* mentioned in.
- Hashtags are also filterable, same pattern as Name: a "Tags" row of
  toggleable checkboxes in the filter bar (only shown once at least one
  tag has been used anywhere), and every entry shows its own `#tags` as
  clickable bubbles that toggle the same filter directly from the log.
  Multi-select (OR) like Name — an entry matches if it contains at least
  one selected tag. Matching is a whole-tag match, not a loose substring,
  so filtering by `#urgent` won't also catch `#urgent-followup`.
- A green **Copy** button next to Edit/Delete copies Problem Statement,
  Action Item(s), Current Status, and Follow up to the clipboard as plain
  text — just the raw content of each, no field labels, separated by
  blank lines, and only the fields that have content — for pasting into
  an email, chat, or another system.
- A **User guide** link in the header (`/guide`) gives a plain-language walkthrough for people actually using the app day to day — separate from this README, which is for setup/deployment.
- Shifts are configured in `config.py`; team member names and
  categories are both stored in the database and managed in-app —
  names at `/names`, categories at `/categories` — same pattern as
  Tool/Entity: add/remove without touching code, and `config.NAMES` /
  `config.CATEGORIES` only seed each table the first time it's empty.

## Setup

### 1. Postgres

Create a database and user (adjust names/password as you like):

```sql
CREATE DATABASE passdown;
CREATE USER passdown WITH PASSWORD 'changeme';
GRANT ALL PRIVILEGES ON DATABASE passdown TO passdown;
```

That's it — the `passdown_entries` table and its indexes are created
automatically the first time the app starts (`db.init_db()` runs
`CREATE TABLE IF NOT EXISTS` on every launch, so it's a no-op after the
first run). `schema.sql` is kept in the repo as a reference / for
running manually if you'd rather set the table up yourself.

### 2. Python environment

```bash
python3 -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

Copy `.env.example` to `.env` and fill in your Postgres credentials:

```bash
cp .env.example .env
```

Edit `config.py` and set `SHIFTS` to match your site. `NAMES` and
`CATEGORIES` there are both only **seed** lists (`NAMES` empty by
default; `CATEGORIES` defaults to `PM`/`CM`/`SPC`) — used to populate
the `team_members` and `categories` tables the very first time each is
empty. After that, add or remove team members at `/names` and
categories at `/categories` (via the header links, or the "+" next to
each field on the New Entry form); edits there aren't overwritten on
restart.
Database connection settings live separately in `db_config.py` (they
read from `.env`, so you normally won't need to touch that file). Set
`PASSDOWN_TIMEZONE` in `.env` to your site's IANA timezone name (e.g.
`Asia/Singapore`, `America/Chicago`) — every timestamp shown or stored
(entry times, task start/end) uses this zone, regardless of what
timezone the Postgres server itself defaults to. It defaults to
`Asia/Singapore` if not set.

The **Tool / Entity** dropdown is read live from a database view —
`config.MESTOOLLIST_VIEW` (default `mestoollist`) and
`config.MESTOOLLIST_COLUMN` (default `mestoolname`). If the view doesn't
exist yet or the query fails, the app still starts — the dropdown just
shows no options until it's reachable. `mestoollist` itself is a view
over foreign tables in your MES database, provisioned via
`postgres_fdw` — see **"Setting up mestoollist"** below.

**Attachments** are configured in `config.py`:
- `UPLOAD_FOLDER` — where files are saved (default `../eqpassdown_uploads`,
  i.e. a sibling folder next to `passdown/` rather than inside it —
  created automatically on startup. Kept outside the app's own folder so
  it survives a redeploy that replaces `passdown/` wholesale, and so
  it's an obvious separate target for backups).
- `MAX_UPLOAD_SIZE_MB` — per-file size cap (default 200 MB); larger
  uploads are rejected with a flash message rather than a raw error.
- `IMAGE_EXTENSIONS` / `OTHER_ALLOWED_EXTENSIONS` — which file types are
  accepted; images in the first set display inline in the log, anything
  in either set is otherwise accepted and shown as a download link.
  Anything not in either set is rejected (flashed per-file, rest of the
  entry still saves).

### 4. Run

```bash
python3 app.py
```

The app listens on `0.0.0.0:5050` by default (change with
`PASSDOWN_APP_PORT` in `.env`), so it's reachable from other devices on
your local network at `http://<pi-ip-address>:5050`.

This is fine for local/dev use. For always-on production use, run it
under gunicorn behind Apache instead — see below.

## Deploying: gunicorn behind Apache (subfolder, Unix socket)

For production, run the app under **gunicorn** (a proper WSGI server —
Flask's own dev server isn't meant for that) and put **Apache** in front
of it as a reverse proxy, mounted at a subfolder path like
`https://yourhost/eqpassdown/` rather than the domain root. Apache
talks to gunicorn over a **Unix socket** rather than a TCP port — skips
the loopback network stack, and access control is just filesystem
permissions on the socket file rather than "whatever's listening on
that port." Both the subfolder and the systemd service are named
`eqpassdown` (not just `passdown`) — pick your own name if you'd
rather, but keep it consistent across the socket path, service name,
and `X-Forwarded-Prefix` header, since those three have to agree.

1. **Run gunicorn**, bound to a socket, instead of `python3 app.py`:

   ```bash
   gunicorn --workers 3 --bind unix:/run/eqpassdown/eqpassdown.sock --umask 007 app:app
   ```

   `deploy/eqpassdown.service.example` is a ready-to-adapt systemd unit
   that does this properly: it creates `/run/eqpassdown/` on start
   (`RuntimeDirectory=`), runs gunicorn as `Group=www-data` so Apache
   can connect to the socket, and restarts on crash. See the comments in
   that file for install steps and a note on the `Group=www-data`
   tradeoff if you'd rather keep app-owned files under a separate group.
   If you're running gunicorn manually (not via that unit), you're
   responsible for creating the socket's parent directory with
   permissions Apache can reach — the systemd unit's `RuntimeDirectory=`
   handles that automatically, which is one more reason to use it in
   production rather than a bare foreground command.

2. **Configure Apache** to proxy a subfolder to that socket — see
   `deploy/apache-eqpassdown.conf.example` for the block to add to your
   vhost (uses `ProxyPass "unix:/run/eqpassdown/eqpassdown.sock|http://localhost/"`,
   Apache's Unix-socket proxy syntax — needs Apache ≥ 2.4.9, which any
   current Ubuntu has), and the Apache modules it needs enabled
   (`proxy`, `proxy_http`, `headers`). If you're serving HTTP and HTTPS
   from separate `<VirtualHost>` blocks (common with a Certbot-created
   SSL vhost), that block needs to go in **both** — Apache treats each
   `<VirtualHost>` independently, so adding it to only one leaves the
   other returning a plain Apache 404 for `/eqpassdown/`.

3. **Nothing else to change in the app** — `app.py` already wraps the
   WSGI app in Werkzeug's `ProxyFix` (with `x_prefix=1`), which reads the
   `X-Forwarded-Prefix` header Apache sets in that example config and
   makes every `url_for()`-generated link — page links, form actions,
   the stylesheet, attachment download links — come out correctly
   prefixed with `/eqpassdown` instead of pointing at the domain root.
   This is also why it's important the Apache config actually sets that
   header; without it the app will load but every link on the page will
   be wrong. The socket-vs-TCP choice is entirely a gunicorn/Apache
   plumbing detail — Flask itself doesn't know or care which one is in use.

If you're not using a subfolder (mounting at the domain root instead),
the same setup works — just drop the `X-Forwarded-Prefix` header and
use `ProxyPass "unix:/run/eqpassdown/eqpassdown.sock|http://localhost/"`
at `/` instead of `<Location /eqpassdown/>`.

For always-on use on a Raspberry Pi without Apache in front (still
recommended over the dev server for anything long-running), running
gunicorn directly under `systemd` or `screen`/`tmux` also works — bound
to a TCP port is simpler in that case since there's no reverse proxy
needing socket access, e.g. `--bind 127.0.0.1:5050`. You just won't get
subfolder mounting, TLS, or fronting multiple apps on one domain.

## Setting up mestoollist (MES foreign data wrapper)

`mestoollist` is a local view over two tables (`Tool_Selection`,
`Location_Selection`) that live in a separate MES database, accessed via
Postgres's `postgres_fdw` extension. This is a one-time (or
whenever-credentials-change) database setup step, separate from running
the app.

1. Add the MES connection details to `.env` (see `.env.example` for the
   `MES_FDW_*` variables — host, port, dbname, user, password, and the
   schema name on the MES side that holds those two tables).
2. Run the provisioning script:

   ```bash
   ./scripts/setup_fdw.sh
   ```

   This creates the `postgres_fdw` extension, the `mes_server` foreign
   server, a user mapping, imports `Tool_Selection` and
   `Location_Selection` as foreign tables into a local `mes` schema, and
   (re)creates the `public.mestoollist` view on top of them. It's safe
   to re-run any time — it drops and recreates everything so changed
   credentials in `.env` take effect.
3. Requires `psql` and `envsubst` (the latter is in the `gettext-base`
   package — `sudo apt install gettext-base` if it's missing).

The raw SQL (with `${...}` placeholders the script fills in from `.env`)
lives in `fdw/setup_mestoollist_fdw.sql.template` if you'd rather run it
by hand.

The MES user in `.env` only needs read access to `Tool_Selection` and
`Location_Selection` on their end — it's used solely to populate the
Tool / Entity dropdown.

## Project layout

```
eqpassdown_uploads/        # attachment files — sibling of passdown/, created
                            # automatically on startup, not part of this repo
passdown_logs/              # application logs — see config.LOG_FOLDER, also
                            # a sibling of passdown/, created automatically,
                            # not part of this repo (deliberately a different
                            # name from eqpassdown_uploads — see config.py)
passdown/
├── app.py              # routes
├── config.py            # names, shifts, app settings
├── db_config.py          # database connection settings (from .env)
├── db.py                 # Postgres connection pool helper + auto table creation
├── schema.sql            # reference/manual table setup (not required — app creates it automatically)
├── requirements.txt
├── .env.example
├── fdw/
│   └── setup_mestoollist_fdw.sql.template  # FDW + mestoollist view (templated)
├── scripts/
│   └── setup_fdw.sh       # fills in the template from .env and runs it
├── deploy/
│   ├── apache-eqpassdown.conf.example  # Apache reverse-proxy config (subfolder mount)
│   └── eqpassdown.service.example      # systemd unit to run gunicorn
├── templates/
│   ├── base.html
│   ├── index.html         # log view + add-entry form
│   ├── edit_entry.html
│   ├── manage_names.html      # add/remove team members
│   ├── manage_categories.html # add/remove categories
│   ├── guide.html             # end-user how-to page (/guide)
│   └── export.html            # standalone HTML export (not part of app navigation)
└── static/
    ├── style.css
    ├── attachments.js      # drag-and-drop / multi-pick attachment widget
    ├── namepicker.js       # multi-name chip picker for the Name field
    └── mentions.js         # @name / #hashtag autocomplete for free-text fields
```

## Notes

- The bubbles in `.entry-meta` (Name, Shift, Tool/Entity, Location,
  Chamber, Category, Time) each have a trailing space baked into their
  own text content, and the field labels (Problem Statement, Action
  Item(s), Current Status, Follow up) have a space right after the
  label. Both fixes exist because of the same underlying issue:
  `.entry-meta` is a flex container, and flexbox drops whitespace-only
  text nodes between flex items — so even though the template has
  newlines between bubbles, a raw browser text-selection copy (dragging
  to select, not the Copy button) would glue them together with no
  separator at all, e.g. "ToolName📍CR1CM09:00" instead of "ToolName
  📍 CR1 CM 09:00". Putting the space *inside* each element's own
  content (not as a separate sibling text node) survives that
  stripping. The Copy button itself was never affected by this — it
  builds its text from `data-*` attributes with its own explicit
  `\n\n` joins, unrelated to what's visually selectable on the page.
- `@mentions` are clickable/filterable in the log now too, but only
  when they match a real, current `/names` roster entry — see above.
  There's still no notification of any kind (no auth means no one to
  notify) — clicking a mention bubble just toggles the Name filter,
  same as clicking the entry's own author bubble would.
- Every page has a small "Build: ..." line in the footer, showing when
  the app process was last started — the closest thing to a build/deploy
  date without a real CI pipeline. It updates automatically every time
  you restart the app (including a gunicorn/systemd restart after
  deploying a change), so it's a quick way to confirm a deploy actually
  took effect. Rendered client-side in the viewer's local time, like
  everything else timestamp-related in this app.
- "All time" in the Days back filter has no lower bound at all — on a
  deployment that's been running a long while with lots of entries and
  attachments, that can mean loading a lot of data into one page. There's
  no pagination yet, so if this becomes slow in practice, worth adding.
- The Copy button uses the browser's Clipboard API when available, and
  falls back to the older `execCommand('copy')` approach otherwise. This
  matters because Clipboard API access requires a "secure context"
  (HTTPS, or `localhost`) — accessing the app over plain HTTP from
  another device on the network (e.g. `http://<pi-ip>:5050`, the normal
  way this app is reached) doesn't count as secure to the browser, so
  the fallback is what actually runs in that common case. It still
  works, just via an older mechanism.
- Validation errors on the New Entry and Edit forms redisplay the form
  with everything you typed still in place (name chips, shift, tool,
  chamber, category, task times, all four text fields) instead of
  clearing it — the one unavoidable exception is attachments: browsers
  won't let a server hand a file back into a file input, so if a
  validation error happens on the same submit as picking files, you'll
  need to re-attach them. A request rejected for being over the size
  limit (`config.MAX_UPLOAD_SIZE_MB`) is also an exception — the browser
  stops that upload before the form data even reaches the app, so
  there's nothing to redisplay from.
- Attachment files live on disk in `../eqpassdown_uploads` (a sibling
  folder next to `passdown/`, not inside it — see `config.UPLOAD_FOLDER`),
  not in Postgres — back that folder up alongside your database if
  attachments matter for the
  record (a DB-only backup won't include them). There's currently no
  in-app way to manually remove an individual attachment, and
  soft-deleting an entry doesn't touch its attachment files or rows —
  the only thing that removes an attachment today is the disk-usage
  auto-purge described above, which is automatic and not
  entry-specific. Say the word if you'd like manual per-attachment
  removal added too.
- The single free-text **Note** field was replaced with 4 structured
  fields (Problem Statement, Action Item(s), Current Status, Follow up).
  If you're upgrading a deployment that already had entries under the
  old single-note schema, `db.init_db()` drops that old `note` column
  outright (and `previous_note` on the edit-history table) — there's no
  automatic migration of old note text into the new fields. Back up
  first if that old data matters to you.
- All displayed timestamps (entry time, "edited" time, task start/end, day
  grouping) are rendered client-side in the viewer's own browser
  timezone — the server sends the absolute instant and a small script
  formats it locally, so two people in different timezones see the same
  entry at their own local time. Day headers group by local calendar
  day too, so an entry near midnight may land under a different date
  for viewers in different timezones — that's expected.
- If an entry has a **Task start**, the log shows and groups by that
  time instead of when the entry was logged (`created_at`) — it's the
  more meaningful "when did this happen" for a shift log. Entries
  without a task start still use their logged time. The log's sort
  order matches (`COALESCE(task_start, created_at) DESC`), so day
  headers stay contiguous instead of an entry with an out-of-order task
  start splintering a day into two headers.
- The **Task start**/**Task end** input fields are plain `datetime-local`
  inputs, which don't carry timezone info themselves — whatever numbers
  are typed are stored as-is, interpreted using the app's configured
  `PASSDOWN_TIMEZONE` (see "Configure" above), not whatever timezone the
  submitting browser happens to be set to. On the New Entry form
  specifically, the initial pre-fill (Task start) and the Shift
  auto-selection are computed from the *viewer's own browser clock* on a
  fresh page load rather than the server's — this matters if the server
  runs in a different timezone than the people using the app (e.g.
  server on UTC, shop floor on UTC+8). That fix assumes the browser's
  own clock/timezone is set correctly for wherever it physically is;
  it's a reasonable assumption for devices on a shop floor, less so for
  someone filling in an entry remotely from a different timezone — in
  that case, double-check the pre-filled Task start before saving.
  Re-opening an *existing* entry to edit its Task start/end still shows
  whatever was originally stored, unchanged — that's not a timezone
  conversion, just redisplaying the value, and keeps the round-trip
  (fill in → save → re-open to edit) consistent.
- Tool/Entity uses a native HTML `<datalist>` input — the person
  can type to filter suggestions or click one, but the browser doesn't
  strictly enforce picking from the list; a typo would still submit as
  free text. Name uses the same datalist for suggestions inside its chip
  picker, with the same caveat — a typed name that isn't a real team
  member still adds as a chip. That's a deliberate simplicity tradeoff
  (no JS framework needed); add server-side validation against
  `get_names()`/`get_tool_list()`
  in `app.py` if you'd rather reject anything not in the list.
- There's no authentication — anyone on the local network with access to
  the app can add, edit, or remove entries. That's intentional for a
  trusted shop-floor setup; add auth (e.g. Flask-Login) if you ever
  expose this beyond a trusted local network.
- Like Tool/Entity, **Chamber** and **Category** are set at creation and
  aren't editable from the edit page — only Name(s), Problem Statement,
  Action Item(s), Current Status, Follow up, and Task start/end are. Say
  the word if you'd like Chamber/Category made editable too (they'd
  start getting snapshotted into the edit history alongside the rest).
- The non-destructive edit/delete behavior applies to **passdown
  entries** only. Removing a team member at `/names` is still a real
  `DELETE` on the `team_members` table (their name stays intact on any
  entries they already wrote) — say the word if you'd like that made
  non-destructive too.
- There's currently no in-app way to view removed entries or restore
  one — they're just hidden (`is_deleted = TRUE`) and stay queryable
  directly in Postgres. Easy to add an admin view if useful.
- `app.secret_key` in `app.py` is a static string, fine for local-only
  flash messages. Change it if you ever deploy this somewhere less
  trusted.

## Possible extensions

Nothing outstanding right now — the ideas that used to be listed here
(date-range PDF/CSV export, search across note text, per-entry tags)
have all since shipped as features. Add new ones here as they come up.
