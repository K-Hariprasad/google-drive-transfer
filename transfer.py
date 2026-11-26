#!/usr/bin/env python3
"""
Google Drive File Transfer Script
Transfers selected files listed in a text file from a public Google Drive folder
to a specified destination folder in your Google Drive account.
"""

import os
import sys
import re
import json
import argparse
import tempfile
from datetime import datetime

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    COLOR_ENABLED = True
except ImportError:
    COLOR_ENABLED = False
    class Fore:
        GREEN = RED = YELLOW = CYAN = BLUE = MAGENTA = WHITE = RESET = ""
    class Style:
        BRIGHT = NORMAL = RESET_ALL = ""

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# Required Drive scopes: full drive access allows reading public folders and writing to destination
SCOPES = ['https://www.googleapis.com/auth/drive']


def print_banner():
    banner = f"""
{Fore.CYAN}{Style.BRIGHT}=============================================================
           GOOGLE DRIVE SELECTIVE FILE TRANSFER TOOL         
============================================================={Style.RESET_ALL}
"""
    print(banner)


def print_credentials_guide(credentials_path: str):
    print(f"\n{Fore.RED}{Style.BRIGHT}[ERROR] Credentials file not found: '{credentials_path}'{Style.RESET_ALL}")
    print(f"\n{Fore.YELLOW}{Style.BRIGHT}=== How to get your Google Drive credentials.json (One-time setup) ==={Style.RESET_ALL}")
    print("""
1. Open Google Cloud Console:
   https://console.cloud.google.com/

2. Create a new project (or select an existing one):
   Click the project dropdown at the top -> "New Project" -> Name it (e.g. "DriveTransfer") -> Create.

3. Enable the Google Drive API:
   - Go to "APIs & Services" -> "Library".
   - Search for "Google Drive API" and click "Enable".

4. Configure the OAuth Consent Screen:
   - Go to "APIs & Services" -> "OAuth consent screen".
   - Choose "External" (or "Internal" if you have Google Workspace) -> Click "Create".
   - App name: "Drive Transfer Script"
   - User support email: Select your email
   - Developer contact email: Enter your email
   - Click "Save and Continue" through Scopes.
   - Under "Test users", click "+ ADD USERS" and add the Google email address of the account you want to copy files INTO.
   - Click "Save and Continue".

5. Create OAuth Client ID:
   - Go to "APIs & Services" -> "Credentials".
   - Click "+ CREATE CREDENTIALS" -> "OAuth client ID".
   - Application type: "Desktop app".
   - Name: "Drive Transfer CLI".
   - Click "Create".

6. Download JSON:
   - Download the JSON file and rename it to:
     credentials.json
   - Place credentials.json into this project directory:
     """ + os.path.abspath(credentials_path) + """

Then run this script again!
""")


def extract_folder_id(url_or_id: str) -> str:
    """Extract folder ID from URL or return raw folder ID."""
    if not url_or_id:
        return ""
    text = url_or_id.strip()
    
    # Check for /folders/<ID>
    m = re.search(r"folders/([a-zA-Z0-9_-]+)", text)
    if m:
        return m.group(1)
    
    # Check for id=<ID> parameter
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", text)
    if m:
        return m.group(1)
        
    # Check for raw alphanumeric ID (typically 25 to 45 chars)
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", text):
        return text
        
    raise ValueError(f"Could not extract a valid Google Drive folder ID from: '{text}'")


def authenticate_drive(credentials_file: str = "credentials.json", token_file: str = "token.json"):
    """Authenticate and return Google Drive API service instance."""
    creds = None
    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] Existing token.json could not be loaded ({e}), re-authenticating...{Style.RESET_ALL}")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"{Fore.YELLOW}[WARN] Token refresh failed ({e}), requesting new authorization...{Style.RESET_ALL}")
                creds = None

        if not creds or not creds.valid:
            if not os.path.exists(credentials_file):
                print_credentials_guide(credentials_file)
                sys.exit(1)

            print(f"{Fore.CYAN}[AUTH] Launching browser for Google Drive authorization...{Style.RESET_ALL}")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials for future runs
        try:
            with open(token_file, 'w', encoding='utf-8') as token:
                token.write(creds.to_json())
            print(f"{Fore.GREEN}[AUTH] Authentication successful! Saved session to {token_file}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] Could not save token to file: {e}{Style.RESET_ALL}")

    return build('drive', 'v3', credentials=creds)


def verify_folder(service, folder_id: str, label: str = "Folder") -> dict:
    """Verify that a folder exists and is accessible."""
    try:
        folder = service.files().get(
            fileId=folder_id,
            fields='id, name, mimeType',
            supportsAllDrives=True
        ).execute()
        return folder
    except HttpError as err:
        raise RuntimeError(f"Cannot access {label} (ID: {folder_id}): {err.reason}")
    except Exception as err:
        raise RuntimeError(f"Cannot access {label} (ID: {folder_id}): {err}")


def fetch_all_files_in_folder(service, folder_id: str) -> list:
    """Retrieve all files contained directly in the given folder."""
    files = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"

    while True:
        results = service.files().list(
            q=query,
            pageSize=1000,
            fields="nextPageToken, files(id, name, mimeType, size)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageToken=page_token
        ).execute()

        items = results.get('files', [])
        files.extend(items)
        page_token = results.get('nextPageToken')
        if not page_token:
            break

    return files


def load_file_list(file_path: str) -> list:
    """Read the file names to transfer from the text file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File list '{file_path}' does not exist.")

    requested_files = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            clean = line.strip()
            # Ignore empty lines and lines starting with #
            if clean and not clean.startswith('#'):
                requested_files.append(clean)

    return requested_files


def copy_file_server_side(service, source_file_id: str, file_name: str, dest_folder_id: str) -> dict:
    """Attempt direct server-side copy in Google Drive."""
    body = {
        'name': file_name,
        'parents': [dest_folder_id]
    }
    return service.files().copy(
        fileId=source_file_id,
        body=body,
        supportsAllDrives=True
    ).execute()


def copy_file_stream_fallback(service, source_file_id: str, file_name: str, dest_folder_id: str, mime_type: str = None) -> dict:
    """
    Fallback method: Stream download file to a temporary file,
    then upload it to the destination folder.
    """
    # Create a temporary file on disk to handle any file size safely
    with tempfile.NamedTemporaryFile(delete=False) as temp_f:
        temp_path = temp_f.name

    try:
        # Download
        request = service.files().get_media(fileId=source_file_id, supportsAllDrives=True)
        with open(temp_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request, chunksize=1024 * 1024 * 5)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        # Upload
        media = MediaFileUpload(
            temp_path,
            mimetype=mime_type or 'application/octet-stream',
            resumable=True
        )
        body = {
            'name': file_name,
            'parents': [dest_folder_id]
        }
        created = service.files().create(
            body=body,
            media_body=media,
            fields='id, name',
            supportsAllDrives=True
        ).execute()
        return created
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def transfer_files(service, source_folder_id: str, dest_folder_id: str, file_names: list, dry_run: bool = False, callback=None, stop_event=None):
    """
    Main transfer loop.
    Iterates through each file name requested, matches in source folder,
    and copies to destination. Errors in one item DO NOT terminate the loop.
    Supports optional progress callbacks and cancellation via stop_event.
    """
    if callback:
        callback('scan_start', {'source_folder_id': source_folder_id})
    print(f"\n{Fore.CYAN}[SCAN] Indexing files in source folder...{Style.RESET_ALL}")
    source_files = fetch_all_files_in_folder(service, source_folder_id)
    print(f"{Fore.GREEN}[SCAN] Found {len(source_files)} total files in source folder.{Style.RESET_ALL}\n")
    if callback:
        callback('scan_done', {'total_source_files': len(source_files), 'source_files': source_files})

    # Build lookup dictionaries: exact match and case-insensitive match
    exact_lookup = {}
    lower_lookup = {}
    for item in source_files:
        name = item['name']
        exact_lookup[name] = item
        lower_lookup[name.lower()] = item

    success_list = []
    failed_list = []
    total = len(file_names)

    print(f"{Fore.CYAN}{Style.BRIGHT}Starting transfer of {total} requested file(s)...{Style.RESET_ALL}")
    print("-" * 65)

    for idx, target_name in enumerate(file_names, 1):
        if stop_event and stop_event.is_set():
            print(f"{Fore.YELLOW}[CANCELLED] Transfer stopped by user.{Style.RESET_ALL}")
            if callback:
                callback('cancelled', {'index': idx, 'total': total})
            break

        prefix = f"[{idx}/{total}] {target_name}"
        if callback:
            callback('file_start', {'index': idx, 'total': total, 'file_name': target_name})

        # 1. Check if file exists in source folder
        matched_item = exact_lookup.get(target_name)
        case_fallback_used = False

        if not matched_item:
            matched_item = lower_lookup.get(target_name.lower())
            if matched_item:
                case_fallback_used = True

        if not matched_item:
            error_msg = "Not found in source folder"
            print(f"{prefix} ... {Fore.RED}{Style.BRIGHT}[FAILED]{Style.RESET_ALL} ({error_msg})")
            failed_entry = {
                'name': target_name,
                'reason': error_msg,
                'source_id': None
            }
            failed_list.append(failed_entry)
            if callback:
                callback('file_failed', {'index': idx, 'total': total, 'file_name': target_name, 'reason': error_msg})
            continue

        source_file_id = matched_item['id']
        actual_name = matched_item['name']
        mime_type = matched_item.get('mimeType', '')

        if dry_run:
            note = f" (case match: '{actual_name}')" if case_fallback_used else ""
            print(f"{prefix} ... {Fore.YELLOW}[DRY RUN - OK]{Style.RESET_ALL}{note} (ID: {source_file_id})")
            success_entry = {
                'name': target_name,
                'actual_name': actual_name,
                'id': source_file_id,
                'method': 'Dry-run verification'
            }
            success_list.append(success_entry)
            if callback:
                callback('file_success', {'index': idx, 'total': total, 'file_name': target_name, 'actual_name': actual_name, 'method': 'Dry-run verification'})
            continue

        # 2. Attempt transfer: Primary = Server-side copy, Fallback = Stream
        try:
            try:
                # Fast server-side copy
                new_file = copy_file_server_side(service, source_file_id, actual_name, dest_folder_id)
                method = "Server-side copy"
            except Exception as copy_err:
                # Fallback to download & upload
                new_file = copy_file_stream_fallback(service, source_file_id, actual_name, dest_folder_id, mime_type)
                method = "Streamed copy (fallback)"

            note = f" (matched as '{actual_name}')" if case_fallback_used else ""
            print(f"{prefix} ... {Fore.GREEN}{Style.BRIGHT}[SUCCESS]{Style.RESET_ALL} ({method}){note}")
            success_entry = {
                'name': target_name,
                'actual_name': actual_name,
                'new_id': new_file.get('id'),
                'method': method
            }
            success_list.append(success_entry)
            if callback:
                callback('file_success', {'index': idx, 'total': total, 'file_name': target_name, 'actual_name': actual_name, 'method': method, 'new_id': new_file.get('id')})

        except HttpError as http_err:
            reason = f"HTTP {http_err.resp.status}: {http_err.reason}"
            print(f"{prefix} ... {Fore.RED}{Style.BRIGHT}[FAILED]{Style.RESET_ALL} ({reason})")
            failed_entry = {
                'name': target_name,
                'reason': reason,
                'source_id': source_file_id
            }
            failed_list.append(failed_entry)
            if callback:
                callback('file_failed', {'index': idx, 'total': total, 'file_name': target_name, 'reason': reason})
        except Exception as ex:
            reason = str(ex)
            print(f"{prefix} ... {Fore.RED}{Style.BRIGHT}[FAILED]{Style.RESET_ALL} ({reason})")
            failed_entry = {
                'name': target_name,
                'reason': reason,
                'source_id': source_file_id
            }
            failed_list.append(failed_entry)
            if callback:
                callback('file_failed', {'index': idx, 'total': total, 'file_name': target_name, 'reason': reason})

    print("-" * 65)
    return success_list, failed_list


def print_summary_and_save_report(success_list: list, failed_list: list, source_folder: str, dest_folder: str, files_file: str):
    """Print the final summary table and save a detailed report to a file."""
    total = len(success_list) + len(failed_list)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{Fore.CYAN}{Style.BRIGHT}=============================================================")
    print(f"                       TRANSFER REPORT                       ")
    print(f"============================================================={Style.RESET_ALL}")
    print(f" Timestamp:      {timestamp}")
    print(f" Source Folder:  {source_folder}")
    print(f" Dest Folder:    {dest_folder}")
    print(f" Files Input:    {files_file}")
    print("-" * 65)
    print(f" Total Requested: {Fore.WHITE}{Style.BRIGHT}{total}{Style.RESET_ALL}")
    print(f" Succeeded:       {Fore.GREEN}{Style.BRIGHT}{len(success_list)}{Style.RESET_ALL}")
    print(f" Failed:          {Fore.RED if failed_list else Fore.WHITE}{Style.BRIGHT}{len(failed_list)}{Style.RESET_ALL}")
    print("-" * 65)

    if failed_list:
        print(f"\n{Fore.RED}{Style.BRIGHT}[!] LIST OF FAILED TRANSFERS ({len(failed_list)}):{Style.RESET_ALL}")
        for idx, item in enumerate(failed_list, 1):
            print(f"  {idx}. {Fore.RED}{item['name']}{Style.RESET_ALL}")
            print(f"     Reason: {item['reason']}")
    else:
        print(f"\n{Fore.GREEN}{Style.BRIGHT}[✓] All requested files were transferred successfully!{Style.RESET_ALL}")

    # Write report to disk
    report_filename = f"transfer_report_{file_timestamp}.txt"
    try:
        with open(report_filename, 'w', encoding='utf-8') as rf:
            rf.write("=============================================================\n")
            rf.write("               GOOGLE DRIVE TRANSFER REPORT                 \n")
            rf.write("=============================================================\n")
            rf.write(f"Date/Time:      {timestamp}\n")
            rf.write(f"Source Folder:  {source_folder}\n")
            rf.write(f"Dest Folder:    {dest_folder}\n")
            rf.write(f"File List:      {files_file}\n")
            rf.write("-------------------------------------------------------------\n")
            rf.write(f"Total Processed: {total}\n")
            rf.write(f"Successful:      {len(success_list)}\n")
            rf.write(f"Failed:          {len(failed_list)}\n")
            rf.write("-------------------------------------------------------------\n\n")

            if failed_list:
                rf.write("=== FAILED TRANSFERS ===\n")
                for idx, item in enumerate(failed_list, 1):
                    rf.write(f"{idx}. File:   {item['name']}\n")
                    rf.write(f"   Reason: {item['reason']}\n")
                    if item.get('source_id'):
                        rf.write(f"   Source File ID: {item['source_id']}\n")
                    rf.write("\n")

            if success_list:
                rf.write("=== SUCCESSFUL TRANSFERS ===\n")
                for idx, item in enumerate(success_list, 1):
                    rf.write(f"{idx}. File:   {item['name']}\n")
                    if item.get('actual_name') and item['actual_name'] != item['name']:
                        rf.write(f"   Matched As: {item['actual_name']}\n")
                    rf.write(f"   Method: {item.get('method', 'Copied')}\n")
                    if item.get('new_id'):
                        rf.write(f"   New File ID: {item['new_id']}\n")
                    rf.write("\n")

        print(f"\n{Fore.CYAN}[REPORT] Detailed report saved to: {Style.BRIGHT}{report_filename}{Style.RESET_ALL}")
        return report_filename
    except Exception as e:
        print(f"\n{Fore.YELLOW}[WARN] Could not save report file: {e}{Style.RESET_ALL}")
        return None


def load_config(config_path: str = "config.json") -> dict:
    """Load configuration from config.json if present."""
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] Could not parse '{config_path}': {e}{Style.RESET_ALL}")
    return {}


def main():
    print_banner()

    parser = argparse.ArgumentParser(
        description="Copy specific files from a public Google Drive folder to your destination Drive folder."
    )
    parser.add_argument("--gui", action="store_true", help="Launch the graphical user interface (GUI)")
    parser.add_argument("--source", "-s", help="Public Google Drive folder URL or ID")
    parser.add_argument("--dest", "-d", help="Destination Google Drive folder URL or ID")
    parser.add_argument("--files", "-f", default="files-to-transfer.txt", help="Path to text file containing file names (default: files-to-transfer.txt)")
    parser.add_argument("--config", "-c", default="config.json", help="Path to JSON config file (default: config.json)")
    parser.add_argument("--dry-run", action="store_true", help="Verify matching files without actually copying them")
    parser.add_argument("--list-source", action="store_true", help="List all files available in the public source folder and exit")
    parser.add_argument("--credentials", default="credentials.json", help="Path to credentials.json (default: credentials.json)")
    parser.add_argument("--token", default="token.json", help="Path to token.json (default: token.json)")

    args = parser.parse_args()

    if args.gui:
        import gui
        gui.main()
        return

    # Load configuration file defaults
    cfg = load_config(args.config)
    source_input = args.source or cfg.get("source_folder_url") or cfg.get("source_folder_id")
    dest_input = args.dest or cfg.get("destination_folder_url") or cfg.get("destination_folder_id")
    files_input = args.files or cfg.get("files_to_transfer_path") or "files-to-transfer.txt"

    # Interactive prompts if still not provided
    if not source_input:
        source_input = input(f"{Fore.YELLOW}Enter Public Source Drive Folder URL or ID: {Style.RESET_ALL}").strip()
    if not source_input:
        print(f"{Fore.RED}[ERROR] Source folder is required.{Style.RESET_ALL}")
        sys.exit(1)

    try:
        source_folder_id = extract_folder_id(source_input)
    except ValueError as e:
        print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
        sys.exit(1)

    # Authenticate with Google Drive
    service = authenticate_drive(credentials_file=args.credentials, token_file=args.token)

    # If --list-source flag is set, just list files and exit
    if args.list_source:
        print(f"\n{Fore.CYAN}[INFO] Listing files in source folder ({source_folder_id})...{Style.RESET_ALL}")
        try:
            files = fetch_all_files_in_folder(service, source_folder_id)
            print(f"\n{Fore.GREEN}Found {len(files)} files:{Style.RESET_ALL}")
            for idx, item in enumerate(files, 1):
                size_str = f"({int(item.get('size', 0)) / 1024:.1f} KB)" if 'size' in item else ""
                print(f" {idx:4d}. {item['name']} {size_str}")
            return
        except Exception as e:
            print(f"{Fore.RED}[ERROR] Failed to list source files: {e}{Style.RESET_ALL}")
            sys.exit(1)

    if not dest_input:
        dest_input = input(f"{Fore.YELLOW}Enter Destination Drive Folder URL or ID: {Style.RESET_ALL}").strip()
    if not dest_input:
        print(f"{Fore.RED}[ERROR] Destination folder is required.{Style.RESET_ALL}")
        sys.exit(1)

    try:
        dest_folder_id = extract_folder_id(dest_input)
    except ValueError as e:
        print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
        sys.exit(1)

    # Verify destination folder access
    print(f"\n{Fore.CYAN}[VERIFY] Checking destination folder access...{Style.RESET_ALL}")
    try:
        dest_meta = verify_folder(service, dest_folder_id, label="Destination Folder")
        print(f"{Fore.GREEN}[VERIFY] Destination folder verified: '{dest_meta.get('name')}' (ID: {dest_folder_id}){Style.RESET_ALL}")
    except RuntimeError as e:
        print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Tip: Ensure your authenticated account has 'Editor' or 'Owner' permission on the destination folder.{Style.RESET_ALL}")
        sys.exit(1)

    # Read list of files to transfer
    try:
        files_to_transfer = load_file_list(files_input)
    except FileNotFoundError as e:
        print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Please create '{files_input}' and add the file names you want to copy (one per line).{Style.RESET_ALL}")
        sys.exit(1)

    if not files_to_transfer:
        print(f"{Fore.YELLOW}[WARN] '{files_input}' is empty or contains only comments/blank lines. Nothing to transfer.{Style.RESET_ALL}")
        sys.exit(0)

    # Run the transfer process
    success_list, failed_list = transfer_files(
        service=service,
        source_folder_id=source_folder_id,
        dest_folder_id=dest_folder_id,
        file_names=files_to_transfer,
        dry_run=args.dry_run
    )

    # Summary report
    print_summary_and_save_report(
        success_list=success_list,
        failed_list=failed_list,
        source_folder=source_folder_id,
        dest_folder=dest_folder_id,
        files_file=files_input
    )


if __name__ == "__main__":
    main()

