# Version 3 Action Plan

## Status (keep this section current)

- **Released and tagged: v3.0 through v3.6.3.** Tag lineage: v1.0, v2.0,
  v3.0, v3.1, v3.2, v3.3, v3.4, v3.5, v3.5.1, v3.5.2, v3.6 (v3.6 on
  2026-08-05, 287 tests on SQLite / 293 on MariaDB), v3.6.1 (merged as
  `e054f8e`), v3.6.2 (merged as `2742dc9` on 2026-08-11, 352 tests green
  on SQLite — the database backend is chosen in Settings; see that
  section), v3.6.3 (2026-08-11, 361 tests green on SQLite — four small
  tweaks; see that section). Branches deleted after merging, as is the
  convention.
- **Released and tagged: v3.7**, the work-scoped ReplayGain tagger
  (2026-08-13; see that section). Riding along on the same branch: the
  multi-library webhook and the `cron.m3u_output_dir` tilde fix
  (2026-08-12), the latter carrying a behaviour change — see *Riding
  along on `v3.7-dev`*.
- **Released and tagged: v3.8**, quietness metrics and curation
  (2026-08-14, 612 tests on SQLite / 618 on MariaDB). Find Similar gained
  two filters, on-demand measurement, an audition, and a pool report. The
  banded shuffle originally planned as its Stage D was **deferred to
  Future directions** rather than built — see below for why the pool
  report has to answer that question first. This completes the
  loudness/MA programme.
- **The version lives in four places and nowhere else**: `__version__` in
  `music_manager/__init__.py` (added v3.6.3), the git tag, the heading in
  this file, and the docstrings of test modules added by that release. A
  "bump" is exactly those four edits. `__version__` must be bumped in the
  commit that then gets tagged — if the two drift, the tag is right and
  the app lies about itself.
- Branch naming: use `v3.2-dev` style, **not** a bare version number — a
  branch and tag sharing a name (`v3.1`) made git refuse plain pushes
  ("src refspec matches more than one"). Merged release branches are
  deleted; `v3` and `rules-overhaul` remain from earlier work.
- Branch point: tag `v2.0` on `master` (2026-07-19). All V3 work happens on branch `v3`.
- Decisions resolved 2026-07-19: **D1 = enforce honors track-level EXCEPTs**
  (behavior change). **D2 = empty selection → empty playlist** (fix labels, engine
  unchanged). **D3 = duplicates are a hard stop**: report them and require a fix
  before adding the unique index — do NOT fall back to a non-unique index.
  **D4 = deferred**: present the Year/work_source relocation options in detail when
  Phase 5 reaches that step, before acting.
- Found during Phase 1: V2's Profile Summary is broken —
  `gui.py:1377` unpacks `resolve_selections()`'s 3-tuple into 2 names
  (ValueError for any profile with selections). Fixed by the Phase 1 switch to a
  `SelectionResult` object.
- [x] Phase 0 — Test safety net — **done 2026-07-19** (40 tests green:
  `tests/test_selection.py`, `test_engine.py`, `test_reconcile.py`,
  `test_overrides.py`; fixtures/factories in `tests/conftest.py`;
  `pytest==9.1.1` in `requirements-dev.txt`; run with
  `venv/bin/python -m pytest`). F2/F3/F4/F5 oddities are pinned as
  characterization tests with finding-ID markers — the F3 assertion in
  `test_enforce_readds_track_level_excepts_F3` flips when D1 lands.
- [x] Phase 1 — Core effective-state engine — **done 2026-07-19** (49 tests green).
  Delivered in `selection.py`: `SelectionResult` (attribute-based; retires the
  positional tuple that broke Profile Summary), shared `_decide_track`,
  `load_library_index` (4 bulk queries → `LibraryIndex`), `Rule` /
  `rules_from_profile`, `resolve_effective_state` (per-entity
  included/partial/excluded/none for Phase 4 trees), `classify_selections`
  (active/redundant/no_op/orphaned + governs/covers counts + needs_breadcrumbs,
  for Phase 5 Rules window). Engine: **D1 implemented** — enforce expansion now
  skips explicit track EXCEPTs; `_apply_work_integrity` batched to 3 queries;
  `work_sequence` carried on `ResolvedTrack` (album-mode N+1 gone);
  `find_unused_tracks` bulk-grouped. GUI call sites updated
  (`gui.py` Profile Summary bug fixed, similarity resolver). The
  `overridden_by_integrity` status became unnecessary once D1 landed — enforce
  no longer overrides track EXCEPTs, so classify has no such case.
  Note for Phase 4: `resolve_effective_state`/`classify_selections` take `Rule`
  objects — build them from the GUI's `_current_selections` dicts.
- [x] Phase 2 — Data layer hardening — **code done 2026-07-19** (56 tests green).
  `database.py`: `idx_tracks_library_relpath` + UNIQUE
  `uq_tracks_folder_relpath`, gated by `find_duplicate_track_paths()`;
  duplicates raise `DuplicateTracksError` at startup with the offending rows
  (D3 hard stop — surfaces in the GUI's existing DB-error dialog).
  Verified read-only against both real DBs: local dev (0 tracks) and prod
  `/mnt/MediaLib/music_manager.db` (5,902 tracks) have **zero duplicates** —
  index will create cleanly on next launch. `scanner.py`:
  `_snapshot_analyses`/`_restore_analyses` carry TrackAnalysis across full
  rescans keyed on (folder_id, relative_path) with mtime/size match;
  `ScanStats.analyses_preserved` reported in scan-complete status.
  `similarity.py` timestamps now UTC-aware.
  **User checkpoint passed 2026-07-19** on a fresh testMusicData library
  (`no_git/config-v3test.json` → `no_git/v3test.db`): analyses preserved
  across rescan, Find Similar works without re-analysis.
- [x] Phase 3 — Mechanical GUI decomposition — **code done 2026-07-19**
  (56 tests green, pyflakes clean). `gui.py` (5,285 lines) split via AST into
  `music_manager/interfaces/gui/`: `app.py` (App shell, 35 methods),
  `builder_tab.py` (34), `cleanup_tab.py` (18), `dialogs.py` (9),
  `treeutil.py` (9), `similarity_ui.py` (9), `explorer_tab.py` (6 — deleted
  whole in Phase 5), `common.py` (prefs/log helpers). App = mixin composition;
  120 methods verified reachable via MRO; public surface unchanged
  (`from music_manager.interfaces.gui import launch_gui`). Method bodies are
  verbatim except: `__add_with_breadcrumbs` de-mangled to
  `_add_with_breadcrumbs`, and `Path(__file__).*parent*3` replaced with
  `PROJECT_ROOT` (package is one level deeper).
  **User checkpoint passed 2026-07-19:** GUI behaves as before across tabs.
- [x] Phase 4 — Builder performance + shared-state adoption — **code done
  2026-07-19** (67 tests green, pyflakes clean). New pure viewmodel
  `music_manager/core/viewmodel.py` (`library_tree_rows`/`playlist_tree_rows`
  → `TreeRow` specs; no Tk, no SQL). `builder_tab.py`: cached `LibraryIndex`
  (`_get_library_index`/`_invalidate_library_index`), rebuilds consume
  index + `resolve_effective_state` — **zero SQL in rebuild loops**; V2's
  ~150 lines of hand-derived tag logic deleted; **F2 display bug fixed**
  (playlist pane now shows ADDs inside an excluded album, regression-tested).
  `_is_item_selected`/`_cascade_remove_children`/`_add_with_breadcrumbs`
  answered from the index (no per-call queries). Invalidation: data-changed
  entry `_refresh_builder_tree` + `_refresh_works_list` choke point (all
  cleanup/override/redetect actions funnel there); selection-only changes
  reuse the cache via `_refresh_rules_display`. Remaining DB use in
  builder_tab is click-time actions only.
  **User checkpoint passed 2026-07-19:** refresh is fast. Two findings from
  the walkthrough, both addressed:
  (a) container-remove bug fixed same day — removing an album/work covered
  purely by child rules did nothing in V2; `_remove_item_selection` now
  always cascades descendants and records an EXCEPT only if a broader ADD
  still covers the item (regression-tested);
  (b) **carried into Phase 5:** the playlist pane must also show
  work-integrity expansion — extend `resolve_effective_state` with an
  "included via work integrity" track state, render it visually distinct
  (dimmed variant), count it in the header/strip ("8 selected + 4 via work
  integrity"), and update live when the Integrity dropdown changes. Help
  must state explicitly that integrity applies to works only, never albums.
- [x] Phase 5 — Rules surface + retire Explorer — **code done 2026-07-19**
  (77 tests green, pyflakes clean). D4 resolved: sortable Year column added to
  both Builder trees (album rows); work_source already visible in Cleanup's
  Works Browser. Delivered: integrity-aware effective state
  (`resolve_effective_state(..., work_integrity="enforce")` mirrors engine
  expansion incl. D1, parity-tested against `generate_playlist`); playlist
  pane renders expanded movements in dimmed blue ('integrity' tag) and
  updates live on Integrity dropdown change; health strip
  (replaces "(empty = all tracks)" label — D2 text fixed everywhere) with
  active/redundant/no-op/orphaned counts + "N + M via integrity" tracks,
  click opens Rules window; new `gui/rules_window.py` (RulesWindowMixin):
  graded rule list, surgical Remove, Reveal-in-Library, Clean Up dead rules;
  breadcrumb backfill on profile save AND load; `explorer_tab.py` deleted,
  tab removed, all references gone; help_content + USERGUIDE rewritten
  (Rules section added, Explorer removed, integrity works-only documented).
  **Remaining user checkpoint:** GUI walkthrough — two-tab layout, Year
  column, dimmed integrity tracks toggling with the Integrity setting,
  health strip counts, Rules window (remove/reveal/clean up), and a
  save→load round trip.
- [x] Phase 6 — Minor findings sweep — **done 2026-07-20** (80 tests green).
  `plex.py` uses `NamedTemporaryFile` (mktemp retired); webhook m3u filenames
  allowlist-sanitized (`[A-Za-z0-9._ -]`, leading dots stripped, fallback name;
  traversal-tested); autosave delete+recreate wrapped in `database.atomic()`;
  dead `assigned` local removed from `redetect_works`; CLAUDE.MD rewritten for
  the V3 architecture; USERGUIDE gained a "What's New in Version 3" section.
  Deliberately skipped (documented, not needed): DB uniqueness on
  profile names (GUI enforces a stricter global rule) and on Override match
  keys (code-enforced upsert).
- **Incident 2026-07-20 (during Phase 7 verification):** overnight full rescan
  on the prod DB; the workstation suspended ~02:30 (webhook poll gap proves it);
  the CIFS `soft` mount returned disk-I/O errors on resume. Catalog rebuilt
  fine (integrity ok, 5,902 tracks, profiles intact) but **all similarity
  analyses were lost** — the F8 snapshot lived only in process RAM and the
  restore step fell inside the crash window. No backup contains analyses
  (db_bkp copy predates the table); user must re-run analysis (it is
  resumable). Hardening landed same day:
  (a) **durable snapshot** — `track_analysis_snapshot` table written before
  the delete, consumed only on successful restore, retried by any later scan
  (full or incremental); snapshot failure aborts the scan; restore failure is
  non-fatal with the snapshot retained;
  (b) **autosave resilience** — tick catches failures, logs once with
  traceback then one line per retry, recycles the DB connection (peewee
  auto-reconnects), reports recovery; `_on_close` can no longer be blocked by
  a failing final autosave.
  Reminder for the user: the installed copy at `~/.local/share/
  classical-manager` is V2 vintage — refresh it after the v3 merge.
- [x] Phase 7 — Verification & wrap-up — **complete 2026-07-20.** Automated:
  full suite 83 green; py_compile sweep clean; pyflakes clean except
  pre-existing cosmetic f-strings in cli.py. User verification: full rescan
  + clean Scan Changes on the prod library (surfaced the mount incident →
  hardening above), GUI walkthroughs each phase, user sign-off 2026-07-20.
  **Merged `v3` → `master`, tagged `v3.0`.** Post-release: refresh the V2
  install at `~/.local/share/classical-manager`; audio re-analysis running
  (resumable). v3.1 work starts from the Backlog section above.

## v3.1 progress (branch `v3.1`, started 2026-07-21)

- [x] **Dirty-state tracking with save prompts** — done 2026-07-21 (91 tests
  green). `_builder_snapshot`/`_mark_builder_clean`/`_is_builder_dirty`/
  `_confirm_discard_changes` in `builder_tab.py`; baseline captured on
  new/save/load (NOT on autosave restore — restored work is genuinely
  unsaved). Prompts on New, Load, library switch (reverts the combobox on
  Cancel), Find Unused, and window close. `_save_profile` now returns
  bool and prompts for a name when the profile is unnamed
  (`_ask_profile_name`). Discard clears the autosave so discarded work
  cannot be resurrected next launch. "• unsaved" marker in the health
  strip; settings widgets refresh it via `_on_setting_changed`. Note:
  `_new_profile` returns bool — callers that populate afterwards (Find
  Unused) must abort on False or they merge two playlists.
- [x] **Merged scan dialog** — done 2026-07-21. One "Scan Library..." button →
  `_ask_scan_mode` (Quick default / Full rebuild with cost stated); Quick is
  disabled with an explanation when `can_scan_incremental()` is False (new
  core helper), replacing the incremental scanner's silent refusal.
  `_scan_changes` wrapper removed; both `_run_scan*` workers unchanged.
  CLI keeps `scan` and `scan-changes` verbs.
- [x] **Analyze Audio button** — done 2026-07-21. `similarity_popup.py`
  deleted (556 lines); sidebar button is now batch analysis with gap count,
  time estimate, progress, cancel, and summary (`_analyze_audio`,
  `_analysis_gap`, `_analysis_estimate`; `_run_sim_analysis(None)` = analyze
  only). Find Similar keeps auto-top-up but warns loudly above
  `_LARGE_ANALYSIS_GAP` (100) unanalyzed tracks.
- [x] **Thumbs-down webhook** — done 2026-07-21. Core: `find_track`
  (case-insensitive title + album/artist narrowing, or exact path; raises
  `TrackNotFound`/`AmbiguousTrack` — never guesses) and
  `exclude_track_from_profile` (idempotent; converts a conflicting ADD;
  scope=track|work). CLI `exclude-track` (exit 2 ambiguous/invalid, 3 not
  found). Webhook command `exclude-track` with a `track` object, plus an
  optional shared secret (`webhook.token`/`token_env`, `X-Auth-Token`,
  constant-time compare) since this is the first op that writes to profiles.
  Verified end-to-end against a scratch DB under enforce integrity.
  Documented in help, USERGUIDE (with a Music Assistant HA snippet),
  main.py usage, and config.example.json.

## v3.4 (branch `v3.4-dev`, started 2026-07-30)

- [x] **APEv2 tags** — read Monkey's Audio (`.ape`) and WavPack (`.wv`).
- [x] **Scan report dialog** — what a scan actually did, including files
  skipped per extension and tracks with no track number.
- [x] **Cleanup edit fields** — select-on-focus, Return applies, real
  select-all; Ctrl+A in the works tree; live "N work(s), M track(s)
  selected" so a short selection is visible before acting, not after.
- [x] **A recording is not a file** (bug, 2026-07-31). Applying a composer
  to all 18 tracks of "Waltzes (Prokofiev; Scottish National Orchestra,
  Neeme Jarvi)" stored only 8 overrides.

  Both `set_override` and `_match_track` treated the MusicBrainz *recording*
  ID as if it identified a *file*. It doesn't: a compilation reuses
  recordings that also sit on their original albums. Ten of the Waltzes
  tracks share recording IDs with three other Järvi/SNO albums, so
  `_find_existing_override` matched by MB ID first and updated the *other
  album's* row, while `_match_track`'s `Track.get()` resolved the same ID to
  one arbitrary track (lowest rowid). The other copies were unreachable.

  Measured before fixing: 7,279 tracks, 10 recordings on more than one file
  (20 files, 0.3%), 10 affected overrides, all `composer`. **No data was
  corrupted** — only because the value written matched what the other row
  already said. A different composer would have silently rewritten another
  album.

  **Decision (user, 2026-07-31): an override identifies a FILE.** Path is
  the primary match key. The MB ID remains the fallback that carries a
  correction across a rename, but only adopts a row whose own path is
  orphaned; at apply time, an ambiguous MB ID with a missing path is
  skipped and logged rather than applied to an arbitrary track. Explicit
  "apply to all copies of this recording" stays a possible future action —
  deliberate, not a silent side effect. Position-specific fields
  (`disc_number`, `track_number`, `movement_number`) are why per-recording
  semantics can't be the default.

  Regression tests in `tests/test_overrides.py` cover: two copies get two
  rows; different values on each copy stay put; every copy is reachable by
  apply; renames still carry forward and refresh the stale path; ambiguous
  match is skipped.

  *Lesson: the reported symptom ("only some tracks took it") pointed at the
  selection UI, and the first fix was aimed there and was wrong. What
  settled it was replaying the exact loop against a copy of the production
  database and logging each call's create-vs-update outcome.*

## v3.5 — MySQL/MariaDB backend (branch `v3.5-dev`, started 2026-08-03)

Server: MariaDB 10.6.7 at `mariadb.lan` (10.10.0.130). Database
`classical_manager`, charset utf8mb4, **collation utf8mb4_bin**, user
`cmanager`@`%`. The box also hosts the user's Kodi databases — all changes
stay additive. Driver: `PyMySQL==1.2.0`.

**Facts established by testing the server, not by assumption:**

- The server default `utf8mb4_general_ci` is case- AND accent-insensitive:
  `Bach`=`bach` *and* `Dvořák`=`Dvorak` both compare equal (so does
  `utf8mb4_unicode_ci`). That would merge distinct composers under the
  unique index on `composers(library, norm_key)`. MariaDB 10.6 offers only
  `utf8mb4_bin`/`utf8mb4_nopad_bin` as non-`ci` options, so utf8mb4_bin it
  is — which also matches SQLite's binary comparison. Measured on the real
  library: 0 case collisions, 0 accent collisions today, so migrating now
  is safe; the divergence would appear later.
- **The client connects as latin1 by default.** `charset="utf8mb4"` must be
  passed explicitly or accented names corrupt on write. ASCII test data
  hides this.
- **Index width: cap indexed text at VARCHAR(512).** InnoDB's 3072-byte key
  limit is real — a non-unique index on `(INT, VARCHAR(768))` fails with
  error 1071. UNIQUE indexes appear to escape it only because MariaDB 10.4+
  silently rewrites over-long unique keys as `USING HASH`; verified in the
  generated DDL, where `composers` came out
  `UNIQUE KEY (...) USING HASH` over a `text` column. That is MariaDB-only
  (MySQL 8 errors) and a hash index cannot serve ordered or prefix scans.
  512 keeps every index a real B-tree and stays MySQL-portable. Longest
  observed `relative_path`: 300 chars (p99 232).

**Export/import does NOT cover migration** (audited 2026-08-03).
`export_library` omits: all `TrackAnalysis` (6,373 rows, ~4 MB — the
expensive librosa work), `Track.file_mtime`/`file_size` (so the next scan
re-reads everything), `genre`/`performer`/`conductor`/`ensemble`,
`disc_total`, `work_tag`, `mb_work_id`, `first_seen`,
`PlaylistProfile.auto_generated`, and `Override.updated_at`. It also
assigns every imported album to the *first* source folder — a latent bug
for multi-folder libraries. Hence migration is a direct row copy (Phase 3),
not a JSON round trip; the JSON export stays a portable curation backup.

- [x] **Phase 1 — Backend abstraction** — done 2026-08-03 (212 tests green).
  `pw.DatabaseProxy()` replaces the module-level `SqliteDatabase(None)`;
  `_make_database()` builds SQLite (with the WAL/FK pragmas) or MySQL (with
  the mandatory charset). `initialize_database(db_path=None, settings=None)`
  keeps the old path-based calls working for tests and the GUI's
  fall-back-to-local. New `config.DbSettings` + `resolve_db_settings()`;
  optional `database` config section, absent = SQLite as before;
  `password_env` beats `password` so a shared config need not carry the
  credential; `describe()` never includes the password. Migrator chosen per
  backend. `PRAGMA index_list` replaced with portable `get_indexes()` (also
  in the tests), and `CREATE INDEX IF NOT EXISTS` dropped since MySQL
  rejects it. CLI and GUI connection-failure hints are now backend-aware.
  Verified against the live server: config → connection → DDL, failing only
  at `_ensure_track_indexes`' non-unique index on a `text` column — exactly
  Phase 2's scope.
- [x] **Phase 2 — Schema portability** — done 2026-08-03 (214 tests green on
  SQLite, 7 more against the live server). `MAX_PATH_LENGTH = 512` /
  `MAX_KEY_LENGTH = 255` in `database.py`; every column taking part in an
  index is now a `CharField`: `Track.relative_path`, `Album.album_key`,
  `Composer.norm_key`, `ProfileSelection.key`, `ProfileSelection.level`
  (16), `AnalysisSnapshot.relative_path`. `track_paths` stays TEXT — 6,040
  chars, unindexed. No migration needed: SQLite ignores column widths, so
  existing databases keep working untouched (verified against a copy of the
  production library — 7,279 tracks, 431 albums, 758 composers, 6,373
  analyses all read back, prefix queries included).

  Scanner guard: a relative path over the cap is recorded in
  `paths_too_long` and skipped, on both the full and quick paths, and
  surfaced in the scan report. Skipping beats truncating (which would
  collide two tracks onto one identity) and beats erroring mid-scan. In the
  quick path the key is still added to `seen_keys`, so an existing row is
  not mistaken for a deleted file.

  *`ProfileSelection.level` was missed on the first pass and the DDL test
  caught it* — its unique index is `(profile, level, key)`, and `level` was
  still TEXT, so MariaDB silently made the whole index `USING HASH`. Nothing
  else would have reported this: no error, no warning, and every test
  passed. The `USING HASH` assertion is the only reason it surfaced; keep
  it.
- [x] **Phase 3 — Migration command** — done 2026-08-03 (226 tests green on
  SQLite, 8 against the live server). `music_manager/core/db_migrate.py` +
  `main.py --cli migrate-db --target URL [--source FILE] [--dry-run]
  [--force]`. Table-by-table copy in FK order preserving primary keys,
  reading through raw SQL so values move untranslated, batched at 500 rows
  (~0.3 MB against a 16 MB `max_allowed_packet`). Target password comes
  from `$CM_TARGET_DB_PASSWORD`, not the URL, which is visible in `ps`. A
  non-empty target is refused unless `--force`. Each table is verified by
  re-reading it and comparing a content hash of normalized values.

  **The verification immediately earned itself.** `Track.file_mtime` was a
  `FloatField`, which peewee maps to MySQL `FLOAT` — single precision,
  ~7 significant digits. A Unix timestamp needs 17, so `1666807963.287016`
  came back as `1666810000.0`, over half an hour out. Every file would have
  looked modified to an incremental scan, and analysis restore compares on
  exactly this value, so the 6,373 analyses would have been re-computed.
  Counts and row totals were all perfect; only the content hash caught it.
  Fixed by moving every `FloatField` to `DoubleField` (`Track.file_mtime`,
  `TrackAnalysis.volatility`, `AnalysisSnapshot.volatility` and
  `.file_mtime`). SQLite is unaffected — it has one numeric type — which is
  why this could only ever surface against a server.

  The other two mismatches were representation, not loss: SQLite keeps
  tz-aware timestamps as text with `+00:00` while MySQL `DATETIME` has no
  timezone and stores whole seconds. Normalization compares instants, so
  the values are equal; MySQL holds naive UTC.

  **Real-data result:** a copy of the production library (22,701 rows —
  7,279 tracks, 5,420 works, 6,373 analyses, 1,773 selections) migrates in
  ~2.5 s with every table verified. `generate-all` against MariaDB produced
  22 of 24 playlists with track sets identical to SQLite; the other two
  differ between two *SQLite* runs as well, so that is the shuffle on
  length-limited profiles, not the backend.
- [x] **Phase 4 — Close the export/import gaps** — done 2026-08-03 (233 tests
  green). `library_io` now writes `format_version: 2` carrying similarity
  analyses (keyed by folder + relative path, so they survive a rebuild), the
  ten missing `Track` columns, `folder_idx` per album,
  `profile.auto_generated`, and `override.updated_at` (previously stamped
  "now" on every restore, losing the history). Import accepts version 1
  files unchanged — absent fields stay absent rather than being invented.

  The album→folder bug is fixed: every imported album used to be assigned
  to the *first* source folder, which for a multi-folder library is both
  wrong and capable of colliding on UNIQUE (folder_id, relative_path). A
  test now round-trips two folders holding the same relative path.

  Verified on the real library: a 14.2 MB export re-imported into an empty
  database gives byte-identical values for all 7,279 tracks across all 16
  columns, all 6,373 analyses, and every work and composer assignment.

  *Note on the verification itself: the first comparison reported 84
  mismatching tracks and was wrong — it compared "first 300 rows by id" in
  each database, but ids are assigned in import order, so the two samples
  were different tracks. Match on `relative_path`, never on id, when
  comparing across a rebuild.*
- [x] **Phase 5 — Test matrix** — done 2026-08-03. `pytest --backend=mysql`
  runs the **whole** suite against a server, not just the schema tests:
  233 pass on SQLite (7 s), 239 on MariaDB (35 s; +8 schema tests that
  SQLite skips, −2 marked `sqlite_only`). `./run-tests.sh --both` runs
  both and resolves the target from `CM_TEST_MYSQL_URL` or from
  `config.json`, always against its own `cm_test` schema so a real library
  is never truncated.

  Fixtures: MySQL builds the schema once per session and TRUNCATEs between
  tests. Deliberately not drop-and-recreate — repeated DDL is slow and is
  what wedged `dict_sys.latch` and took the server down. Two things had to
  be handled that only appear in a full run: other suites rebind the global
  proxy (the migration tests point it at their own target, the io tests
  close it), so `db` re-points every test; and `test_mysql_schema.py`
  legitimately drops every table, so `db` recreates the schema when it
  finds it missing.

  `sqlite_only` marks the two tests asserting SQLite's index bootstrap —
  `DROP INDEX x` without `ON <table>` is invalid MySQL, and the server-side
  equivalents already live in `test_mysql_schema.py`.

  *Run `--both` before merging anything touching models or queries.* SQLite
  cannot catch type-mapping faults at all: it has one numeric type and
  ignores column widths, which is why it passed a FLOAT that shifted file
  mtimes by half an hour and TEXT columns MySQL cannot index.

## v3.6 — Similarity that measures what it claims to (tagged 2026-08-05)

*Backfilled 2026-08-11 from the six commits in `v3.5.2..v3.6`, which is
where the measured numbers below come from. v3.6 shipped without a
section here; this records what changed, and the reasoning survives only
as far as those commits carried it.*

The theme is that several numbers Find Similar depended on were not
measuring what their names said.

**Feature vector v3, then v4.** Measured on the v2 vector across 20,000
random pairs, timbre and register drove **74%** of every comparison while
loudness and percussiveness drove **6%** — an accident of column count,
since MFCC contributed 13 z-scored columns and loudness contributed 1.
Features are now declared in `FEATURE_GROUPS`, each group normalised by
`sqrt(size)` before its weight applies, so influence is a decision rather
than a side effect. Register defaults to 0.6: cello and violin are close
musically, but not when you specifically want violin.

Two gaps closed with it. **Dynamic range replaced volatility**, which was
`std/mean` of windowed RMS — a ratio, so a small mean inflated it and
quiet music scored as highly dynamic. It correlated −0.39 with loudness;
it was measuring quietness. It is now the dB difference between the 95th
and 10th percentile of frame loudness, with mean loudness as a separate
dimension so "how loud" and "how much it varies" stop being one
confounded number. **Rhythm was entirely new** — tempo, onset rate, onset
strength, zero-crossing rate. Correlation between v2 feature distance and
tempo difference was 0.11: effectively blind.

**HPSS removed.** `librosa.effects.harmonic` was 61–72% of analysis
runtime and fed only tonnetz; computing tonnetz from the raw signal gives
the same direction (cosine 0.998–0.999). A full re-analysis went from
21.7 h to 6.9 h single-threaded while *gaining* features.

**FEATURE_VERSION 4** came from gating silence out of the measurements.
Six real tracks reported 150–186 dB of dynamic range — physically
impossible — because any track with more than 10% silence put the 10th
percentile in the digital-silence floor. The damage was not local:
outliers at 186 dB against a median of 16.5 inflated that column's
standard deviation by 30%, and z-scoring divides by it, so dynamic range
had been counting about a third less than it should for *every* track.
Frames more than 60 dB below the track's own peak are now excluded.

**Scoring reworked.** Match % and Agreement both derived from the median
distance among the seeds, which describes the seeds and says nothing
about the library. Match % read 100% for all 2,000 results of a 5-seed
search *and* all 2,000 of a 546-seed search. It is now a percentile of
candidate distances — 99.5 means "closer than 99.5% of your library" —
and each result carries its rank. Agreement saturated at both ends (0/4
for every result in one search, 464/546 in another) and was removed;
Blend now interpolates between distance to the nearest seed and mean
distance to all seeds. Per-group weight sliders live in the Find Similar
window, with rhythm split into tempo and attack — a regrouping of the
same stored vector, so no re-analysis.

Worth keeping: **seed-count-aware aggregation was planned and then not
implemented.** Measuring it on v3 showed the features had already fixed
most of the degradation from 4 seeds to 546, and mean-of-all actively
hurt one profile. The evidence stopped supporting the plan.

**MySQL concurrency.** `initialize_database` ran 49 queries — nine
`create_tables`, three `get_columns`, the similarity `ensure_table`, two
index inspections — on every GUI launch, CLI command and script. Free
against SQLite; against a server with a second client connected it is
metadata-lock contention on every table, and it wedged the instance
twice, unkillable, needing a restart both times. A `schema_state` table
now records the version the database was built to: **49 queries on first
startup, 1 on every startup after.** Bumping `SCHEMA_VERSION` is how a
future upgrade reaches an existing database. Separately, MySQL
connections now use a `ReconnectMixin` — MariaDB's `wait_timeout` is 8
hours and peewee holds one connection with no recovery, so a GUI left
open overnight lost it.

**Sidebar buttons tearing during scans.** `scan_status` was a `CTkLabel`
created with no width, and its text is `[n/total] <filename>`, so every
progress update changed the label's requested width to whatever file the
scanner had reached — routinely wider than the 260px sidebar. That forced
a pack re-layout of every sibling, and a CustomTkinter button repaints
its whole rounded-rectangle canvas each time; the tearing was that
repaint interrupted. `pack_propagate(False)` holds the frame but does
nothing to stop a child asking for more. Fixed width plus truncation, and
progress updates throttled to ~20/s.

Recorded because it cost time: **the first two diagnoses were both
wrong** — widget calls from the worker thread (already marshalled through
`root.after`) and event-loop flooding (a scan over CIFS manages about
twelve files a second; the arithmetic does not support it). The unbounded
label was found by reading the widget construction, not by reasoning from
the symptom.

Also: the Find Similar dynamic-range filter still ran 0–1, correct for
the old unitless ratio and wrong for dB — ticking it would have excluded
every track. `SECONDS_PER_TRACK` dropped 10.5 → 3.1. And `-j/--workers`
was missing from `main.py`'s `analyze-similarity` help line, which is the
flag deciding whether analysis takes forty minutes or seven hours.

Ended at 287 tests on SQLite, 293 on MariaDB.

## v3.6.1 — Bug fixes, and an MA export path that was already there (branch `v3.7-dev`, started 2026-08-09)

*Numbered as a patch, not v3.7 (decided 2026-08-11). Every `.0` on this
project introduced a capability; this one adds none. `generate-all
--format m3u --output-dir` behaves identically before and after. v3.5.1
and v3.5.2 set the precedent — v3.5.2 was a single GUI fix, close kin to
the file-chooser freeze here. The branch keeps its `v3.7-dev` name
because renaming a pushed branch buys nothing.*

Started as "add a Music Assistant export target". **It shipped as nothing
of the kind: MA needed no new code at all.** Everything MA requires was
already in CM —

    main.py --cli generate-all --library MainMusic --format m3u \
        --output-dir /mnt/MediaLib/Albums/Playlists

with `targets.m3u.path_style` set to `relative_to_playlist`. MA's File
System provider imports by scanning a folder, and CM has written batches
of M3U files to a chosen folder for a long time. Measured MA behaviour is
in `no_git/CM-MA-findings.md`; the export design doc
(`no_git/CM-MA-export-handoff.md`) is superseded by this section.

The route to that answer is worth recording, because it was not free.
A separate `targets.ma` was built first, then renamed to a `publish`
operation on the M3U target, then removed entirely. What settled it:
`generate-all --target ma` and `generate-all --format m3u --output-dir`
produced **byte-identical files** — diffed, not assumed. The second
attempt collapsed the two targets but kept a `publish` config block, a
`--publish` flag, `publish`/`scan+publish` in both cron and the webhook,
and a separate module. That was renaming, not simplifying; the user
called it and the whole apparatus came out (2026-08-11).

**The lesson, since it will come up again:** the design document reasoned
about MA's requirements without first checking what CM already did with
them. Every requirement it derived was real; the conclusion that they
needed new machinery was not. Check the existing capability against the
new requirement before designing to it.

Kept from the attempt, on their own merits:

- `safe_profile_filename` / `find_filename_collisions` in `paths.py`, and
  a warning when two profiles in one `generate-all` sanitize to the same
  filename — the later one silently overwrote the earlier.
- A warning channel in `config.py`, which had none: every path raised
  `ConfigError`. `load_config` has thirteen call sites, so warnings are
  emitted once per `(path, message)` rather than on every load. It carries
  the pre-existing footgun the findings doc identified — `path_rules` set
  alongside `path_style: relative_to_playlist`, which `m3u.py` ignores.
- `validate_config`, so the settings dialog can check a config before
  writing it.
- Direct test coverage for `M3USerializer`, which had none despite being
  the oldest output format and the file the Plex target hands off.

**`base_path` was removed** (user's call, 2026-08-11). It prepended a
prefix to absolute paths, did nothing at all in relative mode, and read as
an output folder — the installed config had it set to
`/mnt/MediaLib/Albums/Playlists` under `relative_to_playlist`, where it
was inert. `path_rules` with `path_style: absolute` does the real job
properly. A config still carrying the key keeps loading and gets a warning
saying it no longer applies.

Note the three filename sanitizers that still exist (`cli.py`,
`webhook.py`, `classical-manager-cron.sh`); the first two disagree, as
`Bach & Sons` → `Bach_&_Sons` from the CLI and `Bach___Sons` from the
webhook. Left alone deliberately: the webhook's is stricter because its
input arrives over HTTP, and the shell copy cannot call Python.

**Found while adding a Settings section during the attempt: saving
Settings deleted every config key the dialog does not show.** It rebuilt config.json from
its own fields and wrote the whole file, so `database`, `cron`, `webhook`
and `autosave_interval` all vanished on any save — and losing `database`
drops this MariaDB install back to SQLite at `db_path`, quietly opening a
different library. Within a section too: Plex's `strategy` is read by
`plex.py`, has no widget, and did not survive. The save now updates the
loaded config, the assembly lives in `apply_settings_fields` so it is
testable without a display, and the result is validated before writing —
an invalid config.json otherwise stops the app loading on its next start.

A second, worse hazard in the same area: choosing a folder from Settings
froze the whole desktop. Settings is modal, so it holds an X input grab,
and zenity is a separate application — the grab stopped the chooser (and
everything else) receiving input while the app blocked in `subprocess.run`
for up to 300 seconds still holding it. `filedialog` now releases the grab
around any external chooser. Latent since long before this work: the
Database browse button in the same dialog hung identically.

That browse button was also invisible. It was gridded into column 2, but
the plain field rows span columns 1-2 with a 400px entry, which stretches
column 2 past the visible width of the scrollable frame — and there is no
horizontal scrollbar to reach it. The entry and its button now share one
cell in their own frame, so nothing depends on column widths, and the
button is labelled "Browse…" rather than "...".

## v3.6.2 — The database is chosen in Settings (branch `v3.6.2-dev`, started 2026-08-11)

The `database` section landed in v3.5 and the settings dialog never
caught up: it showed one SQLite file browser, wrote the legacy top-level
`db_path`, and said nothing about a backend. On this MariaDB install the
field displayed a path that was not in use, and editing it changed
nothing. v3.6.1 stopped the dialog *destroying* that section; this
release lets it write one.

- **Backend chooser** — SQLite or MySQL/MariaDB, with the rest of the
  section swapping to match: a file browser, or host / port / database /
  user / password / password env var / charset.
- Both panels are built in the **one grid**, hidden with `grid_remove()`.
  A nested frame per backend was tried first and looked wrong: it has its
  own column widths, so the server fields did not line up with the Plex
  fields below. An emptied grid row collapses to nothing, so hiding a
  panel leaves no gap.
- **Test Connection** tries the entered values on a worker thread with a
  5-second timeout, and reports the driver's own error. An unreachable
  host blocks for the whole timeout, so it cannot run on the UI thread —
  and the alternative is discovering a typo on the next start, since a
  database change only takes effect on restart.
- The password field is masked and shows **only a password stored in
  `config.json`**. One resolved from `password_env` stays in the
  environment; displaying it would copy the secret into the file on the
  next save.
- **The legacy `db_path` is retired on save.** `resolve_db_settings`
  already prefers `database.path`, so a config carrying both named one
  database and opened another. Reading `db_path` is unchanged, so
  configs that never meet the dialog keep working.
- A SQLite path equal to the default is **not** written out. The field is
  prefilled with the path in use, so writing it back unconditionally
  would pin `/home/…/ClassicalManager/music_manager.db` into config.json
  — and a config that then moved between the dev checkout and
  `~/.local/share/classical-manager` would have one opening the other's
  database. The dialog **says so** while the field holds the default
  (added 2026-08-11 after the user switched to SQLite, picked the default
  file, and found nothing in config.json). Silence there reads as a
  setting that was ignored. The note is driven by a `StringVar` trace, not
  a key binding, because Browse… fills the field in without the keyboard.
- The restart prompt now compares **resolved `DbSettings`**, not the raw
  section. Writing `database` for the first time rewrites keys without
  changing which database opens, and a restart prompt for that is noise.

**Browsing to an existing database asked to replace it** (found
2026-08-11). Pointing the browse button at a second `.db` produced *"A
file named music_manager.db already exists. Do you want to replace it?"*
— from GTK, not from us. The call already passed `confirmoverwrite=False`
and `filedialog.py` had been dropping it on the floor for Linux: GTK4
removed the property that turns the prompt off, so zenity 4's save
chooser always asks and no argument spelling suppresses it (kdialog is
the same). `confirmoverwrite=False` now routes to tkinter, whose
`tk_getSaveFile` honours it (`tkfbox.tcl` only prompts when the flag is
set). A save dialog is still the right control here — you must be able to
name a database that does not exist yet — and every real save keeps its
native chooser and its confirmation. Second time zenity has cost this one
button: v3.6.1 fixed it freezing the desktop under a Tk grab.

**Comments in config.json** (asked 2026-08-11): JSON has none, and adding
a JSONC parser would be worse than useless here — `save_config`
re-serializes the whole file, so the first Save would delete every
comment. The `_`-prefixed key convention already in
`config.example.json` survives a round trip, because the dialog
deep-copies the loaded config and only touches keys it owns. One section
rejected it: `similarity_weights` validated its keys against the known
groups, making a note there the single way to write a config.json the app
refuses to load. It now skips `_` keys, like everywhere else.

## v3.6.3 — Small tweaks, and a version the app can state (branch `v3.6.3-dev`, 2026-08-11)

Four items off the user's list, one commit.

- **Rank and Dyn Range sorted as text** in Find Similar — 1, 10, 11 rather
  than 1, 2, 3. `numeric_sort_key` knew `12 trk`, `95%`, `M:SS` and `N/M`
  but not `1 of 500` or `12.3 dB`, so it returned `None` and
  `_sort_treeview_column` fell back to a string sort. Rank sorts by the
  rank, not the pool size, which is identical on every row anyway.
- **A blank cell no longer disqualifies a numeric column.** The sort
  required *every* value to parse, so one unanalysed track — empty Match
  and Dyn Range — dropped the whole column back to text. Blanks are held
  out and reattached at the end, staying out of the way in either
  direction.
- **Show Album** added to the Find Similar context menu, matching the
  builder tree's menu.
- **The wheel now scrolls `CTkScrollableFrame`.** CustomTkinter binds only
  `<MouseWheel>`, which X11 never sends — there a wheel turn is
  Button-4/Button-5 — so its own Linux branch
  (`ctk_scrollable_frame.py:262`) is unreachable and the Settings dialog
  could not be wheel-scrolled on Linux at all. It worked on Windows, which
  is why the behaviour looked inconsistent. `bind_wheel_scroll` in
  `common.py` binds on the enclosing **Toplevel**, not with `bind_all`: a
  Toplevel is in every descendant's bindtags, so it catches the wheel
  anywhere in the dialog and dies with the window instead of outliving it
  application-wide the way CustomTkinter's binding does. The canvas check
  is what stops a wheel turn over a Treeview from scrolling the frame
  underneath it as well. Trees and text widgets never needed this: Tk
  gives those class-level Button-4/5 bindings.
- **`__version__` in `music_manager/__init__.py`**, plus `--version` on
  `main.py` and the version in the window title. A literal, not
  `git describe`: that needs a `.git` directory *and* the git executable,
  and the Windows setup path assumes only Python — a frozen build would
  report "unknown" for the same commit that reads 3.6.3 in a checkout.
  `--version` is answered in `main.py` before routing, so it means the
  same thing on either side of `--cli` and needs no database.

`help_content.py` still describes an **Agreement column** (`12/31`) that
the v3.6 rewrite replaced with Rank; the sorting and context-menu bullets
were updated here, that one was left for whoever re-reads the Find Similar
help as a whole.

## v3.8 — Quietness metrics and sleep-playlist curation (branch `v3.8-dev`, started 2026-08-13)

Filter Find Similar on how likely a track is to wake you, and control level
seams in a shuffled pool. Plan: `no_git/CM-quietness-plan.md`. Stage A's
report, which gates the rest: `no_git/CM-quietness-A4-report.md`.

Four stages. **Stage A gated everything and ended in a report, not code.**
A1 the tag-derived playback level and its coverage; A2 an `ffmpeg ebur128`
metrics harness; A3 the distribution from a 300-track sample; A4 the report.
Then B storage, C Find Similar, D banded shuffle.

### Stage A — what the measurements changed

**Audio measurement is required, and the reason is not the one expected.**
The plan allowed that high ReplayGain coverage might make the audio pass
unnecessary. Coverage came back at **99.5%** — the entire 38-track residue
is the 31 m4a and 7 ape files no tagger can write — and the answer was
still no. **68.8% of the library scores exactly zero** on the tag-derived
axis, by construction: a standalone work is its own work, so it plays at
precisely the reference level, and the library is ~3,800 standalone works
out of ~5,500. Coverage and discriminating power turned out to be different
questions, and only the first was being asked.

The algebra itself is exact: `ALBUM_GAIN − TRACK_GAIN` recovered
`L_m − L_work` with a **worst disagreement of 0.000 dB** over seven
re-measured members, and **3,772 of 3,772** standalone works gave exactly
zero.

**`startle_delta` inverts, and was dropped.** It is `p99(S) − integrated`,
and R128 integrated loudness is *gated*: for a track with 30 s at −1 dBFS
and 50 s at −20, every quiet block falls outside the relative gate and
integrated converges on the loud passage itself. A 200 ms crack scores 7.17
and a 30 s blast scores 0.04 — the harmless signal ranked ahead of the
dangerous one. Pinned as a test so the arithmetic is not "fixed" without
meeting the reason.

**Two sliders ship, not five.** `startle_local` (0..25 LU) and the derived
playback level (−10..+5 dB). The two are **orthogonal** — the offset
correlates at −0.05 to −0.11 against every envelope metric — which is the
argument for keeping both. `rise_rate` measures how deep the trough was ten
seconds earlier, so it scores 64 LU on a piece with 11.6 LU of range; `lra`
duplicates the `volatility` already in the UI at r=0.78.

**Three assumptions in the plan did not survive contact.** ffmpeg's
per-frame `framelog` prints nothing at the default log level, so the series
comes from `ametadata=print` on stdout instead. Short-term loudness is
invalid until t=2.9 s and momentary until t=0.3 s, so head and tail levels
come from momentary — an entry 1.5 s in is exactly the seam risk, and S
cannot see it. And percentiles do not reject brief transients: a 3 s window
smears 200 ms across thirty frames, so what damps a crack is the window's
own averaging, 19 dB down to 7.9 LU.

**One finding changed a specification rather than a parameter.**
`tail_level` runs to −62 LU with 69 of 299 tracks below −20, while
`head_level` bottoms out at −27 with only 7 below −20. That asymmetry is
trailing silence in the rips, not music. The pool report's worst-seam
formula computes to 65.7 LU on real data — a statement about ripping. The
tail must be measured over the last 10 s of *audible* material.

### Stage B — storage

Quietness columns on **both** `TrackAnalysis` and `AnalysisSnapshot`, named
once in `similarity.LOUDNESS_FIELDS` because four places copy them and the
failure mode when they drift is a column that blanks on the next full
rescan with the feature vector intact, so nothing looks broken.

`loudness_version` moves independently of `FEATURE_VERSION`. That is the
whole reason the quietness metrics are a separate pass: librosa analysis
costs 219 MB + 93 MB per audio-minute per worker and ffmpeg costs a few MB,
and forcing either to rerun for the other's sake is the coupling avoided.

ReplayGain goes on `Track` as `rg_track_gain` / `rg_album_gain`, read by
the ordinary scan alongside genre and performer, so it survives rescans by
the ordinary path. **The offset is derived, never stored** — storing it
would let the tags and their difference disagree. Read by one
`_extract_replaygain` rather than a branch in each of the five per-format
extractors: the tag names are identical everywhere and only the container
differs, so five copies would be five chances to write it differently. Opus
is checked first and separately, being an Ogg container that would
otherwise match the Vorbis branch, find nothing, and be recorded as
untagged when it is in fact tagged as Q7.8 fixed point against −23 LUFS.

**Two hazards fixed while here.** `similarity.ensure_table()` hardcoded
`SqliteMigrator` against a MariaDB production database — it happened to
work for the one column it added, and would not have kept working. It also
wrapped the add in a bare `except OperationalError: pass`, which cannot
tell "already exists" from "was not added"; presence is now checked with
`get_columns()` and a real failure raises. Every new column is `null=True`,
because a non-null `add_column` makes peewee rebuild the table and
`track_analysis` is CASCADE-linked to `Track`.

### Stage C — Find Similar becomes the curation tool

Two sliders, not five: `startle_local` (0..25 LU) and the derived playback
level (−10..+5 dB), with both metrics shown as sortable columns. Endpoints
come from A3's sample. Both default to their maximum, so a search nobody
has touched returns exactly what v3.7 returned.

**The filters run in the tree, not in the query**, so a drag is instant.
`find_similar` is called once with `limit=None` and carries the metrics on
every result; the sliders re-render from that cache.

**Match % had a subtler problem than the plan described.** The plan says
fetch ~500 deep and recompute the percentile over the survivors — but a
percentile recomputed over a *truncated* fetch is on a different scale
entirely, so the 500th candidate would read 0% rather than its real
position. What made it clean is that `find_similar` already builds a dict
for every candidate and truncates only at the end, so `limit=None` costs
nothing and recomputing over the survivors is then exact. It matches what
`volatility_max` has always done; that just filters before scoring.

**An unmeasured track is excluded when a filter is on, never admitted.**
It cannot be shown to be quiet, and admitting unknowns is the one thing a
sleep pool exists to prevent. The status line counts those apart from
tracks that genuinely failed, because "run Measure" and "this is loud"
call for different actions. The surviving-candidate count is load-bearing,
not decoration: the level slider has a cliff at zero where 68.8% of the
library sits, so one step below it drops two thirds of the candidates.

C4 measures on demand, 8 parallel ffmpeg processes over the candidates on
screen. It ignores the sliders when choosing what to measure — with a
filter on, unmeasured tracks are excluded from the view, so measuring what
is displayed could never measure anything. The queue keys on
`loudness_version`, not on a null metric: a silent track measures fine and
legitimately has no startle value, and keying on the metric would re-queue
it forever.

C5 cuts twelve seconds around `loud_at_ms`, with two seconds of lead
because the same fortissimo is alarming or unremarkable depending on what
preceded it. WAV, so no encoder dependency. Excerpts are swept by age, not
deleted after playing — deleting on completion pulls the file out from
under the player.

C6 reports on the *pool*, since under shuffle there is no sequence to
describe and the pool's properties hold for every reachable ordering. The
ceiling is stated as a frequency ("6 exceed 15 LU; expect 1.2 per
playlist; 74% of nights contain at least one"), because a length-capped
draw makes a flat worst case an overstatement.

**LOUDNESS_VERSION went to 2 during Stage C.** `head_level` and
`tail_level` now cover the first and last ten seconds of *audible*
material rather than of the file — ungated they were reporting how much
digital silence a rip carried, which put the worst reachable seam at
65.7 LU. Related: those two windows are 10 s each, so on anything shorter
than 20 s they overlap and are not independent measurements.

### Stage D — deferred, not built

The banded shuffle moved to *Future directions* on 2026-08-14, with the
mechanism designed and the two decisions it needs written down. The
reason is the plan's own framing: under shuffle, seam control is variance
control of the pool, so a homogeneous pool needs no ordering logic at
all. C6 now reports exactly the figures that settle it, and a real
curated pool should answer the question before any code is written.

### What using it changed

Six rounds of fixes came from the application being used, and none was
reachable by the test suite — each was either two correct parts fitting
together badly, or a number that meant the wrong thing to a listener.

The freezes are worth remembering as a family. **A modal dialog with no
`parent=` under a grabbing window** takes the input grab invisibly;
**a non-modal window** opened under one receives no events at all; and
**destroying a window that holds a grab** returns the grab to nobody. All
three present as a hung application.

**The worst one was not a hang.** ffmpeg reads stdin for interactive
keys, `capture_output=True` leaves stdin inherited, and the GUI is
launched as a background job — so ffmpeg took SIGTTIN and suspended the
whole process group. Three plausible theories about threads, grabs and
the database were investigated and disproved before `jobs` reported
`Stopped` in one line. **Check the process state before theorising about
the code.**

And two numbers that were right but not useful: the audition played the
raw file rather than the level the playlist would use, and the worst-seam
figure named a track following itself.

## v3.7 — Work-scoped ReplayGain tagger (branch `v3.7-dev`, started 2026-08-11)

Phase 3 of the loudness/MA programme. Design: `no_git/CM-rg-tagger-handoff.md`;
measured MA behaviour, which is binding: `no_git/CM-MA-findings.md`.

MA applies `REPLAYGAIN_ALBUM_GAIN` in playlist context, and every existing
scanner scopes album gain to the *folder*. For classical repertoire the
loudness unit is the **Work**, not the disc. This tool writes work-scoped
gain into `ALBUM_GAIN` so a symphony sits on MA's target as a whole while
its movements keep their relative levels.

It is a **separate entry point** (`rgtag.py`), not a CM feature: it is the
only component needing an external scanner binary, it runs per acquisition
rather than continuously, and keeping it outside the app answers the parent
document's "does this open the V2 tag-writeback door?" by construction.

### Task 0 — the checks the handoff demanded before any design

Following the v3.6.1 lesson: check what already satisfies the requirement
before building to it. All three checks were run against the live library.

**Can an existing scanner be told what a work is? Yes.** `rsgain custom`
takes an explicit file list and treats *that list* as the album unit —
directory scoping belongs to `easy` mode alone. Verified by measurement,
not just by the man page: across the 20-work sample, rsgain's album
loudness matched an independent `ffmpeg ebur128` measurement of the
concatenated audio to within **0.04 dB**, which is entirely ffmpeg's 0.1 dB
print resolution. `-s s` changed 0 of 75 mtimes. So this project is an
orchestrator, and the `ffmpeg` + hand-rolled-R128 design in the handoff
does not get built.

**Provenance distribution** (MainMusic: 5,519 works / 7,279 tracks):

| work_source | works | tracks | multi-track works |
|---|---:|---:|---:|
| standalone | 3,804 | 3,804 | 0 |
| mb_workid | 1,430 | 2,201 | ~235 |
| heuristic | 165 | 815 | 165 |
| override | 85 | 278 | 85 |
| work_tag | 35 | 181 | 33 |

No `import` works exist. Two facts reframe the job: **only ~519 works are
multi-track**, so for everyone else `W == G_m` and this writes plain
ReplayGain; and **`heuristic` is 165 works, every one multi-track** — a
third of the works the feature actually exists for. Excluding it is not the
free choice the handoff assumed, so it sits behind `--include-heuristic`,
default off, and the dry-run report is how those groupings get reviewed.

**Speed, measured not estimated.** rsgain computes track and album gain in
one pass, so the handoff's N+1 passes are N: **0.16 s per audio-minute**
against the 20-work sample. The library is 31,111 audio-minutes → **1.37 h
serial, ~10 min at 8 workers**. (The `ffmpeg` design measured 0.46 s per
audio-minute, 3.96 h serial — recorded because it is the number the
handoff's own design would have cost.)

**Memory is a non-issue, unlike the librosa analysis** — measured, because
the comparison is the obvious worry. rsgain streams: peak RSS is 37 MB for
a *60-minute single track* and 57 MB for a 40-track, 106-minute Passion,
so it scales with track count (~0.5 MB each, one gating state per file
held for the album combination) and is flat in duration. The whole process
tree at `-j 20` peaked at **795 MB**, of which 92 MB was the Python parent
(which already holds every track row in the library). Compare the "Analysis
memory" section below: librosa costs 219 MB + 93 MB *per audio-minute* per
worker, so that same 60-minute track is ~5.8 GB there against 37 MB here.
The ceiling on `--workers` is CPU threads, not RAM.

### Three things the handoff did not anticipate

- **The library is 86% MP3** — 6,335 mp3, 1,004 flac, 31 m4a, 7 ape. §4 of
  the handoff assumed "FLAC is probably the only case" and would skip any
  work containing a non-FLAC file, which is 322 of the 519 multi-track
  works. Scope is FLAC **and** MP3. No work mixes formats, which is what
  makes a per-format writer tractable. m4a and ape are skipped and reported.
- **673 files already carry ReplayGain tags** (405 FLAC, 268 MP3), written
  with **lowercase** keys. Vorbis comment keys are case-insensitive so FLAC
  is safe; **ID3v2 `TXXX` descriptions are not**, so writing uppercase onto
  those 268 MP3s would leave two conflicting frames per tag. The writer
  deletes by case-insensitive match before writing, and there is a test
  pinning exactly that.
- **The clipping report fires almost everywhere, and handoff §7's
  correction is confirmed.** At MA's -17 LUFS target, 17 of the 20 sample
  works exceed the -1.5 dBFS limiter — but the *untagged status quo* is
  worse on 14 of them, because MA measures per track today (work 5508:
  +1.8 dBFS work-scoped against **+7.0** per-track). The limiter is already
  engaging on this library; work gain reduces exposure rather than adding
  it. The report prints both figures side by side so that stays visible.

### Design decisions

- **rsgain measures, CM writes.** rsgain runs scan-only (`-s s -O`) for the
  numbers; every tag is written by one `mutagen` pass of ours. Two writers
  per file would have split idempotency, mtime handling and the
  lowercase-collision fix across a binary we do not control — and rsgain
  cannot write the `CM_GAIN_*` state tags at all.
- **`-c n`** — rsgain's clipping protection stays off. It would silently
  adjust the gains; clipping is *reported*, not applied.
- **`-l -18`**, the ReplayGain 2.0 reference. Decoupled from MA's target
  because MA re-targets rather than applying the tag verbatim, so MA's
  target can change later without retagging.
- **Dry-run is the default**; `--write` is required to touch a file. The
  inverse of CM's usual convention, deliberately: ~7,000 irreplaceable files.
- **The tool reads CM's database and never writes it.** No new tables, no
  columns, no migration; state lives in the files as `CM_GAIN_WORK_KEY`
  (a digest of ordered member paths) and `CM_GAIN_VERSION`. It connects
  without running DDL — a second process creating tables against the live
  server is exactly the metadata-lock contention v3.6 fixed.
- **No new Python dependencies.** `mutagen`, `typer` and `peewee` are
  already in `requirements.txt`; `rsgain` is a documented runtime
  prerequisite of this tool alone, and the packaged Windows app never sees
  it.

### Preserving mtimes made the whole thing invisible (found 2026-08-11)

Handoff §5 said "preserve mtimes where practical — other tooling keys on
them", and that was implemented as the default. It is exactly backwards.
**MA decides whether to re-read a file from its mtime**, so preserving it
means MA never notices the tags these files were written for. Verified
the hard way: Mahler retagged at a -23 reference, confirmed as
`-4.70 dB` on disk in Picard, and still playing at the -18 value after a
forced resync in MA.

FLAC makes it worse than it sounds. The new tags fit inside the existing
padding, so **the file size does not change either** — measured at zero
bytes' difference across all 48 WTC files. A preserved mtime therefore
leaves a file of identical length with an identical timestamp, and
nothing downstream can tell it was touched at all.

Isolated to a single variable before the fix went in: `touch` on the
first Mahler movement alone, then a resync. That one track moved to
**-3.70 dB** applied — which is its on-disk `-4.70 dB` plus MA's +1.0
re-target — while its four untouched siblings kept serving the cached
+1.3. Same directory, same resync, one changed timestamp. Confirmed
after the fix by a `--force` retag: timestamps moved, and MA picked up
every work.

The mtime now moves by default; `--preserve-mtime` opts back in.

This collides with one thing inside CM, so the sequence matters.
`_restore_analyses` ([scanner.py:1091](music_manager/core/scanner.py:1091))
re-links a similarity analysis only when mtime **and** size both match,
so a *full* rescan after a tagging run would discard every analysis and
require the multi-hour librosa job again. Incremental `scan-changes` does
not: it updates the track row in place
([scanner.py:1546](music_manager/core/scanner.py:1546)) and the analysis
survives. **So follow a tagging run with `scan-changes`** — CM's stored
mtimes then match the files, and any later full rescan restores normally.

### Selecting a work when the GUI does not show ids

`--work-id` was the only way to name a work, and nothing in the GUI
displays a work id, so in practice there was no way to use it. Added
`--list` (the selected works with their ids, measuring nothing) plus
`--album TEXT` and `--work TEXT` substring filters. These *select* rather
than refuse: a work outside the filter is not reported as skipped, since
listing several thousand of them would bury the works genuinely refused.

### Open risk

**~~Whether MA reads ID3v2 `TXXX:REPLAYGAIN_*` on MP3 is untested.~~
Settled 2026-08-11: it does.** Verified against real MP3 works (Mahler 5,
Brahms symphonies, Bach sonatas) and FLAC (WTC Book II) through MA's
quality display: applied gain matched `ALBUM_GAIN + 1.0 dB` throughout,
which is the -17 re-target of a -18-referenced tag, and was constant
across each work's movements. Works sharing one physical album each kept
their own gain, confirming §2.3 at real-world scale rather than with
probes. Original text follows, for the record:
`CM-MA-findings.md` §7 lists formats other than FLAC as not covered, and
MP3 is now 86% of the library and 62% of the multi-track works. Settled by
playing one MP3 work and one FLAC work through MA's audio-pipeline view. If
MA ignores MP3 ReplayGain the tags remain correct for Kodi, but the MA half
of the design would cover only 1,004 files.

## Riding along on `v3.7-dev` (2026-08-12)

Neither of these is part of the tagger. They share the branch because
they arrived while it was open, and the first is what put the second
under scrutiny.

### One webhook serves several libraries

The webhook fixed its library and its m3u output directory at startup:
both came from config when the service booted, and the request body
carried only `command`, `quiet`, `profile` and `track`. One service
therefore meant one library, which does not survive a second collection —
the case that prompted this was an everyday `MainMusic` alongside a
seasonal `XmasMusic` that has to be regenerated separately.

A request may now name a `library`. The output directory is *not* a
request field: `webhook.libraries` maps each library name to its own
`m3u_output_dir`, and only names in that map are accepted.

**Why the map rather than a path in the request.** The endpoint is
unauthenticated unless a token is configured, so a free-form output
directory would let anything that reaches port 5588 write files anywhere
the service account can — the same exposure the profile-name
sanitization in `webhook.py` already exists to prevent. Taking only the
*name* and looking the path up in config keeps the filesystem out of the
request entirely.

**Why unlisted libraries are refused rather than defaulted.** Falling
back to the default directory would turn a forgotten config entry into a
`202`, an `exit_code: 0`, and Christmas playlists sitting among the
everyday ones — discovered months later, with nothing recording which
file came from which library. A `400` naming the library is the correct
answer to "regenerate a library I have not been told where to write".

**Rejected:** a second webhook instance on a second port (the pattern
`classical-manager-cron.sh` documents for cron). It works there because
each cron run is a fresh process; the webhook is a daemon, so it would
mean a second systemd unit and a duplicated `database` block running all
year for a library used six weeks of it. Also rejected: storing the
directory on the `Library` row, which reads as the tidier model until you
remember the database is shared MariaDB and the paths are host-specific —
and it would still need a separate allowlist.

Two config mistakes are caught at startup rather than per request, both
being silent and seasonal: a library name that does not exist, and a
`webhook.library` missing from its own map (which is what a request
omitting `library` falls back to). The service refuses to start on
either. Each job records its library and output directory in
`webhook.log` and in `/api/jobs/last`.

Omitting the map keeps the previous behaviour — one library, writing to
`cron.m3u_output_dir` — so existing Home Assistant automations and the
cron script are unaffected. In that mode naming a *different* library is
now an error rather than being ignored. Covered by
`tests/test_webhook.py`.

### Tilde in `cron.m3u_output_dir` (fixed 2026-08-12)

`cron.m3u_output_dir` has always defaulted to `~/Playlists`, and nothing
expanded the tilde. The cron script and the webhook both pass the value
quoted (`--output-dir "$OUTPUT_DIR"`), so the shell leaves it alone, and
`Path("~/Playlists")` is a relative path — playlists went to a literal
directory named `~` under whatever the working directory happened to be
(the install directory for cron, the webhook's cwd otherwise). The cron
script's own `os.path.expanduser` covered only the *default*, so it fired
exactly when the key was absent and never when it was set.

**Behaviour change:** an install whose config says `~/Playlists` now
writes to `$HOME/Playlists` instead of `./~/Playlists`. Anything reading
the old literal directory — a Music Assistant folder mapping, a sync
script — needs repointing, and the stale `~` directory can be deleted
once its contents are accounted for. Absolute paths are unaffected.

Expansion happens at both ends: `_output_result` and `generate-all`'s
`--output-dir` expand whatever they are handed (`cli.py`), and the two
places that read the config value — the `webhook` command and the cron
script's config snippet — expand it as they read. `webhook.libraries`
already expanded its per-library directories, so the two now agree.
Covered by `tests/test_output_paths.py`.

## Analysis memory: swap saturation (investigated 2026-08-04, NOT yet fixed)

A full re-analysis at `-j 18` drove the workstation into swap near the end
of the run: 6 GB of 7 GB swap used, 4 GB RAM free, load 21, and the
symptom the user reported was "fewer processors busy, slower churn". The
run completed with no errors — this costs time, not correctness.

**Measured, per worker process** (peak RSS against track duration, six
tracks from 1 to 24 minutes):

    ~219 MB baseline + ~93 MB per minute of audio

So a 4-minute track needs ~590 MB and a 24-minute track ~2.5 GB. With 18
workers that is 10.7 GB of typical tracks but 45 GB of long ones.

**Why it hit at the end, not the start.** Jobs are submitted in track-id
order, and that correlates with length here: the 929 tracks still
outstanding averaged 319 s against 242 s for those already done, with 27
over fifteen minutes. It was accidentally close to shortest-first, whose
worst wave is at the end.

**Ordering strategies, modelled against the real duration distribution**
(7,279 tracks, mean 4.2 min, p95 10.3 min, max 60.1 min; per-track worker
memory mean 610 MB, p95 1,178 MB, max 5,810 MB), 18 workers:

| ordering        | concurrent memory                              |
|-----------------|------------------------------------------------|
| longest-first   | **51.2 GB** immediately                        |
| shortest-first  | **51.2 GB** at the end (what happened)         |
| random          | mean 10.7 GB, p99 14.2 GB, worst of 20k trials 19.4 GB |

Longest-first does **not** move the problem — the peak wave is identical,
only its timing changes. That was the user's point and the model confirms
it. Randomising genuinely flattens the peak *for this library*, because
long tracks are rare; it would not save a library of Wagner acts, where 18
random draws are all long. Random makes a bad peak unlikely; it does not
bound it.

**Agreed approach when this is picked up:**

1. **Cap worker count by memory, sized on the p95 track, not the longest.**
   p95 = 1,178 MB, so a 20 GB budget gives 17 workers — just under the
   CPU-derived 18, costing nothing on this library while protecting a
   heavier one automatically. Sizing on the longest track gives 3 workers,
   which is uselessly conservative.
2. **Randomise the job order**, so the p95 assumption holds in practice
   rather than being defeated by the tail clustering.
3. **Log the chosen worker count and the reason**, so a future slowdown is
   diagnosable without re-measuring RSS.

**Open trade the user should decide.** Randomising costs makespan.
Longest-first is the standard scheduling answer precisely because it
minimises the tail — a 24-minute track drawn last leaves every other
worker idle. Random order will occasionally do that. Memory safety looks
like the better trade for a job run rarely and unattended, but it is a
real trade. A middle option exists — shuffle, then bias the very longest
tracks to start early while the pool is still empty — which keeps most of
the tail benefit without an all-long first wave; probably not worth the
logic at this library's shape.

Both changes live in `analyze_library` / `default_worker_count` in
`similarity.py`. Neither changes the feature vector, so **no re-analysis
is needed** to adopt them.

*Diagnostic note: per-worker memory was measured by running `analyze_file`
in a child process and reading `resource.getrusage(RUSAGE_SELF).ru_maxrss`.
`free -g` plus the remaining-track duration distribution is what identified
it; CPU and I/O both looked fine.*

## v3.5 — remaining (optional)

- [x] **Regroup Works batched inserts** — done 2026-08-03. **21,464 → 1,945
  queries; 45.1 s → ~4.1 s predicted on MySQL.** Works are built in memory
  with locally reserved primary keys and inserted per album by
  `_flush_works`, instead of one `Work.create` each. `redetect_works` also
  clears the whole library in two statements rather than three per album,
  and loads every track in one query instead of one per album.

  Primary keys come from `_reserve_work_id`, a counter keyed on the database
  object so switching databases recomputes it. Deletes cannot cause a
  collision because the counter only ever rises.

  Verified identical grouping across all 7,279 tracks against a baseline,
  with no orphaned track→work references and every track assigned. Seven
  new tests in `test_work_batching.py` cover id uniqueness across albums and
  across repeated runs, non-collision with works in another library, every
  column of the hand-built insert row, work_sequence, and that a part-way
  failure cannot attach one album's works to the next. Both mutations
  (omitting a column, handing out duplicate ids) were confirmed to fail
  those tests before being reverted.

  Left alone deliberately: `_next_work_sequence` still issues one MAX per
  album (431 queries, ~0.9 s). Priming it from `redetect_works` would couple
  the two for very little, and `detect_works` stays correct for any caller.
- [ ] **Analysis memory / swap saturation** — see the dedicated section
  above. Cap workers by memory (p95 track) and randomise job order.
  No re-analysis needed.
- [ ] **Full vs incremental analysis** (user, 2026-08-03). Only a
  FEATURE_VERSION bump currently forces re-analysis; there is no "re-do
  everything" for a parameter change that does not warrant a bump, or to
  rebuild suspect data. Same shape as the scan/rescan chooser.
- [ ] **`reconcile_selections`**: 637 queries (~1.3 s), runs on profile
  load. `_tracks_for_work_key` is called once per work-level selection;
  the work-key → tracks map that `load_library_index` already builds would
  remove it.
- [x] **Cut over for real** — done 2026-08-03. Production runs on MariaDB;
  the SQLite file at `/mnt/MediaLib/music_manager.db` is the frozen
  rollback point, last written 11:57 that day. Server upgraded to MariaDB
  11.4 on 2026-08-04 after two dictionary-latch wedges on 10.6.7.
- [ ] **Sidebar metrics labels** (`Albums: 431` etc.) are unbounded
  CTkLabels in the same frame as the scan status label that caused the
  button tearing. They change width when a count gains a digit, so they
  are the same defect class — just rarer. Same fix: fixed width.
- [ ] **Pepperland at rank 2** for Test-albinoni, and whether match %
  rounding to 100.0 for the top few results reads badly. Both need the
  user's ears rather than code.

## v3.3 — next up (promoted from Future directions 2026-07-28)

Two features that are really one capability seen from two angles: knowing
which tracks arrived recently, and being able to restrict any tree to a
profile's membership. Design them together.

- **Auto-generate an "Imports-<timestamp>" profile after an incremental
  scan** (user, 2026-07-24). A quick scan that adds files would create a
  profile like `Imports-2026.07.24.14.30` selecting exactly the added
  tracks, which the user can keep and work with. This is effectively what
  the user does now by hand via Find Unused. Needs the scan-batch marker
  from the Cleanup-filtering item (added-this-run set), and a decision on
  lifecycle (transient like `__autosave__`, or a normal saved profile the
  user renames). Pairs naturally with the Cleanup "newly added" filter.
- **Filter all tree views by profile inclusion, orthogonal to text search**
  (user, 2026-07-24). Add a "in profile: [picker]" filter to the Builder
  library pane, the Cleanup Works Browser, and similar trees (NOT the
  Builder playlist pane, which already shows one profile). Two use cases it
  unlocks: (1) assign newly imported music to playlists by filtering the
  library to an "Imports-date" profile and adding from there; (2) copy items
  from one playlist to another by filtering to profile A while building
  profile B. Machinery exists: `resolve_selections(profile).track_ids` gives
  the membership set; the viewmodel already builds rows and could take an
  optional "restrict to these track ids" set. Composes with text search and
  the source filter. This is the general form of the Cleanup-by-playlist
  item — worth designing them together.

**Imports-profile decisions (user, 2026-07-28): REAL profiles, one per
import.** A "last import" virtual profile was rejected: two imports in one
work session would lose the first. Clutter is contained by design, not by
avoiding profiles.

- **CRITICAL — needs a first-class flag, not a name convention.**
  `engine.find_unused_tracks()` treats every non-`__` profile as evidence a
  track is used, so a normally-named import profile makes every newly
  imported track look assigned — breaking Find Unused, the very workflow
  this feature automates. Add `PlaylistProfile.auto_generated` (bool,
  null=True per the Peewee CASCADE constraint) or a `kind` column, and
  EXCLUDE auto-generated profiles from find_unused_tracks. A name prefix is
  not enough: it breaks when the user renames one, or names their own
  profile "Imports ...".
- **Assignment progress**: show each import as
  `Imports 2026-07-28 14:30 — 18/40 assigned`, computed with the same
  machinery as Find Unused. Turns clutter into a to-do list and gives a
  principled deletion moment; enables a "Delete fully-assigned imports"
  bulk action that only removes provably-finished ones.
- **Promotion by rename**: renaming an import profile clears the flag and
  makes it a normal profile — the natural "keep this one" gesture, no extra
  UI.
- **Grouping**: profile pickers list user profiles first, then a separator,
  then imports newest-first.
- **Multi-select delete already exists** — `_delete_profile`'s listbox is
  `selectmode="extended"` and deletes every selection. Nothing to build.
- **Do NOT auto-prune.** Same reasoning as the deliberate decision to keep
  Rules "Clean Up" manual: automatic deletion of user-visible data is a
  trust problem, and an edited import profile is the user's. Make the state
  visible (progress counts) and disposal one click.
- The scan-batch marker also enables a zero-clutter browse path ("added
  since <date>" as a tree filter), which complements import profiles rather
  than replacing them — it lowers the pressure for them to live forever.

**Shared groundwork both need:**
- A **scan-batch marker**. `Track.file_mtime` is FILE time, not scan time,
  so it cannot answer "added by the last scan". Add a nullable column
  (e.g. `first_seen` timestamp, or `scan_id`) set on INSERT only — never
  updated — plus a migration (remember: `null=True`, see the Peewee CASCADE
  constraint below). `scan_incremental` already computes its added set;
  the full scan needs the same treatment so a rebuild does not make every
  track look new (probably: preserve first_seen across a full rescan the
  same way analyses are preserved, keyed on (folder_id, relative_path)).
- A **restrict-set parameter on the viewmodel**. `library_tree_rows` /
  `playlist_tree_rows` take an optional set of track ids; rows whose
  tracks fall outside it are dropped (an album/work disappears when it has
  no surviving tracks). This is the single mechanism behind "filter by
  profile", "show only new imports", and the Cleanup-by-playlist item.
- **Composition rule:** the profile filter is ORTHOGONAL to the text
  filter and the source filter — they intersect, never replace. The
  Builder playlist pane is excluded (it already shows one profile).

**Design questions to settle before building:**
- Where does the profile picker live in the Builder header — a dropdown
  next to the text filter? What labels the "no filter" state?
- Should an Imports profile be created when a scan adds 0 files? (No.)
- Does an imports profile respect the `__` internal-name convention?
  (No — the user must see and keep it, so it needs a normal name. This is
  exactly why the auto_generated flag is required.)

## Future directions (not scheduled)

Larger or longer-horizon ideas. Nothing here is committed to a release;
each needs its own design pass before work starts.

- **Banded shuffle — planned as v3.8 Stage D, deferred 2026-08-14 with
  the mechanism designed but unbuilt.** Split a pool into 3–4 bands on a
  key, order the bands, shuffle freely within each: downward drift across
  the playlist with full local randomness, so there is no recognisable
  sequence and big jumps are confined to band boundaries. Generalised as
  **(key, direction, band count)** from the start — a quiet-first playlist
  is `(playback_level, descending)` and a morning mix is the same key
  ascending, so tempo banding would cost nothing extra later.

  **Deferred because the measurements may remove the need for it.** Under
  shuffle, seam control is variance control *of the pool*: if the levels
  are homogeneous then every reachable ordering is already safe and no
  ordering logic buys anything. v3.8's pool report states exactly that —
  worst reachable seam, and expected jumps per playlist — so a real
  curated pool answers the question before any code is written. This is
  the same shape as v3.8's `rise_rate` decision, where measuring first
  meant not building something.

  **Two things to settle before starting, both already established.**

  *The pipeline order is the trap.* The pipeline is shuffle → pins → stop
  conditions, and `_apply_stop_conditions` truncates with `tracks[:n]` —
  it keeps the **head**, in both `count` and `duration` modes. A banded
  shuffle inserted at the shuffle step and ordered loud→quiet would be
  truncated to its loud bands: the playlist comes out as the loudest 50
  tracks of the pool, in descending order, with the entire quiet end
  discarded. That presents as "why is this mix all forte" rather than as
  an obvious bug. **Sample the pool to the length target first, then band
  and order the survivors** — a change to the step *sequence*, not to a
  step, which is why it needs deciding before the work rather than
  during. Bands computed over tonight's 50 rather than the full 250 are
  also tighter, which improves the seams for free. Cover it with a test
  asserting the quiet band is non-empty after truncation.

  *Band boundaries.* Fixed count with quantile boundaries keeps every band
  populated; fixed dB widths keep a band's meaning stable across pools.
  Not decided.

  Held in reserve alongside it: a **level-aware separation constraint**.
  `_apply_separation` is already a constrained shuffle — greedy pick from
  non-conflicting candidates, with a least-conflicting fallback — and a
  level-jump predicate fits it naturally, being graded where the existing
  conflicts are binary. If a tightened pool makes it unnecessary, it
  should not be built.

- **Disc-spanning works — investigated 2026-07-29, NOT automated.** The
  heuristic cannot group a work split across a disc boundary:
  `_assign_by_heuristic` buckets `by_disc` first, and `_contiguous_runs`
  requires the same disc, so each half becomes its own Work (often with
  byte-identical names). A manual work_name override on all the tracks DOES
  merge them — the override step has no disc or contiguity restriction —
  followed by Regroup Works; verified by simulation.
  A candidate auto-rule was evaluated against the full library: merge two
  same-named works in one album when the second begins at **track 1 of the
  immediately following disc**. Of 92 disc boundaries and 62 same-named
  cross-disc pairs, that rule selects exactly the 4 genuine splits and
  rejects all the false ones (Dowland's many "Galliard"s, a Simon &
  Garfunkel box set repeating songs across discs). **Not built**: only 5
  real cases exist in ~6,400 tracks, and the 5th (The Three Cornered Hat,
  one ballet over three single-track discs with differing titles) is
  invisible to the rule anyway — so the code path would add failure modes
  while still leaving manual work. Revisit only if the pattern becomes
  common. Note the deeper fix would be letting the prefix heuristic look
  across disc boundaries when tracks are contiguous in album order, which
  would catch the ballet too — a bigger change to a deliberately
  conservative heuristic (see the 3-word guard the user chose to keep).

- **Write overrides back to source file tags** (user, 2026-07-28). A way to
  push meaningful corrections — work name, composer, and similar — into the
  files themselves, so other tools (Plex, Picard, players) see them too.
  **This deliberately reverses a founding rule**: spec §6 states corrections
  are stored "only as Overrides records — audio files are never modified in
  V1", and the whole overlay system exists to honour that. Reversing it is a
  design decision, not a feature toggle, and needs its own pass. Notes:
  * **Field mapping is mostly clean**: composer (TCOM / COMPOSER / ©wrt),
    work (TXXX:Work or TIT1 / WORK / ©wrk), title, genre, performer,
    conductor, ensemble, disc/track/movement numbers; album-scope fields
    (album title, artist, year) fan out to every track in the folder.
  * **`__standalone__` MUST NEVER be written.** It is a grouping directive
    in the work_name field, not a title. Any writeback needs an explicit
    denylist of directive values, not just a field allowlist.
  * **Writing tags changes mtime and size, which currently DESTROYS the
    similarity analysis** for every file touched: `_restore_analyses`
    matches on (folder_id, relative_path) plus mtime/size. Tagging 6,000
    files would silently discard hours of librosa work. **Sequencing: do the
    "preserve analyses by MB recording ID" item FIRST**, then writeback is
    safe. The two are coupled and should not be done in the other order.
  * **Irreversibility**: an override can be deleted to undo; a written tag
    cannot. Needs a dry-run preview (per file, old → new), and a decision on
    whether to keep a backup of original tags (a JSON sidecar of prior
    values would make it undoable without copying audio).
  * **After a successful write the override is redundant** — decide whether
    to delete it, or mark it applied and keep it as provenance. Deleting is
    risky if a write silently failed; verify by re-reading the tag before
    considering it done.
  * **Failure modes to handle explicitly**: read-only files, permissions,
    partial batches over the CIFS share (see the 2026-07-20 incident),
    formats with weak or absent tag support (WAV, APE), and Plex or another
    process reading the file mid-write.
  * Scope choice: everything, a selected album, or the current scope filter
    — the Show mechanism from v3.3 already gives a natural selection UI.
  * **The real motivation (user, 2026-07-28): curation work should outlive
    the database.** Today every correction lives only in
    music_manager.db (with overrides-JSON export as an app-specific
    backup). Written into tags, the work becomes portable — Plex, Picard,
    players and any future install read it natively, and a fresh scan on a
    new machine reproduces the corrections with no import step.
  * That reframes the override table itself: it stops being a permanent
    overlay and becomes a **staging area** — pending corrections not yet
    committed to the files, much like a working tree versus commits. Which
    in turn answers the "delete or keep after writing?" question above:
    written overrides are history, not active state. Note this only holds
    for overrides that are *meaningful in a file* — app-specific grouping
    decisions (notably `__standalone__`) stay database-only, so the table
    never fully empties.
  * **Round-trip fidelity becomes a hard requirement**, not a nicety: write
    the tag, re-read it with `extract_tags`, and confirm the value comes
    back identical. The reader has format-specific preferences (ID3 takes
    TXXX:Work before TIT1/GRP1; Vorbis reads WORK; MP4 reads ©wrk), so a
    writeback must target exactly what the reader prefers per format or the
    value silently fails to round-trip and the correction appears to
    "not stick" after the next scan.

- **Preserve audio analyses across file moves/renames** (found 2026-07-28
  while answering how a Picard multi-disc merge behaves). `TrackAnalysis`
  cascades from `Track`, and the full-scan snapshot matches on
  `(folder_id, relative_path)` — so reorganising files (e.g. merging
  "XXX disc1"/"XXX disc2" into one folder with 1-01/2-01 numbering) throws
  away analyses for content that did not change. On a ~6,000-track library
  that is hours of librosa work lost to a rename. Fix: match the snapshot
  on content identity as well as path — `musicbrainz_recording_id` first
  (Picard-tagged files have it, and overrides already match this way), then
  `(file_size, mtime)` as a fallback. Note overrides ALREADY survive such a
  move via MB-ID matching; analyses should behave the same way.
  Simulation of the current behaviour: analyses deleted, overrides kept and
  re-applied via MB ID, work-level rules deleted by reconciliation,
  album/track rules left orphaned for the Rules window to clean up.

- **Bootstrap installer** (user, 2026-07-21) — one fetched script that
  clones/downloads and hands off to `install.sh`, so a fresh or headless box
  needs no browser, unzip, or manual path juggling:
  `curl -fsSL .../bootstrap.sh | bash`. The real payoff is upgrades: today an
  upgrade means re-download, extract, remember where, re-run installer;
  after this it is one command (pull + re-run installer, which already
  handles venv, service restart, config merge). Design decisions to honor:
  * **Clone and install must be SEPARATE directories** — e.g. source in
    `~/.local/src/classical-manager`, install in
    `~/.local/share/classical-manager`. Installing from a directory
    containing `.git` would recreate the dev/installed confusion fixed in
    v3.1 (and the `.git` guard would suppress the desktop entry).
  * **Default to the newest release TAG, not master**, so a bootstrap never
    installs mid-development code; allow `--ref` to override.
  * Prefer `git clone` (cheap updates, tag pinning) with a tarball fallback
    when git is absent.
  * Document the two-step form (`curl -O`, inspect, `bash bootstrap.sh`) as
    the default and the pipe-to-bash one-liner as the convenience option —
    piping a remote script into a shell should be an informed choice.
  * Windows needs a thin `bootstrap.ps1` (Invoke-WebRequest + Expand-Archive);
    `install.bat` cannot be curl-piped.
  * Add an update entry point (`classical-manager-update`) once the source
    location is known and stable.
  * Test against a scratch prefix, never the live install — install-path
    changes caused three of the v3.1 bugs (stale config template, no service
    restart, launcher hijack).

- **Cleanup/Overlay workflow — filter works by relevance, not just
  detection method** (user, 2026-07-21). The Cleanup tab's Works Browser
  currently filters on ONE axis: `work_source` (Heuristic / Standalone /
  Override / MB Work ID / Work Tag / All), plus text search and hide-1-track.
  That axis answers "how was this grouped?" but not "is this worth my
  attention?" — so reviewing corrections means wading through the whole
  library. Add relevance-based selection:
  * **By playlist/profile** — show only works that appear in a chosen
    profile's resolved selection (or in any profile). The machinery exists:
    `resolve_selections(profile).track_ids` → the works those tracks belong
    to. This lets the user clean up exactly the works a playlist actually
    uses, ignoring the long tail they never play.
  * **Newly added** — show works whose tracks were added by the most recent
    scan, so freshly imported music can be reviewed/regrouped right after
    import. `Track.file_mtime` exists but records file time, not scan time;
    this likely needs a scan-batch marker (e.g. a `first_seen`/`scan_id`
    column set on insert, or reuse the incremental scan's
    added-this-run set surfaced to the GUI).
  * These compose with the existing source filter (e.g. "heuristic works in
    'Morning Mix'"), so it is an added filter dimension, not a replacement.
  * Broader framing: the Cleanup tab is organized around detection
    provenance; a review workflow wants to be organized around
    what-needs-fixing. Worth a small design pass on the whole tab before
    building, not just bolting on two dropdown options.

- **Pluggable database backends — SQLite plus MySQL/MariaDB** (user,
  2026-07-21). Motivation is concrete: the SQLite file lives on a CIFS
  share, which has already produced a disk-I/O incident mid-scan and makes
  genuine multi-machine access unsafe (SQLite locking over SMB is
  unreliable). A real database server — e.g. on the OMV box that already
  hosts the files — would let the GUI, the nightly cron, and the webhook
  share one database properly, and would make a headless deployment
  straightforward. Peewee supports MySQL/MariaDB natively, so the ORM layer
  is largely portable, but these are NOT free:
  * **SQLite-specific code must be abstracted**: `pragmas={journal_mode:
    wal, foreign_keys: 1}`; `playhouse.migrate.SqliteMigrator` (needs
    `MySQLMigrator`); `_ensure_track_indexes()` uses `PRAGMA index_list`
    and `CREATE INDEX IF NOT EXISTS` (MySQL 8 does not support IF NOT
    EXISTS on CREATE INDEX); `AnalysisSnapshot` upsert uses
    `on_conflict("replace")` (MySQL wants ON DUPLICATE KEY UPDATE).
  * **Schema portability**: MySQL cannot index a TEXT column without a
    prefix length. `Track.relative_path`, `ProfileSelection.key`, and
    `Album.album_key` are all TextField and all indexed/unique — they would
    need VARCHAR with a defined length, which means picking maximum path
    and key lengths and enforcing them.
  * **Concurrency semantics change**: the app currently assumes one writer.
    Real concurrent writers (GUI editing while cron generates) would need
    thought about transactions and the autosave/`__temp_` profile churn.
  * **Config and setup**: connection settings (host/port/user/password or
    socket), driver dependency (`pymysql`), migration/bootstrap of an empty
    server, and a documented path for moving an existing SQLite library
    across (export-library JSON already exists and may be the migration
    tool).
  * Keep SQLite as the default and the zero-configuration path — a
    single-user desktop install should never require a database server.
  * Related, smaller, and independently useful: **switching between
    databases from the GUI** (currently a config edit plus restart). The
    window title already names the active database; a picker with recent
    databases would make prod/test/scratch juggling safe and obvious.

## v3.2 (RELEASED 2026-07-28) — record of what shipped

**In progress on branch `v3.2-dev` (started 2026-07-26).**

Shipped and **user-verified 2026-07-28** (158 tests green):
- works-ordering bug fixed everywhere: tree views, engine album-mode,
  Show Album popup, and library export now share
  `selection.works_in_track_order()` (the popup and export were missed in
  the first pass — the same album looked different in two places)
- Cleanup Works Browser defaults to "All Works"
- Builder refresh (⟳) button; the stale-data message now names it
- filter/search ✕ clear buttons + app-wide Ctrl+A select-all
- sortable Find Similar columns; shared numeric key extracted to
  `treeutil.numeric_sort_key` (handles %, N/M ratios, durations, counts)
- **M3U/JSON save dialogs pre-fill the filename.** Root cause was NOT
  ours: zenity 4 (GTK4) dropped save-name pre-filling — `--filename`
  means "select this existing file", so a new playlist's name is
  discarded and the dialog opens in the process CWD. Verified by
  screenshotting zenity 4.0.1 with an absolute path (still empty).
  Save dialogs WITH a suggested name now use tkinter (which pre-fills and
  pre-selects); open/dir dialogs keep native zenity; kdialog unaffected.
  **Do not "simplify" this back to zenity-for-everything.**
- scans now list which files could not be read (scrollable + copy
  button). Previously only a count was shown, making a silently-missing
  track undiagnosable. Surfaced by a real case: a FLAC on the CIFS share
  that `stat`s fine but returns EINVAL on open() for every tool — bad
  data, correctly skipped by the scanner.

**Deferred out of v3.2 — needs a design review first (user, 2026-07-28:
"we need to take a hard look at how the whole analysis and 'find similar'
features work"). Not simply a tuning exercise: revisit the feature's
shape before changing feature vectors. Both items below need a
FEATURE_VERSION bump + full re-analysis, so do them in ONE pass:**

- **Sortable column headers in the Find Similar results dialog** (user,
  2026-07-21) — the Builder trees already have `_setup_tree_sort`; the
  similarity results tree does not.
- **Similarity/volatility quality pass** (user, 2026-07-21) — similarity is
  "rough at best"; volatility does not track the actual soft/loud contrast
  it is meant to represent. Profiling done 2026-07-21 (see below) is the
  natural entry point: `librosa.effects.harmonic` (HPSS) is ~75% of analysis
  runtime and feeds only the 6 tonnetz dims; dropping it leaves tonnetz
  direction identical (cosine 1.000) with ~8-12% smaller magnitude, which
  z-scoring largely absorbs. Changing features requires a FEATURE_VERSION
  bump + full re-analysis, so bundle it with this work rather than doing it
  piecemeal.
- **Scan parallelism — MEASURED, NOT WORTH DOING** (2026-07-21). Unlike the
  similarity analysis, scanning is I/O-latency bound, not CPU bound:
  `extract_tags` costs **1.4 ms/file locally vs ~158 ms/file over the CIFS
  mount** (113x). Thread-pool trials with distinct cold batches, alternating
  1-vs-8 workers across three rounds to cancel network drift, gave a median
  **1.14x** (158 → 139 ms/file; 16 min → 14 min for 5,902 files); 32 threads
  regressed to 0.89x. Pre-reading each file into BytesIO before handing it to
  mutagen was *worse* (0.79x) — mutagen often needs only the header, so bulk
  reads transfer 14 MB needlessly. The SMB session/server is the
  serialization point and one stream already saturates it. Verdict: adding
  thread-safe progress, cancellation, and parent-only DB writes to buy ~10%
  is a bad trade on a mount that has already caused one data incident.
  Better levers if full-rescan time ever matters: (a) run the scan **on the
  NAS** (files local there ⇒ ~1.4 ms/file, potentially ~100x), (b) relax the
  mount's `actimeo=1`/`closetimeo=1` for a mostly-static library, (c) nothing
  — Quick scan already skips unchanged files and `stat()` is effectively free
  once the directory walk has run, which is why routine updates are fast.
- **Analysis speed** (measured 2026-07-21 on 24-core Ultra 9 275HX):
  ~12s/track today (HPSS 6-10s, other features ~2s, double file decode
  ~0.5s — `_extract_features` and `compute_volatility` each call
  `librosa.load`). Planned: (a) honest progress estimate measured from the
  first few tracks instead of a hardcoded guess, (b) single decode shared by
  features + volatility, (c) `ProcessPoolExecutor` parallelism — workers do
  pure file→features with NO database access, parent does all writes
  (avoids SQLite-over-CIFS concurrency, keeps per-track resumability); set
  `OMP_NUM_THREADS=1` in workers, cap workers ~8 (each holds a decoded
  track, ~100MB for a 20-min movement), module-level worker fn for spawn
  picklability. Projected 5,902 tracks: ~20h today → ~2.5h parallel →
  ~37min parallel without HPSS.

## Backlog (post-v3.0, user-proposed 2026-07-20)

- **Merge Rescan + Scan Changes** into one "Scan Library…" button → dialog:
  radio Quick scan (changes only, default) / Full rebuild (warning: re-reads
  every file, rebuilds catalog, hours on large libraries). Auto-select Full
  when the library lacks mtime data (replaces incremental's silent refusal).
  CLI keeps both verbs. Candidate third option later: "Deep" — re-read all
  tags but update rows in place (no scrub/ID churn); covers
  retagged-without-mtime-change and new-tag-column backfills, demoting Full
  rebuild to disaster recovery.
- **Dirty-state tracking with save prompts** — the real intent behind
  autosave was protection against *forgetting to save before navigating*,
  which autosave does not provide (Load overwrites the builder immediately
  and the next autosave tick destroys the only copy within 60s). Design:
  baseline-diff dirty detection (canonical snapshot of settings + sorted
  Rule tuples captured at load/save/new; dirty = current != baseline — no
  boolean-flag false positives, and a crash-restored autosave computes as
  dirty automatically since it differs from the saved baseline). Prompt
  Save / Discard / Cancel on New, Load, library switch, app close, library
  import; Cancel aborts the navigation (revert the library combobox).
  Unnamed profile ⇒ "Save as…". Dirty marker in title/profile field.
  Autosave stays as crash insurance, but every prompt resolution must
  immediately refresh the autosave to the post-decision state — otherwise
  Discard can be resurrected by a stale autosave on next launch.
- **Retire the Track Similarity popup** (`similarity_popup.py`) — vestigial
  first home of the similarity feature; Builder's Find Similar supersedes its
  seed/browse role. Keep its one load-bearing job as a sidebar
  **"Analyze Audio"** button: scan-button-style batch analysis with
  missing-count, progress, cancel, and summary (mirrors CLI
  `analyze-similarity`). Find Similar keeps auto-top-up for small gaps but
  prompts before large ones (hundreds of unanalyzed tracks ⇒ hours) instead
  of silently launching the marathon.

- **Thumbs-down webhook** (Pandora-style) — remove a specific track from a
  named profile via HTTP, for a Home Assistant button wired to the currently
  playing Plex track; takes effect at the nightly regenerate. Core insight:
  this is exactly a track-level EXCEPT rule — specificity beats any covering
  ADD, D1 keeps enforce-integrity from re-adding it, the unique
  (profile, level, key) index makes repeats idempotent, and the Rules window
  shows/undoes it. No engine changes. The work is identification + plumbing:
  new CLI verb `exclude-track --profile NAME`. **Playback context (2026-07-21):
  HA plays via Music Assistant, not Plex directly** (chain: CM → Plex push
  nightly → HA script syncs MA playlists from Plex nightly → MA plays; Plex
  is used directly on the phone/externally). So the HA button captures an MA
  media_player whose media_content_id is an MA URI, not a Plex ratingKey —
  primary resolution is `--title/--album` (+artist) exact match, error on
  ambiguity, never guess; investigate at build time whether MA's content ID
  embeds a usable Plex provider key as a bonus `--rating-key` path. Webhook
  gains an endpoint/command invoking the verb as a job (keeps the webhook
  process DB-free). Optional variant: scope=work to thumb down the whole
  work. Since this is the first webhook op that MODIFIES profiles, add the
  optional shared-secret header in the same pass. Note: the Plex
  serializer's update-in-place (playlist-ID preservation) is load-bearing
  for the MA sync — do not regress it.

Target consumer: Claude Code. Each phase is independently completable and committable;
finish a phase, run its checkpoint, commit+push with a descriptive message, then stop or
continue. Phases are ordered by dependency — do not reorder 0 → 1 → 2; 3–6 have limited
flexibility noted inline.

Origin: full-codebase review (2026-07-19). Findings addressed here, by ID:

- **F1** Selection "effective state" logic exists in 4 places (core `resolve_selections`,
  GUI `_is_item_selected`, `_rebuild_library_tree` tags, `_rebuild_playlist_tree`
  visibility) with real disagreements.
- **F2** Engine/GUI disagreement: track/work-level ADD inside an album-level EXCEPT is
  included by the engine but hidden by the playlist tree.
- **F3** `work_integrity=enforce` (the default) silently re-adds tracks that carry an
  explicit track-level EXCEPT.
- **F4** "(empty = all tracks)" label contradicts the engine (empty selections → empty
  playlist).
- **F5** Album-level EXCEPT is a near-no-op by construction (nothing broader to except
  from); Explorer offers it symmetrically anyway.
- **F6** Builder tree rebuilds issue tens of thousands of N+1 queries on the Tk main
  thread on every include/exclude toggle.
- **F7** `gui.py` is a 5,285-line single class.
- **F8** Full rescan deletes all `TrackAnalysis` rows via CASCADE (expensive librosa work
  lost); incremental scan preserves them.
- **F9** No index on `Track.relative_path`; no uniqueness on `(folder, relative_path)`.
- **F10** Explorer & Rules duplicates the Builder (pre-tree legacy per spec §10); its
  rule-creation path skips breadcrumbs (`track_paths=None` → reconciliation deletes the
  rule after regrouping) and skips the Builder's redundancy-avoidance logic. Unique value
  is only the raw rules listbox + Year column + work_source visibility.
- **F11** Engine N+1s: `_apply_work_integrity` per-track `get_by_id`,
  `_shuffle_album_mode` per-work `get_by_id`, `find_unused_tracks` per-album/work queries.
- **F12** Minor: `tempfile.mktemp` in plex serializer; naive `datetime.now()` in
  similarity vs UTC-aware in overrides; webhook m3u filename sanitization misses `\` and
  leading dots; autosave delete/recreate not in a transaction.

Decisions already made by the project owner:

- **Retire the Explorer & Rules tab entirely** (Phase 5).
- Rules get a new surface: an always-visible health strip in the Builder + a non-modal
  singleton Rules window (design in Phase 5).

## Standing constraints (do not violate)

- Python venv is at `venv/` (not `.venv/`). Install any new dev deps there.
- **Never run library scans or similarity analysis yourself** — they take a long time.
  Make the change, then ask the user to run the scan and report back.
- The user runs the GUI for manual verification; you can do static/py_compile/import
  checks and run the test suite.
- Production DB for realistic data: `/mnt/MediaLib/music_manager.db`. **Never write to
  it.** If needed, copy it to the scratchpad and point a test config at the copy.
- Peewee migrations: always `null=True` on `add_column` (NOT NULL triggers table
  drop/recreate → CASCADE wipes related tables).
- Internal profiles are filtered by the `__` name prefix; preserve that convention.
- Commit and push together at each phase boundary with a descriptive message.

## Decision points (ask the user before the phase that needs them)

- **D1 (Phase 1, F3):** Should `enforce` work-integrity honor explicit track-level
  EXCEPTs (skip them during expansion)? **Recommended: yes** — consistent with the
  specificity model and with what the Builder tree displays. This is a behavior change
  for existing profiles; the alternative is keeping current behavior and only *surfacing*
  it via the Rules window's "overridden by integrity" status.
- **D2 (Phase 1, F4):** Empty selections = empty playlist (fix the labels), or
  empty = all tracks (change the engine)? **Recommended: empty = empty** — pure-additive
  is the documented model; fix labels/help instead.
- **D3 (Phase 2, F9):** If a uniqueness pre-check finds existing duplicate
  `(folder, relative_path)` tracks, report them and add a non-unique index only; ask
  before any dedup.
- **D4 (Phase 5, F10):** Where do Explorer's two unique read-only affordances land?
  **Recommended:** album Year → new sortable column in the Builder library tree;
  work_source → verify it already shows in the Cleanup works list (it should; add if not).

---

## Phase 0 — Test safety net (characterization first)

No behavior changes. There are currently **no tests**; later phases change semantics and
need a baseline.

1. `pip install pytest` into `venv/`; add `tests/` package and a `pytest.ini` (or
   `pyproject` section) setting `testpaths`.
2. Build fixtures that create an **in-memory or tmp-file SQLite DB** via
   `initialize_database()` and insert Library/SourceFolder/Album/Work/Track/Profile rows
   directly (no file scanning, no mutagen).
3. Characterization tests (assert *current* behavior, even where known-odd, with comments
   linking finding IDs):
   - `tests/test_selection.py` — full specificity matrix for `resolve_selections`:
     album ADD; album ADD + work EXCEPT; album ADD + track EXCEPT; work EXCEPT +
     track ADD inside it; **album EXCEPT + track/work ADD inside it (F2 — engine
     includes them: assert that)**; duplicate-key replacement; empty selections → empty
     set (F4).
   - `tests/test_engine.py` — `enforce` expansion incl. the F3 case (track EXCEPT gets
     re-added: assert current behavior); `respect_selection`; pins incl. boundary index;
     stop conditions (count/duration/all); seeded shuffle determinism for all 3 modes;
     separation constraints smoke test.
   - `tests/test_reconcile.py` — work-key remap via breadcrumbs; orphan with no
     breadcrumbs is deleted/reported; merge-into-existing on key collision.
   - `tests/test_overrides.py` — set/apply/export/import round-trip.
4. Checkpoint: `venv/bin/python -m pytest` green. Commit ("Add core test harness and
   characterization tests").

## Phase 1 — Core: single effective-state engine (F1, F2, F3, F4, F11)

1. In `music_manager/core/selection.py`, add a bulk resolver, e.g.:
   - `load_library_index(library)` — **3 queries** (albums, works, tracks for the
     library), returning plain dicts keyed by id with parent links and precomputed keys.
   - `resolve_effective_state(index, selections)` — returns per-entity state for every
     album/work/track: one of `included | excluded | partial | none`, plus per-track
     inclusion set, computed purely in Python from the index. Must agree with
     `resolve_selections` by construction (share the per-track decision function).
   - `classify_selections(index, selections, work_integrity)` — per-rule status:
     `active` (contributes ≥1 track change), `redundant` (same polarity, fully covered by
     a broader rule), `no_op` (EXCEPT with no covering ADD — includes all album-level
     EXCEPTs, F5), `orphaned` (key resolves to nothing; also flag work rules with missing
     breadcrumbs), `overridden_by_integrity` (track EXCEPT that enforce-mode re-adds —
     only if D1 keeps current behavior). Also return per-rule contributed-track counts.
2. Semantic fixes (behind D1/D2 answers):
   - **F3/D1:** in `engine._apply_work_integrity`, when expanding a work, skip tracks
     whose `relative_path` has an explicit `excluded=True` track selection. Pass the
     track-exclusion set through from `resolve_selections` (extend its return or return a
     small result object).
   - **F2:** no engine change — the engine is correct; the display fix lands in Phase 4
     via the shared resolver.
   - **F4/D2:** no engine change; label fixes land in Phase 5.
3. **F11 batching:**
   - `_apply_work_integrity`: replace per-track `Track.get_by_id` with one
     `Track.select(...).where(Track.id.in_(selected_ids))`; replace per-work track
     fetches with one query grouped in Python.
   - `_shuffle_album_mode`: add `work_sequence: int | None` to `ResolvedTrack`, populate
     it in `_build_resolved_tracks` (Work is already joined), delete the per-work
     `Work.get_by_id` loop.
   - `find_unused_tracks`: load all tracks for the library once with `album_id`/`work_id`
     and group in Python instead of per-album/per-work queries.
4. Update Phase-0 tests to the new intended semantics (the D1 change flips the F3
   assertion); add tests for `resolve_effective_state` asserting it matches
   `resolve_selections` on the whole matrix, and for `classify_selections` statuses.
5. Checkpoint: pytest green. Commit.

## Phase 2 — Data layer hardening (F8, F9, F12-partial)

1. **F9:** in `initialize_database()` migrations, add an index on
   `tracks (library_id, relative_path)`. For uniqueness on `(folder_id, relative_path)`:
   first query for duplicates; if none, add the unique index; if some, log/report and add
   non-unique only (D3). Remember: raw `CREATE INDEX IF NOT EXISTS` via
   `database.execute_sql` is safer here than migrator column tricks.
2. **F8:** preserve similarity analyses across full rescans. In
   `scanner.scan_library`, *before* the delete block, snapshot existing analyses into a
   dict keyed by `(folder_id, relative_path)` → `(features, volatility, analyzed_at,
   feature_version, file_mtime, file_size)`. After tracks are recreated, re-insert
   `TrackAnalysis` rows for new tracks whose `(folder_id, relative_path)` matches **and**
   whose new `file_mtime`/`file_size` equal the snapshot (unchanged file ⇒ analysis still
   valid). Do the re-insert with `bulk_create` inside the existing transaction. Add a
   count to `ScanStats` (e.g. `analyses_preserved`).
3. **F12:** use `datetime.now(timezone.utc)` in `similarity.analyze_track`.
4. Tests: a scan-shaped unit test is impractical without audio files; instead unit-test
   the snapshot/restore helper directly with fabricated rows. Then **ask the user** to
   run a full rescan on a *test* library (e.g. `no_git/testMusicData` config) and confirm
   the analyses-preserved count is nonzero and Find Similar still works.
5. Checkpoint: pytest green + user-confirmed scan. Commit.

## Phase 3 — Mechanical GUI decomposition (F7)

Pure code movement; zero behavior change. Do this before Phases 4–5 so their diffs are
small and reviewable.

1. Convert `music_manager/interfaces/gui.py` into a package:
   - `gui/__init__.py` — re-export `launch_gui` (keep `from music_manager.interfaces.gui
     import launch_gui` working; `main.py` and any imports unchanged).
   - `gui/app.py` — `App` shell: init, theme, sidebar, library management, scan
     orchestration, autosave, prefs.
   - `gui/builder_tab.py` — builder layout + tree rebuild + toggle/include/exclude +
     profile save/load + preview/export/push + find-unused/similar glue.
   - `gui/cleanup_tab.py` — cleanup/overlay tab + override editors + album popup +
     work details.
   - `gui/dialogs.py` — settings, log viewer, import/export dialogs, profile pickers.
   - `gui/treeutil.py` — sort/filter/snapshot/view-state helpers (`_setup_tree_sort`,
     `_apply_tree_filter*`, `_snapshot_tree`, etc.).
   - Keep `similarity_popup.py`, `help_content.py`, `filedialog.py` as siblings.
2. Mechanism: keep `App` as the single stateful object; move method groups out as
   mixin classes (e.g. `class BuilderTabMixin:`) that `App` inherits, or module-level
   builders taking `app`. **Mixins recommended** — smallest diff, `self.` references
   unchanged.
3. Checkpoint: `venv/bin/python -m py_compile` on all new modules, pytest green, then ask
   the user to launch the GUI and click through each tab once. Commit.

## Phase 4 — Builder performance + shared-state adoption (F1, F2, F6)

1. Replace the internals of `_rebuild_library_tree` and `_rebuild_playlist_tree`:
   - Call `load_library_index` once (cache on `App`; invalidate on library switch, scan
     completion, and profile load) and `resolve_effective_state` on every selection
     change (cheap — pure Python).
   - Tags/visibility come **directly** from the returned states; delete the ~150 lines of
     local partial/included/excluded derivation. The playlist tree must show track/work
     ADDs inside an album EXCEPT (F2) — this now falls out of the shared resolver; keep a
     regression test asserting tree-model output for that case if feasible (extract the
     "rows to display" computation into a testable pure function that returns row specs;
     the Tk insert loop stays thin).
   - Per-row metadata (composer/genre/duration/counts) comes from the cached index, not
     per-row queries. Target: **zero SQL** inside the rebuild loops.
2. Rewrite `_is_item_selected` as a lookup into the effective-state map (no DB).
3. Keep view-state save/restore and filter re-application exactly as-is.
4. Delete now-dead helpers; run a quick grep for orphaned references.
5. Checkpoint: pytest green; ask the user to exercise the Builder against a copy of the
   production DB (`/mnt/MediaLib/music_manager.db` → scratchpad copy, custom `--config`)
   and confirm toggles feel instant and colors match expectations. Commit.

## Phase 5 — Rules surface + retire Explorer (F4, F5, F10, D4)

1. **Health strip** in the Builder (replacing the "(empty = all tracks)" label, F4):
   one line, e.g. `Rules: 23 — 18 active · 2 redundant · 1 orphaned ⚠ · 2 pins`, fed by
   `classify_selections`; empty state reads `Rules: 0 — playlist is empty`. Clicking
   opens the Rules window.
2. **Rules window** — new `gui/rules_window.py`, non-modal singleton `tk.Toplevel`
   (follow the help-window pattern: `transient`, `_center_on_main`, focus if open).
   `ttk.Treeview` in headings mode: Action (ADD/EXCEPT), Level, Name, Tracks
   (contributed count), Status, Pin. Row colors reuse the builder palette
   (blue/gray/amber, red for orphaned). Interactions:
   - **Remove** — pop exactly that rule from `_current_selections`, refresh displays
     (same surgical semantics as the old listbox Remove; no cascade).
   - **Reveal in library** — build a reverse map `(level, key) → iid` when the library
     tree is rebuilt; `see()` + `selection_set()` the node.
   - **Clean up** — one confirm dialog, then remove all `redundant`/`no_op`/`orphaned`
     rules.
   - Right-click menu mirrors the buttons; double-click = Reveal.
   - Refresh the window (if open) from `_refresh_rules_display`.
3. **Breadcrumb backfill:** on profile save and on profile load, for any work-level rule
   with empty `track_paths` whose key currently resolves, regenerate breadcrumbs. This
   heals rules created by old Explorer sessions (F10).
4. **Retire Explorer:** remove the tab from `_build_layout`, delete
   `_build_explorer_tab`, `_refresh_explorer`, `_on_album_selected`,
   `_album_context_menu`, `_work_context_menu`, `_debounce_explorer_search`,
   `rules_listbox`/`_remove_selection`, and the `_album_iid_map`/`_work_iid_map` state.
   Grep for `tab_explorer`, `rules_listbox`, `explorer` to catch stragglers
   (`_refresh_rules_display` currently writes to the listbox — repoint it at the strip +
   window).
5. **D4 relocations:** add a Year column (or fold year into the Info column) for album
   rows in the Builder library tree, sortable; confirm the Cleanup works list shows
   `work_source` (add the column if missing).
6. Docs: update `help_content.py` (delete the explorer section; add "Rules" section
   covering strip, window, statuses, Clean up) and `USERGUIDE.md`; update the help "?"
   button targets.
7. Checkpoint: pytest green; user GUI walkthrough: create/edit/save/load a profile
   entirely without Explorer, open Rules window, orphan a rule (rename a test folder →
   user rescans) and confirm it shows red and Clean up removes it. Commit.

## Phase 6 — Minor findings sweep (F12)

1. `serializers/plex.py`: replace `tempfile.mktemp` with
   `NamedTemporaryFile(suffix=".m3u", prefix="plex_", delete=False)`.
2. `webhook.py`: sanitize m3u filenames with an allowlist
   (`re.sub(r'[^A-Za-z0-9._-]', '_', profile)` then strip leading dots).
3. `gui/app.py`: wrap `_autosave`'s delete+recreate in `database.atomic()`.
4. Optional (ask if worth it): unique index on `playlist_profiles (library_id, name)`;
   unique constraint strategy for `overrides` match keys — otherwise leave documented.
5. Update `CLAUDE.MD`: new `gui/` package layout, the core effective-state/classify
   functions, Explorer removal, rules-window pattern, "analyses preserved across full
   rescan" note.
6. Checkpoint: pytest green. Commit.

## Phase 7 — Verification & wrap-up

1. Full pytest run; `py_compile` sweep; grep for dead references to removed symbols.
2. Ask the user to run, at their convenience:
   - full rescan + Find Similar on the real library (F8 verification at scale);
   - a Plex push and an M3U export of an existing profile (regression);
   - a session of normal playlist building with the new Rules surface.
3. Bump any user-facing version strings; summarize behavior changes (D1/D2 outcomes,
   Explorer removal) in the commit message and, if desired, a short CHANGES section in
   `USERGUIDE.md`.
