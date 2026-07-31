from __future__ import annotations

import queue
import shutil
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from .auth import MicrosoftAuthenticator
from .curseforge import ModManager
from .minecraft import MinecraftService
from .modrinth import ModrinthClient
from .models import LOADERS, Profile
from .resources import resource_path
from .storage import LauncherStorage
from .updater import GitHubUpdater, UpdateError
from . import theme


class PlaceholderEntry(tk.Entry):
    """Dark entry with placeholder text that is never returned as its value."""

    def __init__(self, parent, placeholder: str, value: str = "", **kwargs):
        self._content_mask = kwargs.pop("show", "")
        kwargs.setdefault("bg", "#171717")
        kwargs.setdefault("fg", theme.TEXT)
        kwargs.setdefault("insertbackground", theme.TEXT)
        kwargs.setdefault("relief", "sunken")
        kwargs.setdefault("bd", 2)
        kwargs.setdefault("font", theme.FONT)
        super().__init__(parent, **kwargs)
        self.placeholder = placeholder
        self._showing_placeholder = False
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        if value:
            self.insert(0, value)
            if self._content_mask:
                self.configure(show=self._content_mask)
        else:
            self._show_placeholder()

    def _show_placeholder(self):
        self.delete(0, "end")
        self.insert(0, self.placeholder)
        self.configure(fg="#858585", show="")
        self._showing_placeholder = True

    def _focus_in(self, _event=None):
        if self._showing_placeholder:
            self.delete(0, "end")
            self.configure(fg=theme.TEXT, show=self._content_mask)
            self._showing_placeholder = False

    def _focus_out(self, _event=None):
        if not super().get():
            self._show_placeholder()

    def get(self) -> str:
        return "" if self._showing_placeholder else super().get()


class BlocksmithApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Blocksmith Launcher")
        try:
            self._window_icon = tk.PhotoImage(file=resource_path("assets/blocksmith-256.png"))
            self.iconphoto(True, self._window_icon)
        except tk.TclError:
            pass
        self.geometry("1280x800")
        self.minsize(1040, 680)
        self.configure(bg=theme.BG)
        self.storage = LauncherStorage()
        self.profiles = self.storage.load_profiles()
        self.settings = self.storage.load_settings()
        self.minecraft = MinecraftService(self.storage)
        self.auth = MicrosoftAuthenticator(self.storage.auth_file)
        self.events: queue.Queue = queue.Queue()
        self.mod_projects = {}
        self.updater = GitHubUpdater()
        self.available_update = None
        self.active_profile: Profile | None = None
        self.busy = False
        self._styles()
        self._layout()
        self.after(80, self._poll_events)
        if not self.profiles:
            self.after(250, self.open_profile_dialog)
        else:
            self.select_profile(self.profiles[0])
        if self.settings.get("check_updates", True):
            self.after(1500, lambda: self.check_for_updates(silent=True))

    def _styles(self) -> None:
        # Tk's option database also controls popup menus and list portions of
        # ttk comboboxes, which otherwise inherit a white system theme.
        self.option_add("*Background", theme.BG)
        self.option_add("*Foreground", theme.TEXT)
        self.option_add("*selectBackground", theme.ACCENT_DARK)
        self.option_add("*selectForeground", theme.TEXT)
        self.option_add("*insertBackground", theme.TEXT)
        self.option_add("*TCombobox*Listbox.background", "#171717")
        self.option_add("*TCombobox*Listbox.foreground", theme.TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", theme.ACCENT_DARK)
        self.option_add("*TCombobox*Listbox.selectForeground", theme.TEXT)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=theme.BG, foreground=theme.TEXT, font=theme.FONT)
        style.configure("TFrame", background=theme.BG)
        style.configure("Panel.TFrame", background=theme.PANEL)
        style.configure("Dirt.TFrame", background=theme.DIRT)
        style.configure("Stone.TFrame", background=theme.PANEL_2)
        style.configure("TLabel", background=theme.BG, foreground=theme.TEXT)
        style.configure("Muted.TLabel", foreground=theme.MUTED)
        style.configure("Panel.TLabel", background=theme.PANEL)
        style.configure("Dirt.TLabel", background=theme.DIRT)
        style.configure("Stone.TLabel", background=theme.PANEL_2)
        style.configure("Title.TLabel", font=theme.FONT_TITLE)
        style.configure("Heading.TLabel", font=theme.FONT_HEADING)
        style.configure(
            "TButton", background=theme.STONE, foreground=theme.TEXT,
            borderwidth=3, relief="raised", bordercolor=theme.STONE_LIGHT,
            lightcolor=theme.STONE_LIGHT, darkcolor=theme.SHADOW, padding=(16, 9),
            font=("DejaVu Sans", 10, "bold"),
        )
        style.map("TButton", background=[("active", "#8d8d8d"), ("pressed", "#5d5d5d"), ("disabled", theme.PANEL)])
        style.configure(
            "Accent.TButton", background=theme.ACCENT, foreground=theme.TEXT,
            borderwidth=4, relief="raised", bordercolor=theme.ACCENT_LIGHT,
            lightcolor=theme.ACCENT_LIGHT, darkcolor=theme.ACCENT_DARK,
            padding=(28, 13), font=("DejaVu Sans", 14, "bold"),
        )
        style.map("Accent.TButton", background=[("active", "#69bd43"), ("pressed", "#3d8428"), ("disabled", theme.BORDER)])
        style.configure("TEntry", fieldbackground="#171717", foreground=theme.TEXT, insertcolor=theme.TEXT, bordercolor=theme.STONE, lightcolor=theme.STONE, darkcolor=theme.SHADOW, borderwidth=2, padding=8)
        style.configure("TCombobox", fieldbackground="#171717", background=theme.STONE, foreground=theme.TEXT, arrowcolor=theme.TEXT, bordercolor=theme.STONE, padding=7)
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#171717"), ("disabled", theme.PANEL)],
            foreground=[("readonly", theme.TEXT), ("disabled", theme.MUTED)],
            selectbackground=[("readonly", "#171717")],
            selectforeground=[("readonly", theme.TEXT)],
        )
        style.configure("Horizontal.TProgressbar", background=theme.ACCENT, troughcolor=theme.PANEL_2, borderwidth=0)
        style.configure(
            "Treeview", background="#171717", fieldbackground="#171717",
            foreground=theme.TEXT, bordercolor=theme.STONE, rowheight=30,
        )
        style.map("Treeview", background=[("selected", theme.ACCENT_DARK)], foreground=[("selected", theme.TEXT)])
        style.configure("Treeview.Heading", background=theme.PANEL_2, foreground=theme.TEXT, relief="raised", font=("DejaVu Sans", 9, "bold"))
        style.configure("TNotebook", background=theme.BG, borderwidth=0, tabmargins=(0, 16, 0, 0))
        style.configure(
            "TNotebook.Tab", background=theme.PANEL, foreground=theme.MUTED,
            borderwidth=0, padding=(22, 11), font=("DejaVu Sans", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", theme.ACCENT_DARK), ("active", theme.PANEL_2)],
            foreground=[("selected", theme.ACCENT_LIGHT), ("active", theme.TEXT)],
        )

    def _layout(self) -> None:
        main = ttk.Frame(self, padding=(40, 30))
        main.pack(fill="both", expand=True)
        top = ttk.Frame(main)
        top.pack(fill="x")
        title_wrap = ttk.Frame(top)
        title_wrap.pack(side="left")
        ttk.Label(title_wrap, text="BLOCKSMITH", style="Title.TLabel", foreground=theme.TEXT).pack(anchor="w")
        ttk.Label(title_wrap, text="A MINECRAFT JAVA LAUNCHER", style="Muted.TLabel", font=("DejaVu Sans", 9, "bold")).pack(anchor="w")
        self.account_label = ttk.Label(top, text="Offline mode", style="Muted.TLabel")
        self.account_label.pack(side="right")

        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="both", expand=True)
        play_tab = ttk.Frame(self.tabs, padding=(0, 14, 0, 0))
        profiles_tab = ttk.Frame(self.tabs, padding=(4, 24))
        mods_tab = ttk.Frame(self.tabs, padding=(4, 24))
        console_tab = ttk.Frame(self.tabs, padding=(4, 20))
        settings_tab = ttk.Frame(self.tabs, padding=(4, 24))
        self.tabs.add(play_tab, text="  PLAY  ")
        self.tabs.add(profiles_tab, text="  PROFILES  ")
        self.tabs.add(mods_tab, text="  MODS  ")
        self.tabs.add(console_tab, text="  CONSOLE  ")
        self.tabs.add(settings_tab, text="  SETTINGS  ")

        hero_border = tk.Frame(play_tab, bg=theme.SHADOW, bd=0)
        hero_border.pack(fill="x", pady=(8, 18))
        hero = ttk.Frame(hero_border, style="Stone.TFrame", padding=28)
        hero.pack(fill="both", padx=(3, 6), pady=(3, 7))
        selector_row = ttk.Frame(hero, style="Stone.TFrame")
        selector_row.pack(fill="x", pady=(0, 12))
        ttk.Label(selector_row, text="SELECTED PROFILE", style="Stone.TLabel", foreground=theme.ACCENT_LIGHT, font=("DejaVu Sans", 9, "bold")).pack(side="left")
        self.profile_choice = ttk.Combobox(selector_row, state="readonly", width=28)
        self.profile_choice.pack(side="right")
        self.profile_choice.bind("<<ComboboxSelected>>", self._profile_choice_selected)
        self.profile_name = ttk.Label(hero, text="Create a profile", style="Stone.TLabel", font=("DejaVu Sans", 23, "bold"))
        self.profile_name.pack(anchor="w")
        self.profile_subtitle = ttk.Label(hero, text="Choose a Minecraft version and mod loader.", style="Stone.TLabel", foreground=theme.MUTED)
        self.profile_subtitle.pack(anchor="w", pady=(5, 24))

        authrow = ttk.Frame(hero, style="Stone.TFrame")
        authrow.pack(fill="x")
        ttk.Label(authrow, text="PLAY AS", style="Stone.TLabel", foreground=theme.MUTED, font=("DejaVu Sans", 9, "bold")).pack(side="left")
        self.mode = tk.StringVar(value=self.settings.get("mode", "Offline"))
        self.mode_box = ttk.Combobox(authrow, textvariable=self.mode, values=("Offline", "Microsoft"), state="readonly", width=14)
        self.mode_box.pack(side="left", padx=(14, 8))
        self.identity = PlaceholderEntry(
            authrow,
            "Offline username or Microsoft email",
            self.settings.get("identity", ""),
            width=32,
        )
        self.identity.pack(side="left")
        self.play_button = ttk.Button(authrow, text="▶  PLAY", style="Accent.TButton", command=self.play)
        self.play_button.pack(side="right")
        self.install_button = ttk.Button(authrow, text="Install", command=self.install)
        self.install_button.pack(side="right", padx=10)

        status_head = ttk.Frame(play_tab)
        status_head.pack(fill="x", pady=(8, 8))
        self.status_label = ttk.Label(status_head, text="Ready", style="Heading.TLabel")
        self.status_label.pack(side="left")
        self.progress = ttk.Progressbar(status_head, mode="determinate", maximum=100, length=220)
        self.progress.pack(side="right")
        tips = ttk.Frame(play_tab, style="Dirt.TFrame", padding=20)
        tips.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(tips, text="READY FOR ADVENTURE", style="Dirt.TLabel", foreground="#d9c29f", font=("DejaVu Sans", 12, "bold")).pack(anchor="w")
        ttk.Label(
            tips,
            text="Select a profile, choose offline or Microsoft mode, then press Play.\n"
                 "Blocksmith automatically installs Minecraft, Java, and your chosen mod loader.",
            style="Dirt.TLabel", foreground=theme.MUTED, justify="left",
        ).pack(anchor="w", pady=(8, 0))

        # Profiles menu
        ttk.Label(profiles_tab, text="YOUR PROFILES", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            profiles_tab,
            text="Every profile has isolated saves, settings, resource packs, and mods.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 24))
        profile_grid = ttk.Frame(profiles_tab)
        profile_grid.pack(fill="both", expand=True)
        self.profile_list = tk.Listbox(
            profile_grid, bg="#171717", fg=theme.TEXT, selectbackground=theme.ACCENT_DARK,
            selectforeground=theme.TEXT, borderwidth=3, relief="sunken",
            highlightthickness=1, highlightbackground=theme.STONE,
            activestyle="none", font=("DejaVu Sans", 11, "bold"), width=30,
        )
        self.profile_list.pack(side="left", fill="y", padx=(0, 18))
        self.profile_list.bind("<<ListboxSelect>>", self._profile_selected)
        profile_card = ttk.Frame(profile_grid, style="Stone.TFrame", padding=24)
        profile_card.pack(side="left", fill="both", expand=True)
        self.profile_tab_name = ttk.Label(profile_card, text="No profile selected", style="Stone.TLabel", font=("DejaVu Sans", 18, "bold"))
        self.profile_tab_name.pack(anchor="w")
        self.profile_tab_detail = ttk.Label(profile_card, text="Create a profile to get started.", style="Stone.TLabel", foreground=theme.MUTED)
        self.profile_tab_detail.pack(anchor="w", pady=(6, 18))
        profile_actions = ttk.Frame(profile_card, style="Stone.TFrame")
        profile_actions.pack(fill="x")
        ttk.Button(profile_actions, text="+  Create profile", command=self.open_profile_dialog).pack(side="left")
        ttk.Button(profile_actions, text="Edit selected", command=lambda: self.open_profile_dialog(self.active_profile)).pack(side="left", padx=10)
        ttk.Button(profile_actions, text="Open game folder", command=self.open_game_folder).pack(side="left")
        ttk.Button(profile_actions, text="Delete", command=self.delete_profile).pack(side="right")

        # Native Modrinth mod management.
        ttk.Label(mods_tab, text="MOD WORKBENCH", style="Title.TLabel").pack(anchor="w")
        self.mods_context = ttk.Label(mods_tab, text="Select a modded profile to browse compatible mods.", style="Muted.TLabel")
        self.mods_context.pack(anchor="w", pady=(4, 16))
        search_row = ttk.Frame(mods_tab)
        search_row.pack(fill="x", pady=(0, 12))
        self.mod_search = PlaceholderEntry(search_row, "Search Modrinth mods, e.g. JEI or Sodium")
        self.mod_search.pack(side="left", fill="x", expand=True)
        self.mod_search.bind("<Return>", lambda _event: self.search_mods())
        self.mod_search_button = ttk.Button(search_row, text="Search", command=self.search_mods)
        self.mod_search_button.pack(side="left", padx=(10, 0))
        mod_progress_row = ttk.Frame(mods_tab)
        mod_progress_row.pack(fill="x", pady=(0, 12))
        self.mod_status = ttk.Label(mod_progress_row, text="Ready", style="Muted.TLabel")
        self.mod_status.pack(side="left")
        self.mod_progress = ttk.Progressbar(
            mod_progress_row, mode="determinate", maximum=100, length=320
        )
        self.mod_progress.pack(side="right")
        lists = ttk.Panedwindow(mods_tab, orient="horizontal")
        lists.pack(fill="both", expand=True)
        search_panel = ttk.Frame(lists)
        installed_panel = ttk.Frame(lists)
        lists.add(search_panel, weight=1)
        lists.add(installed_panel, weight=1)
        ttk.Label(search_panel, text="MODRINTH RESULTS", style="Muted.TLabel", font=("DejaVu Sans", 9, "bold")).pack(anchor="w", pady=(0, 5))
        self.mod_results = ttk.Treeview(search_panel, columns=("author", "downloads"), show="tree headings", height=7)
        self.mod_results.heading("#0", text="Mod")
        self.mod_results.heading("author", text="Author")
        self.mod_results.heading("downloads", text="Downloads")
        self.mod_results.column("#0", width=290)
        self.mod_results.column("author", width=125)
        self.mod_results.column("downloads", width=90, anchor="e")
        self.mod_results.pack(fill="both", expand=True)
        self.install_mod_button = ttk.Button(search_panel, text="Install selected + dependencies", style="Accent.TButton", command=self.install_selected_mod)
        self.install_mod_button.pack(anchor="e", pady=(8, 14))
        installed_head = ttk.Frame(installed_panel)
        installed_head.pack(fill="x", pady=(0, 5))
        ttk.Label(installed_head, text="INSTALLED IN THIS PROFILE", style="Muted.TLabel", font=("DejaVu Sans", 9, "bold")).pack(side="left")
        ttk.Button(installed_head, text="Refresh", command=self.refresh_installed_mods).pack(side="right")
        self.installed_mods = ttk.Treeview(installed_panel, columns=("version", "state"), show="tree headings", height=5)
        self.installed_mods.heading("#0", text="Mod")
        self.installed_mods.heading("version", text="Version")
        self.installed_mods.heading("state", text="State")
        self.installed_mods.column("#0", width=235)
        self.installed_mods.column("version", width=195)
        self.installed_mods.column("state", width=80)
        self.installed_mods.pack(fill="both", expand=True)
        installed_actions = ttk.Frame(installed_panel)
        installed_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(installed_actions, text="Enable / disable", command=self.toggle_selected_mod).pack(side="left")
        ttk.Button(installed_actions, text="Remove", command=self.remove_selected_mod).pack(side="left", padx=8)

        ttk.Label(console_tab, text="GAME OUTPUT", style="Title.TLabel").pack(anchor="w")
        ttk.Label(console_tab, text="Installation progress and Minecraft logs appear here.", style="Muted.TLabel").pack(anchor="w", pady=(4, 14))
        log_frame = tk.Frame(console_tab, bg=theme.SHADOW, bd=0)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_frame, bg="#111111", fg="#d5d5d5", insertbackground=theme.TEXT,
            borderwidth=3, relief="sunken", highlightthickness=1, highlightbackground=theme.STONE,
            font=("DejaVu Sans Mono", 9), padx=16, pady=14, wrap="word", state="disabled",
        )
        self.log.pack(fill="both", expand=True, padx=(2, 5), pady=(2, 5))

        ttk.Label(settings_tab, text="SETTINGS", style="Title.TLabel").pack(anchor="w")
        ttk.Label(settings_tab, text="Launcher integrations and local storage.", style="Muted.TLabel").pack(anchor="w", pady=(4, 24))
        cf_card = ttk.Frame(settings_tab, style="Stone.TFrame", padding=24)
        cf_card.pack(fill="x")
        ttk.Label(cf_card, text="MODRINTH", style="Stone.TLabel", foreground=theme.ACCENT_LIGHT, font=("DejaVu Sans", 13, "bold")).pack(anchor="w")
        ttk.Label(
            cf_card,
            text="Public mod search and downloads are ready. No API key or account is required.",
            style="Stone.TLabel", foreground=theme.MUTED,
        ).pack(anchor="w", pady=(5, 12))
        ttk.Label(
            cf_card, text="Provider: api.modrinth.com", style="Stone.TLabel", foreground=theme.TEXT,
            font=("DejaVu Sans Mono", 9),
        ).pack(anchor="w")
        storage_card = ttk.Frame(settings_tab, style="Dirt.TFrame", padding=20)
        update_card = ttk.Frame(settings_tab, style="Dirt.TFrame", padding=20)
        update_card.pack(fill="x", pady=(16, 0))
        ttk.Label(update_card, text="UPDATES", style="Dirt.TLabel", foreground="#d9c29f", font=("DejaVu Sans", 10, "bold")).pack(anchor="w")
        update_row = ttk.Frame(update_card, style="Dirt.TFrame")
        update_row.pack(fill="x", pady=(10, 8))
        ttk.Label(update_row, text="Channel", style="Dirt.TLabel", foreground=theme.MUTED).pack(side="left")
        self.update_channel = tk.StringVar(value=self.settings.get("update_channel", "Stable"))
        channel_box = ttk.Combobox(update_row, textvariable=self.update_channel, values=("Stable", "Development"), state="readonly", width=16)
        channel_box.pack(side="left", padx=(10, 14))
        channel_box.bind("<<ComboboxSelected>>", lambda _event: self.save_update_channel())
        ttk.Button(update_row, text="Check now", command=self.check_for_updates).pack(side="left")
        self.update_button = ttk.Button(update_row, text="Download and restart", command=self.download_update, state="disabled")
        self.update_button.pack(side="right")
        self.update_status = ttk.Label(update_card, text="Updates are checked automatically.", style="Dirt.TLabel", foreground=theme.MUTED)
        self.update_status.pack(anchor="w")
        self.update_progress = ttk.Progressbar(update_card, mode="determinate", maximum=100)
        self.update_progress.pack(fill="x", pady=(9, 0))

        storage_card = ttk.Frame(settings_tab, style="Dirt.TFrame", padding=20)
        storage_card.pack(fill="x", pady=(16, 0))
        ttk.Label(storage_card, text="DATA DIRECTORY", style="Dirt.TLabel", foreground="#d9c29f", font=("DejaVu Sans", 10, "bold")).pack(anchor="w")
        ttk.Label(storage_card, text=str(self.storage.root), style="Dirt.TLabel", foreground=theme.MUTED).pack(anchor="w", pady=(5, 0))
        self.log_message("Welcome to Blocksmith. Create or select a profile to begin.")
        self.refresh_profiles()

    def refresh_profiles(self) -> None:
        selected = self.active_profile
        names = [profile.name for profile in self.profiles]
        self.profile_choice.configure(values=names)
        self.profile_list.delete(0, "end")
        for index, profile in enumerate(self.profiles):
            mark = "● " if profile.installed else "○ "
            self.profile_list.insert("end", mark + profile.name)
            if selected and profile.id == selected.id:
                self.profile_list.selection_set(index)
                self.profile_choice.current(index)
        if not self.profiles:
            self.profile_choice.set("")

    def _profile_selected(self, _event=None) -> None:
        selection = self.profile_list.curselection()
        if selection:
            self.select_profile(self.profiles[selection[0]])

    def _profile_choice_selected(self, _event=None) -> None:
        index = self.profile_choice.current()
        if 0 <= index < len(self.profiles):
            self.select_profile(self.profiles[index])

    def select_profile(self, profile: Profile) -> None:
        self.active_profile = profile
        self.profile_name.config(text=profile.name)
        self.profile_subtitle.config(text=profile.subtitle + f"  ·  {profile.memory_mb // 1024} GB memory")
        self.profile_tab_name.config(text=profile.name)
        self.profile_tab_detail.config(
            text=profile.subtitle + f"\n{profile.memory_mb} MB RAM · {profile.resolution}"
        )
        self.status_label.config(text="Installed" if profile.installed else "Ready to install")
        self.mods_context.config(text=f"{profile.name} · Minecraft {profile.minecraft_version} · {profile.loader}")
        self.refresh_profiles()
        self.refresh_installed_mods()

    def delete_profile(self) -> None:
        profile = self.active_profile
        if profile is None:
            messagebox.showinfo("Blocksmith", "Select a profile first.")
            return
        if self.busy:
            messagebox.showwarning("Blocksmith", "Wait for the current installation or game to finish.")
            return
        if not messagebox.askyesno(
            "Delete profile?",
            f"Delete “{profile.name}” from Blocksmith?\n\n"
            "Its game files will be moved to Blocksmith's deleted-profiles folder so they can be recovered.",
            icon="warning",
        ):
            return
        source = self.storage.instances_dir / profile.id
        if source.exists():
            archive = self.storage.root / "deleted-profiles"
            archive.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            destination = archive / f"{stamp}-{profile.id}"
            shutil.move(str(source), str(destination))
        self.profiles.remove(profile)
        self.active_profile = self.profiles[0] if self.profiles else None
        self.storage.save_profiles(self.profiles)
        if self.active_profile:
            self.select_profile(self.active_profile)
        else:
            self.profile_name.config(text="Create a profile")
            self.profile_subtitle.config(text="Choose a Minecraft version and mod loader.")
            self.profile_tab_name.config(text="No profile selected")
            self.profile_tab_detail.config(text="Create a profile to get started.")
            self.status_label.config(text="No profile selected")
            self.refresh_profiles()
        messagebox.showinfo("Profile deleted", "The profile was removed. Its instance files remain recoverable in deleted-profiles.")

    def open_game_folder(self) -> None:
        if self.active_profile is None:
            messagebox.showinfo("Blocksmith", "Select or create a profile first.")
            return
        import os
        import subprocess
        import sys

        path = self.storage.instance_dir(self.active_profile)
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc))

    def _mod_manager(self) -> ModManager:
        return ModManager(self.storage, ModrinthClient())

    def save_update_channel(self) -> None:
        self.settings["update_channel"] = self.update_channel.get()
        self.settings.pop("development_release_id", None)
        self.storage.save_settings(self.settings)
        self.available_update = None
        self.update_button.config(state="disabled")
        self.update_status.config(text=f"Using the {self.update_channel.get()} update channel.")

    def check_for_updates(self, silent: bool = False) -> None:
        channel = self.update_channel.get()
        installed = self.settings.get("development_release_id") if channel == "Development" else None
        self.update_status.config(text=f"Checking {channel.lower()} releases…")

        def worker():
            try:
                update = self.updater.check(channel, installed)
                self.events.put(("update_available", (update, silent)))
            except Exception as exc:
                self.events.put(("update_error", (exc, silent)))
        threading.Thread(target=worker, daemon=True).start()

    def download_update(self) -> None:
        update = self.available_update
        if update is None:
            return
        allowed, reason = self.updater.can_self_update()
        if not allowed:
            messagebox.showinfo("Blocksmith update", reason + "\n\nRelease: " + update.page_url)
            return
        self.update_button.config(state="disabled")
        self.update_status.config(text=f"Downloading {update.name}…")
        self.update_progress["value"] = 0

        def worker():
            try:
                executable = self.updater.download(
                    update, lambda value: self.events.put(("update_progress", value))
                )
                self.events.put(("update_ready", (update, executable)))
            except Exception as exc:
                self.events.put(("update_error", (exc, False)))
        threading.Thread(target=worker, daemon=True).start()

    def search_mods(self) -> None:
        profile = self.active_profile
        if profile is None:
            messagebox.showinfo("Modrinth", "Select a profile first.")
            return
        query = self.mod_search.get().strip()
        if not query:
            messagebox.showinfo("Modrinth", "Enter a mod name to search for.")
            return

        def task():
            results = self._mod_manager().client.search_mods(query, profile)
            self.events.put(("mod_results", results))
        self._run_task(task)

    def install_selected_mod(self) -> None:
        profile = self.active_profile
        selected = self.mod_results.selection()
        if profile is None or not selected:
            messagebox.showinfo("Modrinth", "Select a search result first.")
            return
        project = self.mod_projects.get(selected[0])
        if project is None:
            return

        def task():
            manager = self._mod_manager()
            manager.install(
                project,
                profile,
                lambda text: self.events.put(("log", text)),
                lambda value: self.events.put(("progress", value)),
            )
            self.events.put(("mods_refresh", None))
        self._run_task(task)

    def refresh_installed_mods(self) -> None:
        if not hasattr(self, "installed_mods"):
            return
        self.installed_mods.delete(*self.installed_mods.get_children())
        if self.active_profile is None:
            return
        for entry in self._mod_manager().installed(self.active_profile):
            state = "Enabled" if entry.get("enabled") else "Disabled"
            self.installed_mods.insert(
                "", "end", iid=str(entry["project_id"]), text=entry["name"],
                values=(entry.get("version", ""), state),
            )

    def toggle_selected_mod(self) -> None:
        if self.active_profile is None:
            return
        selected = self.installed_mods.selection()
        if not selected:
            messagebox.showinfo("Mods", "Select an installed mod first.")
            return
        project_id = selected[0]
        enabled = self.installed_mods.set(selected[0], "state") != "Enabled"
        try:
            self._mod_manager().set_enabled(self.active_profile, project_id, enabled)
            self.refresh_installed_mods()
        except Exception as exc:
            messagebox.showerror("Mods", str(exc))

    def remove_selected_mod(self) -> None:
        if self.active_profile is None:
            return
        selected = self.installed_mods.selection()
        if not selected:
            messagebox.showinfo("Mods", "Select an installed mod first.")
            return
        name = self.installed_mods.item(selected[0], "text")
        if not messagebox.askyesno("Remove mod?", f"Remove {name} from this profile?"):
            return
        try:
            self._mod_manager().remove(self.active_profile, selected[0])
            self.refresh_installed_mods()
            self.log_message(f"Removed {name}.")
        except Exception as exc:
            messagebox.showerror("Mods", str(exc))

    def open_profile_dialog(self, profile: Profile | None = None) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Edit profile" if profile else "New profile")
        dialog.geometry("480x470")
        dialog.resizable(False, False)
        dialog.configure(bg=theme.BG)
        dialog.transient(self)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=28)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="PROFILE SETUP", style="Title.TLabel").pack(anchor="w", pady=(0, 22))
        loader_value = tk.StringVar(value=profile.loader if profile else "Vanilla")
        entries = {}
        placeholders = {
            "name": "e.g. Survival 1.21",
            "version": "e.g. 1.21.1",
            "loader_version": "e.g. 0.16.10 (blank = latest)",
            "memory": "e.g. 4096",
            "resolution": "e.g. 1280x720",
        }
        current = {
            "name": profile.name if profile else "",
            "version": profile.minecraft_version if profile else "",
            "loader_version": profile.loader_version if profile else "",
            "memory": str(profile.memory_mb) if profile else "",
            "resolution": profile.resolution if profile else "",
        }
        for label, key in (("PROFILE NAME", "name"), ("MINECRAFT VERSION", "version")):
            ttk.Label(body, text=label, style="Muted.TLabel", font=("DejaVu Sans", 9, "bold")).pack(anchor="w", pady=(8, 5))
            entries[key] = PlaceholderEntry(body, placeholders[key], current[key])
            entries[key].pack(fill="x")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(14, 0))
        left, right = ttk.Frame(row), ttk.Frame(row)
        left.pack(side="left", fill="x", expand=True, padx=(0, 5))
        right.pack(side="left", fill="x", expand=True, padx=(5, 0))
        ttk.Label(left, text="MOD LOADER", style="Muted.TLabel", font=("DejaVu Sans", 9, "bold")).pack(anchor="w", pady=(0, 5))
        ttk.Combobox(left, textvariable=loader_value, values=LOADERS, state="readonly").pack(fill="x")
        ttk.Label(right, text="LOADER VERSION (OPTIONAL)", style="Muted.TLabel", font=("DejaVu Sans", 8, "bold")).pack(anchor="w", pady=(0, 5))
        entries["loader_version"] = PlaceholderEntry(right, placeholders["loader_version"], current["loader_version"])
        entries["loader_version"].pack(fill="x")
        row2 = ttk.Frame(body)
        row2.pack(fill="x", pady=(14, 20))
        for parent, label, key in ((ttk.Frame(row2), "MEMORY (MB)", "memory"), (ttk.Frame(row2), "RESOLUTION", "resolution")):
            parent.pack(side="left", fill="x", expand=True, padx=(0, 10) if key == "memory" else (0, 0))
            ttk.Label(parent, text=label, style="Muted.TLabel", font=("DejaVu Sans", 9, "bold")).pack(anchor="w", pady=(0, 5))
            entries[key] = PlaceholderEntry(parent, placeholders[key], current[key])
            entries[key].pack(fill="x")

        def save():
            try:
                data = Profile(
                    id=profile.id if profile else "",
                    name=entries["name"].get().strip(),
                    minecraft_version=entries["version"].get().strip(),
                    loader=loader_value.get(),
                    loader_version=entries["loader_version"].get().strip(),
                    memory_mb=int(entries["memory"].get() or "4096"),
                    resolution=entries["resolution"].get().strip() or "1280x720",
                    installed=profile.installed if profile else False,
                    last_played=profile.last_played if profile else "",
                )
                if not data.name or not data.minecraft_version:
                    raise ValueError("Name and Minecraft version are required")
            except ValueError as exc:
                messagebox.showerror("Invalid profile", str(exc), parent=dialog)
                return
            if profile:
                self.profiles[self.profiles.index(profile)] = data
            else:
                self.profiles.append(data)
            self.storage.save_profiles(self.profiles)
            self.select_profile(data)
            dialog.destroy()

        ttk.Button(body, text="Save profile", style="Accent.TButton", command=save).pack(fill="x")

    def _run_task(self, function) -> None:
        if self.busy:
            return
        self.busy = True
        self.play_button.config(state="disabled")
        self.install_button.config(state="disabled")
        self.progress["value"] = 0
        self.mod_progress["value"] = 0

        def worker():
            try:
                function()
                self.events.put(("done", None))
            except Exception as exc:
                self.events.put(("error", exc))
        threading.Thread(target=worker, daemon=True).start()

    def install(self) -> None:
        if self.active_profile is None:
            self.open_profile_dialog()
            return
        profile = self.active_profile
        self._run_task(lambda: self._install_task(profile))

    def _install_task(self, profile):
        self.minecraft.install(profile, lambda text: self.events.put(("log", text)), lambda value: self.events.put(("progress", value)))
        profile.installed = True
        self.storage.save_profiles(self.profiles)

    def play(self) -> None:
        if self.active_profile is None:
            self.open_profile_dialog()
            return
        mode, identity = self.mode.get(), self.identity.get().strip()
        if not identity:
            messagebox.showerror("Identity required", "Enter an offline username or Microsoft email.")
            return
        self.settings.update({"mode": mode, "identity": identity})
        self.storage.save_settings(self.settings)
        profile = self.active_profile

        def task():
            emit = lambda text: self.events.put(("log", text))
            progress = lambda value: self.events.put(("progress", value))
            if mode == "Offline":
                session = self.minecraft.offline_session(identity)
                self.events.put(("account", f"Offline · {identity}"))
            else:
                session = self.auth.login(identity, emit)
                self.events.put(("account", f"Microsoft · {session.username}"))
            profile.installed = True
            profile.last_played = datetime.now().isoformat(timespec="seconds")
            self.storage.save_profiles(self.profiles)
            self.minecraft.launch(profile, session, emit, progress)
        self._run_task(task)

    def log_message(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.config(state="normal")
        self.log.insert("end", f"[{stamp}] {text}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.status_label.config(text=value)
                    self.mod_status.config(text=value)
                    self.log_message(value)
                elif kind == "progress":
                    self.progress["value"] = float(value) * 100
                    self.mod_progress["value"] = float(value) * 100
                elif kind == "account":
                    self.account_label.config(text=value)
                elif kind == "mod_results":
                    self.mod_projects = {str(project.id): project for project in value}
                    self.mod_results.delete(*self.mod_results.get_children())
                    for project in value:
                        self.mod_results.insert(
                            "", "end", iid=str(project.id), text=project.name,
                            values=(project.author, f"{project.downloads:,}"),
                        )
                    self.log_message(f"Found {len(value)} compatible Modrinth mods.")
                elif kind == "mods_refresh":
                    self.refresh_installed_mods()
                elif kind == "update_available":
                    update, silent = value
                    self.available_update = update
                    if update is None:
                        self.update_button.config(state="disabled")
                        self.update_status.config(text="Blocksmith is up to date.")
                        if not silent:
                            messagebox.showinfo("Blocksmith update", "You already have the newest build.")
                    else:
                        self.update_status.config(text=f"{update.name} is available.")
                        self.update_button.config(state="normal")
                        if not silent:
                            messagebox.showinfo("Blocksmith update", f"{update.name} is ready to download.")
                elif kind == "update_progress":
                    self.update_progress["value"] = float(value) * 100
                elif kind == "update_ready":
                    update, executable = value
                    self.update_progress["value"] = 100
                    self.update_status.config(text="Verified. Ready to restart.")
                    if messagebox.askyesno(
                        "Install update?",
                        f"{update.name} was downloaded and its SHA-256 checksum passed.\n\n"
                        "Restart Blocksmith and install it now?",
                    ):
                        if update.channel == "Development":
                            self.settings["development_release_id"] = update.release_id
                            self.storage.save_settings(self.settings)
                        try:
                            self.updater.apply_and_restart(executable)
                            self.destroy()
                        except Exception as exc:
                            self.update_button.config(state="normal")
                            messagebox.showerror("Update failed", str(exc))
                    else:
                        self.update_button.config(state="normal")
                elif kind == "update_error":
                    error, silent = value
                    self.update_status.config(text="Update check failed.")
                    self.update_button.config(state="normal" if self.available_update else "disabled")
                    self.log_message(f"Updater: {error}")
                    if not silent:
                        messagebox.showerror("Blocksmith update", str(error))
                elif kind == "done":
                    self.busy = False
                    self.play_button.config(state="normal")
                    self.install_button.config(state="normal")
                    self.status_label.config(text="Ready")
                    if self.mod_progress["value"] >= 100:
                        self.mod_status.config(text="Download complete")
                    else:
                        self.mod_status.config(text="Ready")
                    self.refresh_profiles()
                elif kind == "error":
                    self.busy = False
                    self.play_button.config(state="normal")
                    self.install_button.config(state="normal")
                    self.status_label.config(text="Something went wrong")
                    self.mod_status.config(text="Download failed")
                    self.log_message(f"ERROR: {value}")
                    messagebox.showerror("Blocksmith", str(value))
        except queue.Empty:
            pass
        self.after(80, self._poll_events)


def main() -> None:
    BlocksmithApp().mainloop()


if __name__ == "__main__":
    main()
