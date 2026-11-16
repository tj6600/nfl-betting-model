# GoonerGamble Android app (Play Store wrapper)

The Android app is a **Trusted Web Activity (TWA)**: a thin Play Store shell that opens the live Render site
(https://nfl-betting-model-u14v.onrender.com/) full screen in Chrome's engine. There is no app code to maintain.
Every board update the scheduled runs push shows up in the app the next time it opens, with no new Play release.
You only rebuild and re-upload the app to change its name, icon or package settings.

What's already done in the repo:

| Piece | Where |
|---|---|
| Web app manifest (name, colors, icons, NBA/NHL/Bank shortcuts) | `board/site/manifest.webmanifest` |
| Icons | `board/site/icons/` (made by `android/store/make_icons.py`) |
| Service worker: network first so boards stay fresh, cached copy only when offline | `board/site/sw.js`, `board/site/offline.html` |
| Install tags on every page (also rebuilt by the board scripts) | `APP_HEAD` in `bank.py` |
| Privacy policy page (Play requires one) | `board/site/privacy.html` |
| Digital Asset Links (removes the URL bar in the app) | `board/site/.well-known/assetlinks.json`, fingerprint still to fill in |
| Bubblewrap config | `android/twa-manifest.json` |
| Play listing art: 512 icon, 1024x500 feature graphic | `android/store/` |

Package name: **`com.tj6600.goonergamble`**. It is permanent once uploaded to Play, so keep it.

## 0. Quick win, no Play Store needed

Once this is merged and Render redeploys:

- **Android:** open the site in Chrome, tap the ⋮ menu, then **Install app** (or *Add to Home screen*). It installs as a real app in your app drawer.
- **iPhone:** open the site in Safari, tap **Share**, then **Add to Home Screen**.

## 1. Google Play developer account ($25, one time)

Sign up at https://play.google.com/console/signup as a **personal** account. Google asks for ID verification and
for you to verify a real Android phone in the Play Console app. Approval can take a day or two.

## 2. Build the app package (no installs needed)

1. Go to https://www.pwabuilder.com, paste `https://nfl-betting-model-u14v.onrender.com/`, and start.
2. Choose **Package for stores**, then **Android**, then **Options**:
   - Package ID: `com.tj6600.goonergamble`
   - App name: `GoonerGamble: NFL, NBA, NHL`, Launcher name: `GoonerGamble`
   - Version `1.0.0`, version code `1`
   - Signing key: **Create new**
3. Download the zip. It holds:
   - the `.aab` file (this is what you upload to Play),
   - an `.apk` you can install directly on your phone to try it,
   - `signing.keystore` and `signing-key-info.txt`: **your upload key and its passwords. Back these up somewhere private
     (e.g. Google Drive). Never commit them, email them, or paste them into a chat.** You need them for every future update.

*Alternative for later:* with Node and Java installed, `npm i -g @bubblewrap/cli`, then `bubblewrap build` inside
`android/` uses `twa-manifest.json` here (keep the keystore in that folder; `.gitignore` already blocks committing it).

## 3. Create the app in Play Console

**Create app** → name *GoonerGamble*, type *App*, *Free*. Then work through **Set up your app**:

- **Privacy policy:** `https://nfl-betting-model-u14v.onrender.com/privacy.html`
- **App access:** all functionality available without special access
- **Ads:** no ads
- **Content rating:** fill in the questionnaire honestly (it covers gambling content; expect an adult rating)
- **Target audience:** 18 and over
- **Data safety:** no data collected or shared
- **App category:** Sports
- **Store listing:** icon `android/store/play-icon-512.png`, feature graphic `android/store/feature-graphic-1024x500.png`,
  and at least 2 phone screenshots (take them on your phone)

## 4. Get it on your phone: Internal testing

**Test and release → Testing → Internal testing → Create new release.**

1. Accept **Play App Signing** (Google keeps the final app signing key; you keep the upload key from step 2).
2. Upload the `.aab`, save, and roll out.
3. Under **Testers**, make an email list with your own Google account, then open the **opt-in link** on your phone and install.

Internal testing is enough for personal use and skips the public-release requirements below.

## 5. Remove the address bar (one value to send back)

Until the site lists your app's signing fingerprint, the app opens with a small address bar at the top.

In Play Console: **Test and release → Setup → App integrity → App signing**, copy the **SHA-256 certificate fingerprint**
under *App signing key certificate* (it looks like `AB:CD:12:...`). This value is public, not a secret. Send it in the
project thread and it goes into `board/site/.well-known/assetlinks.json`. After Render redeploys, reopen the app (you may
need to clear the app's storage once) and it runs full screen.

## 6. Going public later (optional)

- New personal developer accounts must run a **closed test with at least 12 testers for 14 days in a row** before a
  public (production) release is allowed.
- Google Play's gambling policy limits apps that aren't licensed gambling apps from linking or driving users to
  real-money betting. The **Open in DraftKings** buttons could get a public listing rejected. If you go public, the app
  version can hide those links (the website keeps them).

## Updating the app

- **Board, picks, layout, new tabs:** nothing to do. The app shows the live site.
- **Name, icon, colors, package settings:** rebuild in PWABuilder (or Bubblewrap) **with the same signing key**, raise the
  version code by 1, and upload a new release in Play Console.

## Alerts (push notifications)

Tap the 🔔 at the end of the sport bar (or open `/alerts.html`), pick sports, tap **Turn on alerts**, then copy the code
it shows into an environment variable named `GG_PUSH` in the cloud environment the scheduled runs use. The runs call
`python scripts/push_alert.py <nfl|nba|nhl> "<summary>"` after pushing a new board (no Odds API credits). The
environment must allow `fcm.googleapis.com` (Android) and `web.push.apple.com` (iPhone). On iPhone, alerts only work
from the Home Screen app (iOS 16.4+).
