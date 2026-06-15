"""GUI interface using customtkinter (§10).

Provides the main application window with:
  - Sidebar: library selector, metrics, rescan button
  - Tab 1: Explorer & Rules (albums, works, include/exclude)
  - Tab 2: Playlist Builder (modes, preview, export, push)
  - Tab 3: Cleanup / Overlay (work review, overrides, import/export)

Treeview note: customtkinter has no native tree widget.  Uses styled
ttk.Treeview themed to approximate the customtkinter palette.
"""

import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

logger = logging.getLogger(__name__)


def launch_gui():
    """Launch the main GUI window."""
    try:
        import customtkinter as ctk
    except ImportError:
        print("Error: customtkinter is required for the GUI. "
              "Install it with: pip install customtkinter")
        return

    from music_manager.core.database import initialize_database
    initialize_database()

    app = App(ctk)
    app.mainloop()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class App:
    """Main application window."""

    def __init__(self, ctk):
        self.ctk = ctk
        self.root = ctk.CTk()
        self.root.title("Classical Music Playlist Manager")
        self.root.geometry("1280x800")

        self.active_library = None
        self._current_profile_rules = []  # in-memory include/exclude rules

        self._setup_theme()
        self._build_layout()
        self._refresh_library_list()

    def mainloop(self):
        """Start the Tk event loop."""
        self.root.mainloop()

    def _setup_theme(self):
        """Configure ttk.Treeview style to blend with customtkinter."""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background="#2b2b2b", foreground="white",
                        fieldbackground="#2b2b2b", rowheight=25,
                        font=("Segoe UI", 11))
        style.configure("Treeview.Heading",
                        background="#3b3b3b", foreground="white",
                        font=("Segoe UI", 11, "bold"))
        style.map("Treeview",
                  background=[("selected", "#1f6aa5")],
                  foreground=[("selected", "white")])

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        """Build the main window layout: sidebar + tabbed content."""
        ctk = self.ctk

        # Sidebar
        self.sidebar = ctk.CTkFrame(self.root, width=260, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self._build_sidebar()

        # Content area with tabs
        self.tabview = ctk.CTkTabview(self.root)
        self.tabview.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        self.tab_explorer = self.tabview.add("Explorer & Rules")
        self.tab_builder = self.tabview.add("Playlist Builder")
        self.tab_cleanup = self.tabview.add("Cleanup / Overlay")

        self._build_explorer_tab()
        self._build_builder_tab()
        self._build_cleanup_tab()

    # ------------------------------------------------------------------
    # Sidebar (§10)
    # ------------------------------------------------------------------

    def _build_sidebar(self):
        """Build sidebar: library selector, metrics, rescan, manage."""
        ctk = self.ctk

        ctk.CTkLabel(self.sidebar, text="Library",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
            padx=15, pady=(15, 5), anchor="w")

        self.lib_combo = ctk.CTkComboBox(self.sidebar, values=["(none)"],
                                         command=self._on_library_changed,
                                         width=230)
        self.lib_combo.pack(padx=15, pady=5)

        # Library management buttons
        btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        btn_frame.pack(padx=15, pady=5, fill="x")
        ctk.CTkButton(btn_frame, text="New Library", width=110,
                      command=self._new_library).pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_frame, text="Add Folder", width=110,
                      command=self._add_source_folder).pack(side="left")

        # Metrics
        ctk.CTkLabel(self.sidebar, text="Metrics",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=15, pady=(20, 5), anchor="w")

        self.lbl_albums = ctk.CTkLabel(self.sidebar, text="Albums: -")
        self.lbl_albums.pack(padx=20, anchor="w")
        self.lbl_works = ctk.CTkLabel(self.sidebar, text="Works: -")
        self.lbl_works.pack(padx=20, anchor="w")
        self.lbl_tracks = ctk.CTkLabel(self.sidebar, text="Tracks: -")
        self.lbl_tracks.pack(padx=20, anchor="w")
        self.lbl_composers = ctk.CTkLabel(self.sidebar, text="Composers: -")
        self.lbl_composers.pack(padx=20, anchor="w")

        # Scan button + progress
        self.scan_btn = ctk.CTkButton(self.sidebar, text="Rescan Library",
                                      command=self._start_scan)
        self.scan_btn.pack(padx=15, pady=(20, 5), fill="x")

        self.scan_progress = ctk.CTkProgressBar(self.sidebar, width=230)
        self.scan_progress.pack(padx=15, pady=5)
        self.scan_progress.set(0)

        self.scan_status = ctk.CTkLabel(self.sidebar, text="")
        self.scan_status.pack(padx=15, anchor="w")

        # Source folders list
        ctk.CTkLabel(self.sidebar, text="Source Folders",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=15, pady=(20, 5), anchor="w")
        self.folders_text = ctk.CTkTextbox(self.sidebar, height=120, width=230,
                                           state="disabled")
        self.folders_text.pack(padx=15, pady=5)

    def _refresh_library_list(self):
        """Reload the library dropdown from the database."""
        from music_manager.core.database import Library
        libs = list(Library.select())
        names = [lib.name for lib in libs]
        self.lib_combo.configure(values=names if names else ["(none)"])
        if libs:
            self.lib_combo.set(libs[0].name)
            self._on_library_changed(libs[0].name)
        else:
            self.lib_combo.set("(none)")
            self.active_library = None

    def _on_library_changed(self, name):
        """Handle library selection change."""
        from music_manager.core.database import Library
        if name == "(none)":
            self.active_library = None
            return
        try:
            self.active_library = Library.get(Library.name == name)
        except Library.DoesNotExist:
            self.active_library = None
            return
        self._refresh_metrics()
        self._refresh_source_folders()
        self._refresh_explorer()
        self._refresh_cleanup()

    def _refresh_metrics(self):
        """Update sidebar metric counts."""
        if not self.active_library:
            for lbl in (self.lbl_albums, self.lbl_works, self.lbl_tracks, self.lbl_composers):
                lbl.configure(text=lbl.cget("text").split(":")[0] + ": -")
            return

        from music_manager.core.database import Album, Work, Track, Composer
        lib = self.active_library

        album_count = Album.select().where(Album.library == lib).count()
        work_count = Work.select().join(Album).where(Album.library == lib).count()
        track_count = Track.select().where(Track.library == lib).count()
        composer_count = Composer.select().where(Composer.library == lib).count()

        self.lbl_albums.configure(text=f"Albums: {album_count}")
        self.lbl_works.configure(text=f"Works: {work_count}")
        self.lbl_tracks.configure(text=f"Tracks: {track_count}")
        self.lbl_composers.configure(text=f"Composers: {composer_count}")

    def _refresh_source_folders(self):
        """Update the source folders display."""
        self.folders_text.configure(state="normal")
        self.folders_text.delete("1.0", "end")
        if self.active_library:
            from music_manager.core.database import SourceFolder
            for sf in SourceFolder.select().where(
                SourceFolder.library == self.active_library
            ):
                self.folders_text.insert("end", sf.root_path + "\n")
        self.folders_text.configure(state="disabled")

    def _new_library(self):
        """Create a new library via dialog."""
        ctk = self.ctk
        dialog = ctk.CTkInputDialog(text="Library name:", title="New Library")
        name = dialog.get_input()
        if not name or not name.strip():
            return
        from music_manager.core.database import Library
        Library.create(name=name.strip())
        self._refresh_library_list()

    def _add_source_folder(self):
        """Add a source folder to the active library."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select or create a library first.")
            return
        folder = filedialog.askdirectory(title="Select Source Folder")
        if not folder:
            return
        from music_manager.core.database import SourceFolder
        # Store as POSIX path
        posix = folder.replace("\\", "/")
        SourceFolder.create(library=self.active_library, root_path=posix)
        self._refresh_source_folders()

    def _start_scan(self):
        """Start a library scan on a background thread."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select or create a library first.")
            return

        self.scan_btn.configure(state="disabled", text="Scanning...")
        self.scan_progress.set(0)
        self.scan_status.configure(text="Starting scan...")

        lib = self.active_library
        thread = threading.Thread(target=self._run_scan, args=(lib,), daemon=True)
        thread.start()

    def _run_scan(self, library):
        """Run the scan in a background thread."""
        from music_manager.core.scanner import scan_library
        from music_manager.core.overrides import apply_overrides

        def progress(current, total, message):
            frac = current / total if total else 0
            self.root.after(0, lambda: self.scan_progress.set(frac))
            self.root.after(0, lambda: self.scan_status.configure(
                text=f"[{current}/{total}] {message}"))

        try:
            stats = scan_library(library, progress_callback=progress)
            apply_overrides(library)
            msg = (f"Done: {stats.tracks_created} tracks, "
                   f"{stats.albums_created} albums, "
                   f"{stats.works_created} works")
            if stats.files_failed:
                msg += f", {len(stats.files_failed)} failed"
        except Exception as exc:
            msg = f"Scan error: {exc}"
            logger.exception("Scan failed")

        def finish():
            self.scan_status.configure(text=msg)
            self.scan_progress.set(1)
            self.scan_btn.configure(state="normal", text="Rescan Library")
            self._refresh_metrics()
            self._refresh_explorer()
            self._refresh_cleanup()

        self.root.after(0, finish)

    # ------------------------------------------------------------------
    # Tab 1: Explorer & Rules (§10)
    # ------------------------------------------------------------------

    def _build_explorer_tab(self):
        """Build the Explorer & Rules tab with album/work treeviews."""
        ctk = self.ctk
        tab = self.tab_explorer

        # Search bar
        search_frame = ctk.CTkFrame(tab, fg_color="transparent")
        search_frame.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(search_frame, text="Search:").pack(side="left", padx=5)
        self.explorer_search = ctk.CTkEntry(search_frame, width=300,
                                            placeholder_text="Filter albums and works...")
        self.explorer_search.pack(side="left", padx=5)
        ctk.CTkButton(search_frame, text="Search", width=80,
                      command=self._refresh_explorer).pack(side="left", padx=5)
        self.explorer_search.bind("<Return>", lambda e: self._refresh_explorer())

        # Paned view: albums left, works/tracks right
        pane = ctk.CTkFrame(tab, fg_color="transparent")
        pane.pack(fill="both", expand=True, padx=5, pady=5)

        # Albums tree
        left = ctk.CTkFrame(pane)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        ctk.CTkLabel(left, text="Albums",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=5)
        self.album_tree = ttk.Treeview(left, columns=("artist", "year", "tracks"),
                                       show="headings", selectmode="browse")
        self.album_tree.heading("artist", text="Album")
        self.album_tree.heading("year", text="Year")
        self.album_tree.heading("tracks", text="Tracks")
        self.album_tree.column("artist", width=300)
        self.album_tree.column("year", width=60, anchor="center")
        self.album_tree.column("tracks", width=60, anchor="center")
        self.album_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.album_tree.bind("<<TreeviewSelect>>", self._on_album_selected)
        self.album_tree.bind("<Button-3>", self._album_context_menu)

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
                      command=self._remove_rule).pack(side="right", padx=5)

        # Store album_id map for treeview items
        self._album_iid_map = {}
        self._work_iid_map = {}

    def _refresh_explorer(self):
        """Reload album and work treeviews from the database."""
        self.album_tree.delete(*self.album_tree.get_children())
        self._album_iid_map.clear()

        if not self.active_library:
            return

        from music_manager.core.database import Album, Track

        search = self.explorer_search.get().strip().lower() if hasattr(self, 'explorer_search') else ""

        albums = Album.select().where(Album.library == self.active_library).order_by(Album.title)
        for album in albums:
            if search and search not in album.title.lower() and search not in (album.album_artist or "").lower():
                continue
            track_count = Track.select().where(Track.album == album).count()
            iid = self.album_tree.insert("", "end", values=(
                album.title,
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

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Include Album",
                         command=lambda: self._add_rule("include", "album", album_id))
        menu.add_command(label="Exclude Album",
                         command=lambda: self._add_rule("exclude", "album", album_id))
        menu.post(event.x_root, event.y_root)

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
        menu = tk.Menu(self.root, tearoff=0)

        if level == "work":
            menu.add_command(label="Include Work",
                             command=lambda: self._add_rule("include", "work", entity_id))
            menu.add_command(label="Exclude Work",
                             command=lambda: self._add_rule("exclude", "work", entity_id))
        elif level == "track":
            menu.add_command(label="Include Track",
                             command=lambda: self._add_rule("include", "track", entity_id))
            menu.add_command(label="Exclude Track",
                             command=lambda: self._add_rule("exclude", "track", entity_id))

        menu.post(event.x_root, event.y_root)

    def _add_rule(self, rule_type, target_level, target_id):
        """Add an include/exclude rule to the in-memory list."""
        # Get a display label
        from music_manager.core.database import Album, Work, Track
        if target_level == "album":
            name = Album.get_by_id(target_id).title
        elif target_level == "work":
            name = Work.get_by_id(target_id).work_name
        elif target_level == "track":
            name = Track.get_by_id(target_id).title
        elif target_level == "composer":
            from music_manager.core.database import Composer
            name = Composer.get_by_id(target_id).name
        else:
            name = str(target_id)

        rule = {
            "rule_type": rule_type,
            "target_level": target_level,
            "target_id": target_id,
            "display": f"{rule_type.upper()}: {target_level} — {name}",
        }
        self._current_profile_rules.append(rule)
        self._refresh_rules_display()

    def _remove_rule(self):
        """Remove selected rule from the in-memory list."""
        sel = self.rules_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._current_profile_rules):
            self._current_profile_rules.pop(idx)
            self._refresh_rules_display()

    def _refresh_rules_display(self):
        """Update the rules listbox."""
        self.rules_listbox.delete(0, "end")
        for rule in self._current_profile_rules:
            self.rules_listbox.insert("end", rule["display"])

    # ------------------------------------------------------------------
    # Tab 2: Playlist Builder (§10)
    # ------------------------------------------------------------------

    def _build_builder_tab(self):
        """Build the Playlist Builder tab."""
        ctk = self.ctk
        tab = self.tab_builder

        # Profile name
        row0 = ctk.CTkFrame(tab, fg_color="transparent")
        row0.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(row0, text="Profile Name:").pack(side="left", padx=5)
        self.profile_name_entry = ctk.CTkEntry(row0, width=250,
                                               placeholder_text="e.g. Sunday Classical")
        self.profile_name_entry.pack(side="left", padx=5)
        ctk.CTkButton(row0, text="Load Profile", width=110,
                      command=self._load_profile).pack(side="left", padx=5)
        ctk.CTkButton(row0, text="Save Profile", width=110,
                      command=self._save_profile).pack(side="left", padx=5)

        # Settings row
        row1 = ctk.CTkFrame(tab, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(row1, text="Shuffle Mode:").pack(side="left", padx=5)
        self.shuffle_mode = ctk.CTkComboBox(row1, values=["track", "work", "album"],
                                            width=120)
        self.shuffle_mode.pack(side="left", padx=5)
        self.shuffle_mode.set("work")

        ctk.CTkLabel(row1, text="Work Integrity:").pack(side="left", padx=15)
        self.work_integrity = ctk.CTkComboBox(
            row1, values=["enforce", "respect_selection"], width=160)
        self.work_integrity.pack(side="left", padx=5)
        self.work_integrity.set("enforce")

        row2 = ctk.CTkFrame(tab, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(row2, text="Length Mode:").pack(side="left", padx=5)
        self.length_mode = ctk.CTkComboBox(row2, values=["all", "count", "duration"],
                                           width=120)
        self.length_mode.pack(side="left", padx=5)
        self.length_mode.set("all")

        ctk.CTkLabel(row2, text="Value:").pack(side="left", padx=15)
        self.length_value = ctk.CTkEntry(row2, width=80, placeholder_text="e.g. 50")
        self.length_value.pack(side="left", padx=5)

        ctk.CTkLabel(row2, text="Seed:").pack(side="left", padx=15)
        self.seed_entry = ctk.CTkEntry(row2, width=80, placeholder_text="(random)")
        self.seed_entry.pack(side="left", padx=5)

        self.no_repeat_var = ctk.CTkCheckBox(row2, text="No repeat tracks")
        self.no_repeat_var.pack(side="left", padx=15)
        self.no_repeat_var.select()

        # Action buttons
        row3 = ctk.CTkFrame(tab, fg_color="transparent")
        row3.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(row3, text="Preview (Dry Run)", width=160,
                      command=self._preview_playlist).pack(side="left", padx=5)
        ctk.CTkButton(row3, text="Export to M3U", width=140,
                      command=self._export_m3u).pack(side="left", padx=5)
        ctk.CTkButton(row3, text="Export to JSON", width=140,
                      command=self._export_json).pack(side="left", padx=5)
        ctk.CTkButton(row3, text="Push to Plex", width=140,
                      command=self._push_plex).pack(side="left", padx=5)

        # Preview results
        self.preview_tree = ttk.Treeview(tab,
                                         columns=("order", "composer", "work", "title", "dur"),
                                         show="headings", selectmode="browse")
        self.preview_tree.heading("order", text="#")
        self.preview_tree.heading("composer", text="Composer")
        self.preview_tree.heading("work", text="Work")
        self.preview_tree.heading("title", text="Title")
        self.preview_tree.heading("dur", text="Duration")
        self.preview_tree.column("order", width=40, anchor="center")
        self.preview_tree.column("composer", width=180)
        self.preview_tree.column("work", width=250)
        self.preview_tree.column("title", width=250)
        self.preview_tree.column("dur", width=70, anchor="center")
        self.preview_tree.pack(fill="both", expand=True, padx=10, pady=5)

        self.preview_status = ctk.CTkLabel(tab, text="")
        self.preview_status.pack(padx=10, pady=5, anchor="w")

    def _build_temp_profile(self):
        """Build a temporary PlaylistProfile from current UI settings."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return None

        from music_manager.core.database import PlaylistProfile, ProfileRule

        name = self.profile_name_entry.get().strip() or "Untitled"
        length_val = self.length_value.get().strip()
        seed_val = self.seed_entry.get().strip()

        profile = PlaylistProfile.create(
            library=self.active_library,
            name=name,
            shuffle_mode=self.shuffle_mode.get(),
            work_integrity=self.work_integrity.get(),
            length_mode=self.length_mode.get(),
            length_value=int(length_val) if length_val else None,
            seed=int(seed_val) if seed_val else None,
            no_repeat_tracks=self.no_repeat_var.get() == 1,
        )

        for rule in self._current_profile_rules:
            ProfileRule.create(
                profile=profile,
                rule_type=rule["rule_type"],
                target_level=rule["target_level"],
                target_id=rule["target_id"],
            )

        return profile

    def _delete_temp_profile(self, profile):
        """Delete a temporarily-created profile."""
        if profile:
            from music_manager.core.database import ProfileRule
            ProfileRule.delete().where(ProfileRule.profile == profile).execute()
            profile.delete_instance()

    def _preview_playlist(self):
        """Preview the playlist (dry-run)."""
        profile = self._build_temp_profile()
        if not profile:
            return

        try:
            from music_manager.core.engine import generate_playlist
            result = generate_playlist(profile)

            self.preview_tree.delete(*self.preview_tree.get_children())
            for rt in result.playlist:
                dur_s = rt.duration_ms // 1000
                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                self.preview_tree.insert("", "end", values=(
                    rt.order_key,
                    rt.composer_name or "",
                    rt.work_name or "",
                    rt.title,
                    dur_str,
                ))

            total_s = result.total_duration_ms // 1000
            self.preview_status.configure(
                text=f"{result.track_count} tracks, "
                     f"{total_s // 3600}h {(total_s % 3600) // 60}m {total_s % 60}s total"
            )
        finally:
            self._delete_temp_profile(profile)

    def _export_m3u(self):
        """Export the playlist to an M3U file."""
        path = filedialog.asksaveasfilename(
            defaultextension=".m3u",
            filetypes=[("M3U Playlist", "*.m3u"), ("All files", "*.*")],
            title="Export M3U",
        )
        if not path:
            return

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
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            title="Export JSON",
        )
        if not path:
            return

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
        profile = self._build_temp_profile()
        if not profile:
            return

        try:
            from music_manager.core.engine import generate_playlist
            from music_manager.core.serializers.plex import PlexSerializer, PlexConnectionError, PlexPushError
            from music_manager.core.config import load_config

            result = generate_playlist(profile)
            config = load_config()
            plex_config = config.get("targets", {}).get("plex", {})
            plex_config["playlist_name"] = profile.name

            serializer = PlexSerializer()
            serializer.serialize(result.playlist, plex_config)
            messagebox.showinfo("Plex", f"Pushed '{profile.name}' to Plex "
                               f"({result.track_count} tracks)")
        except (PlexConnectionError, PlexPushError) as exc:
            messagebox.showerror("Plex Error", str(exc))
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
        finally:
            self._delete_temp_profile(profile)

    def _save_profile(self):
        """Save current settings as a named profile in the DB."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        name = self.profile_name_entry.get().strip()
        if not name:
            messagebox.showwarning("No Name", "Enter a profile name.")
            return

        from music_manager.core.database import PlaylistProfile, ProfileRule

        # Delete existing profile with same name
        for existing in PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (PlaylistProfile.name == name)
        ):
            ProfileRule.delete().where(ProfileRule.profile == existing).execute()
            existing.delete_instance()

        length_val = self.length_value.get().strip()
        seed_val = self.seed_entry.get().strip()

        profile = PlaylistProfile.create(
            library=self.active_library,
            name=name,
            shuffle_mode=self.shuffle_mode.get(),
            work_integrity=self.work_integrity.get(),
            length_mode=self.length_mode.get(),
            length_value=int(length_val) if length_val else None,
            seed=int(seed_val) if seed_val else None,
            no_repeat_tracks=self.no_repeat_var.get() == 1,
        )

        for rule in self._current_profile_rules:
            ProfileRule.create(
                profile=profile,
                rule_type=rule["rule_type"],
                target_level=rule["target_level"],
                target_id=rule["target_id"],
            )

        messagebox.showinfo("Saved", f"Profile '{name}' saved.")

    def _load_profile(self):
        """Load a profile by name from the DB."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        name = self.profile_name_entry.get().strip()
        if not name:
            # Show picker
            from music_manager.core.database import PlaylistProfile
            profiles = list(PlaylistProfile.select().where(
                PlaylistProfile.library == self.active_library))
            if not profiles:
                messagebox.showinfo("No Profiles", "No saved profiles found.")
                return
            # Simple selection dialog
            names = [p.name for p in profiles]
            picker = tk.Toplevel(self.root)
            picker.title("Select Profile")
            picker.geometry("300x300")
            lb = tk.Listbox(picker, bg="#2b2b2b", fg="white",
                           selectbackground="#1f6aa5", font=("Segoe UI", 11))
            for n in names:
                lb.insert("end", n)
            lb.pack(fill="both", expand=True, padx=10, pady=10)

            def on_select():
                sel = lb.curselection()
                if sel:
                    self.profile_name_entry.delete(0, "end")
                    self.profile_name_entry.insert(0, names[sel[0]])
                    picker.destroy()
                    self._load_profile()

            ctk = self.ctk
            ctk.CTkButton(picker, text="Load", command=on_select).pack(pady=5)
            return

        from music_manager.core.database import PlaylistProfile, ProfileRule

        try:
            profile = PlaylistProfile.get(
                (PlaylistProfile.library == self.active_library) &
                (PlaylistProfile.name == name)
            )
        except PlaylistProfile.DoesNotExist:
            messagebox.showwarning("Not Found", f"Profile '{name}' not found.")
            return

        # Populate UI
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

        # Load rules
        self._current_profile_rules.clear()
        from music_manager.core.database import Album, Work, Track, Composer
        for rule in ProfileRule.select().where(ProfileRule.profile == profile):
            try:
                if rule.target_level == "album":
                    display_name = Album.get_by_id(rule.target_id).title
                elif rule.target_level == "work":
                    display_name = Work.get_by_id(rule.target_id).work_name
                elif rule.target_level == "track":
                    display_name = Track.get_by_id(rule.target_id).title
                elif rule.target_level == "composer":
                    display_name = Composer.get_by_id(rule.target_id).name
                else:
                    display_name = str(rule.target_id)
            except Exception:
                display_name = f"(deleted id={rule.target_id})"

            self._current_profile_rules.append({
                "rule_type": rule.rule_type,
                "target_level": rule.target_level,
                "target_id": rule.target_id,
                "display": f"{rule.rule_type.upper()}: {rule.target_level} — {display_name}",
            })
        self._refresh_rules_display()
        messagebox.showinfo("Loaded", f"Profile '{name}' loaded.")

    # ------------------------------------------------------------------
    # Tab 3: Cleanup / Overlay (§10)
    # ------------------------------------------------------------------

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
        ctk.CTkButton(top, text="Refresh", width=80,
                      command=self._refresh_cleanup).pack(side="right", padx=5)

        # Heuristic works review
        ctk.CTkLabel(tab, text="Works Detected by Heuristic (review recommended)",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=10, pady=(10, 5), anchor="w")

        self.heuristic_tree = ttk.Treeview(
            tab, columns=("album", "tracks", "composer"),
            show="headings", selectmode="browse", height=8)
        self.heuristic_tree.heading("album", text="Work Name")
        self.heuristic_tree.heading("tracks", text="Tracks")
        self.heuristic_tree.heading("composer", text="Composer")
        self.heuristic_tree.column("album", width=400)
        self.heuristic_tree.column("tracks", width=60, anchor="center")
        self.heuristic_tree.column("composer", width=200)
        self.heuristic_tree.pack(fill="x", padx=10, pady=5)
        self._heuristic_work_map = {}

        # Edit section
        edit_frame = ctk.CTkFrame(tab)
        edit_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(edit_frame, text="Edit Selected Work / Track",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            padx=10, pady=5, anchor="w")

        row_e1 = ctk.CTkFrame(edit_frame, fg_color="transparent")
        row_e1.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row_e1, text="Work Name:").pack(side="left", padx=5)
        self.edit_work_name = ctk.CTkEntry(row_e1, width=300)
        self.edit_work_name.pack(side="left", padx=5)
        ctk.CTkButton(row_e1, text="Set Work Name", width=120,
                      command=self._set_work_name_override).pack(side="left", padx=5)

        row_e2 = ctk.CTkFrame(edit_frame, fg_color="transparent")
        row_e2.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row_e2, text="Work Group Key:").pack(side="left", padx=5)
        self.edit_group_key = ctk.CTkEntry(row_e2, width=300)
        self.edit_group_key.pack(side="left", padx=5)
        ctk.CTkButton(row_e2, text="Set Group Key", width=120,
                      command=self._set_work_group_key_override).pack(side="left", padx=5)

        row_e3 = ctk.CTkFrame(edit_frame, fg_color="transparent")
        row_e3.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row_e3, text="Composer:").pack(side="left", padx=5)
        self.edit_composer = ctk.CTkEntry(row_e3, width=300)
        self.edit_composer.pack(side="left", padx=5)
        ctk.CTkButton(row_e3, text="Set Composer", width=120,
                      command=self._set_composer_override).pack(side="left", padx=5)

        # Overrides list
        ctk.CTkLabel(tab, text="Current Overrides",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=10, pady=(10, 5), anchor="w")

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
        self._override_id_map = {}

        del_btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        del_btn_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(del_btn_frame, text="Delete Override", width=140,
                      command=self._delete_override).pack(side="left", padx=5)

    def _refresh_cleanup(self):
        """Reload heuristic works and overrides lists."""
        self._refresh_heuristic_works()
        self._refresh_overrides_list()

    def _refresh_heuristic_works(self):
        """Reload the heuristic works treeview."""
        self.heuristic_tree.delete(*self.heuristic_tree.get_children())
        self._heuristic_work_map.clear()

        if not self.active_library:
            return

        from music_manager.core.database import Work, Album, Track

        works = (Work.select(Work, Album)
                 .join(Album)
                 .where((Album.library == self.active_library) &
                        (Work.work_source == "heuristic"))
                 .order_by(Work.work_name))

        for work in works:
            tracks = list(Track.select().where(Track.work == work))
            composer = tracks[0].composer.name if tracks and tracks[0].composer_id else ""
            iid = self.heuristic_tree.insert("", "end", values=(
                work.work_name,
                len(tracks),
                composer,
            ))
            self._heuristic_work_map[iid] = work.id

    def _refresh_overrides_list(self):
        """Reload the overrides treeview."""
        self.overrides_tree.delete(*self.overrides_tree.get_children())
        self._override_id_map.clear()

        if not self.active_library:
            return

        from music_manager.core.database import Override

        for ov in Override.select().where(Override.library == self.active_library):
            match = ov.match_mb_id or ov.match_relative_path or ""
            iid = self.overrides_tree.insert("", "end", values=(
                ov.scope, ov.field, ov.value, match
            ))
            self._override_id_map[iid] = ov.id

    def _get_selected_heuristic_work(self):
        """Get the work ID of the selected heuristic work."""
        sel = self.heuristic_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select a heuristic work first.")
            return None
        return self._heuristic_work_map.get(sel[0])

    def _set_work_name_override(self):
        """Set a work_name override for the selected heuristic work's tracks."""
        work_id = self._get_selected_heuristic_work()
        if not work_id:
            return
        new_name = self.edit_work_name.get().strip()
        if not new_name:
            messagebox.showwarning("Empty", "Enter a work name.")
            return

        from music_manager.core.database import Work, Track
        from music_manager.core.overrides import set_override

        work = Work.get_by_id(work_id)
        tracks = list(Track.select().where(Track.work == work))

        for t in tracks:
            set_override(
                library=self.active_library, scope="track", field="work_name",
                value=new_name, match_relative_path=t.relative_path,
                match_mb_id=t.musicbrainz_recording_id,
            )

        # Also update the work directly for immediate display
        work.work_name = new_name
        work.save()

        messagebox.showinfo("Done", f"Set work name to '{new_name}' "
                           f"for {len(tracks)} tracks.")
        self._refresh_cleanup()
        self._refresh_explorer()

    def _set_work_group_key_override(self):
        """Set work_group_key overrides for the selected work's tracks."""
        work_id = self._get_selected_heuristic_work()
        if not work_id:
            return
        group_key = self.edit_group_key.get().strip()
        if not group_key:
            messagebox.showwarning("Empty", "Enter a work group key.")
            return

        from music_manager.core.database import Work, Track
        from music_manager.core.overrides import set_override

        work = Work.get_by_id(work_id)
        tracks = list(Track.select().where(Track.work == work))

        for t in tracks:
            set_override(
                library=self.active_library, scope="track", field="work_group_key",
                value=group_key, match_relative_path=t.relative_path,
                match_mb_id=t.musicbrainz_recording_id,
            )

        messagebox.showinfo("Done", f"Set work_group_key to '{group_key}' "
                           f"for {len(tracks)} tracks. Rescan to apply.")
        self._refresh_cleanup()

    def _set_composer_override(self):
        """Set a composer override for selected work's tracks."""
        work_id = self._get_selected_heuristic_work()
        if not work_id:
            return
        composer_name = self.edit_composer.get().strip()
        if not composer_name:
            messagebox.showwarning("Empty", "Enter a composer name.")
            return

        from music_manager.core.database import Work, Track
        from music_manager.core.overrides import set_override

        work = Work.get_by_id(work_id)
        tracks = list(Track.select().where(Track.work == work))

        for t in tracks:
            set_override(
                library=self.active_library, scope="track", field="composer",
                value=composer_name, match_relative_path=t.relative_path,
                match_mb_id=t.musicbrainz_recording_id,
            )

        messagebox.showinfo("Done", f"Set composer to '{composer_name}' "
                           f"for {len(tracks)} tracks. Rescan or apply overrides to update.")
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

        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            title="Export Overrides",
        )
        if not path:
            return

        from music_manager.core.overrides import export_overrides
        count = export_overrides(self.active_library, Path(path))
        messagebox.showinfo("Export", f"Exported {count} overrides to:\n{path}")

    def _import_overrides(self):
        """Import overrides from a JSON file."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")],
            title="Import Overrides",
        )
        if not path:
            return

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
