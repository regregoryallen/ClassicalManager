# Version 3 Action Plan

## Status (keep this section current)

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
  **Remaining user checkpoint:** launch the GUI and click through each tab
  once (builder toggles, a popup or two, help window).
- [ ] Phase 4 — Builder performance + shared-state adoption
- [ ] Phase 5 — Rules surface + retire Explorer
- [ ] Phase 6 — Minor findings sweep
- [ ] Phase 7 — Verification & wrap-up

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
