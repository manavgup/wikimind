# Browser Extension Store Publishing

This guide covers setting up automated publishing for the WikiMind browser
extension to the Chrome Web Store and Firefox Add-ons (AMO).

## Overview

The CI workflow (`.github/workflows/extension-publish.yml`) handles building,
testing, packaging, and uploading the extension when a tag matching
`extension/v*` is pushed. Publishing to each store is gated behind repository
variables so you can enable them independently after completing the manual
setup below.

## Prerequisites

Before automated publishing can work, each store requires a **first manual
upload** to register the extension and establish metadata.

## Step 1: First manual upload

### Chrome Web Store

1. Run `make extension-package` (or `cd apps/web-extension && npm run build`
   then zip the `dist/` directory).
2. Go to the [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole).
3. Click **New item** and upload the zip.
4. Fill in the required metadata (description, screenshots, category).
5. Submit for review.
6. After the extension is published, note the **Extension ID** shown on the
   dashboard (a 32-character string like `abcdefghijklmnopabcdefghijklmnop`).

### Firefox AMO

1. Go to the [Firefox Developer Hub](https://addons.mozilla.org/developers/).
2. Click **Submit a New Add-on** and upload the same zip.
3. Fill in the required metadata.
4. Submit for review.

## Step 2: Chrome Web Store API credentials

The CI workflow uses the Chrome Web Store Publish API, which requires OAuth 2.0
credentials.

1. Go to [Google Cloud Console](https://console.cloud.google.com) and create a
   project (or use an existing one).
2. Enable the **Chrome Web Store API** under APIs & Services.
3. Go to **APIs & Services > Credentials** and create an **OAuth 2.0 Client ID**
   (application type: Desktop app).
4. Note the **Client ID** and **Client Secret**.
5. Obtain a refresh token by running the OAuth consent flow:

   Open this URL in a browser (replace `YOUR_CLIENT_ID`):

   ```
   https://accounts.google.com/o/oauth2/auth?response_type=code&scope=https://www.googleapis.com/auth/chromewebstore&client_id=YOUR_CLIENT_ID&redirect_uri=urn:ietf:wg:oauth:2.0:oob
   ```

   Authorize the app, then exchange the authorization code for a refresh token:

   ```bash
   curl -X POST https://oauth2.googleapis.com/token \
     -d "client_id=YOUR_CLIENT_ID" \
     -d "client_secret=YOUR_CLIENT_SECRET" \
     -d "code=YOUR_AUTH_CODE" \
     -d "grant_type=authorization_code" \
     -d "redirect_uri=urn:ietf:wg:oauth:2.0:oob"
   ```

   The response JSON contains a `refresh_token` field. Save it.

## Step 3: Firefox AMO API credentials

1. Go to the [AMO API Keys page](https://addons.mozilla.org/developers/addon/api/key/).
2. Generate API credentials.
3. Note the **JWT issuer** and **JWT secret**.

## Step 4: Add GitHub secrets

Go to the repository **Settings > Secrets and variables > Actions > Secrets**
and add the following:

| Secret                  | Source                                       |
|-------------------------|----------------------------------------------|
| `CHROME_EXTENSION_ID`   | Extension ID from Chrome Web Store dashboard |
| `CHROME_CLIENT_ID`      | OAuth 2.0 Client ID from Google Cloud        |
| `CHROME_CLIENT_SECRET`  | OAuth 2.0 Client Secret from Google Cloud    |
| `CHROME_REFRESH_TOKEN`  | Refresh token from the OAuth flow            |
| `FIREFOX_JWT_ISSUER`    | JWT issuer from AMO API Keys page            |
| `FIREFOX_JWT_SECRET`    | JWT secret from AMO API Keys page            |

## Step 5: Enable automated publishing

Go to **Settings > Secrets and variables > Actions > Variables** and add:

| Variable                    | Value  |
|-----------------------------|--------|
| `EXTENSION_PUBLISH_CHROME`  | `true` |
| `EXTENSION_PUBLISH_FIREFOX` | `true` |

You can enable one store at a time. If a variable is missing or not set to
`true`, the corresponding upload step is skipped (build, test, and GitHub
Release still run).

## Step 6: Verify publishing works

1. Bump the version in both `apps/web-extension/manifest.json` and
   `apps/web-extension/package.json`.
2. Commit the version bump.
3. Create and push a tag:

   ```bash
   git tag extension/v0.1.0
   git push origin extension/v0.1.0
   ```

4. Watch the **Extension Publish** workflow in the Actions tab.
5. The workflow will:
   - Build and test the extension
   - Package `dist/` into a zip
   - Upload to Chrome Web Store (if enabled)
   - Upload to Firefox AMO (if enabled)
   - Create a GitHub Release with the zip attached

## What is automated vs. manual

| Task                           | Automated | Manual |
|--------------------------------|-----------|--------|
| Build, test, package           | Yes       |        |
| Upload to Chrome Web Store     | Yes       |        |
| Upload to Firefox AMO          | Yes       |        |
| Create GitHub Release          | Yes       |        |
| First upload to each store     |           | Yes    |
| API credential setup           |           | Yes    |
| Store metadata / screenshots   |           | Yes    |
| Version bumps before tagging   |           | Yes    |
| Store review approval          |           | Yes    |

## Workflow file reference

The publishing workflow lives at `.github/workflows/extension-publish.yml`.
It uses these third-party actions:

- [`mnao305/chrome-extension-upload@v5.0.0`](https://github.com/mnao305/chrome-extension-upload) for Chrome Web Store
- [`yayuyokitano/firefox-addon@v1.0.4`](https://github.com/yayuyokitano/firefox-addon) for Firefox AMO
- [`softprops/action-gh-release@v2`](https://github.com/softprops/action-gh-release) for GitHub Releases
