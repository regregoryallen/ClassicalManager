"""Cleanup / Overlay tab: work review and overrides.

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


class CleanupTabMixin:
    def _build_cleanup_tab(self):
        """Build the Cleanup / Overlay tab."""
        ctk = self.ctk
        tab = self.tab_cleanup

        # Top bar: export/import overrides
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(top, text="Export Overrides JSON", width=180,
                      command=self._export_overrides).pack(side="left", padx=5)
        ctk.CTkButton(top, text="Import Overrides JSON", width=180,
                      command=self._import_overrides).pack(side="left", padx=5)
        ctk.CTkButton(top, text="?", width=28, height=28,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: self._show_help("cleanup"),
                      ).pack(side="right", padx=5)

        # Works browser with source filter + search
        filter_frame = ctk.CTkFrame(tab, fg_color="transparent")
        filter_frame.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(filter_frame, text="Works Browser",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            side="left", padx=5)
        ctk.CTkButton(filter_frame, text="+", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.works_tree, True)
                      ).pack(side="left", padx=(6, 0))
        ctk.CTkButton(filter_frame, text="\u2013", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.works_tree, False)
                      ).pack(side="left")

        self._cleanup_search_var = tk.StringVar()
        self._cleanup_search_var.trace_add("write", lambda *_: self._debounce_cleanup_search())
        self.cleanup_search = ctk.CTkEntry(filter_frame, width=200,
                                           placeholder_text="Search works...",
                                           textvariable=self._cleanup_search_var)
        self.cleanup_search.pack(side="right", padx=5)
        self._cleanup_search_after = None

        self.cleanup_hide_single = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(filter_frame, text="Hide 1-track",
                        variable=self.cleanup_hide_single,
                        command=self._refresh_works_list,
                        width=20).pack(side="right", padx=5)

        _SOURCE_OPTIONS = ["Heuristic", "Standalone", "All Works",
                           "Override", "MB Work ID", "Work Tag"]
        self.cleanup_source_var = tk.StringVar(value="Heuristic")
        self.cleanup_source_menu = ctk.CTkOptionMenu(
            filter_frame, variable=self.cleanup_source_var,
            values=_SOURCE_OPTIONS, width=140,
            command=lambda _: self._refresh_works_list())
        self.cleanup_source_menu.pack(side="right", padx=5)
        ctk.CTkLabel(filter_frame, text="Source:").pack(side="right", padx=(5, 0))

        self.works_tree = ttk.Treeview(
            tab, columns=("source", "album", "tracks", "composer"),
            show="tree headings", selectmode="extended", height=10)
        self.works_tree.heading("#0", text="Name")
        self.works_tree.heading("source", text="Source")
        self.works_tree.heading("album", text="Album")
        self.works_tree.heading("tracks", text="Tracks")
        self.works_tree.heading("composer", text="Composer")
        self.works_tree.column("#0", width=300)
        self.works_tree.column("source", width=80)
        self.works_tree.column("album", width=200)
        self.works_tree.column("tracks", width=60, anchor="center")
        self.works_tree.column("composer", width=150)
        self.works_tree.pack(fill="both", expand=True, padx=10, pady=5)

        w_scroll = ttk.Scrollbar(self.works_tree, orient="vertical",
                                 command=self.works_tree.yview)
        self.works_tree.configure(yscrollcommand=w_scroll.set)
        w_scroll.pack(side="right", fill="y")
        self.works_tree.bind("<Button-3>", self._cleanup_work_context_menu)
        self._setup_tree_sort(self.works_tree)

        self._cleanup_work_map = {}  # iid → work.id (work-level items only)
        self._cleanup_track_map = {}  # iid → track.id (track-level children)

        # Edit section
        edit_frame = ctk.CTkFrame(tab)
        edit_frame.pack(fill="x", padx=10, pady=10)

        edit_top = ctk.CTkFrame(edit_frame, fg_color="transparent")
        edit_top.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(edit_top, text="Edit Selected Work",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=0)
        ctk.CTkButton(edit_top, text="Show Album", width=110,
                      command=self._show_album_for_selected).pack(
            side="right", padx=5)

        row_e1 = ctk.CTkFrame(edit_frame, fg_color="transparent")
        row_e1.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row_e1, text="Work Name:").pack(side="left", padx=5)
        self.edit_work_name = ctk.CTkEntry(row_e1, width=300)
        self.edit_work_name.pack(side="left", padx=5)
        ctk.CTkButton(row_e1, text="Set Work Name", width=120,
                      command=self._set_work_name_override).pack(side="left", padx=5)

        row_e2 = ctk.CTkFrame(edit_frame, fg_color="transparent")
        row_e2.pack(fill="x", padx=10, pady=3)
        ctk.CTkButton(row_e2, text="Make Standalone", width=120,
                      command=self._make_work_standalone).pack(side="left", padx=5)

        row_e3 = ctk.CTkFrame(edit_frame, fg_color="transparent")
        row_e3.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row_e3, text="Composer:").pack(side="left", padx=5)
        self.edit_composer = ctk.CTkEntry(row_e3, width=300)
        self.edit_composer.pack(side="left", padx=5)
        ctk.CTkButton(row_e3, text="Set Composer", width=120,
                      command=self._set_composer_override).pack(side="left", padx=5)

        # Overrides list
        ov_header = ctk.CTkFrame(tab, fg_color="transparent")
        ov_header.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(ov_header, text="Current Overrides",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            side="left", padx=5)
        self._overrides_search_var = tk.StringVar()
        self._overrides_search_var.trace_add("write", lambda *_: self._debounce_overrides_search())
        self.overrides_search = ctk.CTkEntry(ov_header, width=200,
                                             placeholder_text="Filter overrides...",
                                             textvariable=self._overrides_search_var)
        self.overrides_search.pack(side="right", padx=5)
        self._overrides_search_after = None

        self.overrides_tree = ttk.Treeview(
            tab, columns=("scope", "field", "value", "match"),
            show="headings", selectmode="browse", height=6)
        self.overrides_tree.heading("scope", text="Scope")
        self.overrides_tree.heading("field", text="Field")
        self.overrides_tree.heading("value", text="Value")
        self.overrides_tree.heading("match", text="Match")
        self.overrides_tree.column("scope", width=60)
        self.overrides_tree.column("field", width=130)
        self.overrides_tree.column("value", width=300)
        self.overrides_tree.column("match", width=300)
        self.overrides_tree.pack(fill="both", expand=True, padx=10, pady=5)
        self._setup_tree_sort(self.overrides_tree)
        self._override_id_map = {}

        del_btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        del_btn_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(del_btn_frame, text="Delete Override", width=140,
                      command=self._delete_override).pack(side="left", padx=5)

    def _debounce_cleanup_search(self):
        """Debounce live search on the cleanup works tree."""
        if self._cleanup_search_after:
            self.root.after_cancel(self._cleanup_search_after)
        self._cleanup_search_after = self.root.after(250, self._refresh_works_list)

    def _debounce_overrides_search(self):
        """Debounce live search on the overrides list."""
        if self._overrides_search_after:
            self.root.after_cancel(self._overrides_search_after)
        self._overrides_search_after = self.root.after(250, self._refresh_overrides_list)

    def _refresh_cleanup(self):
        """Reload works list and overrides."""
        self._refresh_works_list()
        self._refresh_overrides_list()

    def _refresh_works_list(self):
        """Reload the works treeview based on source filter and search."""
        # Every data-changing cleanup action (overrides, work renames,
        # redetect) funnels through here — drop the builder's cached
        # library index so its next rebuild sees the changes (V3 Phase 4).
        self._invalidate_library_index()
        self._clear_tree_sort(self.works_tree)
        self.works_tree.delete(*self.works_tree.get_children())
        self._cleanup_work_map.clear()
        self._cleanup_track_map.clear()

        if not self.active_library:
            return

        from music_manager.core.database import Work, Album, Track

        source_label = self.cleanup_source_var.get()
        source_map = {
            "Heuristic": "heuristic",
            "Standalone": "standalone",
            "Override": "override",
            "MB Work ID": "mb_workid",
            "Work Tag": "work_tag",
        }

        query = (Work.select(Work, Album)
                 .join(Album)
                 .where(Album.library == self.active_library))

        if source_label in source_map:
            query = query.where(Work.work_source == source_map[source_label])

        query = query.order_by(Album.title, Work.work_name)

        search = self.cleanup_search.get().strip().lower()
        hide_single = self.cleanup_hide_single.get()

        for work in query:
            tracks = list(Track.select().where(Track.work == work)
                          .order_by(Track.disc_number, Track.track_number))

            if hide_single and len(tracks) <= 1:
                continue

            composer = tracks[0].composer.name if tracks and tracks[0].composer_id else ""

            if search:
                haystack = f"{work.work_name} {work.album.title} {composer}".lower()
                if search not in haystack:
                    continue

            work_iid = self.works_tree.insert(
                "", "end", text=work.work_name,
                values=(work.work_source, work.album.title, len(tracks), composer))
            self._cleanup_work_map[work_iid] = work.id

            for t in tracks:
                dur_s = (t.duration_ms or 0) // 1000
                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                track_iid = self.works_tree.insert(
                    work_iid, "end",
                    text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
                    values=("", "", dur_str, ""))
                self._cleanup_track_map[track_iid] = t.id

    def _refresh_overrides_list(self):
        """Reload the overrides treeview with optional search filter."""
        self._clear_tree_sort(self.overrides_tree)
        self.overrides_tree.delete(*self.overrides_tree.get_children())
        self._override_id_map.clear()

        if not self.active_library:
            return

        from music_manager.core.database import Override

        search = self.overrides_search.get().strip().lower() if hasattr(self, "overrides_search") else ""

        for ov in Override.select().where(Override.library == self.active_library):
            match = ov.match_mb_id or ov.match_relative_path or ""
            if search:
                haystack = f"{ov.scope} {ov.field} {ov.value} {match}".lower()
                if search not in haystack:
                    continue
            iid = self.overrides_tree.insert("", "end", values=(
                ov.scope, ov.field, ov.value, match
            ))
            self._override_id_map[iid] = ov.id

    def _get_selected_cleanup_work(self):
        """Get the work ID of the first selected work (or its parent if a track is selected)."""
        sel = self.works_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select a work first.")
            return None
        iid = sel[0]
        if iid not in self._cleanup_work_map:
            parent = self.works_tree.parent(iid)
            if parent:
                iid = parent
        return self._cleanup_work_map.get(iid)

    def _get_selected_cleanup_works(self):
        """Get work IDs for all selected items (resolving tracks to their parent works)."""
        sel = self.works_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select one or more works first.")
            return []
        work_ids = []
        seen = set()
        for iid in sel:
            if iid not in self._cleanup_work_map:
                parent = self.works_tree.parent(iid)
                if parent:
                    iid = parent
            wid = self._cleanup_work_map.get(iid)
            if wid and wid not in seen:
                work_ids.append(wid)
                seen.add(wid)
        return work_ids

    def _cleanup_work_context_menu(self, event):
        """Right-click context menu on the works tree."""
        iid = self.works_tree.identify_row(event.y)
        if not iid:
            return
        # Add to selection if not already selected (preserve multi-select)
        if iid not in self.works_tree.selection():
            self.works_tree.selection_set(iid)

        # Check if clicked item is a track child
        track_id = self._cleanup_track_map.get(iid)

        # Resolve clicked item to work level
        click_iid = iid
        if click_iid not in self._cleanup_work_map:
            parent = self.works_tree.parent(click_iid)
            if parent:
                click_iid = parent
        work_id = self._cleanup_work_map.get(click_iid)
        if not work_id:
            return

        from music_manager.core.database import Work
        work = Work.get_by_id(work_id)

        menu = tk.Menu(self.root, tearoff=0)
        if track_id:
            menu.add_command(label="Play",
                             command=lambda: self._play_track(track_id))
            menu.add_separator()
        menu.add_command(label="Details...",
                         command=lambda: self._show_work_details(work_id))
        menu.add_command(label="Show Album",
                         command=lambda: self._show_album_popup(work.album_id))
        menu.add_separator()
        menu.add_command(label="Set Work Name...",
                         command=lambda: self.edit_work_name.focus_set())
        menu.add_command(label="Set Group Key...",
                         command=lambda: self.edit_group_key.focus_set())
        menu.add_command(label="Set Composer...",
                         command=lambda: self.edit_composer.focus_set())
        menu.add_separator()
        menu.add_command(label="Make Standalone",
                         command=self._make_work_standalone)
        menu.tk_popup(event.x_root, event.y_root)

    def _show_album_for_selected(self):
        """Open the Show Album popup for the album containing the selected work."""
        work_id = self._get_selected_cleanup_work()
        if not work_id:
            return
        from music_manager.core.database import Work
        work = Work.get_by_id(work_id)
        self._show_album_popup(work.album_id)

    def _show_work_details(self, work_id):
        """Show a details popup for a work and its tracks."""
        from music_manager.core.database import Work, Track, Album
        ctk = self.ctk

        work = Work.get_by_id(work_id)
        album = work.album
        tracks = list(Track.select().where(Track.work == work)
                      .order_by(Track.disc_number, Track.track_number))
        composer_name = work.composer.name if work.composer_id else ""

        from music_manager.core.similarity import TrackAnalysis
        volatility_by_track = {
            ta.track_id: ta.volatility for ta in
            TrackAnalysis.select(TrackAnalysis.track, TrackAnalysis.volatility)
            .where(TrackAnalysis.track.in_([t.id for t in tracks]))
        }

        popup = tk.Toplevel(self.root)
        popup.title(f"Details: {work.work_name}")
        popup.transient(self.root)
        self._center_on_main(popup, 750, 500)
        popup.wait_visibility()
        popup.grab_set()

        # Scrollable text widget with all details
        text = tk.Text(popup, wrap="word", font=("monospace", 10),
                       bg="#2b2b2b", fg="#dcdcdc", insertbackground="#dcdcdc",
                       selectbackground="#4a6984", padx=10, pady=10)
        text.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        scroll = ttk.Scrollbar(text, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        def _add(label, value):
            text.insert("end", f"{label}: ", "label")
            text.insert("end", f"{value}\n")

        text.tag_configure("label", foreground="#88aacc", font=("monospace", 10, "bold"))
        text.tag_configure("heading", foreground="#ccddaa", font=("monospace", 11, "bold"))
        text.tag_configure("sep", foreground="#555555")

        text.insert("end", "WORK\n", "heading")
        _add("  Name", work.work_name)
        _add("  Source", work.work_source)
        _add("  Composer", composer_name)
        _add("  Sequence", work.work_sequence)
        _add("  MB Work ID", work.musicbrainz_work_id or "")
        _add("  Album", album.title)
        _add("  Album Artist", album.album_artist or "")
        _add("  Album Key", album.album_key)

        text.insert("end", f"\nTRACKS ({len(tracks)})\n", "heading")
        for t in tracks:
            dur_s = (t.duration_ms or 0) // 1000
            dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
            t_composer = t.composer.name if t.composer_id else ""
            text.insert("end", "-" * 60 + "\n", "sep")
            _add(f"  {t.disc_number}-{t.track_number:02d}", t.title)
            _add("    Composer", t_composer)
            _add("    Duration", dur_str)
            _add("    Path", t.relative_path)
            _add("    MB Recording", t.musicbrainz_recording_id or "")
            if t.movement_number is not None:
                _add("    Movement #", t.movement_number)
            volatility = volatility_by_track.get(t.id)
            _add("    Volatility", f"{volatility:.3f}" if volatility is not None
                 else "not analyzed")

        text.configure(state="disabled")

        # Bottom buttons
        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(btn_frame, text="Copy Work Name", width=130,
                      command=lambda: (self.root.clipboard_clear(),
                                       self.root.clipboard_append(work.work_name))
                      ).pack(side="left", padx=5)
        if work.musicbrainz_work_id:
            ctk.CTkButton(btn_frame, text="Copy MB Work ID", width=130,
                          command=lambda: (self.root.clipboard_clear(),
                                           self.root.clipboard_append(
                                               work.musicbrainz_work_id))
                          ).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Close", width=80,
                      command=popup.destroy).pack(side="right", padx=5)

    def _show_album_popup(self, album_id):
        """Open a popup showing all works and tracks in an album for editing."""
        from music_manager.core.database import Album, Work, Track
        from music_manager.core.overrides import set_override

        album = Album.get_by_id(album_id)
        ctk = self.ctk

        popup = tk.Toplevel(self.root)
        popup.title(f"Album: {album.title}")
        popup.transient(self.root)
        self._center_on_main(popup, 1100, 750)
        popup.wait_visibility()
        popup.grab_set()

        # --- Album header edit fields ---
        header = ctk.CTkFrame(popup)
        header.pack(fill="x", padx=10, pady=(10, 5))

        for row_idx, (label, field, current_val, scope_field) in enumerate([
            ("Album Title:", "album_title", album.title, "album_title"),
            ("Album Artist:", "album_artist", album.album_artist or "", "album_artist"),
            ("Year:", "year", str(album.year) if album.year else "", "year"),
        ]):
            row = ctk.CTkFrame(header, fg_color="transparent")
            row.pack(fill="x", padx=5, pady=2)
            ctk.CTkLabel(row, text=label, width=100, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(row, width=350)
            entry.insert(0, current_val)
            entry.pack(side="left", padx=5)

            def _make_album_setter(ent, sf, alb):
                def _set():
                    val = ent.get().strip()
                    if not val:
                        return
                    set_override(
                        library=self.active_library, scope="album",
                        field=sf, value=val,
                        match_relative_path=alb.album_key,
                        match_mb_id=alb.musicbrainz_album_id,
                    )
                    if sf == "album_title":
                        alb.title = val
                    elif sf == "album_artist":
                        alb.album_artist = val
                    elif sf == "year":
                        alb.year = int(val) if val.isdigit() else None
                    alb.save()
                    messagebox.showinfo("Done", f"Set {sf} to '{val}'.",
                                        parent=popup)
                    self._refresh_overrides_list()
                return _set

            ctk.CTkButton(row, text="Set", width=60,
                          command=_make_album_setter(entry, scope_field, album)
                          ).pack(side="left", padx=5)

        # --- Works/Tracks treeview ---
        tree_frame = ctk.CTkFrame(popup, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

        album_tree = ttk.Treeview(
            tree_frame, columns=("source", "composer", "detail"),
            show="tree headings", selectmode="extended", height=15)
        album_tree.heading("#0", text="Name")
        album_tree.heading("source", text="Source")
        album_tree.heading("composer", text="Composer")
        album_tree.heading("detail", text="Tracks/Duration")
        album_tree.column("#0", width=400)
        album_tree.column("source", width=80)
        album_tree.column("composer", width=150)
        album_tree.column("detail", width=80, anchor="center")
        album_tree.pack(side="left", fill="both", expand=True)

        a_scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                                 command=album_tree.yview)
        album_tree.configure(yscrollcommand=a_scroll.set)
        a_scroll.pack(side="right", fill="y")

        # Track map for resolving selections
        popup_track_map = {}  # iid → ("work", work_id) or ("track", track_id)

        works = Work.select().where(Work.album == album).order_by(Work.work_sequence)
        for work in works:
            tracks = list(Track.select().where(Track.work == work)
                          .order_by(Track.disc_number, Track.track_number))
            composer = tracks[0].composer.name if tracks and tracks[0].composer_id else ""
            work_iid = album_tree.insert(
                "", "end", text=work.work_name,
                values=(work.work_source, composer, f"{len(tracks)} tracks"))
            popup_track_map[work_iid] = ("work", work.id)

            for t in tracks:
                dur_s = (t.duration_ms or 0) // 1000
                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                t_iid = album_tree.insert(
                    work_iid, "end",
                    text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
                    values=("", t.composer.name if t.composer_id else "", dur_str))
                popup_track_map[t_iid] = ("track", t.id)

        # Selection info
        sel_label = ctk.CTkLabel(popup, text="No tracks selected",
                                 font=ctk.CTkFont(size=11))
        sel_label.pack(padx=10, pady=(5, 0), anchor="w")

        def _update_selection_label(event=None):
            tracks = _resolve_selected_tracks()
            sel_label.configure(text=f"{len(tracks)} track(s) selected")

        album_tree.bind("<<TreeviewSelect>>", _update_selection_label)

        def _album_popup_context_menu(event):
            iid = album_tree.identify_row(event.y)
            if not iid:
                return
            if iid not in album_tree.selection():
                album_tree.selection_set(iid)
            entry = popup_track_map.get(iid)
            if not entry:
                return
            level, eid = entry
            if level == "track":
                menu = tk.Menu(popup, tearoff=0)
                menu.add_command(label="Play",
                                 command=lambda: self._play_track(eid))
                menu.tk_popup(event.x_root, event.y_root)

        album_tree.bind("<Button-3>", _album_popup_context_menu)

        def _resolve_selected_tracks():
            """Resolve selected treeview items to a list of Track objects."""
            sel = album_tree.selection()
            track_ids = set()
            for iid in sel:
                entry = popup_track_map.get(iid)
                if not entry:
                    continue
                level, eid = entry
                if level == "track":
                    track_ids.add(eid)
                elif level == "work":
                    for t in Track.select(Track.id).where(Track.work == eid):
                        track_ids.add(t.id)
            return list(Track.select().where(Track.id.in_(list(track_ids)))
                        ) if track_ids else []

        # --- Action buttons ---
        action_frame = ctk.CTkFrame(popup)
        action_frame.pack(fill="x", padx=10, pady=5)

        # Group Key
        # Work Name
        row_w = ctk.CTkFrame(action_frame, fg_color="transparent")
        row_w.pack(fill="x", padx=5, pady=3)
        ctk.CTkLabel(row_w, text="Work Name:").pack(side="left", padx=5)
        popup_work_name = ctk.CTkEntry(row_w, width=280)
        popup_work_name.pack(side="left", padx=5)

        def _set_work_name():
            name = popup_work_name.get().strip()
            if not name:
                messagebox.showwarning("Empty", "Enter a work name.",
                                       parent=popup)
                return
            tracks = _resolve_selected_tracks()
            if not tracks:
                messagebox.showwarning("Select", "Select tracks first.",
                                       parent=popup)
                return
            work_ids_updated = set()
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track",
                    field="work_name", value=name,
                    match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
                if t.work_id:
                    work_ids_updated.add(t.work_id)
            for wid in work_ids_updated:
                w = Work.get_by_id(wid)
                w.work_name = name
                w.save()
            messagebox.showinfo(
                "Done",
                f"Set work name to '{name}' for {len(tracks)} track(s).",
                parent=popup)
            self._refresh_overrides_list()
            self._refresh_works_list()
            # Refresh the popup tree
            _refresh_popup_tree()

        ctk.CTkButton(row_w, text="Set for Selected", width=130,
                      command=_set_work_name).pack(side="left", padx=5)

        def _make_standalone():
            tracks = _resolve_selected_tracks()
            if not tracks:
                messagebox.showwarning("Select", "Select tracks first.",
                                       parent=popup)
                return
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track",
                    field="work_name", value="__standalone__",
                    match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
            messagebox.showinfo(
                "Done",
                f"Marked {len(tracks)} track(s) as standalone.\n"
                f"Re-detect Works or Rescan to apply.",
                parent=popup)
            self._refresh_overrides_list()

        ctk.CTkButton(row_w, text="Make Standalone", width=130,
                      command=_make_standalone).pack(side="left", padx=5)

        # Composer
        row_c = ctk.CTkFrame(action_frame, fg_color="transparent")
        row_c.pack(fill="x", padx=5, pady=3)
        ctk.CTkLabel(row_c, text="Composer:").pack(side="left", padx=5)
        popup_composer = ctk.CTkEntry(row_c, width=280)
        popup_composer.pack(side="left", padx=5)

        def _set_composer():
            comp = popup_composer.get().strip()
            if not comp:
                messagebox.showwarning("Empty", "Enter a composer name.",
                                       parent=popup)
                return
            tracks = _resolve_selected_tracks()
            if not tracks:
                messagebox.showwarning("Select", "Select tracks first.",
                                       parent=popup)
                return
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track",
                    field="composer", value=comp,
                    match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
            messagebox.showinfo(
                "Done",
                f"Set composer to '{comp}' for {len(tracks)} track(s).\n"
                f"Rescan or apply overrides to update.",
                parent=popup)
            self._refresh_overrides_list()

        ctk.CTkButton(row_c, text="Set for Selected", width=130,
                      command=_set_composer).pack(side="left", padx=5)

        def _refresh_popup_tree():
            """Reload the popup treeview after changes."""
            album_tree.delete(*album_tree.get_children())
            popup_track_map.clear()
            for work in Work.select().where(Work.album == album).order_by(Work.work_sequence):
                tracks = list(Track.select().where(Track.work == work)
                              .order_by(Track.disc_number, Track.track_number))
                composer = tracks[0].composer.name if tracks and tracks[0].composer_id else ""
                w_iid = album_tree.insert(
                    "", "end", text=work.work_name,
                    values=(work.work_source, composer, f"{len(tracks)} tracks"))
                popup_track_map[w_iid] = ("work", work.id)
                for t in tracks:
                    dur_s = (t.duration_ms or 0) // 1000
                    dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                    t_iid = album_tree.insert(
                        w_iid, "end",
                        text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
                        values=("", t.composer.name if t.composer_id else "", dur_str))
                    popup_track_map[t_iid] = ("track", t.id)
            sel_label.configure(text="No tracks selected")

        # Bottom bar
        ctk.CTkButton(popup, text="Close", width=80,
                      command=popup.destroy).pack(pady=(0, 10))

    def _set_work_name_override(self):
        """Set a work_name override for all selected works' tracks."""
        work_ids = self._get_selected_cleanup_works()
        if not work_ids:
            return
        new_name = self.edit_work_name.get().strip()
        if not new_name:
            messagebox.showwarning("Empty", "Enter a work name.")
            return

        from music_manager.core.database import Work, Track
        from music_manager.core.overrides import set_override

        total = 0
        for work_id in work_ids:
            work = Work.get_by_id(work_id)
            tracks = list(Track.select().where(Track.work == work))
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track", field="work_name",
                    value=new_name, match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
            work.work_name = new_name
            work.save()
            total += len(tracks)

        messagebox.showinfo("Done", f"Set work name to '{new_name}' "
                           f"for {total} tracks across {len(work_ids)} work(s).")
        self._refresh_cleanup()
        self._refresh_explorer()

    def _make_work_standalone(self):
        """Set __standalone__ work name for all tracks in all selected works."""
        work_ids = self._get_selected_cleanup_works()
        if not work_ids:
            return

        from music_manager.core.database import Work, Track
        from music_manager.core.overrides import set_override

        total = 0
        for work_id in work_ids:
            work = Work.get_by_id(work_id)
            tracks = list(Track.select().where(Track.work == work))
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track", field="work_name",
                    value="__standalone__", match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
            total += len(tracks)

        messagebox.showinfo("Done", f"Marked {total} tracks across "
                           f"{len(work_ids)} work(s) as standalone. "
                           f"Re-detect or rescan to apply.")
        self._refresh_cleanup()

    def _set_composer_override(self):
        """Set a composer override for all selected works' tracks."""
        work_ids = self._get_selected_cleanup_works()
        if not work_ids:
            return
        composer_name = self.edit_composer.get().strip()
        if not composer_name:
            messagebox.showwarning("Empty", "Enter a composer name.")
            return

        from music_manager.core.database import Work, Track
        from music_manager.core.overrides import set_override

        total = 0
        for work_id in work_ids:
            work = Work.get_by_id(work_id)
            tracks = list(Track.select().where(Track.work == work))
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track", field="composer",
                    value=composer_name, match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
            total += len(tracks)

        messagebox.showinfo("Done", f"Set composer to '{composer_name}' "
                           f"for {total} tracks across {len(work_ids)} work(s). "
                           f"Rescan or apply overrides to update.")
        self._refresh_cleanup()

    def _delete_override(self):
        """Delete the selected override."""
        sel = self.overrides_tree.selection()
        if not sel:
            return
        ov_id = self._override_id_map.get(sel[0])
        if not ov_id:
            return

        from music_manager.core.overrides import delete_override
        if delete_override(ov_id):
            self._refresh_overrides_list()

    def _export_overrides(self):
        """Export overrides to a JSON file."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        initial_dir = self._prefs.get("last_export_dir", "")
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=initial_dir or None,
            title="Export Overrides",
            parent=self.root,
        )
        if not path:
            return
        self._prefs["last_export_dir"] = str(Path(path).parent)
        _save_prefs(self._prefs)

        from music_manager.core.overrides import export_overrides
        count = export_overrides(self.active_library, Path(path))
        messagebox.showinfo("Export", f"Exported {count} overrides to:\n{path}")

    def _import_overrides(self):
        """Import overrides from a JSON file."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        initial_dir = self._prefs.get("last_export_dir", "")
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")],
            initialdir=initial_dir or None,
            title="Import Overrides",
            parent=self.root,
        )
        if not path:
            return
        self._prefs["last_export_dir"] = str(Path(path).parent)
        _save_prefs(self._prefs)

        from music_manager.core.overrides import import_overrides, apply_overrides
        counts = import_overrides(self.active_library, Path(path))
        apply_overrides(self.active_library)
        messagebox.showinfo("Import",
                           f"Imported: {counts['imported']} new, "
                           f"{counts['updated']} updated, "
                           f"{counts['errors']} errors.\n"
                           f"Overrides applied.")
        self._refresh_cleanup()
        self._refresh_metrics()
