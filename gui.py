#!/usr/bin/env python3
"""
Google Drive Selective Transfer - Modern GUI Application
Provides a user-friendly graphical interface to browse public Drive folders,
select files with checkboxes or custom lists, and transfer them safely to another Drive account.
"""

import os
import sys
import json
import threading
import webbrowser
from datetime import datetime

# Suppress harmless font warnings from customtkinter on Windows
import io
_orig_stderr = sys.stderr
sys.stderr = io.StringIO()
try:
    import customtkinter as ctk
    from tkinter import filedialog, messagebox
finally:
    sys.stderr = _orig_stderr

import transfer

# Configure appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class DriveTransferApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Google Drive Selective File Transfer")
        self.geometry("980 x 820")
        self.minsize(860, 700)

        # State variables
        self.service = None
        self.scanned_files = []          # List of file dicts from source folder
        self.file_checkbox_vars = {}     # Mapping of file_id -> BooleanVar
        self.file_checkbox_widgets = []  # List of (file_id, checkbox_widget, name, size_str)
        self.is_running = False
        self.stop_event = threading.Event()
        self.last_report_path = None

        # Load initial config
        self.config_data = self.load_initial_config()

        # Build UI
        self.create_widgets()
        self.check_credentials_status()

    def load_initial_config(self) -> dict:
        cfg = transfer.load_config("config.json")
        return {
            "source_folder_url": cfg.get("source_folder_url", ""),
            "destination_folder_url": cfg.get("destination_folder_url", ""),
            "files_to_transfer_path": cfg.get("files_to_transfer_path", "files-to-transfer.txt"),
        }

    def save_current_config(self):
        cfg = {
            "source_folder_url": self.source_entry.get().strip(),
            "destination_folder_url": self.dest_entry.get().strip(),
            "files_to_transfer_path": "files-to-transfer.txt"
        }
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def create_widgets(self):
        # Grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # File selection area expands
        self.grid_rowconfigure(4, weight=1)  # Log area expands

        # =====================================================================
        # 1. HEADER SECTION
        # =====================================================================
        header_frame = ctk.CTkFrame(self, corner_radius=10)
        header_frame.grid(row=0, column=0, padx=15, pady=(15, 8), sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)

        title_label = ctk.CTkLabel(
            header_frame,
            text="📁 Google Drive Selective Transfer",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.grid(row=0, column=0, padx=15, pady=(10, 2), sticky="w")

        subtitle_label = ctk.CTkLabel(
            header_frame,
            text="Transfer specific images or files between Google Drive folders with automatic error recovery",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        subtitle_label.grid(row=1, column=0, padx=15, pady=(0, 10), sticky="w")

        # Credentials status badge & setup button
        badge_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        badge_frame.grid(row=0, column=2, rowspan=2, padx=15, pady=10, sticky="e")

        self.cred_badge = ctk.CTkLabel(
            badge_frame,
            text="Checking credentials...",
            font=ctk.CTkFont(size=12, weight="bold"),
            padx=10,
            pady=4,
            corner_radius=6
        )
        self.cred_badge.pack(side="left", padx=5)

        self.cred_help_btn = ctk.CTkButton(
            badge_frame,
            text="Credentials Help",
            width=110,
            command=self.show_credentials_guide
        )
        self.cred_help_btn.pack(side="left", padx=5)

        # =====================================================================
        # 2. FOLDER INPUTS SECTION
        # =====================================================================
        folders_frame = ctk.CTkFrame(self, corner_radius=10)
        folders_frame.grid(row=1, column=0, padx=15, pady=5, sticky="ew")
        folders_frame.grid_columnconfigure(1, weight=1)

        # Source folder row
        src_label = ctk.CTkLabel(folders_frame, text="Public Source Folder URL / ID:", font=ctk.CTkFont(weight="bold"))
        src_label.grid(row=0, column=0, padx=12, pady=8, sticky="w")

        self.source_entry = ctk.CTkEntry(folders_frame, placeholder_text="Paste public Google Drive folder link or ID here...")
        self.source_entry.insert(0, self.config_data.get("source_folder_url", ""))
        self.source_entry.grid(row=0, column=1, padx=8, pady=8, sticky="ew")

        self.scan_btn = ctk.CTkButton(
            folders_frame,
            text="🔍 Scan Public Folder",
            width=150,
            fg_color="#1f538d",
            hover_color="#14375e",
            command=self.on_scan_source_folder
        )
        self.scan_btn.grid(row=0, column=2, padx=12, pady=8)

        # Destination folder row
        dst_label = ctk.CTkLabel(folders_frame, text="Destination Folder URL / ID:", font=ctk.CTkFont(weight="bold"))
        dst_label.grid(row=1, column=0, padx=12, pady=8, sticky="w")

        self.dest_entry = ctk.CTkEntry(folders_frame, placeholder_text="Paste your destination Google Drive folder link or ID here...")
        self.dest_entry.insert(0, self.config_data.get("destination_folder_url", ""))
        self.dest_entry.grid(row=1, column=1, padx=8, pady=8, sticky="ew")

        self.verify_dest_btn = ctk.CTkButton(
            folders_frame,
            text="✔ Verify Access",
            width=150,
            command=self.on_verify_destination
        )
        self.verify_dest_btn.grid(row=1, column=2, padx=12, pady=8)

        # =====================================================================
        # 3. FILE SELECTION SECTION (TABVIEW: EXPLORER vs MANUAL LIST)
        # =====================================================================
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.grid(row=2, column=0, padx=15, pady=5, sticky="nsew")

        tab_explorer = self.tabview.add("📁 Public Folder Explorer (Checkboxes)")
        tab_manual = self.tabview.add("📝 Manual File List (.txt / Paste)")

        # --- TAB 1: EXPLORER WITH CHECKBOXES ---
        tab_explorer.grid_columnconfigure(0, weight=1)
        tab_explorer.grid_rowconfigure(1, weight=1)

        # Explorer controls row (Filter, Select All, etc.)
        exp_controls = ctk.CTkFrame(tab_explorer, fg_color="transparent")
        exp_controls.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        exp_controls.grid_columnconfigure(1, weight=1)

        filter_label = ctk.CTkLabel(exp_controls, text="Filter / Search:")
        filter_label.grid(row=0, column=0, padx=(5, 5), sticky="w")

        self.filter_entry = ctk.CTkEntry(exp_controls, placeholder_text="Search files (e.g. .jpg, IMG_)...")
        self.filter_entry.grid(row=0, column=1, padx=5, sticky="ew")
        self.filter_entry.bind("<KeyRelease>", self.on_filter_changed)

        btn_select_all = ctk.CTkButton(exp_controls, text="Select All", width=85, command=self.on_select_all)
        btn_select_all.grid(row=0, column=2, padx=4)

        btn_deselect_all = ctk.CTkButton(exp_controls, text="Deselect All", width=95, command=self.on_deselect_all)
        btn_deselect_all.grid(row=0, column=3, padx=4)

        btn_sync_to_text = ctk.CTkButton(
            exp_controls,
            text="Export to Tab 2",
            width=110,
            command=self.sync_explorer_to_manual
        )
        btn_sync_to_text.grid(row=0, column=4, padx=(4, 5))

        self.selection_count_label = ctk.CTkLabel(
            exp_controls,
            text="Selected: 0 files",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#64b5f6"
        )
        self.selection_count_label.grid(row=0, column=5, padx=8)

        # Scrollable list for file checkboxes
        self.files_scroll_frame = ctk.CTkScrollableFrame(tab_explorer, corner_radius=6)
        self.files_scroll_frame.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
        self.files_scroll_frame.grid_columnconfigure(0, weight=1)

        self.empty_explorer_label = ctk.CTkLabel(
            self.files_scroll_frame,
            text="No files scanned yet.\nEnter a Public Source Folder URL above and click 'Scan Public Folder'.",
            text_color="gray",
            font=ctk.CTkFont(size=13)
        )
        self.empty_explorer_label.pack(pady=40)

        # --- TAB 2: MANUAL TEXT BOX / LOAD FROM FILE ---
        tab_manual.grid_columnconfigure(0, weight=1)
        tab_manual.grid_rowconfigure(1, weight=1)

        manual_controls = ctk.CTkFrame(tab_manual, fg_color="transparent")
        manual_controls.grid(row=0, column=0, sticky="ew", pady=(0, 5))

        man_desc = ctk.CTkLabel(
            manual_controls,
            text="Enter file names to transfer (one per line, # for comments):",
            text_color="gray"
        )
        man_desc.pack(side="left", padx=5)

        btn_load_txt = ctk.CTkButton(
            manual_controls,
            text="📂 Load from .txt",
            width=120,
            command=self.load_from_txt_file
        )
        btn_load_txt.pack(side="right", padx=5)

        btn_save_txt = ctk.CTkButton(
            manual_controls,
            text="💾 Save to .txt",
            width=110,
            command=self.save_to_txt_file
        )
        btn_save_txt.pack(side="right", padx=5)

        # Textbox for file names
        self.manual_textbox = ctk.CTkTextbox(tab_manual, font=ctk.CTkFont(family="Consolas", size=12))
        self.manual_textbox.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)

        # Pre-fill with files-to-transfer.txt if exists
        self.load_default_txt_content()

        # =====================================================================
        # 4. EXECUTION CONTROLS & PROGRESS
        # =====================================================================
        action_frame = ctk.CTkFrame(self, corner_radius=10)
        action_frame.grid(row=3, column=0, padx=15, pady=5, sticky="ew")
        action_frame.grid_columnconfigure(2, weight=1)

        self.dry_run_var = ctk.BooleanVar(value=False)
        self.dry_run_check = ctk.CTkCheckBox(
            action_frame,
            text="Dry Run (Verify files exist without copying)",
            variable=self.dry_run_var,
            font=ctk.CTkFont(size=12)
        )
        self.dry_run_check.grid(row=0, column=0, padx=15, pady=8, sticky="w")

        self.start_btn = ctk.CTkButton(
            action_frame,
            text="▶ Start Transfer",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#28a745",
            hover_color="#218838",
            width=160,
            height=36,
            command=self.on_start_transfer
        )
        self.start_btn.grid(row=0, column=1, padx=10, pady=8)

        self.cancel_btn = ctk.CTkButton(
            action_frame,
            text="⏹ Stop Transfer",
            font=ctk.CTkFont(size=14),
            fg_color="#dc3545",
            hover_color="#c82333",
            width=120,
            height=36,
            state="disabled",
            command=self.on_cancel_transfer
        )
        self.cancel_btn.grid(row=0, column=2, padx=10, pady=8, sticky="w")

        # Progress bar & status row
        self.progress_bar = ctk.CTkProgressBar(action_frame)
        self.progress_bar.set(0.0)
        self.progress_bar.grid(row=1, column=0, columnspan=3, padx=15, pady=(2, 4), sticky="ew")

        self.status_label = ctk.CTkLabel(
            action_frame,
            text="Ready",
            font=ctk.CTkFont(size=12),
            text_color="#81c784"
        )
        self.status_label.grid(row=2, column=0, columnspan=3, padx=15, pady=(0, 6), sticky="w")

        # =====================================================================
        # 5. CONSOLE / ACTIVITY LOG
        # =====================================================================
        log_frame = ctk.CTkFrame(self, corner_radius=10)
        log_frame.grid(row=4, column=0, padx=15, pady=(5, 15), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))
        log_header.grid_columnconfigure(0, weight=1)

        log_title = ctk.CTkLabel(log_header, text="Activity Log & Results:", font=ctk.CTkFont(weight="bold"))
        log_title.grid(row=0, column=0, sticky="w")

        self.summary_badge = ctk.CTkLabel(
            log_header,
            text="",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.summary_badge.grid(row=0, column=1, padx=10)

        self.btn_open_report = ctk.CTkButton(
            log_header,
            text="📄 Open Report File",
            width=130,
            height=26,
            state="disabled",
            command=self.open_last_report
        )
        self.btn_open_report.grid(row=0, column=2, padx=4)

        btn_clear_log = ctk.CTkButton(
            log_header,
            text="Clear Log",
            width=80,
            height=26,
            fg_color="#555",
            hover_color="#444",
            command=self.clear_log
        )
        btn_clear_log.grid(row=0, column=3, padx=(4, 0))

        self.log_textbox = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word"
        )
        self.log_textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 10))

    # =========================================================================
    # HELPERS & CREDENTIALS
    # =========================================================================
    def check_credentials_status(self):
        has_creds = os.path.exists("credentials.json")
        has_token = os.path.exists("token.json")

        if has_creds or has_token:
            self.cred_badge.configure(
                text="✓ Credentials Ready",
                fg_color="#2e7d32",
                text_color="white"
            )
        else:
            self.cred_badge.configure(
                text="⚠ credentials.json Missing",
                fg_color="#e65100",
                text_color="white"
            )

    def show_credentials_guide(self):
        guide = """How to get your free Google Drive credentials.json:

1. Open Google Cloud Console:
   https://console.cloud.google.com/
2. Create a project (e.g. 'DriveTransfer').
3. Enable 'Google Drive API' under APIs & Services > Library.
4. Set up OAuth Consent Screen (External, add your Google account under Test Users).
5. Create Credentials > OAuth client ID > Desktop app.
6. Download the JSON, rename it to 'credentials.json', and place it in this folder.

Would you like to open Google Cloud Console now?"""
        if messagebox.askyesno("Google Drive Credentials Setup", guide):
            webbrowser.open("https://console.cloud.google.com/apis/credentials")

    def log(self, message: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{timestamp}] "
        full_line = f"{prefix}{message}\n"

        self.log_textbox.insert("end", full_line)
        self.log_textbox.see("end")

    def clear_log(self):
        self.log_textbox.delete("1.0", "end")
        self.summary_badge.configure(text="")

    def set_status(self, text: str, color: str = "#81c784"):
        self.status_label.configure(text=text, text_color=color)

    def load_default_txt_content(self):
        path = "files-to-transfer.txt"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.manual_textbox.delete("1.0", "end")
                self.manual_textbox.insert("1.0", content)
            except Exception:
                pass

    def load_from_txt_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Text File with File Names",
            filetypes=[("Text Files (*.txt)", "*.txt"), ("All Files (*.*)", "*.*")]
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.manual_textbox.delete("1.0", "end")
                self.manual_textbox.insert("1.0", content)
                self.log(f"Loaded file list from: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load file: {e}")

    def save_to_txt_file(self):
        file_path = filedialog.asksaveasfilename(
            title="Save File Names to Text File",
            defaultextension=".txt",
            initialfile="files-to-transfer.txt",
            filetypes=[("Text Files (*.txt)", "*.txt")]
        )
        if file_path:
            try:
                content = self.manual_textbox.get("1.0", "end").strip()
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content + "\n")
                self.log(f"Saved file list to: {os.path.basename(file_path)}")
                messagebox.showinfo("Saved", "File list saved successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save file: {e}")

    # =========================================================================
    # GOOGLE DRIVE SERVICE ACCESS (THREAD-SAFE)
    # =========================================================================
    def get_service(self):
        if self.service is None:
            self.service = transfer.authenticate_drive()
            self.check_credentials_status()
        return self.service

    # =========================================================================
    # SCAN PUBLIC FOLDER
    # =========================================================================
    def on_scan_source_folder(self):
        url = self.source_entry.get().strip()
        if not url:
            messagebox.showwarning("Input Required", "Please enter a Public Source Folder URL or ID.")
            return

        try:
            folder_id = transfer.extract_folder_id(url)
        except ValueError as e:
            messagebox.showerror("Invalid URL", str(e))
            return

        self.scan_btn.configure(state="disabled", text="Scanning...")
        self.set_status("Scanning source folder...", "#64b5f6")
        self.log(f"Scanning public source folder (ID: {folder_id})...")

        def worker():
            try:
                service = self.get_service()
                files = transfer.fetch_all_files_in_folder(service, folder_id)
                self.after(0, lambda: self.on_scan_completed(files))
            except Exception as e:
                self.after(0, lambda: self.on_scan_failed(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def on_scan_completed(self, files: list):
        self.scan_btn.configure(state="normal", text="🔍 Scan Public Folder")
        self.scanned_files = files
        self.set_status(f"Scan complete: Found {len(files)} files in public folder.", "#81c784")
        self.log(f"Scan complete. Found {len(files)} total files in public folder.")

        # Populate Explorer UI
        self.populate_explorer(files)

    def on_scan_failed(self, error_msg: str):
        self.scan_btn.configure(state="normal", text="🔍 Scan Public Folder")
        self.set_status("Scan failed.", "#ef5350")
        self.log(f"Scan failed: {error_msg}")
        messagebox.showerror("Scan Error", f"Failed to access public folder:\n{error_msg}\n\nMake sure the folder is set to 'Anyone with the link can view'.")

    def populate_explorer(self, files: list):
        # Clear existing
        for widget in self.files_scroll_frame.winfo_children():
            widget.destroy()

        self.file_checkbox_vars.clear()
        self.file_checkbox_widgets.clear()

        if not files:
            lbl = ctk.CTkLabel(self.files_scroll_frame, text="The folder is empty.", text_color="gray")
            lbl.pack(pady=30)
            self.selection_count_label.configure(text="Selected: 0 files")
            return

        for f in files:
            file_id = f['id']
            name = f['name']
            size_bytes = int(f.get('size', 0)) if 'size' in f else 0
            if size_bytes > 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            elif size_bytes > 0:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = ""

            row_frame = ctk.CTkFrame(self.files_scroll_frame, fg_color="transparent")
            row_frame.pack(fill="x", padx=4, pady=2)
            row_frame.grid_columnconfigure(0, weight=1)

            var = ctk.BooleanVar(value=False)
            self.file_checkbox_vars[file_id] = var

            chk = ctk.CTkCheckBox(
                row_frame,
                text=name,
                variable=var,
                command=self.update_selection_counter
            )
            chk.grid(row=0, column=0, sticky="w")

            if size_str:
                size_lbl = ctk.CTkLabel(row_frame, text=size_str, text_color="gray", font=ctk.CTkFont(size=11))
                size_lbl.grid(row=0, column=1, sticky="e", padx=10)

            self.file_checkbox_widgets.append((file_id, row_frame, chk, name, size_str))

        self.update_selection_counter()

    def update_selection_counter(self):
        count = sum(1 for v in self.file_checkbox_vars.values() if v.get())
        total = len(self.file_checkbox_vars)
        self.selection_count_label.configure(text=f"Selected: {count} / {total} files")

    def on_filter_changed(self, event=None):
        query = self.filter_entry.get().strip().lower()
        for file_id, row_frame, chk, name, _ in self.file_checkbox_widgets:
            if not query or query in name.lower():
                row_frame.pack(fill="x", padx=4, pady=2)
            else:
                row_frame.pack_forget()

    def on_select_all(self):
        query = self.filter_entry.get().strip().lower()
        for file_id, row_frame, chk, name, _ in self.file_checkbox_widgets:
            # If search filter is active, only select visible items
            if not query or query in name.lower():
                self.file_checkbox_vars[file_id].set(True)
        self.update_selection_counter()

    def on_deselect_all(self):
        for v in self.file_checkbox_vars.values():
            v.set(False)
        self.update_selection_counter()

    def sync_explorer_to_manual(self):
        """Export all checked files from Tab 1 into the Tab 2 textbox."""
        selected_names = []
        for f in self.scanned_files:
            file_id = f['id']
            if self.file_checkbox_vars.get(file_id, None) and self.file_checkbox_vars[file_id].get():
                selected_names.append(f['name'])

        if not selected_names:
            messagebox.showinfo("Export", "No files are currently selected in the Explorer.")
            return

        self.manual_textbox.delete("1.0", "end")
        self.manual_textbox.insert("1.0", "\n".join(selected_names) + "\n")
        self.tabview.set("📝 Manual File List (.txt / Paste)")
        self.log(f"Exported {len(selected_names)} selected file(s) to Manual List tab.")

    # =========================================================================
    # VERIFY DESTINATION
    # =========================================================================
    def on_verify_destination(self):
        url = self.dest_entry.get().strip()
        if not url:
            messagebox.showwarning("Input Required", "Please enter a Destination Folder URL or ID.")
            return

        try:
            folder_id = transfer.extract_folder_id(url)
        except ValueError as e:
            messagebox.showerror("Invalid URL", str(e))
            return

        self.verify_dest_btn.configure(state="disabled", text="Verifying...")
        self.set_status("Verifying destination folder access...", "#64b5f6")

        def worker():
            try:
                service = self.get_service()
                meta = transfer.verify_folder(service, folder_id, label="Destination Folder")
                folder_name = meta.get("name", "Unknown")
                self.after(0, lambda: self.on_verify_dest_success(folder_name, folder_id))
            except Exception as e:
                self.after(0, lambda: self.on_verify_dest_failed(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def on_verify_dest_success(self, folder_name: str, folder_id: str):
        self.verify_dest_btn.configure(state="normal", text="✔ Verify Access")
        self.set_status(f"Destination verified: '{folder_name}'", "#81c784")
        self.log(f"Destination folder verified: '{folder_name}' (ID: {folder_id})")
        messagebox.showinfo("Verified", f"Destination folder verified successfully!\n\nFolder Name: {folder_name}\nID: {folder_id}")

    def on_verify_dest_failed(self, error_msg: str):
        self.verify_dest_btn.configure(state="normal", text="✔ Verify Access")
        self.set_status("Destination access denied.", "#ef5350")
        self.log(f"Destination verification failed: {error_msg}")
        messagebox.showerror("Access Error", f"Cannot access destination folder:\n{error_msg}\n\nMake sure your signed-in Google account has 'Editor' permission.")

    # =========================================================================
    # START / STOP TRANSFER
    # =========================================================================
    def get_target_files_to_transfer(self) -> list:
        """
        Determines the list of file names to transfer based on:
        1. If user is on the Explorer tab and has checked items -> use checked items.
        2. Otherwise -> use lines from the manual textbox.
        """
        active_tab = self.tabview.get()

        if "Explorer" in active_tab:
            checked_names = []
            for f in self.scanned_files:
                file_id = f['id']
                if self.file_checkbox_vars.get(file_id, None) and self.file_checkbox_vars[file_id].get():
                    checked_names.append(f['name'])
            if checked_names:
                return checked_names

        # Fallback to manual textbox
        raw = self.manual_textbox.get("1.0", "end")
        files = []
        for line in raw.splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#"):
                files.append(clean)
        return files

    def on_start_transfer(self):
        source_url = self.source_entry.get().strip()
        dest_url = self.dest_entry.get().strip()

        if not source_url:
            messagebox.showwarning("Input Required", "Please enter the Public Source Folder URL.")
            return

        if not dest_url:
            messagebox.showwarning("Input Required", "Please enter your Destination Folder URL.")
            return

        try:
            source_folder_id = transfer.extract_folder_id(source_url)
            dest_folder_id = transfer.extract_folder_id(dest_url)
        except ValueError as e:
            messagebox.showerror("Invalid URL", str(e))
            return

        files_to_transfer = self.get_target_files_to_transfer()
        if not files_to_transfer:
            messagebox.showwarning(
                "No Files Selected",
                "Please select files using checkboxes in the 'Explorer' tab, OR enter file names in the 'Manual File List' tab."
            )
            return

        # Auto-save current folder links to config.json
        self.save_current_config()

        # Update UI state
        self.is_running = True
        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.scan_btn.configure(state="disabled")
        self.verify_dest_btn.configure(state="disabled")
        self.btn_open_report.configure(state="disabled")
        self.progress_bar.set(0.0)
        self.summary_badge.configure(text="")

        dry_run = self.dry_run_var.get()
        mode_str = " [DRY RUN]" if dry_run else ""
        self.log(f"--- Starting Transfer{mode_str}: {len(files_to_transfer)} file(s) requested ---")
        self.set_status(f"Starting transfer of {len(files_to_transfer)} file(s)...", "#64b5f6")

        def worker():
            try:
                service = self.get_service()

                def progress_cb(event_type, data):
                    self.after(0, lambda: self.handle_worker_callback(event_type, data))

                success_list, failed_list = transfer.transfer_files(
                    service=service,
                    source_folder_id=source_folder_id,
                    dest_folder_id=dest_folder_id,
                    file_names=files_to_transfer,
                    dry_run=dry_run,
                    callback=progress_cb,
                    stop_event=self.stop_event
                )

                # Generate and save report
                report_file = transfer.print_summary_and_save_report(
                    success_list=success_list,
                    failed_list=failed_list,
                    source_folder=source_folder_id,
                    dest_folder=dest_folder_id,
                    files_file="UI Selection"
                )

                self.after(0, lambda: self.on_transfer_finished(success_list, failed_list, report_file))

            except Exception as e:
                self.after(0, lambda: self.on_transfer_error(str(e)))

        self.transfer_thread = threading.Thread(target=worker, daemon=True)
        self.transfer_thread.start()

    def handle_worker_callback(self, event_type: str, data: dict):
        if event_type == "scan_start":
            self.set_status("Scanning source folder files...", "#64b5f6")

        elif event_type == "file_start":
            idx = data['index']
            total = data['total']
            name = data['file_name']
            pct = (idx - 1) / total
            self.progress_bar.set(pct)
            self.set_status(f"[{idx}/{total}] Transferring: {name} ({int(pct * 100)}%)", "#64b5f6")

        elif event_type == "file_success":
            idx = data['index']
            total = data['total']
            name = data['file_name']
            method = data.get('method', 'Copied')
            self.log(f"✔ [SUCCESS] {name} ({method})")

        elif event_type == "file_failed":
            idx = data['index']
            total = data['total']
            name = data['file_name']
            reason = data['reason']
            self.log(f"✘ [FAILED] {name} - Reason: {reason}")

        elif event_type == "cancelled":
            self.log("⚠ Transfer cancelled by user.")

    def on_transfer_finished(self, success_list: list, failed_list: list, report_file: str):
        self.is_running = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.scan_btn.configure(state="normal")
        self.verify_dest_btn.configure(state="normal")
        self.progress_bar.set(1.0)

        total = len(success_list) + len(failed_list)
        s_count = len(success_list)
        f_count = len(failed_list)

        self.last_report_path = report_file
        if report_file and os.path.exists(report_file):
            self.btn_open_report.configure(state="normal")

        # Update badge
        self.summary_badge.configure(
            text=f"Total: {total} | Success: {s_count} | Failed: {f_count}",
            text_color="#81c784" if f_count == 0 else "#ffb74d"
        )

        status_msg = f"Done! {s_count} Succeeded, {f_count} Failed."
        self.set_status(status_msg, "#81c784" if f_count == 0 else "#ffb74d")
        self.log(f"--- Transfer Finished: {s_count} Succeeded, {f_count} Failed ---")

        if report_file:
            self.log(f"Report saved: {report_file}")

        # Show notification popup
        if f_count == 0:
            messagebox.showinfo("Transfer Complete", f"All {s_count} files were transferred successfully!")
        else:
            messagebox.showwarning(
                "Transfer Completed with Failures",
                f"Transfer finished with:\n\n• {s_count} Succeeded\n• {f_count} Failed\n\nCheck the activity log or report for failure details."
            )

    def on_transfer_error(self, error_msg: str):
        self.is_running = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.scan_btn.configure(state="normal")
        self.verify_dest_btn.configure(state="normal")

        self.set_status(f"Error: {error_msg}", "#ef5350")
        self.log(f"Error during transfer: {error_msg}")
        messagebox.showerror("Transfer Error", f"An error occurred during transfer:\n{error_msg}")

    def on_cancel_transfer(self):
        if self.is_running:
            self.set_status("Stopping transfer after current file...", "#ffb74d")
            self.log("Stopping transfer after current file...")
            self.stop_event.set()
            self.cancel_btn.configure(state="disabled")

    def open_last_report(self):
        if self.last_report_path and os.path.exists(self.last_report_path):
            try:
                os.startfile(self.last_report_path)
            except Exception as e:
                messagebox.showerror("Error", f"Could not open report file: {e}")


def main():
    app = DriveTransferApp()
    app.mainloop()


if __name__ == "__main__":
    main()
