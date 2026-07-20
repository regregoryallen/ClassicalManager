"""Rules window: the raw-rule "view source" for the current profile.

V3 Phase 5.  The Builder trees are a WYSIWYG editor over a declarative
rule system; this non-modal singleton window shows the rules themselves,
graded by `classify_selections` (active / redundant / no-op / orphaned),
with surgical Remove, Reveal-in-library, and one-click Clean Up of dead
rules.  It is the only place orphaned rules are visible at all — a rule
whose key no longer resolves matches no tree node by construction.

Read-remove-repair only: rule *creation* stays in the Builder trees,
which produce well-formed rules (breadcrumbs, cascade hygiene).
"""

import logging
import tkinter as tk
from tkinter import messagebox, ttk

logger = logging.getLogger(__name__)

_STATUS_LABEL = {
    "active": "active",
    "redundant": "redundant",
    "no_op": "no-op",
    "orphaned": "orphaned",
}
_DEAD_STATUSES = {"redundant", "no_op", "orphaned"}


class RulesWindowMixin:
    def _show_rules_window(self):
        """Open or focus the singleton Rules window."""
        if not self.active_library:
            return
        if self._rules_window and self._rules_window.winfo_exists():
            self._rules_window.lift()
            self._rules_window.focus_force()
            self._refresh_rules_window()
            return

        win = tk.Toplevel(self.root)
        win.title("Rules — current profile")
        win.transient(self.root)
        self._center_on_main(win, 780, 420)
        win.configure(bg="#2b2b2b")
        # Non-modal: no grab_set(), so the Builder stays interactive
        self._rules_window = win

        tree_frame = tk.Frame(win, bg="#2b2b2b")
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        tree = ttk.Treeview(
            tree_frame,
            columns=("action", "level", "name", "tracks", "status", "pin"),
            show="headings", selectmode="extended")
        for col, label, width, anchor in (
                ("action", "Action", 70, "center"),
                ("level", "Level", 60, "center"),
                ("name", "Name", 330, "w"),
                ("tracks", "Tracks", 60, "center"),
                ("status", "Status", 150, "w"),
                ("pin", "Pin", 40, "center")):
            tree.heading(col, text=label)
            tree.column(col, width=width, anchor=anchor)
        tree.tag_configure("orphaned", foreground="#e05a5a")
        tree.tag_configure("dead", foreground="#e6a332")

        scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                               command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        self._rules_tree = tree
        self._rules_iid_map = {}  # iid → (level, key)

        tree.bind("<Double-Button-1>",
                  lambda _e: self._rules_window_reveal())
        tree.bind("<Button-3>", self._rules_window_context_menu)

        bot = tk.Frame(win, bg="#2b2b2b")
        bot.pack(fill="x", padx=10, pady=8)
        tk.Button(bot, text="Remove", bg="#7d2d2d", fg="white",
                  command=self._rules_window_remove).pack(
            side="left", padx=(0, 5))
        tk.Button(bot, text="Reveal in Library", bg="#3b3b3b", fg="white",
                  command=self._rules_window_reveal).pack(
            side="left", padx=5)
        tk.Button(bot, text="Clean Up", bg="#3b3b3b", fg="white",
                  command=self._rules_window_cleanup).pack(
            side="left", padx=5)
        tk.Button(bot, text="Close", bg="#3b3b3b", fg="white",
                  command=win.destroy).pack(side="right")
        tk.Label(bot, text="Double-click a rule to reveal it in the "
                           "library tree",
                 bg="#2b2b2b", fg="gray70").pack(side="left", padx=10)

        self._refresh_rules_window()

    def _refresh_rules_window(self):
        """Repopulate the Rules window from the current selections."""
        win = getattr(self, "_rules_window", None)
        if not (win and win.winfo_exists()):
            return
        from music_manager.core.selection import classify_selections

        tree = self._rules_tree
        tree.delete(*tree.get_children())
        self._rules_iid_map.clear()

        if not (self.active_library and self._current_selections):
            return

        index = self._get_library_index()
        results = classify_selections(index, self._current_rules())

        for rs in results:
            rule = rs.rule
            status_text = _STATUS_LABEL.get(rs.status, rs.status)
            if rs.needs_breadcrumbs and rs.status != "orphaned":
                status_text += " · no breadcrumbs"
            if rs.status == "orphaned":
                tag = "orphaned"
            elif rs.status in _DEAD_STATUSES:
                tag = "dead"
            else:
                tag = ""
            iid = tree.insert(
                "", "end",
                values=("EXCEPT" if rule.excluded else "ADD",
                        rule.level,
                        self._display_name(rule.level, rule.key),
                        rs.governs if rs.status != "orphaned" else "—",
                        status_text,
                        f"#{rule.pin_position}" if rule.pin_position else ""),
                tags=(tag,) if tag else ())
            self._rules_iid_map[iid] = (rule.level, rule.key)

    def _rules_window_selected_keys(self):
        return [self._rules_iid_map[iid]
                for iid in self._rules_tree.selection()
                if iid in self._rules_iid_map]

    def _rules_window_remove(self):
        """Surgically remove the selected rules — no cascades, no
        synthesized exclusions; exactly these rows are deleted."""
        targets = self._rules_window_selected_keys()
        if not targets:
            return
        self._current_selections = [
            s for s in self._current_selections
            if (s["level"], s["key"]) not in set(targets)
        ]
        self._refresh_rules_display()

    def _rules_window_reveal(self):
        """Select and scroll the Builder library tree to the rule's node."""
        targets = self._rules_window_selected_keys()
        if not targets:
            return
        level, key = targets[0]
        reverse = {(lvl, k): iid for iid, (lvl, _eid, k)
                   in self._builder_lib_iid_map.items()}
        iid = reverse.get((level, key))
        if iid is None:
            messagebox.showinfo(
                "Not in tree",
                "This rule's item is not present in the library tree "
                "(orphaned rule, or hidden by the current filter).",
                parent=self._rules_window)
            return
        self.tabview.set("Playlist Builder")
        tree = self.builder_lib_tree
        parent = tree.parent(iid)
        while parent:
            tree.item(parent, open=True)
            parent = tree.parent(parent)
        tree.see(iid)
        tree.selection_set(iid)

    def _rules_window_cleanup(self):
        """Remove every redundant / no-op / orphaned rule in one step."""
        from music_manager.core.selection import classify_selections
        if not (self.active_library and self._current_selections):
            return
        index = self._get_library_index()
        results = classify_selections(index, self._current_rules())
        dead = [(rs.rule.level, rs.rule.key) for rs in results
                if rs.status in _DEAD_STATUSES]
        if not dead:
            messagebox.showinfo("Clean Up", "No dead rules to remove.",
                                parent=self._rules_window)
            return
        if not messagebox.askyesno(
                "Clean Up",
                f"Remove {len(dead)} rule(s) that have no effect "
                f"(redundant, no-op, or orphaned)?",
                parent=self._rules_window):
            return
        dead_set = set(dead)
        self._current_selections = [
            s for s in self._current_selections
            if (s["level"], s["key"]) not in dead_set
        ]
        self._refresh_rules_display()

    def _rules_window_context_menu(self, event):
        iid = self._rules_tree.identify_row(event.y)
        if iid and iid not in self._rules_tree.selection():
            self._rules_tree.selection_set(iid)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Remove", command=self._rules_window_remove)
        menu.add_command(label="Reveal in Library",
                         command=self._rules_window_reveal)
        menu.add_separator()
        menu.add_command(label="Clean Up dead rules",
                         command=self._rules_window_cleanup)
        menu.tk_popup(event.x_root, event.y_root)
