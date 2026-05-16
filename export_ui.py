"""
Salesforce Weekly Data Export -> Google Drive
Automated export downloader — configurable for any Salesforce org.
All settings are read from environment variables / GitHub Secrets.
"""

import os
import re
import json
import logging
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — all values come from environment variables / GitHub Secrets
# ---------------------------------------------------------------------------

SF_CLIENT_ID     = os.environ["SF_CLIENT_ID"]
SF_CLIENT_SECRET = os.environ["SF_CLIENT_SECRET"]
SF_REFRESH_TOKEN = os.environ["SF_REFRESH_TOKEN"]

SF_ORG_DOMAIN   = os.environ["SF_ORG_DOMAIN"]   # e.g. "mycompany.my"
SF_LOGIN_BASE   = f"https://{SF_ORG_DOMAIN}.salesforce.com"
SF_SETUP_BASE   = f"https://{SF_ORG_DOMAIN}.salesforce-setup.com"
DATA_EXPORT_URL = f"{SF_SETUP_BASE}/lightning/setup/DataManagementExport/home"

GDRIVE_FOLDER_ID            = os.environ["GDRIVE_FOLDER_ID"]
GDRIVE_SERVICE_ACCOUNT_JSON = os.environ["GDRIVE_SERVICE_ACCOUNT_JSON"]

HEADLESS     = os.environ.get("HEADLESS", "true").lower() != "false"
DOWNLOAD_DIR = Path("/tmp/sf_exports")
DRIVE_CHUNK  = 50 * 1024 * 1024
WAIT_BETWEEN_DOWNLOADS = int(os.environ.get("WAIT_BETWEEN_DOWNLOADS", "30"))

# ---------------------------------------------------------------------------
# Salesforce OAuth
# ---------------------------------------------------------------------------

def sf_get_access_token() -> str:
    log.info("Getting Salesforce access token via OAuth refresh ...")
    resp = requests.post(f"{SF_LOGIN_BASE}/services/oauth2/token", data={
        "grant_type":    "refresh_token",
        "client_id":     SF_CLIENT_ID,
        "client_secret": SF_CLIENT_SECRET,
        "refresh_token": SF_REFRESH_TOKEN,
    }, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"OAuth token refresh failed: {resp.status_code} {resp.text}")
    log.info("Access token obtained.")
    return resp.json()["access_token"]

# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------

def gdrive_service():
    info = json.loads(GDRIVE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def file_exists_in_drive(service, filename: str, folder_id: str) -> bool:
    results = service.files().list(
        q=f"name='{filename}' and '{folder_id}' in parents and trashed=false",
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    return len(results.get("files", [])) > 0


def upload_file_to_drive(service, local_path: Path, folder_id: str) -> str:
    size_mb = local_path.stat().st_size // 1024 // 1024
    log.info("  Uploading to Drive: %s (%d MB) ...", local_path.name, size_mb)
    file_metadata = {"name": local_path.name, "parents": [folder_id]}
    media = MediaFileUpload(str(local_path), resumable=True, chunksize=DRIVE_CHUNK)
    request = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
        supportsAllDrives=True
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("    Drive upload: %d%%", int(status.progress() * 100))
    log.info("  Uploaded: %s", response.get("webViewLink", ""))
    return response.get("webViewLink", "")

# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def navigate_to_export_page(page):
    log.info("  Navigating to Data Export page ...")
    page.goto(DATA_EXPORT_URL, wait_until="load", timeout=30_000)
    try:
        page.wait_for_selector("iframe", timeout=25_000)
        log.info("  iframe appeared.")
    except PWTimeout:
        log.warning("  No iframe appeared after 25s.")
    time.sleep(10)


def get_export_frame(page, wait_secs=45):
    deadline = time.time() + wait_secs
    while time.time() < deadline:
        for f in page.frames:
            if f.url == page.url:
                continue
            try:
                count = f.evaluate("""
                    () => Array.from(document.querySelectorAll('a'))
                        .filter(a => a.innerText.trim().toLowerCase() === 'download').length
                """)
                if count > 0:
                    log.info("  Export frame found with %d download links: %s", count, f.url[:80])
                    return f, count
            except Exception:
                pass
        time.sleep(2)
    log.warning("  No export frame found. Frames present:")
    for f in page.frames:
        log.warning("    %s", f.url[:100])
    return None, 0

# ---------------------------------------------------------------------------
# Main browser automation
# ---------------------------------------------------------------------------

def run_browser_downloads(access_token: str, drive, folder_id: str, download_dir: Path, run_date: str):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        try:
            log.info("Step 1: Authenticating ...")
            page.goto(f"{SF_LOGIN_BASE}/secur/frontdoor.jsp?sid={access_token}", wait_until="load", timeout=30_000)
            time.sleep(3)

            log.info("Step 2: Bridging to setup domain ...")
            import urllib.parse
            encoded_url = urllib.parse.quote(DATA_EXPORT_URL)
            bridge = f"{SF_LOGIN_BASE}/visualforce/session?url={encoded_url}&sid={access_token}"
            page.goto(bridge, wait_until="load", timeout=30_000)
            time.sleep(5)

            if "salesforce-setup.com" not in page.url:
                log.info("Step 3: Navigating directly to Data Export ...")
                page.goto(DATA_EXPORT_URL, wait_until="load", timeout=30_000)
                time.sleep(8)

            log.info("Current URL: %s", page.url)

            log.info("Waiting for export iframe ...")
            try:
                page.wait_for_selector("iframe", timeout=25_000)
                time.sleep(10)
            except PWTimeout:
                pass

            export_frame, total_links = get_export_frame(page, wait_secs=45)
            if not export_frame:
                raise RuntimeError("Could not find Data Export iframe")
            log.info("Total download links found: %d", total_links)

            zip_names = []
            rows = export_frame.query_selector_all("tr")
            for row in rows:
                try:
                    for a in row.query_selector_all("a"):
                        if a.inner_text().strip().lower() != "download":
                            continue
                        href = a.get_attribute("href") or ""
                        decoded = urllib.parse.unquote(href)
                        m = re.search(r"fileName=([^&'\")\s]+)", decoded)
                        raw_name = m.group(1) if m else f"export_{len(zip_names)+1}.zip"
                        base, ext = raw_name.rsplit(".", 1)
                        zip_name = f"{base}_{run_date}.{ext}"
                        zip_names.append(zip_name)
                        break
                except Exception:
                    pass

            log.info("Found %d file(s) to process.", len(zip_names))

            log.info("Checking Drive for already-uploaded files ...")
            in_drive = [file_exists_in_drive(drive, z, folder_id) for z in zip_names]
            already_count = sum(in_drive)
            log.info("Already in Drive: %d, To download: %d", already_count, len(zip_names) - already_count)

            results = []
            click_index = already_count

            for i, zip_name in enumerate(zip_names, 1):
                log.info("[%d/%d] %s", i, len(zip_names), zip_name)

                if in_drive[i-1]:
                    log.info("  Already in Drive — skipping.")
                    results.append({"file": zip_name, "status": "skipped"})
                    continue

                dest = download_dir / zip_name

                try:
                    import shutil as sh
                    free_gb = sh.disk_usage("/tmp").free / 1024**3
                    log.info("  Disk space available: %.1f GB", free_gb)
                    if free_gb < 1.5:
                        log.warning("  Low disk space — running cleanup ...")
                        import glob, shutil
                        for tmp in glob.glob("/tmp/playwright*") + glob.glob("/tmp/download*") + glob.glob("/tmp/sf_exports/*"):
                            try:
                                if os.path.isdir(tmp): shutil.rmtree(tmp)
                                else: os.unlink(tmp)
                            except Exception:
                                pass
                        free_gb = sh.disk_usage("/tmp").free / 1024**3
                        log.info("  Disk space after cleanup: %.1f GB", free_gb)
                        if free_gb < 1.0:
                            raise RuntimeError(f"Insufficient disk space: {free_gb:.1f} GB free")

                    frame, link_count = get_export_frame(page, wait_secs=45)
                    if not frame:
                        raise RuntimeError("Lost export frame")

                    log.info("  Clicking Download link #%d (of %d) via JS ...", click_index, link_count)
                    with page.expect_download(timeout=600_000) as dl_info:
                        frame.evaluate("""(idx) => {
                            const links = Array.from(document.querySelectorAll('a'))
                                .filter(a => a.innerText.trim().toLowerCase() === 'download');
                            if (!links[idx]) throw new Error('No link at ' + idx + ', found ' + links.length);
                            links[idx].click();
                        }""", click_index)

                    dl = dl_info.value
                    dl.save_as(str(dest))
                    click_index += 1
                    size_mb = dest.stat().st_size // 1024 // 1024
                    log.info("  Downloaded: %s (%d MB)", zip_name, size_mb)

                    try:
                        upload_file_to_drive(drive, dest, folder_id)
                    finally:
                        if dest.exists():
                            dest.unlink()
                            log.info("  Local file deleted.")
                        import glob, shutil
                        for tmp in glob.glob("/tmp/playwright*") + glob.glob("/tmp/download*"):
                            try:
                                if os.path.isdir(tmp): shutil.rmtree(tmp)
                                else: os.unlink(tmp)
                            except Exception:
                                pass
                        import shutil as sh
                        log.info("  Disk space free: %.1f GB", sh.disk_usage("/tmp").free / 1024**3)

                    results.append({"file": zip_name, "status": "ok"})

                    log.info("  Waiting %ds before next download ...", WAIT_BETWEEN_DOWNLOADS)
                    time.sleep(WAIT_BETWEEN_DOWNLOADS)
                    navigate_to_export_page(page)

                except Exception as exc:
                    log.error("  FAILED: %s", exc)
                    results.append({"file": zip_name, "status": "error", "error": str(exc)})
                    if dest.exists():
                        dest.unlink()
                        log.info("  Cleaned up partial file: %s", dest.name)
                    try:
                        navigate_to_export_page(page)
                    except Exception:
                        pass

            return results

        finally:
            context.close()
            browser.close()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    run_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    log.info("=== Salesforce Data Export -> Google Drive === %s", run_date)
    log.info("Org: %s", SF_ORG_DOMAIN)

    access_token = sf_get_access_token()
    drive = gdrive_service()
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    leftover = list(DOWNLOAD_DIR.glob("*.ZIP")) + list(DOWNLOAD_DIR.glob("*.zip"))
    if leftover:
        log.info("Cleaning up %d leftover file(s) from previous run ...", len(leftover))
        for f in leftover:
            f.unlink()
            log.info("  Deleted: %s", f.name)

    results = run_browser_downloads(access_token, drive, GDRIVE_FOLDER_ID, DOWNLOAD_DIR, run_date)

    log.info("\n=== Summary ===")
    ok      = [r for r in results if r["status"] == "ok"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed  = [r for r in results if r["status"] == "error"]
    log.info("OK: %d  Skipped: %d  Failed: %d", len(ok), len(skipped), len(failed))
    for r in failed:
        log.error("  FAILED: %s -- %s", r["file"], r.get("error"))

    if failed:
        raise SystemExit(f"Completed with {len(failed)} error(s).")
    log.info("=== Done ===")


if __name__ == "__main__":
    main()
