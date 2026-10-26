# Changelog

Versions match `APP_VERSION` in `config.py` (shown in the page footer).
Newest first.

## 1.4.0 — 2026-10-19
- Log pane has a **size slider** (70%–160%) next to the download links to
  scale the log entries; click the percentage to reset. Remembered per browser.

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
