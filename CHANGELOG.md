# Changelog

All notable changes to **Equipment Passdown** are listed here, newest first.
Times are commit times in **SGT (UTC+08:00)**. Generated from the git history
of [pangchi/passdown](https://github.com/pangchi/passdown).

---

## 2026-09-04

### 22:30:40 — Fix mp4 reject issue (`ea4dd25`)
**Fixed**
- Video uploads (mp4/mov/webm) were being rejected. Added
  `VIDEO_EXTENSIONS = {"mp4", "mov", "webm"}` to `config.py` and included it
  in `ALLOWED_EXTENSIONS`.

**Added**
- Videos now play inline via an HTML5 `<video>` player with controls on the
  log page, edit page and HTML export (new `.attachment-video` style).
- README documents where allowed file types live, so a rejected extension can
  be added easily.

**Note**
- This commit also added a full duplicate copy of the app under a nested
  `passdown/` folder (24 files, ~5,700 lines). Looks accidental — worth
  checking and removing.

---

## 2026-08-18

### 10:28:38 — Update search feature (`84dcda8`)
**Changed**
- Search box now also matches **Name(s)** and **Tool/Entity**, in addition to
  Problem Statement, Action Item(s), Current Status and Follow up.
- Footer build timestamp is shown in ISO 8601 UTC without microseconds
  (e.g. `v1.1.0 · Built 2026-08-18T01:51:58+00:00`).
- Simplified `templates/base.html` footer.

---

## 2026-08-17

### 09:07:37 — Editable Tool/Entity and removable attachments (`4f5cf7d`)
**Added**
- **Tool/Entity** is now editable on existing entries, with changes tracked in
  the edit diff history (`previous_tool_entity` column).
- Attachments can be added **and removed** from the edit page. Removal is soft
  (`is_deleted`, `deleted_at` columns): hidden everywhere, but the row and file
  stay on disk.

**Changed**
- Disk-pressure auto-purge now deletes already-removed attachments first,
  before touching any active ones.

**Database**
- `ALTER TABLE passdown_entry_edits ADD COLUMN previous_tool_entity`
- `ALTER TABLE passdown_attachments ADD COLUMN is_deleted, deleted_at`

---

## 2026-08-13

### 14:27:39 — Add mention to Tool/Entity (`e8c0a6f`)
**Added**
- `@mentions` can reference a **tool/entity** (e.g. `@CR1`) as well as people.
  Autocomplete suggests both.
- Tool mentions show as an amber bubble; clicking one toggles the Tool/Entity
  filter.
- The Tool/Entity filter also matches entries that only `@mention` the tool.

---

## 2026-08-07

### 18:28:18 — Remove README.md.bak (`6c6c651`)
**Removed**
- Stray `README.md.bak` backup file.

### 18:27:12 — Update README (`45cdada`)
**Docs**
- Cleared the "ideas" list: date-range export, text search and per-entry tags
  have all shipped.

### 18:20:48 — v1.1.0: Archive export to PDF/CSV (`aae29a9`)
**Added**
- **PDF export** (`/export.pdf`) next to CSV/DOCX/HTML, using `fpdf2`.
  Known limitation: latin-1 only; other characters render as `?`.
- **Archive export**: collapsible section with From/To date pickers for
  exporting a complete date range to PDF or CSV. It ignores other filters.
- `date_from` / `date_to` query params take precedence over "Days back".

**Changed**
- `APP_VERSION` bumped **1.0.0 → 1.1.0**.
- New dependency: `fpdf2==2.7.9`.

### 17:52:00 — Add MIT License (`31a0259`)
**Added**
- `LICENSE` (MIT).

### 17:38:58 — Initial commit, v1.0.0 (`a8060d0`)
**Added**
- Flask + PostgreSQL shift passdown log: entries with name(s), shift,
  tool/entity, chamber, category, task start/end, problem statement, action
  items, current status and follow up.
- Attachments (drag-and-drop, inline images, files saved to disk) with
  disk-pressure auto-purge.
- Filters (name bubbles, shift, tool, category, tags, location, days back),
  search, `@mentions` for people, edit history with diffs, soft delete.
- CSV / DOCX / HTML exports.
- Location lookup from MES `mestoollist` through a Postgres FDW
  (`fdw/`, `scripts/setup_fdw.sh`).
- Name and category management pages, user guide page.
- Deployment examples: Apache reverse proxy config and systemd unit.
