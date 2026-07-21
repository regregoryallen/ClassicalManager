"""Find Similar UI: analysis progress and results popup.

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

# Above this many unanalyzed tracks, Find Similar warns loudly rather
# than quietly launching hours of librosa work.
_LARGE_ANALYSIS_GAP = 100


class SimilarityUIMixin:
    def _analysis_gap(self):
        """(unanalyzed_count, total_tracks) for the active library."""
        from music_manager.core.similarity import TrackAnalysis, FEATURE_VERSION
        from music_manager.core.database import Track
        current = TrackAnalysis.select().join(Track).where(
            (Track.library == self.active_library) &
            (TrackAnalysis.feature_version == FEATURE_VERSION)).count()
        total = Track.select().where(
            Track.library == self.active_library).count()
        return max(0, total - current), total

    def _analyze_audio(self):
        """Deliberate batch audio analysis (v3.1).

        Replaces the old Track Similarity popup, whose seed/browse UI was
        superseded by the Builder's Find Similar. What remains valuable
        is starting the long librosa pass on purpose, with progress and
        cancel — the same shape as the scan button.
        """
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        missing, total = self._analysis_gap()
        if not total:
            messagebox.showinfo("Analyze Audio",
                                "This library has no tracks to analyze.")
            return
        if not missing:
            messagebox.showinfo(
                "Analyze Audio",
                f"All {total} tracks are already analyzed.\n\n"
                f"Use Find Similar in the Playlist Builder to search by "
                f"audio similarity.")
            return

        if not messagebox.askyesno(
                "Analyze Audio",
                f"{missing} of {total} tracks need audio analysis.\n\n"
                f"{self._analysis_estimate(missing)}\n"
                f"Progress is saved as it goes — you can cancel and resume "
                f"later.\n\nStart now?"):
            return

        self._run_sim_analysis(None)

    @staticmethod
    def _analysis_estimate(count):
        """Human-scale expectation for a librosa batch (~2s/track)."""
        seconds = count * 2
        if seconds < 120:
            return "This takes under a minute."
        if seconds < 5400:
            return f"This takes roughly {max(1, round(seconds / 60))} minutes."
        return f"This takes roughly {seconds / 3600:.1f} hours."

    def _find_similar_tracks(self):
        """Find tracks similar to the current profile selections."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return
        if not self._current_selections:
            messagebox.showinfo(
                "No Selections",
                "Add some tracks first — all selections are used as seeds "
                "for the similarity search.")
            return

        # Resolve current selections to track IDs
        seed_ids = self._resolve_current_to_track_ids()
        if not seed_ids:
            messagebox.showinfo(
                "No Tracks",
                "Current selections don't match any tracks.")
            return

        # Top up any missing analyses first. Small gaps just run; a large
        # gap gets an explicit warning with a time estimate, so clicking
        # a search button never silently starts a multi-hour job.
        unanalyzed, total_tracks = self._analysis_gap()

        if unanalyzed > 0:
            if unanalyzed >= _LARGE_ANALYSIS_GAP:
                proceed = messagebox.askyesno(
                    "Analysis Required",
                    f"{unanalyzed} of {total_tracks} tracks still need audio "
                    f"analysis.\n\n{self._analysis_estimate(unanalyzed)}\n"
                    f"You can cancel partway and resume later, or run "
                    f"Analyze Audio from the sidebar when convenient.\n\n"
                    f"Start the analysis now?")
            else:
                proceed = messagebox.askyesno(
                    "Analysis Required",
                    f"{unanalyzed} track(s) need analysis first. "
                    f"{self._analysis_estimate(unanalyzed)}\n\nProceed?")
            if not proceed:
                return
            self._run_sim_analysis(seed_ids)
        else:
            self._show_sim_results(seed_ids)

    def _resolve_current_to_track_ids(self):
        """Resolve _current_selections to a set of track IDs."""
        from music_manager.core.selection import resolve_selections
        from music_manager.core.database import PlaylistProfile, ProfileSelection

        profile = self._build_temp_profile()
        if not profile:
            return set()
        try:
            track_ids = resolve_selections(profile).track_ids
        finally:
            profile.delete_instance(recursive=True)
        return track_ids

    def _run_sim_analysis(self, seed_ids):
        """Run library analysis with progress, then show results."""
        import threading
        self._sim_cancel_flag = False

        popup = tk.Toplevel(self.root)
        popup.title("Analyzing Library")
        popup.transient(self.root)
        popup.resizable(False, False)
        self._center_on_main(popup, 400, 120)
        popup.wait_visibility()
        popup.grab_set()

        ctk = self.ctk
        status = ctk.CTkLabel(popup, text="Analyzing...")
        status.pack(padx=20, pady=(15, 5))
        progress = ctk.CTkProgressBar(popup, width=300)
        progress.pack(padx=20, pady=5)
        progress.set(0)
        cancel_btn = ctk.CTkButton(
            popup, text="Cancel", width=80,
            command=lambda: setattr(self, '_sim_cancel_flag', True))
        cancel_btn.pack(pady=(5, 10))

        def worker():
            from music_manager.core.similarity import (
                analyze_library, AnalysisCancelled)
            try:
                def prog(current, total, msg):
                    if self._sim_cancel_flag:
                        raise AnalysisCancelled()
                    title = (msg[:35] + "...") if len(msg) > 35 else msg
                    self.root.after(0, lambda c=current, t=total, m=title:
                                   _update(c, t, m))

                stats = analyze_library(self.active_library,
                                        progress_callback=prog)
                self.root.after(0, lambda: _done(stats))
            except AnalysisCancelled:
                self.root.after(0, _cancelled)
            except Exception as exc:
                self.root.after(0, lambda e=exc: _error(e))

        def _update(current, total, msg):
            if total > 0:
                progress.set(current / total)
            status.configure(text=f"Analyzing {current}/{total}: {msg}")

        def _done(stats):
            popup.destroy()
            if seed_ids is None:
                messagebox.showinfo(
                    "Analyze Audio",
                    f"Analyzed {stats['analyzed']} track(s); "
                    f"{stats['skipped']} already current"
                    + (f"; {stats['failed']} failed"
                       if stats["failed"] else "") + ".")
            else:
                self._show_sim_results(seed_ids)

        def _cancelled():
            popup.destroy()

        def _error(exc):
            popup.destroy()
            messagebox.showerror("Analysis Error", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_sim_results(self, seed_ids):
        """Show similarity results in a Toplevel window."""
        popup = tk.Toplevel(self.root)
        popup.title("Find Similar Tracks")
        popup.transient(self.root)
        self._center_on_main(popup, 900, 560)
        popup.wait_visibility()
        popup.grab_set()

        ctk = self.ctk

        # -- Parameter controls --
        param_frame = ctk.CTkFrame(popup, fg_color="transparent")
        param_frame.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(param_frame, text="Max results:").pack(
            side="left", padx=(0, 4))
        limit_var = tk.StringVar(value="50")
        ctk.CTkEntry(param_frame, textvariable=limit_var, width=55).pack(
            side="left", padx=(0, 12))

        ctk.CTkLabel(param_frame, text="Volatility max:").pack(
            side="left", padx=(0, 4))
        vol_var = tk.DoubleVar(value=1.0)
        vol_slider = ctk.CTkSlider(
            param_frame, from_=0.0, to=1.0, variable=vol_var, width=110,
            command=lambda v: vol_label.configure(
                text=f"{float(v):.2f}" if vol_enabled.get() else "Off"))
        vol_slider.pack(side="left", padx=(0, 2))
        vol_label = ctk.CTkLabel(param_frame, text="Off", width=30)
        vol_label.pack(side="left", padx=(0, 2))
        vol_enabled = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            param_frame, text="", variable=vol_enabled, width=20,
            command=lambda: vol_label.configure(
                text=f"{vol_var.get():.2f}" if vol_enabled.get() else "Off")
        ).pack(side="left", padx=(0, 12))

        ctk.CTkLabel(param_frame, text="Blend:").pack(
            side="left", padx=(0, 4))
        blend_var = tk.DoubleVar(value=0.5)
        ctk.CTkSlider(param_frame, from_=0.0, to=1.0,
                      variable=blend_var, width=110).pack(
            side="left", padx=(0, 4))
        ctk.CTkLabel(param_frame, text="nearest ↔ consensus",
                     font=ctk.CTkFont(size=10)).pack(side="left", padx=(0, 12))

        search_btn = ctk.CTkButton(param_frame, text="Search", width=70)
        search_btn.pack(side="left")

        # -- Results Treeview --
        tree_frame = ctk.CTkFrame(popup, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=4)

        result_tree = ttk.Treeview(
            tree_frame,
            columns=("composer", "album", "match", "agreement", "volatility"),
            show="tree headings", selectmode="extended")
        result_tree.heading("#0", text="Title")
        result_tree.heading("composer", text="Composer")
        result_tree.heading("album", text="Album")
        result_tree.heading("match", text="Match")
        result_tree.heading("agreement", text="Agreement")
        result_tree.heading("volatility", text="Volatility")
        result_tree.column("#0", width=220)
        result_tree.column("composer", width=140)
        result_tree.column("album", width=160)
        result_tree.column("match", width=60)
        result_tree.column("agreement", width=70)
        result_tree.column("volatility", width=70)
        result_tree.pack(fill="both", expand=True)
        result_tree.tag_configure("match_close", foreground="#2d7d46")
        result_tree.tag_configure("match_loose", foreground="#c98a1f")
        result_tree.tag_configure("match_weak", foreground="#a03a3a")

        scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                               command=result_tree.yview)
        result_tree.configure(yscrollcommand=scroll.set)
        scroll.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne",
                     in_=result_tree)

        result_tree.bind("<Button-3>", lambda e: self._sim_result_context_menu(
            e, result_tree, sim_state))

        # -- Bottom: action buttons + status --
        bot_frame = ctk.CTkFrame(popup, fg_color="transparent")
        bot_frame.pack(fill="x", padx=12, pady=(4, 10))

        ctk.CTkButton(
            bot_frame, text="Accept Selected", width=120,
            fg_color="#2d7d46",
            command=lambda: self._accept_sim_tracks(
                result_tree, sim_state, selected_only=True)
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            bot_frame, text="Accept All", width=100,
            fg_color="#2d7d46",
            command=lambda: self._accept_sim_tracks(
                result_tree, sim_state, selected_only=False)
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            bot_frame, text="Re-search (include accepted)", width=200,
            command=lambda: self._sim_re_search(
                result_tree, sim_state, limit_var, vol_var,
                vol_enabled, blend_var)
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            bot_frame, text="Close", width=70,
            command=popup.destroy).pack(side="left", padx=(0, 4))

        status_label = ctk.CTkLabel(bot_frame, text="", text_color="gray")
        status_label.pack(side="right", padx=10)

        # Shared state dict for the results window
        sim_state = {
            "seed_ids": seed_ids,
            "result_map": {},       # iid → result dict
            "status_label": status_label,
            "popup": popup,
        }

        # Wire up search button
        search_btn.configure(command=lambda: self._do_sim_search(
            result_tree, sim_state, limit_var, vol_var,
            vol_enabled, blend_var))

        # Run initial search
        self._do_sim_search(result_tree, sim_state, limit_var, vol_var,
                            vol_enabled, blend_var)

    def _do_sim_search(self, result_tree, sim_state, limit_var, vol_var,
                       vol_enabled, blend_var):
        """Execute similarity search and populate the results Treeview."""
        from music_manager.core.similarity import find_similar

        try:
            limit = int(limit_var.get())
        except ValueError:
            limit = 50
        vol_max = vol_var.get() if vol_enabled.get() else None
        blend = blend_var.get()
        seed_ids = sim_state["seed_ids"]

        results = find_similar(
            list(seed_ids), limit=limit,
            volatility_max=vol_max, blend=blend)

        # Filter out tracks already in the profile
        selected_track_ids = self._resolve_current_to_track_ids()
        results = [r for r in results if r["track_id"] not in selected_track_ids]

        # Populate tree
        result_tree.delete(*result_tree.get_children())
        sim_state["result_map"].clear()
        for r in results:
            match_pct = r.get("match_pct")
            if match_pct is None:
                tag = "match_loose"
            elif match_pct >= 70:
                tag = "match_close"
            elif match_pct >= 40:
                tag = "match_loose"
            else:
                tag = "match_weak"
            iid = result_tree.insert(
                "", "end", text=r["title"],
                tags=(tag,),
                values=(
                    r["composer"],
                    r["album"],
                    f"{match_pct:.0f}%" if match_pct is not None else "",
                    f"{r['agreement']}/{r['seed_count']}",
                    f"{r['volatility']:.3f}" if r["volatility"] is not None else "",
                ))
            sim_state["result_map"][iid] = r

        sim_state["status_label"].configure(
            text=f"{len(results)} similar tracks found")

    def _accept_sim_tracks(self, result_tree, sim_state, selected_only=True):
        """Add result tracks as track-level selections in the profile."""
        if selected_only:
            iids = result_tree.selection()
            if not iids:
                messagebox.showinfo("Select", "Select tracks to accept.",
                                    parent=sim_state["popup"])
                return
        else:
            iids = result_tree.get_children()
            if not iids:
                return

        from music_manager.core.database import Track

        added = 0
        for iid in iids:
            r = sim_state["result_map"].get(iid)
            if not r:
                continue
            track = Track.get_by_id(r["track_id"])
            self._add_selection("track", track.relative_path, refresh=False)
            added += 1

        if added:
            with self._busy():
                view_state = self._save_builder_view_state()
                self._refresh_rules_display()
                self._restore_builder_view_state(view_state)

        # Remove accepted items from the tree
        for iid in list(iids):
            if iid in sim_state["result_map"]:
                del sim_state["result_map"][iid]
            result_tree.delete(iid)

        remaining = len(result_tree.get_children())
        sim_state["status_label"].configure(
            text=f"{added} accepted, {remaining} remaining")

    def _sim_result_context_menu(self, event, result_tree, sim_state):
        """Right-click context menu on the Find Similar results tree."""
        iid = result_tree.identify_row(event.y)
        if not iid:
            return
        if iid not in result_tree.selection():
            result_tree.selection_set(iid)

        r = sim_state["result_map"].get(iid)
        if not r:
            return

        from music_manager.core.database import Track
        track = Track.get_by_id(r["track_id"])

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Play",
                         command=lambda: self._play_track(track.id))
        if track.work_id:
            menu.add_command(label="Details...",
                             command=lambda: self._show_work_details(track.work_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _sim_re_search(self, result_tree, sim_state, limit_var, vol_var,
                       vol_enabled, blend_var):
        """Re-resolve selections (including accepted tracks) and re-search."""
        new_seed_ids = self._resolve_current_to_track_ids()
        if not new_seed_ids:
            messagebox.showinfo(
                "No Seeds", "No tracks to use as seeds.",
                parent=sim_state["popup"])
            return
        sim_state["seed_ids"] = new_seed_ids
        self._do_sim_search(result_tree, sim_state, limit_var, vol_var,
                            vol_enabled, blend_var)
