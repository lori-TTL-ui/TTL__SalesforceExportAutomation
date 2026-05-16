# Salesforce Weekly Data Export → Google Drive

Automatically downloads Salesforce weekly data export files and uploads them to Google Drive — fully automated, weekly, with auto-retry on failure.

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

### Step 2 — Google Drive: Create Shared Drive

1. Go to [drive.google.com](https://drive.google.com) → **Shared drives → + New**
2. Name it (e.g. `Salesforce Exports`)
3. Right-click → **Manage members** → add the service account email as **Content Manager**
4. Open the Shared Drive and copy the **folder ID** from the URL

### Step 3 — Salesforce: Create Connected App

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

Click **Allow**, then copy the `code=` value from the redirect URL and run:

```bash
curl -X POST "https://YOUR_ORG_DOMAIN.salesforce.com/services/oauth2/token" \
  -d "grant_type=authorization_code" \
  -d "client_id=YOUR_CONSUMER_KEY" \
  -d "client_secret=YOUR_CONSUMER_SECRET" \
  -d "redirect_uri=https://login.salesforce.com/services/oauth2/success" \
  -d "code=YOUR_CODE"
```

Copy the `refresh_token` from the response.

### Step 5 — GitHub: Create Repository & Add Secrets

1. Create a **private** GitHub repository
2. Upload these files: `export_ui.py`, `requirements.txt`, `.github/workflows/sf_ui_export.yml`
3. Go to **Settings → Actions → General → Workflow permissions → Read and write**
4. Go to **Settings → Secrets and variables → Actions** and add:

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
| `storageQuotaExceeded` | Must use a Shared Drive, not a regular My Drive folder |
| `EOF occurred in violation of protocol` | Transient SSL error — auto-retry will handle it |
| `No space left on device` | Auto-retry on a fresh runner will have full disk space |
| `Insufficient Privileges` | Salesforce user needs System Administrator profile |

---

## Granting Client Access to This Repository

Once you have set up the repository, follow these steps to give your client access:

### Option A — Invite as a Collaborator (single client)

1. Go to your repository on GitHub (e.g. `github.com/YOUR_USERNAME/SalesforceExportAutomation`)
2. Click the **Settings** tab at the top of the repo page
3. In the left sidebar click **Collaborators**
4. Click **Add people**
5. Enter your client's **GitHub username or email address**
6. Select their name from the dropdown and click **Add to repository**
7. Your client will receive an email invitation — they must click **Accept invitation** before they can access the repo
8. Once accepted, they can view all files and follow the Setup instructions above

### Option B — GitHub Template Repository (best for multiple clients)

This approach lets each client create their own independent copy of the repo with one click — recommended if you plan to deliver this to more than one client.

1. Go to your repository → **Settings**
2. Under the **General** section, check **Template repository**
3. Change the repo visibility to **Public** (required for templates)
   - Settings → scroll to **Danger Zone** → **Change visibility → Change to public**
4. Share this link with your client:
   ```
   https://github.com/YOUR_USERNAME/SalesforceExportAutomation
   ```
5. Your client clicks **Use this template → Create a new repository**
6. They name their own private repo and click **Create repository**
7. All files are copied into their own GitHub account — they then follow the Setup instructions above to add their own secrets and variables

> **Note:** Making the repo public is safe because no credentials or org-specific URLs are hardcoded in the code — everything is configured through GitHub Secrets and Variables which are never visible publicly.
