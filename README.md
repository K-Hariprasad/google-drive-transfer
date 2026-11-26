# Google Drive Selective File Transfer (GUI & CLI)

A modern, fault-tolerant tool to selectively copy files (images, documents, etc.) from a **public Google Drive folder** into a folder in your **Google Drive account**.

Available as a **Modern Desktop GUI** (with folder browsing, search, checkboxes, and real-time logs) or as a **Command-Line Tool**.

---

## 🚀 Quick Launch (UI)

Simply double-click:
```text
run_ui.bat
```
Or run from your terminal:
```powershell
python gui.py
```
*(You can also run `python transfer.py --gui`)*

---

## 🌟 What the UI Offers

1. **No Manual File/Code Editing**:
   - Paste the public Drive URL and your destination folder URL directly in the UI.
   - Click **"🔍 Scan Public Folder"** to inspect and list all files contained in the public drive folder.
2. **Interactive Selection (Checkboxes + Search)**:
   - Browse files in the folder with file sizes displayed.
   - Use the **Search/Filter** bar (e.g. type `.jpg` or `IMG_`) to instantly filter items.
   - Click **"Select All"**, **"Deselect All"**, or pick individual items with checkboxes.
3. **Manual / File Import Tab**:
   - Prefer typing or pasting file names? Switch to the **"📝 Manual File List"** tab to paste names or click **"Load from .txt"**.
4. **Live Progress & Fault Tolerance**:
   - Shows progress bar, current file being transferred, and live colored logs.
   - If one file fails (not found, network glitch, permission issue), **the transfer does not terminate**; it proceeds to the next file.
5. **Summary & Reports**:
   - Shows total processed, successes, and failures in real time.
   - Click **"📄 Open Report File"** to inspect the full breakdown directly in Notepad.
6. **Auto-Remembers Settings**:
   - Folder links and preferences are automatically saved into `config.json` for your next session.

---

## 🔑 One-Time Setup: `credentials.json`

To allow the app to write files to your destination Google Drive account:

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (e.g., `DriveTransfer`).
3. Enable **Google Drive API** under **APIs & Services > Library**.
4. Configure **OAuth consent screen**:
   - Select **External**, set user support email and developer contact email.
   - Under **Test Users**, click **+ ADD USERS** and enter your Google account email.
5. Create Credentials:
   - Go to **APIs & Services > Credentials** > **+ CREATE CREDENTIALS** > **OAuth client ID**.
   - Choose **Desktop app**, name it `DriveTransfer`, and click **Create**.
6. Download the JSON credential file:
   - Rename the file to `credentials.json`.
   - Place it into this folder:
     `d:\Work\Personal\drive-transfer\credentials.json`

*(On first run, a browser tab will open asking you to sign in to your Google Account. After approving, it saves a `token.json` so you never have to sign in again).*

---

## 💻 CLI Mode (Optional)

If you ever prefer running headless from the command line:

```powershell
# Run with interactive prompts or config.json
python transfer.py

# Specify URLs directly
python transfer.py --source "<PUBLIC_DRIVE_URL>" --dest "<DESTINATION_DRIVE_URL>"

# Dry run (verify matching files without copying)
python transfer.py --dry-run

# List all files available in the public folder
python transfer.py --source "<PUBLIC_DRIVE_URL>" --list-source
```
