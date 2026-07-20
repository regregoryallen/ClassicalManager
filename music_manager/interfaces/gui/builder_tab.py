"""Playlist Builder tab: trees, selections, profiles, export.

V3 Phase 3: mechanically split from gui.py — methods are
unchanged; this mixin is mounted on App in app.py.
"""

import json
import io
import logging
import platform
import sys
import threading
import tkinter as tk
from contextlib import contextmanager
from tkinter import messagebox, ttk
from music_manager.interfaces import filedialog
from pathlib import Path

from music_manager.core.config import PROJECT_ROOT
from music_manager.interfaces.gui.common import (
    _PREFS_PATH, _load_prefs, _save_prefs, _ScanCancelled, _GUILogHandler,
)

logger = logging.getLogger(__name__)


class BuilderTabMixin:
    def _add_selection(self, level, key, excluded=False, pin_position=None,
                       track_paths=None, refresh=True):
        """Add a selection to the in-memory list."""
        # At most one selection may exist per (level, key). Skip if this
        # exact state already exists; otherwise remove the stale opposite-
        # state entry so it doesn't linger and get picked up ahead of this
        # one by _find_selection or disagree with resolve_selections.
        existing = self._find_selection(level, key)
        if existing is not None:
            if existing["excluded"] == excluded:
                return
            self._current_selections.remove(existing)

        from music_manager.core.selection import display_name_for_selection
        display_name = display_name_for_selection(self.active_library, level, key)
        prefix = "EXCEPT" if excluded else "ADD"
        pin_str = f"[#{pin_position}] " if pin_position else ""

        sel = {
            "level": level,
            "key": key,
            "excluded": excluded,
            "pin_position": pin_position,
            "track_paths": track_paths,
            "display": f"{pin_str}{prefix}: {level} — {display_name}",
        }
        self._current_selections.append(sel)
        if refresh:
            self._refresh_rules_display()

    def _find_selection(self, level, key):
        """Find an existing selection by level and key."""
        return next((s for s in self._current_selections
                     if s["level"] == level and s["key"] == key), None)

    def _is_item_selected(self, level, key):
        """Check if item is selected (directly or via parent, respecting specificity)."""
        from music_manager.core.selection import parse_work_key, COMPOSITE_SEP
        sel = self._find_selection(level, key)
        if sel is not None:
            return not sel["excluded"]
        # Walk up hierarchy
        if level == "track":
            # Find the work and album this track belongs to
            from music_manager.core.database import Track
            track = Track.select(Track.work, Track.album).where(
                (Track.library == self.active_library) &
                (Track.relative_path == key)
            ).first()
            if track and track.work_id:
                from music_manager.core.selection import key_for_work
                from music_manager.core.database import Work
                work = Work.get_by_id(track.work_id)
                work_key = key_for_work(work)
                work_sel = self._find_selection("work", work_key)
                if work_sel is not None:
                    return not work_sel["excluded"]
                # Check album level
                album_sel = self._find_selection("album", work.album.album_key)
                if album_sel is not None:
                    return not album_sel["excluded"]
            elif track:
                from music_manager.core.database import Album
                album = Album.get_by_id(track.album_id)
                album_sel = self._find_selection("album", album.album_key)
                if album_sel is not None:
                    return not album_sel["excluded"]
        elif level == "work":
            # Extract album_key from work key
            parsed = parse_work_key(key)
            if parsed:
                album_key = parsed[0]
                album_sel = self._find_selection("album", album_key)
                if album_sel is not None:
                    return not album_sel["excluded"]
        return False

    def _remove_selection(self):
        """Remove selected selection from the in-memory list."""
        sel = self.rules_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._current_selections):
            self._current_selections.pop(idx)
            self._refresh_rules_display()

    def _refresh_rules_display(self):
        """Update the rules listbox on the Explorer tab and builder trees."""
        self.rules_listbox.delete(0, "end")
        for sel in self._current_selections:
            self.rules_listbox.insert("end", sel["display"])
        # Refresh builder panes if they exist
        if hasattr(self, "builder_lib_tree"):
            self._rebuild_library_tree()
            self._rebuild_playlist_tree()

    def _build_builder_tab(self):
        """Build the Playlist Builder tab.

        Layout: top (profile + compact settings) | middle (library | buttons | playlist) | bottom (actions).
        """
        ctk = self.ctk
        tab = self.tab_builder

        # -- Row 0: Profile name + load/save --
        row0 = ctk.CTkFrame(tab, fg_color="transparent")
        row0.pack(fill="x", padx=10, pady=(5, 2))
        ctk.CTkLabel(row0, text="Profile:").pack(side="left", padx=(0, 3))
        self.profile_name_entry = ctk.CTkEntry(row0, width=200,
                                               placeholder_text="e.g. Sunday Classical")
        self.profile_name_entry.pack(side="left", padx=3)
        ctk.CTkButton(row0, text="New", width=60,
                      command=self._new_profile).pack(side="left", padx=3)
        ctk.CTkButton(row0, text="Load", width=60,
                      command=self._load_profile).pack(side="left", padx=3)
        ctk.CTkButton(row0, text="Save", width=60,
                      command=self._save_profile).pack(side="left", padx=3)
        ctk.CTkButton(row0, text="Delete", width=60,
                      command=self._delete_profile).pack(side="left", padx=3)
        ctk.CTkButton(row0, text="?", width=28, height=28,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: self._show_help("builder"),
                      ).pack(side="right", padx=5)

        # -- Row 1: Compact settings (all in one line) --
        row1 = ctk.CTkFrame(tab, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=2)

        ctk.CTkLabel(row1, text="Shuffle:").pack(side="left", padx=(0, 2))
        self.shuffle_mode = ctk.CTkComboBox(row1, values=["track", "work", "album"],
                                            width=90)
        self.shuffle_mode.pack(side="left", padx=(0, 8))
        self.shuffle_mode.set("work")

        ctk.CTkLabel(row1, text="Integrity:").pack(side="left", padx=(0, 2))
        self.work_integrity = ctk.CTkComboBox(
            row1, values=["enforce", "respect_selection"], width=140)
        self.work_integrity.pack(side="left", padx=(0, 8))
        self.work_integrity.set("enforce")

        ctk.CTkLabel(row1, text="Length:").pack(side="left", padx=(0, 2))
        self.length_mode = ctk.CTkComboBox(row1, values=["all", "count", "duration"],
                                           width=90)
        self.length_mode.pack(side="left", padx=(0, 2))
        self.length_mode.set("all")
        self.length_value = ctk.CTkEntry(row1, width=55, placeholder_text="H:MM")
        self.length_value.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(row1, text="Seed:").pack(side="left", padx=(0, 2))
        self.seed_entry = ctk.CTkEntry(row1, width=55, placeholder_text="rnd")
        self.seed_entry.pack(side="left", padx=(0, 8))

        self.no_repeat_var = ctk.CTkCheckBox(row1, text="No repeats", width=30)
        self.no_repeat_var.pack(side="left", padx=(0, 4))
        self.no_repeat_var.select()

        # -- Row 1b: Separation constraints --
        row1b = ctk.CTkFrame(tab, fg_color="transparent")
        row1b.pack(fill="x", padx=10, pady=0)

        ctk.CTkLabel(row1b, text="Avoid adjacent:").pack(side="left", padx=(0, 2))
        self.sep_composer_var = ctk.CTkCheckBox(row1b, text="Same Composer", width=30)
        self.sep_composer_var.pack(side="left", padx=(0, 8))
        self.sep_album_var = ctk.CTkCheckBox(row1b, text="Same Album", width=30)
        self.sep_album_var.pack(side="left", padx=(0, 8))
        self.sep_form_var = ctk.CTkCheckBox(row1b, text="Same Form", width=30)
        self.sep_form_var.pack(side="left", padx=(0, 8))

        # -- Main area: library pane | buttons | playlist pane --
        main_pane = ctk.CTkFrame(tab, fg_color="transparent")
        main_pane.pack(fill="both", expand=True, padx=5, pady=5)
        main_pane.columnconfigure(0, weight=1)
        main_pane.columnconfigure(1, weight=0)
        main_pane.columnconfigure(2, weight=1)
        main_pane.rowconfigure(0, weight=1)

        # ---- Left: Library pane ----
        left_frame = ctk.CTkFrame(main_pane)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 3))

        lib_header = ctk.CTkFrame(left_frame, fg_color="transparent")
        lib_header.pack(fill="x", padx=5, pady=(5, 2))
        ctk.CTkLabel(lib_header, text="Library",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left")
        ctk.CTkButton(lib_header, text="+", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.builder_lib_tree, True)
                      ).pack(side="left", padx=(6, 0))
        ctk.CTkButton(lib_header, text="\u2013", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.builder_lib_tree, False)
                      ).pack(side="left")
        self._lib_filter_var = tk.StringVar()
        self._lib_filter_var.trace_add("write", lambda *_: self._apply_tree_filter("lib"))
        lib_filter = ctk.CTkEntry(lib_header, width=150,
                                  placeholder_text="Filter...",
                                  textvariable=self._lib_filter_var)
        lib_filter.pack(side="right")
        ctk.CTkLabel(lib_header, text="Filter:",
                     text_color="gray70").pack(side="right", padx=(0, 3))

        self.builder_hide_single = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(lib_header, text="Hide 1-track",
                        variable=self.builder_hide_single,
                        command=self._on_hide_single_changed,
                        width=20).pack(side="right", padx=5)

        self.builder_lib_tree = ttk.Treeview(
            left_frame, columns=("composer", "genre", "info"),
            show="tree headings", selectmode="extended")
        self.builder_lib_tree.heading("#0", text="Name")
        self.builder_lib_tree.heading("composer", text="Composer")
        self.builder_lib_tree.heading("genre", text="Genre")
        self.builder_lib_tree.heading("info", text="Info")
        self.builder_lib_tree.column("#0", width=220)
        self.builder_lib_tree.column("composer", width=120)
        self.builder_lib_tree.column("genre", width=90)
        self.builder_lib_tree.column("info", width=70, anchor="center")
        self.builder_lib_tree.pack(fill="both", expand=True, padx=5, pady=2)

        lib_scroll = ttk.Scrollbar(left_frame, orient="vertical",
                                   command=self.builder_lib_tree.yview)
        self.builder_lib_tree.configure(yscrollcommand=lib_scroll.set)
        # Place scrollbar on top of tree's right edge
        lib_scroll.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne",
                         in_=self.builder_lib_tree)

        self._setup_tree_sort(self.builder_lib_tree,
                              row_dbl_click=self._builder_toggle_include)
        self.builder_lib_tree.bind("<Button-3>", lambda e: self._builder_context_menu(e, "lib"))
        self._builder_lib_iid_map = {}  # iid → (level, entity_id, key)

        # Tag styles for visual state (colorblind-friendly)
        self.builder_lib_tree.tag_configure("included", foreground="#4da6ff")   # blue
        self.builder_lib_tree.tag_configure("excluded", foreground="#666666")   # gray
        self.builder_lib_tree.tag_configure("partial", foreground="#e6a332")    # amber

        # ---- Center: action buttons ----
        center_frame = ctk.CTkFrame(main_pane, fg_color="transparent", width=90)
        center_frame.grid(row=0, column=1, sticky="ns", padx=4)

        # Spacer to vertically center buttons
        ctk.CTkLabel(center_frame, text="").pack(expand=True)
        ctk.CTkButton(center_frame, text="Add >>", width=80,
                      fg_color="#2d7d46",
                      command=self._builder_include_selected).pack(pady=3)
        ctk.CTkButton(center_frame, text="<< Remove", width=80,
                      fg_color="#7d2d2d",
                      command=self._builder_exclude_selected).pack(pady=3)
        ctk.CTkLabel(center_frame, text="Double-click\nor multi-select\n+ buttons",
                     text_color="gray", font=ctk.CTkFont(size=10),
                     justify="center").pack(pady=6)
        ctk.CTkLabel(center_frame, text="").pack(expand=True)

        # ---- Right: Playlist pane ----
        right_frame = ctk.CTkFrame(main_pane)
        right_frame.grid(row=0, column=2, sticky="nsew", padx=(3, 0))

        pl_header = ctk.CTkFrame(right_frame, fg_color="transparent")
        pl_header.pack(fill="x", padx=5, pady=(5, 2))
        ctk.CTkLabel(pl_header, text="Playlist",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left")
        ctk.CTkButton(pl_header, text="+", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.builder_pl_tree, True)
                      ).pack(side="left", padx=(6, 0))
        ctk.CTkButton(pl_header, text="\u2013", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.builder_pl_tree, False)
                      ).pack(side="left")
        self._pl_filter_var = tk.StringVar()
        self._pl_filter_var.trace_add("write", lambda *_: self._apply_tree_filter("pl"))
        pl_filter = ctk.CTkEntry(pl_header, width=150,
                                 placeholder_text="Filter...",
                                 textvariable=self._pl_filter_var)
        pl_filter.pack(side="right")
        ctk.CTkLabel(pl_header, text="Filter:",
                     text_color="gray70").pack(side="right", padx=(0, 3))

        self._pl_hide_warning = ctk.CTkLabel(
            pl_header, text="  (filter may hide items)",
            text_color="#b08830", font=ctk.CTkFont(size=11))

        self.builder_pl_tree = ttk.Treeview(
            right_frame, columns=("composer", "genre", "info"),
            show="tree headings", selectmode="extended")
        self.builder_pl_tree.heading("#0", text="Name")
        self.builder_pl_tree.heading("composer", text="Composer")
        self.builder_pl_tree.heading("genre", text="Genre")
        self.builder_pl_tree.heading("info", text="Info")
        self.builder_pl_tree.column("#0", width=220)
        self.builder_pl_tree.column("composer", width=120)
        self.builder_pl_tree.column("genre", width=90)
        self.builder_pl_tree.column("info", width=70, anchor="center")
        self.builder_pl_tree.pack(fill="both", expand=True, padx=5, pady=2)

        pl_scroll = ttk.Scrollbar(right_frame, orient="vertical",
                                  command=self.builder_pl_tree.yview)
        self.builder_pl_tree.configure(yscrollcommand=pl_scroll.set)
        pl_scroll.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne",
                        in_=self.builder_pl_tree)

        self._setup_tree_sort(self.builder_pl_tree,
                              row_dbl_click=self._builder_exclude_selected)
        self.builder_pl_tree.bind("<Button-3>", lambda e: self._builder_context_menu(e, "pl"))
        self.builder_pl_tree.tag_configure("pinned", foreground="#e680ff")  # orchid
        self._builder_pl_iid_map = {}  # iid → (level, entity_id, key)

        # -- Bottom: action buttons --
        bot = ctk.CTkFrame(tab, fg_color="transparent")
        bot.pack(fill="x", padx=10, pady=(2, 5))

        ctk.CTkButton(bot, text="Preview", width=110,
                      command=self._preview_playlist).pack(side="left", padx=4)
        ctk.CTkButton(bot, text="Export M3U", width=110,
                      command=self._export_m3u).pack(side="left", padx=4)
        ctk.CTkButton(bot, text="Export JSON", width=110,
                      command=self._export_json).pack(side="left", padx=4)
        ctk.CTkButton(bot, text="Push to Plex", width=110,
                      command=self._push_plex).pack(side="left", padx=4)
        ctk.CTkButton(bot, text="Find Unused", width=110,
                      command=self._find_unused).pack(side="left", padx=4)
        ctk.CTkButton(bot, text="Find Similar", width=110,
                      command=self._find_similar_tracks).pack(side="left", padx=4)

        info = ctk.CTkLabel(bot, text="(empty = all tracks)",
                            text_color="gray")
        info.pack(side="right", padx=10)

    def _toggle_tree(self, tree, expand):
        """Expand or collapse all nodes in a treeview.

        When expanding, opens down to the work level only — albums are
        opened to reveal works, but works stay closed so individual tracks
        remain hidden.  When collapsing, closes everything.
        """
        for iid in tree.get_children():
            tree.item(iid, open=expand)
            for child in tree.get_children(iid):
                tree.item(child, open=False)

    def _on_hide_single_changed(self):
        """Toggle the 1-track filter and show/hide the playlist warning."""
        if self.builder_hide_single.get():
            self._pl_hide_warning.pack(side="left", padx=(4, 0))
        else:
            self._pl_hide_warning.pack_forget()
        with self._busy():
            self._refresh_builder_tree()

    def _refresh_builder_tree(self):
        """Populate the library tree and refresh the playlist tree."""
        self._builder_lib_data = {}   # entity_id → {level, album_id, work_id, ...}
        self._rebuild_library_tree()
        self._rebuild_playlist_tree()

    def _rebuild_library_tree(self):
        """Rebuild the left (library) tree with visual clues for included/excluded."""
        self._clear_tree_sort(self.builder_lib_tree)
        # Reattach any filter-detached items so delete catches everything
        for iid, parent, idx, txt, opn in self._lib_tree_snapshot:
            try:
                self.builder_lib_tree.reattach(iid, "", "end")
            except tk.TclError:
                pass
        self._lib_tree_snapshot = []
        self.builder_lib_tree.delete(*self.builder_lib_tree.get_children())
        self._builder_lib_iid_map.clear()
        self._lib_search_meta = {}

        if not self.active_library:
            return

        from music_manager.core.database import Album, Work, Track
        from music_manager.core.selection import (
            key_for_album, key_for_work, key_for_track, COMPOSITE_SEP,
        )

        # Build selection lookup dicts for quick matching
        sel_by_key = {}  # (level, key) → selection dict
        for s in self._current_selections:
            sel_by_key[(s["level"], s["key"])] = s

        hide_single = self.builder_hide_single.get()

        albums = (Album.select()
                  .where(Album.library == self.active_library)
                  .order_by(Album.title))

        for album in albums:
            a_key = key_for_album(album)
            album_sel = sel_by_key.get(("album", a_key))
            album_is_add = album_sel is not None and not album_sel["excluded"]
            album_is_except = album_sel is not None and album_sel["excluded"]

            works = list(Work.select()
                         .where(Work.album == album)
                         .order_by(Work.work_sequence))

            # Pre-load track counts per work for hide-single filtering
            work_track_counts = {}
            for work in works:
                work_track_counts[work.id] = Track.select().where(
                    Track.work == work).count()

            # Pre-scan children to detect partial state.
            # album_has_child_exception: a child is explicitly excluded
            #   → album is "partial" when it's added (not everything included)
            # album_has_child_add: a child is explicitly added
            #   → album is "partial" when it's NOT added, UNLESS every track is
            #     effectively included (then it's fully "included", not partial)
            album_has_child_exception = False
            album_has_child_add = False
            album_all_tracks_included = True
            for work in works:
                w_key = key_for_work(work)
                w_sel = sel_by_key.get(("work", w_key))
                work_add = w_sel is not None and not w_sel["excluded"]
                if w_sel:
                    if w_sel["excluded"]:
                        album_has_child_exception = True
                    else:
                        album_has_child_add = True
                tracks_for_work = list(Track.select(Track.relative_path).where(
                    Track.work == work))
                for t in tracks_for_work:
                    t_sel = sel_by_key.get(("track", t.relative_path))
                    t_add = t_sel is not None and not t_sel["excluded"]
                    t_exc = t_sel is not None and t_sel["excluded"]
                    if t_sel:
                        if t_exc:
                            album_has_child_exception = True
                        else:
                            album_has_child_add = True
                    # Effectively included (album itself not directly added here)
                    if not (t_add or (work_add and not t_exc)):
                        album_all_tracks_included = False

            # Filter works for display when hiding single-track works
            visible_works = works
            if hide_single:
                visible_works = [w for w in works if work_track_counts[w.id] > 1]
                if not visible_works:
                    continue

            # Determine album tag
            if album_is_except:
                album_tag = "excluded"
            elif album_is_add and album_has_child_exception:
                album_tag = "partial"  # added but some children excluded
            elif album_is_add:
                album_tag = "included"
            elif album_has_child_add:
                # Every track covered by child adds → fully included, else partial
                album_tag = ("included" if album_all_tracks_included
                             else "partial")
            else:
                album_tag = ""

            track_count = Track.select().where(Track.album == album).count()
            album_artist = album.album_artist or ""
            # Get representative genre from first track with one
            album_genre = ""
            first_genre_track = (Track.select(Track.genre)
                                 .where((Track.album == album) & Track.genre.is_null(False))
                                 .limit(1).first())
            if first_genre_track:
                album_genre = first_genre_track.genre or ""
            album_iid = self.builder_lib_tree.insert(
                "", "end", text=album.title,
                values=(album_artist, album_genre, f"{track_count} trk"),
                tags=(album_tag,) if album_tag else ())
            self._builder_lib_iid_map[album_iid] = ("album", album.id, a_key)
            self._lib_search_meta[album_iid] = " ".join(filter(None, [
                album.title, album_artist, album_genre]))

            for work in visible_works:
                w_key = key_for_work(work)
                tracks = list(Track.select().where(Track.work == work)
                              .order_by(Track.disc_number, Track.track_number))

                work_sel = sel_by_key.get(("work", w_key))
                work_is_add = work_sel is not None and not work_sel["excluded"]
                work_is_except = work_sel is not None and work_sel["excluded"]
                work_effectively_included = (
                    (work_is_add or album_is_add) and not work_is_except
                )

                # Check if any child track has an exception or add, and whether
                # every track is directly added (→ fully included, not partial)
                work_has_child_exception = False
                work_has_child_add = False
                work_all_tracks_added = bool(tracks)
                for t in tracks:
                    t_sel = sel_by_key.get(("track", t.relative_path))
                    if t_sel:
                        if t_sel["excluded"]:
                            work_has_child_exception = True
                        else:
                            work_has_child_add = True
                    if not (t_sel is not None and not t_sel["excluded"]):
                        work_all_tracks_added = False

                if work_is_except:
                    if work_has_child_add:
                        work_tag = "partial"  # excluded but some tracks added back
                    else:
                        work_tag = "excluded"
                elif work_effectively_included and work_has_child_exception:
                    work_tag = "partial"  # included but some tracks excluded
                elif work_effectively_included:
                    work_tag = "included"
                elif work_is_add:
                    work_tag = "included"
                elif work_has_child_add:
                    # All tracks added → fully included, otherwise partial
                    work_tag = "included" if work_all_tracks_added else "partial"
                else:
                    work_tag = ""

                work_composer = work.composer.name if work.composer_id else ""
                work_genre = tracks[0].genre if tracks and tracks[0].genre else ""
                work_iid = self.builder_lib_tree.insert(
                    album_iid, "end", text=work.work_name,
                    values=(work_composer, work_genre, f"{len(tracks)} trk"),
                    tags=(work_tag,) if work_tag else ())
                self._builder_lib_iid_map[work_iid] = ("work", work.id, w_key)
                self._lib_search_meta[work_iid] = " ".join(filter(None, [
                    work.work_name, work_composer, work_genre]))

                for t in tracks:
                    t_key = key_for_track(t)
                    dur_s = (t.duration_ms or 0) // 1000
                    dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"

                    track_sel = sel_by_key.get(("track", t_key))
                    track_is_except = track_sel is not None and track_sel["excluded"]
                    track_is_add = track_sel is not None and not track_sel["excluded"]

                    if track_is_except:
                        t_tag = "excluded"
                    elif track_is_add or work_effectively_included:
                        t_tag = "included"
                    else:
                        t_tag = ""

                    t_composer = t.composer.name if t.composer_id else ""
                    t_genre = t.genre or ""
                    t_iid = self.builder_lib_tree.insert(
                        work_iid, "end",
                        text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
                        values=(t_composer, t_genre, dur_str),
                        tags=(t_tag,) if t_tag else ())
                    self._builder_lib_iid_map[t_iid] = ("track", t.id, t_key)
                    self._lib_search_meta[t_iid] = " ".join(filter(None, [
                        t.title, t_composer, t_genre,
                        t.performer or "", t.conductor or "", t.ensemble or ""]))

        self._lib_tree_snapshot = self._snapshot_tree(self.builder_lib_tree)
        # Re-apply active filter if any
        if self._lib_filter_var.get().strip():
            self._apply_tree_filter("lib")

    def _rebuild_playlist_tree(self):
        """Rebuild the right (playlist) tree showing effectively-included items."""
        self._clear_tree_sort(self.builder_pl_tree)
        # Reattach any filter-detached items so delete catches everything
        for iid, parent, idx, txt, opn in self._pl_tree_snapshot:
            try:
                self.builder_pl_tree.reattach(iid, "", "end")
            except tk.TclError:
                pass
        self._pl_tree_snapshot = []
        self.builder_pl_tree.delete(*self.builder_pl_tree.get_children())
        self._builder_pl_iid_map.clear()
        self._pl_search_meta = {}

        if not self.active_library:
            return
        if not self._current_selections:
            return  # empty selections = all tracks (shown via label)

        from music_manager.core.database import Album, Work, Track
        from music_manager.core.selection import (
            key_for_album, key_for_work, key_for_track, COMPOSITE_SEP,
        )

        hide_single = self.builder_hide_single.get()

        # Build selection lookup dicts
        sel_by_key = {}
        for s in self._current_selections:
            sel_by_key[(s["level"], s["key"])] = s

        albums = (Album.select()
                  .where(Album.library == self.active_library)
                  .order_by(Album.title))

        for album in albums:
            a_key = key_for_album(album)
            album_sel = sel_by_key.get(("album", a_key))
            album_is_add = album_sel is not None and not album_sel["excluded"]
            album_is_except = album_sel is not None and album_sel["excluded"]
            if album_is_except:
                continue

            works = list(Work.select()
                         .where(Work.album == album)
                         .order_by(Work.work_sequence))

            # Collect works that should appear
            album_has_content = False
            work_entries = []
            for work in works:
                w_key = key_for_work(work)
                work_sel = sel_by_key.get(("work", w_key))
                work_is_add = work_sel is not None and not work_sel["excluded"]
                work_is_except = work_sel is not None and work_sel["excluded"]
                # Don't skip excluded works entirely — track-level adds
                # within them must still appear (specificity model).
                if work_is_except:
                    work_included = False
                else:
                    work_included = work_is_add or album_is_add

                tracks = list(Track.select().where(Track.work == work)
                              .order_by(Track.disc_number, Track.track_number))

                visible_tracks = []
                for t in tracks:
                    t_key = key_for_track(t)
                    track_sel = sel_by_key.get(("track", t_key))
                    track_is_except = track_sel is not None and track_sel["excluded"]
                    track_is_add = track_sel is not None and not track_sel["excluded"]
                    if track_is_except:
                        continue
                    if track_is_add or work_included:
                        visible_tracks.append(t)

                if visible_tracks:
                    if hide_single and len(visible_tracks) <= 1:
                        continue
                    work_entries.append((work, visible_tracks))
                    album_has_content = True

            if not album_has_content:
                continue

            total_tracks = sum(len(ts) for _, ts in work_entries)
            album_artist = album.album_artist or ""
            # Get representative genre from first track
            album_genre = ""
            for _, vts in work_entries:
                for vt in vts:
                    if vt.genre:
                        album_genre = vt.genre
                        break
                if album_genre:
                    break
            album_iid = self.builder_pl_tree.insert(
                "", "end", text=album.title,
                values=(album_artist, album_genre, f"{total_tracks} trk"))
            self._builder_pl_iid_map[album_iid] = ("album", album.id, a_key)
            self._pl_search_meta[album_iid] = " ".join(filter(None, [
                album.title, album_artist, album_genre]))

            for work, vis_tracks in work_entries:
                w_key = key_for_work(work)
                work_composer = work.composer.name if work.composer_id else ""
                work_genre = vis_tracks[0].genre if vis_tracks and vis_tracks[0].genre else ""
                # Check if this work is pinned (via selection pin_position)
                work_sel = sel_by_key.get(("work", w_key))
                pin_pos = work_sel.get("pin_position") if work_sel else None
                work_text = (f"[#{pin_pos}] {work.work_name}"
                             if pin_pos else work.work_name)
                work_iid = self.builder_pl_tree.insert(
                    album_iid, "end", text=work_text,
                    values=(work_composer, work_genre, f"{len(vis_tracks)} trk"),
                    tags=("pinned",) if pin_pos else ())
                self._builder_pl_iid_map[work_iid] = ("work", work.id, w_key)
                self._pl_search_meta[work_iid] = " ".join(filter(None, [
                    work.work_name, work_composer, work_genre]))

                for t in vis_tracks:
                    t_key = key_for_track(t)
                    dur_s = (t.duration_ms or 0) // 1000
                    dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                    t_composer = t.composer.name if t.composer_id else ""
                    t_genre = t.genre or ""
                    t_iid = self.builder_pl_tree.insert(
                        work_iid, "end",
                        text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
                        values=(t_composer, t_genre, dur_str))
                    self._builder_pl_iid_map[t_iid] = ("track", t.id, t_key)
                    self._pl_search_meta[t_iid] = " ".join(filter(None, [
                        t.title, t_composer, t_genre,
                        t.performer or "", t.conductor or "", t.ensemble or ""]))

            # Auto-expand albums in playlist view
            self.builder_pl_tree.item(album_iid, open=True)

        self._pl_tree_snapshot = self._snapshot_tree(self.builder_pl_tree)
        # Re-apply active filter if any
        if self._pl_filter_var.get().strip():
            self._apply_tree_filter("pl")

    def _builder_context_menu(self, event, pane):
        """Right-click context menu on playlist builder trees."""
        tree = self.builder_lib_tree if pane == "lib" else self.builder_pl_tree
        iid_map = self._builder_lib_iid_map if pane == "lib" else self._builder_pl_iid_map

        iid = tree.identify_row(event.y)
        if not iid:
            return
        if iid not in tree.selection():
            tree.selection_set(iid)

        entry = iid_map.get(iid)
        if not entry:
            return
        level, entity_id, key = entry

        menu = tk.Menu(self.root, tearoff=0)

        try:
            if level == "work":
                from music_manager.core.database import Work
                work = Work.get_by_id(entity_id)
                menu.add_command(label="Details...",
                                 command=lambda: self._show_work_details(entity_id))
                menu.add_command(label="Show Album",
                                 command=lambda: self._show_album_popup(work.album_id))
            elif level == "track":
                from music_manager.core.database import Track
                track = Track.get_by_id(entity_id)
                menu.add_command(label="Play",
                                 command=lambda: self._play_track(entity_id))
                if track.work_id:
                    menu.add_command(label="Details...",
                                     command=lambda: self._show_work_details(track.work_id))
                menu.add_command(label="Show Album",
                                 command=lambda: self._show_album_popup(track.album_id))
            elif level == "album":
                menu.add_command(label="Show Album",
                                 command=lambda: self._show_album_popup(entity_id))
        except Exception:
            messagebox.showinfo("Stale Data", "Data has changed. Please refresh the view.")
            return

        menu.add_separator()
        if pane == "lib":
            menu.add_command(label="Add >>",
                             command=self._builder_include_selected)
            menu.add_command(label="<< Remove",
                             command=self._builder_exclude_selected)
            menu.add_separator()
            menu.add_command(
                label="Show in profiles...",
                command=lambda lv=level, eid=entity_id, k=key: self._show_in_profiles(lv, eid, k))
        else:
            menu.add_command(label="<< Remove",
                             command=self._builder_exclude_selected)
            if level == "work":
                pin_menu = tk.Menu(menu, tearoff=0)
                for pos in range(1, 6):
                    pin_menu.add_command(
                        label=f"Position {pos}",
                        command=lambda p=pos, wid=entity_id, wk=key: self._pin_work(wid, p, wk),
                    )
                pin_menu.add_separator()
                pin_menu.add_command(
                    label="Remove pin",
                    command=lambda wk=key: self._unpin_work(wk),
                )
                menu.add_cascade(label="Pin to position...", menu=pin_menu)

        menu.tk_popup(event.x_root, event.y_root)

    def _pin_work(self, work_id, position, work_key):
        """Pin a work to a position (1-5). Replaces any existing pin at that position."""
        from music_manager.core.database import Work, Track
        from music_manager.core.selection import display_name_for_selection
        try:
            work = Work.get_by_id(work_id)
        except Work.DoesNotExist:
            return

        # Remove any existing pin at this position from other selections
        for s in self._current_selections:
            if s.get("pin_position") == position and s["key"] != work_key:
                s["pin_position"] = None
                # Rebuild display text without pin prefix
                prefix = "EXCEPT" if s["excluded"] else "ADD"
                dn = display_name_for_selection(self.active_library, s["level"], s["key"])
                s["display"] = f"{prefix}: {s['level']} — {dn}"

        # Find or create selection for this work
        sel = self._find_selection("work", work_key)
        if sel is not None:
            sel["pin_position"] = position
            # Rebuild display text with pin prefix
            prefix = "EXCEPT" if sel["excluded"] else "ADD"
            dn = display_name_for_selection(self.active_library, "work", work_key)
            sel["display"] = f"[#{position}] {prefix}: work — {dn}"
        else:
            # Create a new add selection with pin and track_paths breadcrumbs
            track_paths = json.dumps([
                t.relative_path for t in
                Track.select(Track.relative_path).where(Track.work == work)
            ])
            self._add_selection("work", work_key, excluded=False,
                                pin_position=position, track_paths=track_paths,
                                refresh=False)

        self._refresh_rules_display()

    def _unpin_work(self, work_key):
        """Remove a pin for a work."""
        from music_manager.core.selection import display_name_for_selection
        sel = self._find_selection("work", work_key)
        if sel and sel.get("pin_position"):
            sel["pin_position"] = None
            prefix = "EXCEPT" if sel["excluded"] else "ADD"
            dn = display_name_for_selection(self.active_library, "work", work_key)
            sel["display"] = f"{prefix}: work — {dn}"
        self._refresh_rules_display()

    def _show_in_profiles(self, level, entity_id, key):
        """Show a popup listing all profiles that include this item."""
        from music_manager.core.database import (
            PlaylistProfile, ProfileSelection, Album, Work, Track,
        )
        from music_manager.core.selection import parse_work_key

        # Get display name for the item
        if level == "album":
            name = Album.get_by_id(entity_id).title
        elif level == "work":
            name = Work.get_by_id(entity_id).work_name
        elif level == "track":
            name = Track.get_by_id(entity_id).title
        else:
            name = str(entity_id)

        # Find all profiles (non-internal) that have a matching add selection
        # Direct match at this level
        direct_sels = list(ProfileSelection.select().where(
            (ProfileSelection.excluded == False) &
            (ProfileSelection.level == level) &
            (ProfileSelection.key == key)
        ))
        profile_ids = {s.profile_id for s in direct_sels}

        # Also check parent-level adds (album add covers work/track)
        if level == "work":
            parsed = parse_work_key(key)
            if parsed:
                album_key = parsed[0]
                album_sels = list(ProfileSelection.select().where(
                    (ProfileSelection.excluded == False) &
                    (ProfileSelection.level == "album") &
                    (ProfileSelection.key == album_key)
                ))
                profile_ids.update(s.profile_id for s in album_sels)
        elif level == "track":
            track = Track.get_by_id(entity_id)
            if track.work_id:
                from music_manager.core.selection import key_for_work
                work = Work.get_by_id(track.work_id)
                work_key = key_for_work(work)
                work_sels = list(ProfileSelection.select().where(
                    (ProfileSelection.excluded == False) &
                    (ProfileSelection.level == "work") &
                    (ProfileSelection.key == work_key)
                ))
                profile_ids.update(s.profile_id for s in work_sels)
            album = Album.get_by_id(track.album_id)
            album_sels = list(ProfileSelection.select().where(
                (ProfileSelection.excluded == False) &
                (ProfileSelection.level == "album") &
                (ProfileSelection.key == album.album_key)
            ))
            profile_ids.update(s.profile_id for s in album_sels)

        # Also include profiles with NO selections (they include everything)
        all_profiles = list(PlaylistProfile.select().where(
            ~PlaylistProfile.name.startswith("__")))
        profiles_with_no_selections = []
        for prof in all_profiles:
            if prof.id in profile_ids:
                continue
            has_adds = ProfileSelection.select().where(
                (ProfileSelection.profile == prof) &
                (ProfileSelection.excluded == False)
            ).exists()
            if not has_adds:
                profiles_with_no_selections.append(prof)

        # Gather matching profile objects
        matching = [p for p in all_profiles if p.id in profile_ids]
        matching.sort(key=lambda p: p.name)

        # Build popup
        popup = tk.Toplevel(self.root)
        popup.title(f"Profiles including: {name}")
        popup.transient(self.root)
        self._center_on_main(popup, 450, 300)
        popup.wait_visibility()
        popup.grab_set()

        ctk = self.ctk
        frame = ctk.CTkFrame(popup)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        lb = tk.Listbox(frame, bg="#2b2b2b", fg="white",
                        selectbackground="#1f6aa5",
                        font=("Segoe UI", 10))
        lb.pack(fill="both", expand=True)

        if matching:
            for p in matching:
                lb.insert("end", f"{p.name}  ({p.library.name})")
        if profiles_with_no_selections:
            lb.insert("end", "")
            lb.insert("end", "— Profiles with no selections (all tracks) —")
            for p in sorted(profiles_with_no_selections, key=lambda p: p.name):
                lb.insert("end", f"{p.name}  ({p.library.name})")

        if not matching and not profiles_with_no_selections:
            lb.insert("end", "(not included in any profile)")

        ctk.CTkButton(popup, text="Close", width=80,
                      command=popup.destroy).pack(pady=(0, 10))

    def _builder_toggle_include(self, event=None):
        """Toggle selection state of library items on double-click.

        Simple 3-state toggle:
          - Has direct add → remove it (and clean up children)
          - Has direct exception → remove the exception
          - Not selected → add it
          - Selected via parent → add exception
        """
        sel = self.builder_lib_tree.selection()
        if not sel:
            return "break"

        entries = []
        for iid in sel:
            entry = self._builder_lib_iid_map.get(iid)
            if entry:
                entries.append(entry)

        for level, entity_id, key in entries:
            existing = self._find_selection(level, key)
            if existing is not None:
                if existing["excluded"]:
                    # Exception → remove it (re-includes via parent)
                    # Also clean up child selections that were workarounds
                    self._current_selections.remove(existing)
                    self._cascade_remove_children(level, key)
                else:
                    # Direct add → remove it and clean up children
                    self._current_selections.remove(existing)
                    self._cascade_remove_children(level, key)
                    # If still covered by a broader parent selection, one
                    # toggle should hide it — add an exclusion rather than
                    # leaving it visible via the parent (which would take a
                    # second toggle to clear).
                    if self._is_item_selected(level, key):
                        self._add_selection(level, key, excluded=True,
                                            refresh=False)
            elif self._is_item_selected(level, key):
                # Included via parent — add exception
                self._add_selection(level, key, excluded=True, refresh=False)
            else:
                # Not selected — add it
                self._add_with_breadcrumbs(level, key, entity_id)

        with self._busy():
            view_state = self._save_builder_view_state()
            self._refresh_rules_display()
            self._restore_builder_view_state(view_state)
        return "break"

    def _builder_include_selected(self, event=None):
        """Add selected library items as selections."""
        sel = self.builder_lib_tree.selection()
        if not sel:
            if event is None:
                messagebox.showinfo("Select", "Select items in the Library pane first.")
            return "break"

        entries = []
        for iid in sel:
            entry = self._builder_lib_iid_map.get(iid)
            if entry:
                entries.append(entry)

        for level, entity_id, key in entries:
            existing = self._find_selection(level, key)
            if existing and not existing["excluded"]:
                continue  # already added
            if existing and existing["excluded"]:
                # Has exception — remove it to re-include via parent
                # Also clean up child selections that are now redundant
                self._current_selections.remove(existing)
                self._cascade_remove_children(level, key)
            else:
                self._add_with_breadcrumbs(level, key, entity_id)

        with self._busy():
            view_state = self._save_builder_view_state()
            self._refresh_rules_display()
            self._restore_builder_view_state(view_state)
        return "break"

    def _builder_exclude_selected(self, event=None):
        """Remove selected items (remove direct adds or add exceptions)."""
        # Try playlist tree first, then library tree
        sel = self.builder_pl_tree.selection()
        iid_map = self._builder_pl_iid_map
        if not sel:
            sel = self.builder_lib_tree.selection()
            iid_map = self._builder_lib_iid_map
        if not sel:
            if event is None:
                messagebox.showinfo("Select", "Select items to remove.")
            return "break"

        entries = []
        for iid in sel:
            entry = iid_map.get(iid)
            if entry:
                entries.append(entry)

        for level, entity_id, key in entries:
            existing = self._find_selection(level, key)
            if existing and not existing["excluded"]:
                # Direct add — remove it and clean up children
                self._current_selections.remove(existing)
                self._cascade_remove_children(level, key)
            # After dropping any direct add, the item may still be covered by
            # a broader parent selection (e.g. its album was added). Removing
            # only the direct add would leave it visible via the parent, so
            # add an explicit exclusion to actually take it out.
            if self._is_item_selected(level, key):
                self._add_selection(level, key, excluded=True, refresh=False)

        with self._busy():
            view_state = self._save_builder_view_state()
            self._refresh_rules_display()
            self._restore_builder_view_state(view_state)
        return "break"

    def _cascade_remove_children(self, level, key):
        """Remove all child selections when a parent selection is removed."""
        from music_manager.core.selection import COMPOSITE_SEP

        if level == "album":
            album_key = key
            self._current_selections = [
                s for s in self._current_selections
                if not (
                    (s["level"] == "work" and s["key"].startswith(album_key + COMPOSITE_SEP))
                    or (s["level"] == "track" and s["key"].startswith(album_key + "/"))
                )
            ]
        elif level == "work":
            # Remove track-level selections for tracks belonging to this work
            from music_manager.core.selection import parse_work_key
            from music_manager.core.database import Work, Track, Album
            parsed = parse_work_key(key)
            if parsed:
                album_key, work_name, work_seq = parsed
                album = Album.select().where(
                    (Album.library == self.active_library) &
                    (Album.album_key == album_key)
                ).first()
                if album:
                    query = Work.select().where(
                        (Work.album == album) & (Work.work_name == work_name)
                    )
                    if work_seq is not None:
                        query = query.where(Work.work_sequence == work_seq)
                    work = query.first()
                    if work:
                        track_paths = {
                            t.relative_path for t in
                            Track.select(Track.relative_path).where(Track.work == work)
                        }
                        self._current_selections = [
                            s for s in self._current_selections
                            if not (s["level"] == "track" and s["key"] in track_paths)
                        ]

    def _add_with_breadcrumbs(self, level, key, entity_id):
        """Add a selection, including track_paths breadcrumbs for work-level."""
        import json
        track_paths = None
        if level == "work":
            from music_manager.core.database import Track
            track_paths = json.dumps([
                t.relative_path for t in
                Track.select(Track.relative_path).where(Track.work == entity_id)
            ])
        self._add_selection(level, key, excluded=False,
                            track_paths=track_paths, refresh=False)

    def _build_temp_profile(self):
        """Build a temporary PlaylistProfile from current UI settings."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return None

        from music_manager.core.database import PlaylistProfile, ProfileSelection

        # Use a temp name that won't collide with user-saved profiles
        name = "__temp_preview__"
        # Clean up any leftover temp profiles (CASCADE deletes selections)
        for old in PlaylistProfile.select().where(PlaylistProfile.name == name):
            old.delete_instance()

        length_val = self.length_value.get().strip()
        seed_val = self.seed_entry.get().strip()

        profile = PlaylistProfile.create(
            library=self.active_library,
            name=name,
            shuffle_mode=self.shuffle_mode.get(),
            work_integrity=self.work_integrity.get(),
            length_mode=self.length_mode.get(),
            length_value=self._parse_length_value(length_val),
            seed=int(seed_val) if seed_val else None,
            no_repeat_tracks=self.no_repeat_var.get() == 1,
            separate_composers=self.sep_composer_var.get() == 1,
            separate_albums=self.sep_album_var.get() == 1,
            separate_forms=self.sep_form_var.get() == 1,
        )

        for sel in self._current_selections:
            ProfileSelection.create(
                profile=profile,
                level=sel["level"],
                key=sel["key"],
                excluded=sel["excluded"],
                pin_position=sel.get("pin_position"),
                track_paths=sel.get("track_paths"),
            )

        return profile

    @staticmethod
    def _parse_length_value(text):
        """Parse a length value that may be an integer, or H:MM / M:SS duration.

        Returns seconds (int) or None if empty.  Raises ValueError on bad input.
        """
        text = text.strip()
        if not text:
            return None
        if ":" in text:
            parts = text.split(":")
            if len(parts) == 2:
                h_or_m, m_or_s = int(parts[0]), int(parts[1])
                return h_or_m * 3600 + m_or_s * 60  # treat as H:MM
            elif len(parts) == 3:
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                return h * 3600 + m * 60 + s
            else:
                raise ValueError(f"Invalid duration format: {text}")
        return int(text)

    def _delete_temp_profile(self, profile):
        """Delete a temporarily-created profile."""
        if profile:
            profile.delete_instance()  # CASCADE deletes selections

    def _preview_playlist(self):
        """Preview the playlist in a popup window (dry-run)."""
        display_name = self.profile_name_entry.get().strip() or "Untitled"
        profile = self._build_temp_profile()
        if not profile:
            return

        with self._busy():
            try:
                from music_manager.core.engine import generate_playlist
                result = generate_playlist(profile)
            except Exception as exc:
                self._delete_temp_profile(profile)
                messagebox.showerror("Preview Error", str(exc))
                return

        self._delete_temp_profile(profile)

        # Build popup
        popup = tk.Toplevel(self.root)
        popup.title(f"Preview — {display_name}")
        popup.transient(self.root)
        self._center_on_main(popup, 900, 550)
        popup.wait_visibility()
        popup.grab_set()

        # Bottom bar (pack first so tree gets remaining space)
        total_s = result.total_duration_ms // 1000
        status_text = (f"{result.track_count} tracks, "
                       f"{total_s // 3600}h {(total_s % 3600) // 60}m "
                       f"{total_s % 60}s total")

        bot = tk.Frame(popup, bg="#2b2b2b")
        bot.pack(side="bottom", fill="x", padx=10, pady=5)
        tk.Label(bot, text=status_text, bg="#2b2b2b", fg="white",
                 font=("Segoe UI", 11)).pack(side="left", padx=5)
        tk.Button(bot, text="Close", command=popup.destroy,
                  bg="#3b3b3b", fg="white").pack(side="right", padx=5)

        # Tree + scrollbar in a frame
        tree_frame = tk.Frame(popup)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        tree = ttk.Treeview(tree_frame,
                            columns=("order", "composer", "work", "title", "dur"),
                            show="headings", selectmode="browse")
        tree.heading("order", text="#")
        tree.heading("composer", text="Composer")
        tree.heading("work", text="Work")
        tree.heading("title", text="Title")
        tree.heading("dur", text="Duration")
        tree.column("order", width=40, anchor="center")
        tree.column("composer", width=150)
        tree.column("work", width=220)
        tree.column("title", width=280)
        tree.column("dur", width=70, anchor="center")

        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        if not result.playlist:
            tree.insert("", "end", values=(
                "", "", "", "(no tracks matched current rules)", ""))
        else:
            for rt in result.playlist:
                dur_s = rt.duration_ms // 1000
                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                tree.insert("", "end", values=(
                    rt.order_key,
                    rt.composer_name or "",
                    rt.work_name or "",
                    rt.title,
                    dur_str,
                ))

    def _find_unused(self):
        """Populate the builder with tracks not included in any saved profile."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        self._save_before_export()

        with self._busy():
            try:
                from music_manager.core.engine import find_unused_tracks
                albums, works, tracks = find_unused_tracks(self.active_library)
            except Exception as exc:
                messagebox.showerror("Find Unused Error", str(exc))
                return

        if not albums and not works and not tracks:
            messagebox.showinfo(
                "Find Unused",
                "All tracks are used by at least one profile.")
            return

        # Clear builder and populate with unused items
        self._new_profile()
        from music_manager.core.database import Album, Work, Track
        from music_manager.core.selection import key_for_album, key_for_work, key_for_track
        for target_id, name in albums:
            album = Album.get_by_id(target_id)
            self._add_selection("album", key_for_album(album), refresh=False)
        for target_id, name in works:
            work = Work.get_by_id(target_id)
            self._add_with_breadcrumbs("work", key_for_work(work), target_id)
        for target_id, name in tracks:
            track = Track.get_by_id(target_id)
            self._add_selection("track", key_for_track(track), refresh=False)
        self._refresh_rules_display()

    def _save_before_export(self):
        """Silently save profile settings before an export operation.

        Only updates an existing profile's settings (shuffle mode, length,
        etc.) in place — never deletes/recreates the profile or touches its
        rules.  If no profile with this name exists yet, creates a new one
        with the current UI rules.
        """
        name = self.profile_name_entry.get().strip()
        if name and self.active_library:
            from music_manager.core.database import PlaylistProfile, ProfileSelection

            # Skip if there's a cross-library name conflict
            conflict = PlaylistProfile.select().where(
                (PlaylistProfile.name == name) &
                (PlaylistProfile.library != self.active_library) &
                (~PlaylistProfile.name.startswith("__"))
            ).first()
            if conflict:
                return

            length_val = self.length_value.get().strip()
            seed_val = self.seed_entry.get().strip()

            existing = PlaylistProfile.select().where(
                (PlaylistProfile.library == self.active_library) &
                (PlaylistProfile.name == name)
            ).first()

            if existing:
                existing.shuffle_mode = self.shuffle_mode.get()
                existing.work_integrity = self.work_integrity.get()
                existing.length_mode = self.length_mode.get()
                existing.length_value = self._parse_length_value(length_val)
                existing.seed = int(seed_val) if seed_val else None
                existing.no_repeat_tracks = self.no_repeat_var.get() == 1
                existing.separate_composers = self.sep_composer_var.get() == 1
                existing.separate_albums = self.sep_album_var.get() == 1
                existing.separate_forms = self.sep_form_var.get() == 1
                existing.save()
                # Sync selections from current UI state
                ProfileSelection.delete().where(
                    ProfileSelection.profile == existing).execute()
                for sel in self._current_selections:
                    ProfileSelection.create(
                        profile=existing,
                        level=sel["level"],
                        key=sel["key"],
                        excluded=sel["excluded"],
                        pin_position=sel.get("pin_position"),
                        track_paths=sel.get("track_paths"),
                    )
            else:
                profile = PlaylistProfile.create(
                    library=self.active_library,
                    name=name,
                    shuffle_mode=self.shuffle_mode.get(),
                    work_integrity=self.work_integrity.get(),
                    length_mode=self.length_mode.get(),
                    length_value=self._parse_length_value(length_val),
                    seed=int(seed_val) if seed_val else None,
                    no_repeat_tracks=self.no_repeat_var.get() == 1,
                    separate_composers=self.sep_composer_var.get() == 1,
                    separate_albums=self.sep_album_var.get() == 1,
                    separate_forms=self.sep_form_var.get() == 1,
                )
                for sel in self._current_selections:
                    ProfileSelection.create(
                        profile=profile,
                        level=sel["level"],
                        key=sel["key"],
                        excluded=sel["excluded"],
                        pin_position=sel.get("pin_position"),
                        track_paths=sel.get("track_paths"),
                    )

            self._clear_autosave()
        else:
            self._autosave()

    def _export_m3u(self):
        """Export the playlist to an M3U file."""
        self._save_before_export()
        default_name = self.profile_name_entry.get().strip() or "playlist"
        initial_dir = self._prefs.get("last_export_dir", "")
        path = filedialog.asksaveasfilename(
            defaultextension=".m3u",
            initialfile=f"{default_name}.m3u",
            initialdir=initial_dir or None,
            filetypes=[("M3U Playlist", "*.m3u"), ("All files", "*.*")],
            title="Export M3U",
            parent=self.root,
        )
        if not path:
            return
        self._prefs["last_export_dir"] = str(Path(path).parent)
        _save_prefs(self._prefs)

        profile = self._build_temp_profile()
        if not profile:
            return

        try:
            from music_manager.core.engine import generate_playlist
            from music_manager.core.serializers.m3u import M3USerializer
            from music_manager.core.config import load_config

            result = generate_playlist(profile)
            config = load_config()
            m3u_config = config.get("targets", {}).get("m3u", {})
            m3u_config["output_path"] = path

            serializer = M3USerializer()
            serializer.serialize(result.playlist, m3u_config)
            messagebox.showinfo("Export", f"Wrote {result.track_count} tracks to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))
        finally:
            self._delete_temp_profile(profile)

    def _export_json(self):
        """Export the playlist to a JSON file."""
        self._save_before_export()
        default_name = self.profile_name_entry.get().strip() or "playlist"
        initial_dir = self._prefs.get("last_export_dir", "")
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=f"{default_name}.json",
            initialdir=initial_dir or None,
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            title="Export JSON",
            parent=self.root,
        )
        if not path:
            return
        self._prefs["last_export_dir"] = str(Path(path).parent)
        _save_prefs(self._prefs)

        profile = self._build_temp_profile()
        if not profile:
            return

        try:
            from music_manager.core.engine import generate_playlist
            from music_manager.core.serializers.json_dump import serialize_engine_result

            result = generate_playlist(profile)
            serialize_engine_result(result, output_path=Path(path))
            messagebox.showinfo("Export", f"Wrote {result.track_count} tracks to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))
        finally:
            self._delete_temp_profile(profile)

    def _push_plex(self):
        """Push the playlist to Plex."""
        self._save_before_export()
        profile = self._build_temp_profile()
        if not profile:
            return

        with self._busy():
            try:
                from music_manager.core.engine import generate_playlist
                from music_manager.core.serializers.plex import PlexSerializer, PlexConnectionError, PlexPushError
                from music_manager.core.config import load_config

                result = generate_playlist(profile)
                config = load_config()
                plex_config = config.get("targets", {}).get("plex", {})
                plex_config["playlist_name"] = self.profile_name_entry.get().strip() or "Untitled"

                # Use per-library Plex section if set, otherwise fall back to config
                lib_section = (self.active_library.plex_section
                               if self.active_library and self.active_library.plex_section
                               else None)
                if lib_section:
                    plex_config["music_section"] = lib_section

                serializer = PlexSerializer()
                serializer.serialize(result.playlist, plex_config)
                display_name = plex_config["playlist_name"]
                messagebox.showinfo("Plex", f"Pushed '{display_name}' to Plex "
                                   f"({result.track_count} tracks)")
            except (PlexConnectionError, PlexPushError) as exc:
                messagebox.showerror("Plex Error", str(exc))
            except Exception as exc:
                messagebox.showerror("Error", str(exc))
            finally:
                self._delete_temp_profile(profile)

    def _new_profile(self):
        """Clear the builder to start a fresh playlist profile."""
        self.profile_name_entry.delete(0, "end")
        self.shuffle_mode.set("work")
        self.work_integrity.set("enforce")
        self.length_mode.set("all")
        self.length_value.delete(0, "end")
        self.seed_entry.delete(0, "end")
        self.no_repeat_var.select()
        self.sep_composer_var.deselect()
        self.sep_album_var.deselect()
        self.sep_form_var.deselect()
        self._current_selections.clear()
        self._refresh_rules_display()
        self._refresh_builder_tree()

    def _save_profile(self):
        """Save current settings as a named profile in the DB."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        name = self.profile_name_entry.get().strip()
        if not name:
            messagebox.showwarning("No Name", "Enter a profile name.")
            return

        from music_manager.core.database import PlaylistProfile, ProfileSelection

        # Enforce unique profile names across all libraries
        conflict = PlaylistProfile.select().where(
            (PlaylistProfile.name == name) &
            (PlaylistProfile.library != self.active_library) &
            (~PlaylistProfile.name.startswith("__"))
        ).first()
        if conflict:
            messagebox.showwarning(
                "Name Conflict",
                f"A profile named '{name}' already exists in library "
                f"'{conflict.library.name}'. Profile names must be unique "
                f"across all libraries.")
            return

        # Delete existing profile with same name in this library (CASCADE handles selections)
        for existing in PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (PlaylistProfile.name == name)
        ):
            existing.delete_instance()

        length_val = self.length_value.get().strip()
        seed_val = self.seed_entry.get().strip()

        profile = PlaylistProfile.create(
            library=self.active_library,
            name=name,
            shuffle_mode=self.shuffle_mode.get(),
            work_integrity=self.work_integrity.get(),
            length_mode=self.length_mode.get(),
            length_value=self._parse_length_value(length_val),
            seed=int(seed_val) if seed_val else None,
            no_repeat_tracks=self.no_repeat_var.get() == 1,
            separate_composers=self.sep_composer_var.get() == 1,
            separate_albums=self.sep_album_var.get() == 1,
            separate_forms=self.sep_form_var.get() == 1,
        )

        for sel in self._current_selections:
            ProfileSelection.create(
                profile=profile,
                level=sel["level"],
                key=sel["key"],
                excluded=sel.get("excluded", False),
                pin_position=sel.get("pin_position"),
                track_paths=sel.get("track_paths"),
            )

        self._clear_autosave()
        messagebox.showinfo("Saved", f"Profile '{name}' saved.")

    def _delete_profile(self):
        """Show a profile picker, then delete the selected profile after confirmation."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return
        if self._profile_picker_open:
            return
        self._profile_picker_open = True

        from music_manager.core.database import PlaylistProfile

        profiles = list(PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (~PlaylistProfile.name.startswith("__"))))
        if not profiles:
            self._profile_picker_open = False
            messagebox.showinfo("No Profiles", "No saved profiles found.")
            return

        # Deduplicate names (keep latest)
        seen = set()
        names = []
        for p in reversed(profiles):
            if p.name not in seen:
                seen.add(p.name)
                names.append(p.name)
        names.reverse()

        picker = tk.Toplevel(self.root)
        picker.title("Delete Profile")
        picker.transient(self.root)
        self._center_on_main(picker, 300, 300)
        picker.wait_visibility()
        picker.grab_set()

        lb = tk.Listbox(picker, bg="#2b2b2b", fg="white",
                        selectbackground="#1f6aa5", font=("Segoe UI", 11),
                        selectmode="extended")
        for n in names:
            lb.insert("end", n)
        lb.pack(fill="both", expand=True, padx=10, pady=10)

        def on_delete():
            sel = lb.curselection()
            if not sel:
                return
            selected_names = [names[i] for i in sel]
            count = len(selected_names)
            label = selected_names[0] if count == 1 else f"{count} profiles"
            if not messagebox.askyesno("Confirm Delete",
                                       f"Delete {label}?", parent=picker):
                return
            for sname in selected_names:
                for existing in PlaylistProfile.select().where(
                    (PlaylistProfile.library == self.active_library) &
                    (PlaylistProfile.name == sname)
                ):
                    existing.delete_instance()  # CASCADE deletes selections
            picker.destroy()
            self._profile_picker_open = False
            # Clear the profile name if it was one of the deleted profiles
            current_name = self.profile_name_entry.get().strip()
            if current_name in selected_names:
                self.profile_name_entry.delete(0, "end")
                self._current_selections.clear()
                self._refresh_rules_display()
            messagebox.showinfo("Deleted", f"Deleted {label}.")

        def on_close():
            picker.destroy()
            self._profile_picker_open = False

        picker.protocol("WM_DELETE_WINDOW", on_close)
        ctk = self.ctk
        ctk.CTkButton(picker, text="Delete", command=on_delete,
                      fg_color="#c0392b", hover_color="#e74c3c").pack(pady=5)

    def _load_profile(self):
        """Always show a profile picker dialog, then load the selected profile."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return
        if self._profile_picker_open:
            return
        self._profile_picker_open = True

        from music_manager.core.database import PlaylistProfile
        profiles = list(PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (~PlaylistProfile.name.startswith("__"))))
        if not profiles:
            self._profile_picker_open = False
            messagebox.showinfo("No Profiles", "No saved profiles found.")
            return

        # Deduplicate names (keep latest)
        seen = set()
        names = []
        for p in reversed(profiles):
            if p.name not in seen:
                seen.add(p.name)
                names.append(p.name)
        names.reverse()

        picker = tk.Toplevel(self.root)
        picker.title("Select Profile")
        picker.transient(self.root)
        self._center_on_main(picker, 300, 300)
        picker.wait_visibility()
        picker.grab_set()

        lb = tk.Listbox(picker, bg="#2b2b2b", fg="white",
                       selectbackground="#1f6aa5", font=("Segoe UI", 11))
        for n in names:
            lb.insert("end", n)
        lb.pack(fill="both", expand=True, padx=10, pady=10)

        def on_select():
            sel = lb.curselection()
            if not sel:
                return
            chosen = names[sel[0]]
            picker.destroy()
            self._profile_picker_open = False
            self._apply_profile(chosen)

        def on_close():
            picker.destroy()
            self._profile_picker_open = False

        picker.protocol("WM_DELETE_WINDOW", on_close)
        ctk = self.ctk
        ctk.CTkButton(picker, text="Load", command=on_select).pack(pady=5)
        lb.bind("<Double-1>", lambda e: on_select())

    def _apply_profile(self, name):
        """Load a named profile's settings and selections into the UI."""
        from music_manager.core.database import PlaylistProfile, ProfileSelection
        from music_manager.core.selection import display_name_for_selection

        try:
            profile = PlaylistProfile.get(
                (PlaylistProfile.library == self.active_library) &
                (PlaylistProfile.name == name)
            )
        except PlaylistProfile.DoesNotExist:
            messagebox.showwarning("Not Found", f"Profile '{name}' not found.")
            return
        self.root.config(cursor="watch")
        self.root.update_idletasks()

        # Populate UI
        self.profile_name_entry.delete(0, "end")
        self.profile_name_entry.insert(0, name)
        self.shuffle_mode.set(profile.shuffle_mode)
        self.work_integrity.set(profile.work_integrity)
        self.length_mode.set(profile.length_mode)
        self.length_value.delete(0, "end")
        if profile.length_value is not None:
            self.length_value.insert(0, str(profile.length_value))
        self.seed_entry.delete(0, "end")
        if profile.seed is not None:
            self.seed_entry.insert(0, str(profile.seed))
        if profile.no_repeat_tracks:
            self.no_repeat_var.select()
        else:
            self.no_repeat_var.deselect()
        if profile.separate_composers:
            self.sep_composer_var.select()
        else:
            self.sep_composer_var.deselect()
        if profile.separate_albums:
            self.sep_album_var.select()
        else:
            self.sep_album_var.deselect()
        if profile.separate_forms:
            self.sep_form_var.select()
        else:
            self.sep_form_var.deselect()

        # Load selections
        self._current_selections.clear()
        for sel in ProfileSelection.select().where(
            ProfileSelection.profile == profile
        ):
            display_name = display_name_for_selection(
                self.active_library, sel.level, sel.key
            )
            prefix = "EXCLUDE" if sel.excluded else "ADD"
            pin_str = f" [PIN #{sel.pin_position}]" if sel.pin_position else ""
            self._current_selections.append({
                "level": sel.level,
                "key": sel.key,
                "excluded": sel.excluded,
                "pin_position": sel.pin_position,
                "track_paths": sel.track_paths,
                "display": f"{prefix}: {sel.level} — {display_name}{pin_str}",
            })

        self._refresh_rules_display()
        self.root.config(cursor="")
