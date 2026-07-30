# Version 3 Action Plan

## Status (keep this section current)

- **Released: v3.0, v3.1, v3.2 — all merged to `master` and tagged.**
  Tag lineage: v1.0, v2.0, v3.0, v3.1, v3.2 (v3.2 on 2026-07-28, 158 tests
  green). **Next work is v3.3 — see the v3.3 section below.**
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
