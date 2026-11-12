# Changelog

Versions match `APP_VERSION` in `config.py` (shown in the page footer).
Newest first.

## 1.6.3 — 2026-11-12
- Log-file retention (daily files in `../passdown_logs`) is now configurable
  with `PASSDOWN_LOG_RETENTION_DAYS` in `.env`; default stays 90 days.

## 1.6.2 — 2026-11-12
- Fix: picking a Tool/Entity in New Entry sets the log's Tool/Entity filter;
  clearing the New Entry field now clears that filter too (only if the filter
  still shows the same tool).

## 1.6.1 — 2026-11-12
- Fix: reading MES failed with `column "ToolName" does not exist`. The MES
  database exposes `public.mestoollist` (column `mestoolname`), so the
  defaults are now `MES_DB_SCHEMA=public`, `MES_DB_TABLE=mestoollist`,
  tool column `mestoolname`; the column names can be overridden with
  `MES_DB_TOOL_COLUMN` / `MES_DB_LOCATION_COLUMN`.

## 1.6.0 — 2026-11-12
- **MES data is now read directly from the MES database — no more
  `postgres_fdw`.** The app connects (read-only, 3 s connect timeout) to
  `<schema>.<table>` (default `mes.eqlist`) using new `MES_DB_*` settings in
  `.env`, and reads `"ToolName"` / `"Location"`. The `fdw/` folder,
  `scripts/setup_fdw.sh` and `MES_FDW_*` variables are removed; see the
  README for optional cleanup of the old view/server.
- Config: `MESTOOLLIST_VIEW` / `MESTOOLLIST_COLUMN` replaced by
  `MES_TOOL_COLUMN` / `MES_LOCATION_COLUMN`.

## 1.5.2 — 2026-11-12
- (Superseded by 1.6.0, which removes the FDW.) MES source changed: `public.mestoollist` is now a view over the
  `mes.eqlist` foreign table (`mestoolname`, `"Location"`, `"RI"`,
  `"Module"`, `"ModuleCode"`) instead of `Tool_Selection` +
  `Location_Selection`. Re-run `scripts/setup_fdw.sh` to apply. The FDW
  server is also created with `connect_timeout '3'`. The app code is
  unchanged (it reads only `mestoolname` and `"Location"`).

## 1.5.1 — 2026-11-12
- Fix: app crashed on startup with `PermissionError` when the log folder
  wasn't writable by the service user. It now falls back to stderr/journal
  with an error message instead of exiting. README documents the folder setup.

## 1.5.1b — 2026-11-12
- **Fix: "Proxy Error" / gunicorn `WORKER TIMEOUT` when the MES server is
  unreachable.** The mestoollist tool list and locations are now cached,
  fetched in a background thread, and a page waits at most 3 s for them;
  stale data is used while MES is down. New `MES_*` settings in `config.py`.

## 1.5.0 — 2026-11-12
- **First name entered is the writer.** Marked ✍ in the Name(s) picker and
  the log; other names are co-names. CSV export gains a **Writer** column;
  DOCX/HTML/PDF headings show "Writer (with others)".

## 1.4.0 — 2026-10-19
- Log pane has a **text-size slider** (70–160%, click the percentage to
  reset), remembered per browser.
- **Name filter is hidden by default**; click "Name" to expand it (it opens
  automatically while a name is selected).

## 1.3.0 — 2026-10-19
- Log **Category filter is now multi-select checkboxes** with an "All"
  option ticked by default (no filtering); selected categories are OR-ed.
  Clicking a category bubble on an entry toggles its checkbox.
- **Days back now defaults to 30** (was 14).

## 1.2.0 — 2026-10-19
- Log **Location filter accepts wildcards**: `*` (any characters) and `?`
  (one character), case-insensitive — `F2*` matches `F2C2`, `F2C3`, etc.
  Text without a wildcard is still an exact match.
- Location filter is now a type-ahead text box (suggests known locations)
  with an "(add * for wildcard)" hint, instead of a fixed drop-down.
- Video attachments (e.g. `.mp4`) are accepted and play inline in the log,
  edit page and exports.

## 1.1.0
- Footer shows version and build time in ISO 8601 with UTC offset
  (`v1.1.0 · Built 2026-08-18T01:51:58+00:00`).
- Search box covers Problem Statement, Action Items, Current Status,
  Follow up, plus Name(s) and Tool/Entity.
- Edit page can add/remove Tool/Entity and attachments; attachment
  removal is a soft delete (hidden, not destroyed).
- @mentions can reference a tool/entity as well as a person; mentioned
  tools/names are bubbled and filterable together with the Name/Tool filters.
- Collapsible archive export (date range → CSV/DOCX/HTML/PDF).
- Usage statistics logging.

## 1.0.0
- Initial release: Flask + PostgreSQL shift passdown app (gunicorn behind
  Apache, unix socket, `/eqpassdown/` subfolder).
- Structured entries (Problem Statement, Action Item(s), Current Status,
  Follow up), attachments, `@mention` / `#hashtag` autocomplete and
  clickable filter bubbles (Name, Shift, Tool, Category, Tag, Location
  from `mestoollist`).
- Edit history with highlighted changes per version; soft-delete of entries.
- Downloads of the filtered log as CSV / DOCX / HTML (oldest first,
  attachments shown, images inline in DOCX).
- User guide page, collapsible/resizable panes, copy-friendly text spacing.
- Database-health warning with live polling, disabled entry form when the
  DB is down, double-submit protection, and startup retry without quitting.
- Rotating logs in `../passdown_logs` (daily files in ISO 8601 date
  format, purged after 90 days).
