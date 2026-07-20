"""Explorer & Rules tab (retired in Phase 5).

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


class ExplorerTabMixin:
    def _build_explorer_tab(self):
        """Build the Explorer & Rules tab with album/work treeviews."""
        ctk = self.ctk
        tab = self.tab_explorer

        # Search bar
        search_frame = ctk.CTkFrame(tab, fg_color="transparent")
        search_frame.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(search_frame, text="Filter:").pack(side="left", padx=5)
        self._explorer_search_var = tk.StringVar()
        self._explorer_search_var.trace_add("write", lambda *_: self._debounce_explorer_search())
        self.explorer_search = ctk.CTkEntry(search_frame, width=300,
                                            placeholder_text="Filter albums and works...",
                                            textvariable=self._explorer_search_var)
        self.explorer_search.pack(side="left", padx=5)
        ctk.CTkButton(search_frame, text="?", width=28, height=28,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: self._show_help("explorer"),
                      ).pack(side="right", padx=5)
        self._explorer_search_after = None

        # Paned view: albums left, works/tracks right
        pane = ctk.CTkFrame(tab, fg_color="transparent")
        pane.pack(fill="both", expand=True, padx=5, pady=5)

        # Albums tree
        left = ctk.CTkFrame(pane)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        ctk.CTkLabel(left, text="Albums",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=5)
        self.album_tree = ttk.Treeview(left, columns=("artist", "genre", "year", "tracks"),
                                       show="headings", selectmode="browse")
        self.album_tree.heading("artist", text="Album")
        self.album_tree.heading("genre", text="Genre")
        self.album_tree.heading("year", text="Year")
        self.album_tree.heading("tracks", text="Tracks")
        self.album_tree.column("artist", width=260)
        self.album_tree.column("genre", width=100)
        self.album_tree.column("year", width=60, anchor="center")
        self.album_tree.column("tracks", width=60, anchor="center")
        self.album_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.album_tree.bind("<<TreeviewSelect>>", self._on_album_selected)
        self.album_tree.bind("<Button-3>", self._album_context_menu)
        self._setup_tree_sort(self.album_tree)

        # Works/Tracks tree
        right = ctk.CTkFrame(pane)
        right.pack(side="right", fill="both", expand=True, padx=(5, 0))
        ctk.CTkLabel(right, text="Works & Tracks",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=5)
        self.work_tree = ttk.Treeview(right, columns=("source", "composer", "movements"),
                                      show="tree headings", selectmode="browse")
        self.work_tree.heading("#0", text="Name")
        self.work_tree.heading("source", text="Source")
        self.work_tree.heading("composer", text="Composer")
        self.work_tree.heading("movements", text="Tracks")
        self.work_tree.column("#0", width=300)
        self.work_tree.column("source", width=80)
        self.work_tree.column("composer", width=150)
        self.work_tree.column("movements", width=60, anchor="center")
        self.work_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.work_tree.bind("<Button-3>", self._work_context_menu)
        self._setup_tree_sort(self.work_tree)

        # Rules display
        rules_frame = ctk.CTkFrame(tab)
        rules_frame.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(rules_frame, text="Active Rules",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=10)
        self.rules_listbox = tk.Listbox(rules_frame, height=4,
                                        bg="#2b2b2b", fg="white",
                                        selectbackground="#1f6aa5",
                                        font=("Segoe UI", 10))
        self.rules_listbox.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        ctk.CTkButton(rules_frame, text="Remove", width=80,
                      command=self._remove_selection).pack(side="right", padx=5)

        # Store album_id map for treeview items
        self._album_iid_map = {}
        self._work_iid_map = {}

    def _refresh_explorer(self):
        """Reload album and work treeviews from the database."""
        self._clear_tree_sort(self.album_tree)
        self._clear_tree_sort(self.work_tree)
        self.album_tree.delete(*self.album_tree.get_children())
        self._album_iid_map.clear()

        if not self.active_library:
            return

        from music_manager.core.database import Album, Track

        search = self.explorer_search.get().strip().lower() if hasattr(self, 'explorer_search') else ""

        # Pre-compute per-album metadata for genre display and search
        album_genres = {}    # album_id → first non-empty genre
        album_search = {}    # album_id → set of lowercase searchable strings
        for t in Track.select().where(Track.library == self.active_library):
            aid = t.album_id
            if aid not in album_genres and t.genre:
                album_genres[aid] = t.genre
            meta = album_search.setdefault(aid, set())
            for val in (t.genre, t.performer, t.conductor, t.ensemble,
                        t.composer.name if t.composer_id else None):
                if val:
                    meta.add(val.lower())

        albums = Album.select().where(Album.library == self.active_library).order_by(Album.title)
        for album in albums:
            if search:
                if (search not in album.title.lower()
                        and search not in (album.album_artist or "").lower()
                        and not any(search in m for m in album_search.get(album.id, ()))):
                    continue
            track_count = Track.select().where(Track.album == album).count()
            genre = album_genres.get(album.id, "")
            iid = self.album_tree.insert("", "end", values=(
                album.title,
                genre,
                album.year or "",
                track_count,
            ))
            self._album_iid_map[iid] = album.id

        # Clear works tree
        self.work_tree.delete(*self.work_tree.get_children())
        self._work_iid_map.clear()

    def _on_album_selected(self, event):
        """When an album is selected, show its works and tracks."""
        sel = self.album_tree.selection()
        if not sel:
            return
        album_id = self._album_iid_map.get(sel[0])
        if not album_id:
            return

        self._clear_tree_sort(self.work_tree)
        self.work_tree.delete(*self.work_tree.get_children())
        self._work_iid_map.clear()

        from music_manager.core.database import Work, Track

        works = Work.select().where(Work.album == album_id).order_by(Work.work_sequence)
        for work in works:
            tracks = list(Track.select().where(Track.work == work).order_by(
                Track.disc_number, Track.track_number))
            composer_name = tracks[0].composer.name if tracks and tracks[0].composer_id else ""

            work_iid = self.work_tree.insert("", "end", text=work.work_name, values=(
                work.work_source,
                composer_name,
                len(tracks),
            ))
            self._work_iid_map[work_iid] = ("work", work.id)

            for t in tracks:
                t_iid = self.work_tree.insert(work_iid, "end", text=f"  {t.disc_number}-{t.track_number:02d}: {t.title}", values=(
                    "", t.composer.name if t.composer_id else "", ""
                ))
                self._work_iid_map[t_iid] = ("track", t.id)

    def _album_context_menu(self, event):
        """Right-click context menu on albums."""
        iid = self.album_tree.identify_row(event.y)
        if not iid:
            return
        self.album_tree.selection_set(iid)
        album_id = self._album_iid_map.get(iid)
        if not album_id:
            return

        from music_manager.core.database import Album
        from music_manager.core.selection import key_for_album
        album = Album.get_by_id(album_id)
        album_key = key_for_album(album)

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Include Album",
                         command=lambda: self._add_selection("album", album_key))
        menu.add_command(label="Exclude Album",
                         command=lambda: self._add_selection("album", album_key, excluded=True))
        menu.tk_popup(event.x_root, event.y_root)

    def _work_context_menu(self, event):
        """Right-click context menu on works/tracks."""
        iid = self.work_tree.identify_row(event.y)
        if not iid:
            return
        self.work_tree.selection_set(iid)
        entry = self._work_iid_map.get(iid)
        if not entry:
            return

        level, entity_id = entry
        from music_manager.core.selection import key_for_entity
        from music_manager.core.database import Work, Track
        menu = tk.Menu(self.root, tearoff=0)

        if level == "work":
            work = Work.get_by_id(entity_id)
            work_key = key_for_entity("work", work)
            menu.add_command(label="Include Work",
                             command=lambda: self._add_selection("work", work_key))
            menu.add_command(label="Exclude Work",
                             command=lambda: self._add_selection("work", work_key, excluded=True))
        elif level == "track":
            track = Track.get_by_id(entity_id)
            track_key = key_for_entity("track", track)
            menu.add_command(label="Play",
                             command=lambda: self._play_track(entity_id))
            menu.add_separator()
            menu.add_command(label="Include Track",
                             command=lambda: self._add_selection("track", track_key))
            menu.add_command(label="Exclude Track",
                             command=lambda: self._add_selection("track", track_key, excluded=True))

        menu.tk_popup(event.x_root, event.y_root)

    def _debounce_explorer_search(self):
        """Debounce live search on the explorer album list."""
        if self._explorer_search_after:
            self.root.after_cancel(self._explorer_search_after)
        self._explorer_search_after = self.root.after(250, self._refresh_explorer)
