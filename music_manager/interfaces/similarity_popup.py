"""Track Similarity Finder popup window.

Separate from gui.py to keep coupling minimal. Provides a UI for
selecting seed tracks, running bliss+librosa analysis, and browsing
similar tracks with tunable parameters.
"""

import json
import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

logger = logging.getLogger(__name__)


class SimilarityPopup:
    """Popup window for finding tracks similar to user-selected seeds."""

    def __init__(self, root, active_library, ctk, center_fn):
        self.root = root
        self.library = active_library
        self.ctk = ctk
        self._center = center_fn

        self.seed_tracks = {}  # track_id → {title, composer, album}
        self.results = []  # list of dicts from find_similar()
        self._cancel_flag = False

        self._build_window()

    def _build_window(self):
        ctk = self.ctk

        self.win = tk.Toplevel(self.root)
        self.win.title("Track Similarity Finder")
        self.win.transient(self.root)
        self._center(self.win, 1000, 620)
        self.win.wait_visibility()
        self.win.grab_set()

        # Main horizontal split
        main = ctk.CTkFrame(self.win)
        main.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        # ---- Left panel: Seeds + Parameters ----
        left = ctk.CTkFrame(main, width=340)
        left.pack(side="left", fill="y", padx=(0, 4))
        left.pack_propagate(False)

        ctk.CTkLabel(left, text="Seed Tracks",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=8, pady=(8, 4))

        self.seed_tree = ttk.Treeview(
            left, columns=("composer",), show="tree headings",
            selectmode="browse", height=8)
        self.seed_tree.heading("#0", text="Title")
        self.seed_tree.heading("composer", text="Composer")
        self.seed_tree.column("#0", width=180)
        self.seed_tree.column("composer", width=120)
        self.seed_tree.pack(fill="x", padx=8, pady=2)

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=2)
        ctk.CTkButton(btn_row, text="Add from library...", width=140,
                      command=self._open_track_picker).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_row, text="Remove", width=80,
                      command=self._remove_seed).pack(side="left")

        # Parameters
        ctk.CTkLabel(left, text="Parameters",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=8, pady=(12, 4))

        param_frame = ctk.CTkFrame(left, fg_color="transparent")
        param_frame.pack(fill="x", padx=8)

        ctk.CTkLabel(param_frame, text="Max results:").grid(
            row=0, column=0, sticky="w", pady=2)
        self.limit_var = tk.StringVar(value="50")
        ctk.CTkEntry(param_frame, textvariable=self.limit_var,
                     width=60).grid(row=0, column=1, sticky="w", padx=4, pady=2)

        ctk.CTkLabel(param_frame, text="Volatility max:").grid(
            row=1, column=0, sticky="w", pady=2)
        self.vol_var = tk.DoubleVar(value=1.0)
        self.vol_slider = ctk.CTkSlider(
            param_frame, from_=0.0, to=1.0, variable=self.vol_var,
            width=140, command=self._on_vol_change)
        self.vol_slider.grid(row=1, column=1, sticky="w", padx=4, pady=2)
        self.vol_label = ctk.CTkLabel(param_frame, text="Off")
        self.vol_label.grid(row=1, column=2, sticky="w")
        self.vol_enabled = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(param_frame, text="", variable=self.vol_enabled,
                        width=20, command=self._on_vol_toggle).grid(
            row=1, column=3, sticky="w")

        ctk.CTkLabel(param_frame, text="Blend:").grid(
            row=2, column=0, sticky="w", pady=2)
        self.blend_var = tk.DoubleVar(value=0.5)
        ctk.CTkSlider(param_frame, from_=0.0, to=1.0,
                      variable=self.blend_var, width=140).grid(
            row=2, column=1, sticky="w", padx=4, pady=2)
        blend_hint = ctk.CTkLabel(param_frame, text="nearest ↔ consensus",
                                  font=ctk.CTkFont(size=10))
        blend_hint.grid(row=2, column=2, columnspan=2, sticky="w")

        ctk.CTkButton(left, text="Find Similar",
                      command=self._find_similar).pack(
            padx=8, pady=(12, 4), fill="x")

        # ---- Right panel: Results ----
        right = ctk.CTkFrame(main)
        right.pack(side="right", fill="both", expand=True, padx=(4, 0))

        ctk.CTkLabel(right, text="Results",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=8, pady=(8, 4))

        self.result_tree = ttk.Treeview(
            right,
            columns=("composer", "album", "match", "agreement", "volatility"),
            show="tree headings", selectmode="extended")
        self.result_tree.heading("#0", text="Title")
        self.result_tree.heading("composer", text="Composer")
        self.result_tree.heading("album", text="Album")
        self.result_tree.heading("match", text="Match")
        self.result_tree.heading("agreement", text="Agreement")
        self.result_tree.heading("volatility", text="Volatility")
        self.result_tree.column("#0", width=220)
        self.result_tree.column("composer", width=140)
        self.result_tree.column("album", width=130)
        self.result_tree.column("match", width=60)
        self.result_tree.column("agreement", width=70)
        self.result_tree.column("volatility", width=70)
        self.result_tree.pack(fill="both", expand=True, padx=8, pady=2)
        self.result_tree.tag_configure("match_close", foreground="#2d7d46")
        self.result_tree.tag_configure("match_loose", foreground="#c98a1f")
        self.result_tree.tag_configure("match_weak", foreground="#a03a3a")

        # Scrollbar
        scroll = ttk.Scrollbar(right, orient="vertical",
                               command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=scroll.set)
        scroll.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne",
                     in_=self.result_tree)

        # Right-click to play
        self.result_tree.bind("<Button-3>", self._result_context_menu)
        self._result_track_map = {}  # iid → track_id

        result_btns = ctk.CTkFrame(right, fg_color="transparent")
        result_btns.pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(result_btns, text="Export M3U", width=100,
                      command=self._export_m3u).pack(side="left", padx=(0, 4))
        ctk.CTkButton(result_btns, text="Play", width=60,
                      command=self._play_selected).pack(side="left")

        # ---- Bottom: status + progress ----
        bottom = ctk.CTkFrame(self.win, fg_color="transparent")
        bottom.pack(fill="x", padx=8, pady=(4, 8))

        self.status_label = ctk.CTkLabel(bottom, text="Ready")
        self.status_label.pack(side="left", padx=4)

        self.progress = ctk.CTkProgressBar(bottom, width=300)
        self.progress.pack(side="left", padx=8)
        self.progress.set(0)

        self.cancel_btn = ctk.CTkButton(bottom, text="Cancel", width=60,
                                        command=self._cancel_analysis,
                                        state="disabled")
        self.cancel_btn.pack(side="left", padx=4)

        ctk.CTkButton(bottom, text="Close", width=60,
                      command=self.win.destroy).pack(side="right", padx=4)

    # ------------------------------------------------------------------
    # Seed track management
    # ------------------------------------------------------------------

    def _open_track_picker(self):
        """Open a mini library browser to select seed tracks."""
        ctk = self.ctk
        from music_manager.core.database import Album, Work, Track

        picker = tk.Toplevel(self.win)
        picker.title("Select Seed Tracks")
        picker.transient(self.win)
        self._center(picker, 700, 500)
        picker.wait_visibility()
        picker.grab_set()

        # Album list on left, works/tracks on right
        pane = ctk.CTkFrame(picker)
        pane.pack(fill="both", expand=True, padx=8, pady=8)

        left = ctk.CTkFrame(pane)
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        ctk.CTkLabel(left, text="Albums",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", padx=4)

        album_tree = ttk.Treeview(left, columns=("year",),
                                  show="tree headings", selectmode="browse")
        album_tree.heading("#0", text="Album")
        album_tree.heading("year", text="Year")
        album_tree.column("#0", width=250)
        album_tree.column("year", width=50)
        album_tree.pack(fill="both", expand=True, padx=4, pady=2)

        right = ctk.CTkFrame(pane)
        right.pack(side="right", fill="both", expand=True, padx=(4, 0))
        ctk.CTkLabel(right, text="Works & Tracks",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", padx=4)

        track_tree = ttk.Treeview(
            right, columns=("composer",),
            show="tree headings", selectmode="extended")
        track_tree.heading("#0", text="Name")
        track_tree.heading("composer", text="Composer")
        track_tree.column("#0", width=280)
        track_tree.column("composer", width=120)
        track_tree.pack(fill="both", expand=True, padx=4, pady=2)

        album_map = {}  # iid → album_id
        track_map = {}  # iid → (type, id)

        # Populate albums
        albums = (Album.select()
                  .where(Album.library == self.library)
                  .order_by(Album.title))
        for album in albums:
            iid = album_tree.insert("", "end", text=album.title,
                                    values=(album.year or "",))
            album_map[iid] = album.id

        def on_album_select(event):
            sel = album_tree.selection()
            if not sel:
                return
            aid = album_map.get(sel[0])
            if not aid:
                return
            track_tree.delete(*track_tree.get_children())
            track_map.clear()

            works = Work.select().where(Work.album == aid).order_by(
                Work.work_sequence)
            for work in works:
                tracks = list(Track.select().where(Track.work == work).order_by(
                    Track.disc_number, Track.track_number))
                composer = (tracks[0].composer.name
                            if tracks and tracks[0].composer_id else "")
                w_iid = track_tree.insert(
                    "", "end", text=work.work_name,
                    values=(composer,))
                track_map[w_iid] = ("work", work.id)

                for t in tracks:
                    t_iid = track_tree.insert(
                        w_iid, "end",
                        text=f"  {t.disc_number}-{t.track_number:02d}: {t.title}",
                        values=(t.composer.name if t.composer_id else "",))
                    track_map[t_iid] = ("track", t.id)

        album_tree.bind("<<TreeviewSelect>>", on_album_select)

        def add_selected():
            for iid in track_tree.selection():
                entry = track_map.get(iid)
                if not entry:
                    continue
                level, eid = entry
                if level == "track":
                    track = Track.get_by_id(eid)
                    self._add_seed(track)
                elif level == "work":
                    # Add all tracks in the work
                    tracks = Track.select().where(Track.work == eid)
                    for t in tracks:
                        self._add_seed(t)

        btn_row = ctk.CTkFrame(picker, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(btn_row, text="Add Selected", width=120,
                      command=add_selected).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Close", width=80,
                      command=picker.destroy).pack(side="right", padx=4)

    def _add_seed(self, track):
        """Add a track to the seed list (dedup by track_id)."""
        if track.id in self.seed_tracks:
            return
        composer = track.composer.name if track.composer_id else ""
        self.seed_tracks[track.id] = {
            "title": track.title,
            "composer": composer,
            "album": track.album.title if track.album_id else "",
        }
        self.seed_tree.insert("", "end", iid=str(track.id),
                              text=track.title, values=(composer,))

    def _remove_seed(self):
        sel = self.seed_tree.selection()
        for iid in sel:
            tid = int(iid)
            self.seed_tracks.pop(tid, None)
            self.seed_tree.delete(iid)

    # ------------------------------------------------------------------
    # Analysis & search
    # ------------------------------------------------------------------

    def _find_similar(self):
        """Run similarity search, analyzing un-analyzed tracks first."""
        if not self.seed_tracks:
            messagebox.showwarning("No Seeds",
                                   "Add at least one seed track first.",
                                   parent=self.win)
            return

        try:
            limit = int(self.limit_var.get())
        except ValueError:
            limit = 50

        vol_max = self.vol_var.get() if self.vol_enabled.get() else None
        blend = self.blend_var.get()
        seed_ids = list(self.seed_tracks.keys())

        # Check if analysis needed (including stale feature versions)
        from music_manager.core.similarity import (
            TrackAnalysis, Track, FEATURE_VERSION)
        current = set(
            ta.track_id for ta in
            TrackAnalysis.select(TrackAnalysis.track)
            .join(Track)
            .where((Track.library == self.library) &
                   (TrackAnalysis.feature_version == FEATURE_VERSION))
        )
        total_tracks = Track.select().where(
            Track.library == self.library).count()
        unanalyzed = total_tracks - len(current)

        if unanalyzed > 0:
            if not messagebox.askyesno(
                "Analysis Required",
                f"{unanalyzed} tracks need analysis.\n"
                f"This may take a while. Proceed?",
                parent=self.win,
            ):
                return
            self._run_analysis_then_search(seed_ids, limit, vol_max, blend)
        else:
            self._do_search(seed_ids, limit, vol_max, blend)

    def _run_analysis_then_search(self, seed_ids, limit, vol_max, blend):
        """Run analysis in a background thread, then search."""
        self._cancel_flag = False
        self.cancel_btn.configure(state="normal")
        self.status_label.configure(text="Analyzing...")

        def worker():
            from music_manager.core.similarity import (
                analyze_library, AnalysisCancelled)

            def progress(current, total, msg):
                if self._cancel_flag:
                    raise AnalysisCancelled()
                self.win.after(0, self._update_progress, current, total, msg)

            stats = analyze_library(self.library,
                                    progress_callback=progress)
            self.win.after(0, self._analysis_done, stats,
                           seed_ids, limit, vol_max, blend)

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, current, total, msg):
        if total > 0:
            self.progress.set(current / total)
        title = msg[:40] + "..." if len(msg) > 40 else msg
        self.status_label.configure(text=f"Analyzing {current}/{total}: {title}")

    def _cancel_analysis(self):
        self._cancel_flag = True
        self.status_label.configure(text="Cancelling...")

    def _analysis_done(self, stats, seed_ids, limit, vol_max, blend):
        self.cancel_btn.configure(state="disabled")
        self.progress.set(0)
        self.status_label.configure(
            text=f"Analysis done: {stats['analyzed']} analyzed, "
                 f"{stats['failed']} failed")
        self._do_search(seed_ids, limit, vol_max, blend)

    def _do_search(self, seed_ids, limit, vol_max, blend):
        """Execute similarity search and populate results."""
        from music_manager.core.similarity import find_similar

        self.results = find_similar(
            seed_ids, limit=limit,
            volatility_max=vol_max, blend=blend)

        self._populate_results()
        self.status_label.configure(
            text=f"Found {len(self.results)} similar tracks")

    def _populate_results(self):
        self.result_tree.delete(*self.result_tree.get_children())
        self._result_track_map.clear()

        for r in self.results:
            match_pct = r.get("match_pct")
            if match_pct is None:
                tag = "match_loose"
            elif match_pct >= 70:
                tag = "match_close"
            elif match_pct >= 40:
                tag = "match_loose"
            else:
                tag = "match_weak"
            iid = self.result_tree.insert(
                "", "end", text=r["title"],
                tags=(tag,),
                values=(
                    r["composer"],
                    r["album"],
                    f"{match_pct:.0f}%" if match_pct is not None else "",
                    f"{r['agreement']}/{r['seed_count']}",
                    f"{r['volatility']:.3f}" if r["volatility"] is not None else "",
                ))
            self._result_track_map[iid] = r["track_id"]

    # ------------------------------------------------------------------
    # Volatility slider
    # ------------------------------------------------------------------

    def _on_vol_change(self, value):
        if self.vol_enabled.get():
            self.vol_label.configure(text=f"{float(value):.2f}")
            # Re-filter existing results without re-analyzing
            if self.results:
                self._refilter_volatility()

    def _on_vol_toggle(self):
        if self.vol_enabled.get():
            self.vol_label.configure(text=f"{self.vol_var.get():.2f}")
        else:
            self.vol_label.configure(text="Off")
        if self.results:
            self._refilter_volatility()

    def _refilter_volatility(self):
        """Re-filter current results by volatility without re-analyzing."""
        if not self.seed_tracks:
            return
        seed_ids = list(self.seed_tracks.keys())
        try:
            limit = int(self.limit_var.get())
        except ValueError:
            limit = 50
        vol_max = self.vol_var.get() if self.vol_enabled.get() else None
        blend = self.blend_var.get()
        self._do_search(seed_ids, limit, vol_max, blend)

    # ------------------------------------------------------------------
    # Export & playback
    # ------------------------------------------------------------------

    def _export_m3u(self):
        """Export result tracks to an M3U file."""
        if not self.results:
            messagebox.showinfo("No Results", "Run a search first.",
                                parent=self.win)
            return

        from music_manager.interfaces import filedialog as fd
        path = fd.asksaveasfilename(
            defaultextension=".m3u",
            initialfile="similar_tracks.m3u",
            filetypes=[("M3U Playlist", "*.m3u"), ("All files", "*.*")],
            title="Export Similar Tracks",
            parent=self.win,
        )
        if not path:
            return

        from music_manager.core.database import Track, SourceFolder
        lines = ["#EXTM3U"]
        for r in self.results:
            track = Track.get_by_id(r["track_id"])
            seconds = round((track.duration_ms or 0) / 1000)
            composer = r["composer"]
            display = f"{composer} - {r['title']}" if composer else r["title"]
            file_path = str(Path(track.folder.root_path) / track.relative_path)
            lines.append(f"#EXTINF:{seconds},{display}")
            lines.append(file_path)

        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.status_label.configure(text=f"Exported {len(self.results)} tracks to M3U")

    def _play_selected(self):
        """Play the first selected result track."""
        sel = self.result_tree.selection()
        if not sel:
            return
        tid = self._result_track_map.get(sel[0])
        if tid:
            self._play_track(tid)

    def _result_context_menu(self, event):
        iid = self.result_tree.identify_row(event.y)
        if not iid:
            return
        self.result_tree.selection_set(iid)
        tid = self._result_track_map.get(iid)
        if not tid:
            return

        menu = tk.Menu(self.win, tearoff=0)
        menu.add_command(label="Play", command=lambda: self._play_track(tid))
        menu.add_command(label="Add as Seed",
                         command=lambda: self._add_result_as_seed(tid))
        menu.tk_popup(event.x_root, event.y_root)

    def _add_result_as_seed(self, track_id):
        """Add a result track as a new seed."""
        from music_manager.core.database import Track
        track = Track.get_by_id(track_id)
        self._add_seed(track)

    def _play_track(self, track_id):
        """Open a track in the system default player."""
        import subprocess
        import platform
        from music_manager.core.database import Track

        track = Track.get_by_id(track_id)
        file_path = Path(track.folder.root_path) / track.relative_path
        if not file_path.exists():
            messagebox.showerror("File Not Found", str(file_path),
                                 parent=self.win)
            return
        system = platform.system()
        if system == "Windows":
            import os
            os.startfile(str(file_path))
        elif system == "Darwin":
            subprocess.Popen(["open", str(file_path)])
        else:
            subprocess.Popen(["xdg-open", str(file_path)])
