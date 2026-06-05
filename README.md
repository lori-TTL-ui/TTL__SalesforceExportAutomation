# Salesforce Weekly Data Export → Google Drive

Automatically downloads Salesforce weekly data export files and uploads them to Google Drive — fully automated, weekly, with auto-retry on failure.

---

## Prerequisites

Before starting setup, ensure you have the following in place:

### 1. GitHub Account
A free GitHub account is required to host and run the automation.
Sign up at [github.com/signup](https://github.com/signup) if you don't already have one.

### 2. Google Workspace Account
A Google Workspace account (Business Starter at $6/user/month or higher) is required to create a Shared Drive for file storage. Personal Gmail accounts (@gmail.com) are **not supported** due to Google API restrictions on service account uploads.

### 3. Confirm Your Salesforce Data Export Schedule

The automation is pre-configured to run every **Tuesday at 11:00 PM Pacific Time** — designed to run after your weekly Salesforce Data Export has finished generating. Before activating, confirm when your export runs.

**Option 1 — Scheduled Jobs UI:**
In Salesforce Setup, search for **Scheduled Jobs** in the Quick Find box and look for a job named `DataExport` in the list.

**Option 2 — Developer Console Query:**
Go to **Setup → Developer Console → Query Editor** tab and run:

```sql
SELECT Id, CronJobDetail.Name, CronJobDetail.JobType,
       CronExpression, StartTime, EndTime,
       TimesTriggered, NextFireTime, PreviousFireTime
FROM CronTrigger
WHERE CronJobDetail.Name = 'DataExport'
```

To decode the `CronExpression` value from the results (e.g. `0 15 18 ? * 2`), search Google for:
```
decode cron expression "0 15 18 ? * 2"
```
substituting your actual value. This tells you the exact day and time your export runs.

The automation should be set to run a few hours **after** your Data Export completes to ensure all files are ready.

**If no scheduled job is found**, your Data Export may not be scheduled yet or its end date may have expired. To schedule it:

1. In Salesforce Setup search for **Data Export** in the Quick Find box
2. Click **Schedule Export**
3. Select **Weekly** frequency
4. Set Start Date to today and End Date to a date far in the future (e.g. 12/31/2030)
5. Choose a time that completes before our automation runs Tuesday night
6. Click **Save**

Re-run the SOQL query above to confirm the new schedule.

---

## What it does

1. Logs into Salesforce using OAuth (no 2FA issues)
2. Navigates to Setup → Data Export
3. Downloads every available ZIP file
4. Uploads each file to your Google Shared Drive with a date suffix (e.g. `WE_OrgExport_1_20260512.ZIP`)
5. Retries automatically up to 3 times on failure
6. Creates a GitHub Issue if all retries fail

---

## Setup (one-time, ~30 minutes)

### Step 1 — Google Cloud: Enable Drive API & Create Service Account

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create or select a project
2. Go to **APIs & Services → Library** → search **Google Drive API** → **Enable**
3. Go to **APIs & Services → Credentials → + Create Credentials → Service Account**
4. Name it `salesforce-export` → Create and Continue → Done
5. Click the service account → **Keys** tab → **Add Key → Create new key → JSON** → download the file
6. Copy the service account email (e.g. `salesforce-export@project.iam.gserviceaccount.com`)

### Step 2 — Google Drive: Create a Destination Folder

> ⚠️ **Important:** This solution requires a **Google Workspace Shared Drive**. Personal Gmail accounts (@gmail.com) do not support service account uploads and will not work. Google Workspace starts at $6/month per user.

1. Go to [drive.google.com](https://drive.google.com) → **Shared drives → + New**
2. Name it (e.g. `Salesforce Exports`)
3. Right-click the Shared Drive → **Manage members**
4. Add your service account email (e.g. `salesforce-export@project.iam.gserviceaccount.com`) as **Content Manager**
5. Open the Shared Drive and copy the **folder ID** from the URL:
   `https://drive.google.com/drive/u/0/folders/FOLDER_ID_HERE`

### Step 3 — Salesforce: Create an App for OAuth Access

> **Note:** Salesforce Spring '26 introduced **External Client Apps** as the new replacement for Connected Apps. Use the method that matches your org's release.

---

**Option A — Salesforce Spring '26 and later: External Client App**

1. In Setup, search **External Client Apps** in the Quick Find box
2. Click **New External Client App**
3. Fill in the **Basic Information**: name it `SF Export Automation`, enter a contact email
4. Click **Next**
5. On the **OAuth** tab, click **Enable OAuth**
6. Callback URL: `https://login.salesforce.com/services/oauth2/success`
7. Add scopes: **Full access (full)** and **Perform requests at any time (refresh_token)**
8. Uncheck **Require Proof Key for Code Exchange (PKCE)**
9. Click **Save**
10. Go to **External Client Apps → Manage** → find your app → click **View**
11. Copy the **Consumer Key** (= `SF_CLIENT_ID`) and click **Reveal** to copy the **Consumer Secret** (= `SF_CLIENT_SECRET`)
12. Wait up to 10 minutes for the app to activate

---

**Option B — Salesforce Winter '26 and earlier: Connected App**

1. In Salesforce Setup search for **App Manager → New Connected App**
2. Enable **OAuth Settings**
3. Callback URL: `https://login.salesforce.com/services/oauth2/success`
4. Scopes: **Full access** and **Refresh token**
5. Uncheck **Require PKCE**
6. Save — wait up to 10 minutes
7. View the app → copy **Consumer Key** and **Consumer Secret**

### Step 4 — Salesforce: Generate Refresh Token

Paste this URL in your browser while logged into Salesforce as a System Administrator — replacing `YOUR_CONSUMER_KEY` and `YOUR_ORG_DOMAIN`:

```
https://YOUR_ORG_DOMAIN.salesforce.com/services/oauth2/authorize?response_type=code&client_id=YOUR_CONSUMER_KEY&redirect_uri=https://login.salesforce.com/services/oauth2/success
```

Click **Allow**, then copy the `code=` value from the redirect URL.

Then open a Terminal on your computer:
- **Mac:** Press `Cmd + Space` → type `Terminal` → press Enter
- **Windows:** Press `Windows key` → type `PowerShell` → press Enter

**Option 1 — Single-line curl (paste as ONE line, no line breaks):**

```
curl -X POST "https://YOUR_ORG_DOMAIN.salesforce.com/services/oauth2/token" -d "grant_type=authorization_code&client_id=YOUR_CONSUMER_KEY&client_secret=YOUR_CONSUMER_SECRET&redirect_uri=https://login.salesforce.com/services/oauth2/success&code=YOUR_CODE"
```

> **Common errors:**
> - `Bad hostname` — your `YOUR_ORG_DOMAIN` is wrong. Use exactly what appears in your Salesforce URL, e.g. if your org URL is `https://mycompany.my.salesforce.com` use `mycompany.my`
> - Parameters not sent — make sure the entire command is on ONE line with no line breaks

**Option 2 — Python script (recommended, more reliable):**

Save this as `get_token.py` on your Desktop, fill in your values, then run `python3 get_token.py` in your terminal:

```python
import requests

response = requests.post(
    "https://YOUR_ORG_DOMAIN.salesforce.com/services/oauth2/token",
    data={
        "grant_type":    "authorization_code",
        "client_id":     "YOUR_CONSUMER_KEY",
        "client_secret": "YOUR_CONSUMER_SECRET",
        "redirect_uri":  "https://login.salesforce.com/services/oauth2/success",
        "code":          "YOUR_CODE",
    }
)
print(response.json())
refresh_token = response.json().get("refresh_token")
print(f"\n Your SF_REFRESH_TOKEN is:\n{refresh_token}")
```

Copy the value printed after `Your SF_REFRESH_TOKEN is:` — that is your `SF_REFRESH_TOKEN`.

**If using curl**, the response is a block of JSON. Look for `"refresh_token"` and copy the value between the quotes after it. Example:

```
{"access_token":"00D...","refresh_token":"5Aep861KIqfMC.MO4Fw6...","scope":"refresh_token full",...}
                                          ^^^^^^^^^^^^^^^^^^^^^^^^
                                          Copy THIS value
```

The refresh token starts with `5Aep` and is about 100 characters long. Everything between the quotes after `"refresh_token":` is your `SF_REFRESH_TOKEN`.

> ⚠️ **IMPORTANT:** The authorization code expires in **~15 minutes**. Have your terminal open and ready BEFORE you click Allow. Copy the code and run the command immediately — do not pause between steps.

### Step 5 — GitHub: Create Your Repository from Template

1. Go to the template repository: **https://github.com/YOUR_CONSULTANT_USERNAME/SalesforceExportAutomation**
2. Click the green **Use this template** button → **Create a new repository**
3. Name your repo (e.g. `SalesforceExportAutomation`), set it to **Private**, and click **Create repository**
4. All files are automatically copied — no uploading needed ✅
5. Go to **Settings → Actions → General → Workflow permissions → Read and write permissions**
6. Go to **Issues → Labels** and create these labels: `export-success` (green), `export-failure` (red), `auto-retry` (yellow), `manual-required` (purple)
7. Go to **Settings → Secrets and variables → Actions** and add:

**Secrets:**
| Name | Value |
|---|---|
| `SF_CLIENT_ID` | Consumer Key from Connected App |
| `SF_CLIENT_SECRET` | Consumer Secret from Connected App |
| `SF_REFRESH_TOKEN` | Refresh token from curl response |
| `GDRIVE_FOLDER_ID` | Shared Drive folder ID |
| `GDRIVE_SERVICE_ACCOUNT_JSON` | Full contents of the JSON key file |

**Variables** (under the Variables tab, not Secrets):
| Name | Value |
|---|---|
| `SF_ORG_DOMAIN` | Your org domain prefix e.g. `mycompany.my` |
| `WAIT_BETWEEN_DOWNLOADS` | `30` (seconds between downloads) |

---

## Schedule

Edit the `cron` line in `.github/workflows/sf_ui_export.yml`:

```yaml
- cron: "0 7 * * 2"  # Monday 11 PM PST (Tuesday 7 AM UTC)
```

Use [crontab.guru](https://crontab.guru) to build your preferred schedule.

---

## Finding your SF_ORG_DOMAIN

Log into Salesforce and look at the URL. Examples:
- `https://mycompany.my.salesforce.com` → `SF_ORG_DOMAIN = mycompany.my`
- `https://acme.lightning.force.com` → `SF_ORG_DOMAIN = acme.my`

---

## Notifications

This automation notifies you via **GitHub Issues** (GitHub emails you automatically for every new issue). No email server setup required.

### What you receive:

**On success:**
> ✅ Export SUCCESS — 69 files uploaded — 2026-05-19
> - Count of files uploaded, skipped, and failed
> - Whether it was a first run or a retry

**On failure (with retry coming):**
> ⚠️ Export attempt 1/3 failed — retry starting in 2 min — 2026-05-19
> - Exactly which files failed with error details
> - How many files succeeded before the failure
> - Confirmation that a retry will start in 2 minutes
> - A follow-up comment when the retry is triggered

**If all retries exhausted:**
> ❌ Export FAILED after all 3 attempts — MANUAL ACTION REQUIRED
> - Complete list of files NOT in Drive
> - Error details for each
> - Link to trigger a manual run

### Setting up GitHub Issue email notifications

GitHub emails you automatically when issues are created in your repo. To confirm this is enabled:

1. Go to github.com → click your profile photo → **Settings**
2. Click **Notifications** in the left sidebar
3. Under **Participating, @mentions and custom routing** ensure **Email** is checked
4. Under **Subscriptions** make sure issues in your repo are set to **Watching**

To watch your repo:
1. Go to your repository
2. Click the **Watch** button (top right)
3. Select **All Activity**

### Setting up Issue Labels

The workflow uses labels to categorize notifications. Create these labels in your repo:

1. Go to your repo → **Issues** tab → **Labels** → **New label**
2. Create these three labels:

| Label | Color | Description |
|---|---|---|
| `export-success` | `#2da44e` (green) | Weekly export completed successfully |
| `export-failure` | `#d1242f` (red) | Weekly export failed |
| `auto-retry` | `#e3b341` (yellow) | Automatic retry was triggered |
| `manual-required` | `#8250df` (purple) | Manual intervention required |

---

## Running manually

In your GitHub repo → **Actions → Salesforce Data Export to Google Drive → Run workflow**

---

## Running locally for testing

```bash
pip install -r requirements.txt
playwright install chromium

export SF_CLIENT_ID="..."
export SF_CLIENT_SECRET="..."
export SF_REFRESH_TOKEN="..."
export SF_ORG_DOMAIN="yourorg.my"
export GDRIVE_FOLDER_ID="..."
export GDRIVE_SERVICE_ACCOUNT_JSON='{ ...json... }'
export HEADLESS=false  # watch the browser

python export_ui.py
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `OAuth token refresh failed` | Refresh token expired — re-run the authorization URL flow |
| `Could not find Data Export iframe` | Salesforce export not ready yet — wait for the email notification |
| `HTTP 429 Too Many Requests` | Increase `WAIT_BETWEEN_DOWNLOADS` variable to 60 |
| `storageQuotaExceeded` | Personal Gmail accounts are not supported — a Google Workspace account with Shared Drive is required |
| `EOF occurred in violation of protocol` | Transient SSL error — auto-retry will handle it |
| `No space left on device` | Auto-retry on a fresh runner will have full disk space |
| `Insufficient Privileges` | Salesforce user needs System Administrator profile |
| Can't find "New Connected App" | Your org is on Spring '26 or later — use External Client Apps instead (see Step 3 Option A) |

---

## Delivering This Package to a Client

### Recommended: GitHub Template Repository

This is the cleanest delivery method — each client gets their own independent copy with one click, no file uploading required.

**One-time setup (consultant does this once):**
1. Go to your **SalesforceExportAutomation** repo → **Settings**
2. Under **General**, check **Template repository**
3. Change visibility to **Public** (Settings → Danger Zone → Change visibility)
   > Safe to make public — no credentials or org-specific URLs are in the code

**For each new client:**
1. Share this link with your client:
   ```
   https://github.com/YOUR_USERNAME/SalesforceExportAutomation
   ```
2. Client clicks **Use this template → Create a new repository**
3. They name it (e.g. `SalesforceExportAutomation`), set it to **Private**, click **Create repository**
4. All files are automatically copied into their own repo ✅
5. They follow the Setup instructions in this README to add their own secrets and variables

### Alternative: Invite as a Collaborator

If a client doesn't want to manage their own repo, you can invite them to yours:

1. Go to your repo → **Settings → Collaborators → Add people**
2. Enter their GitHub username or email
3. They accept the email invitation and can access the repo
