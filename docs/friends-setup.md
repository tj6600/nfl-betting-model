# Friends page setup (Firebase, free Spark plan)

The Friends page (`board/site/friends.html`) uses Firebase for Google sign-in and to store groups and picks.
Stay on the free **Spark** plan: it needs no card and never charges. Skip any "Start free trial", "Upgrade",
"Blaze" or "Add billing account" prompt. The console's bottom-left corner should say *Spark plan, No-cost $0/month*.

1. **Create the project.** Go to console.firebase.google.com, click *Create a project*, name it GoonerGamble, and turn Google Analytics off.
2. **Turn on Google sign-in.** Open *Build > Authentication > Get started > Sign-in method > Google*. Switch it on, pick your email as the support email, and save.
3. **Allow the site's domain.** Open *Authentication > Settings > Authorized domains* and add the Render domain (`<name>.onrender.com`).
4. **Create the database.** Open *Build > Firestore Database > Create database*. Pick the Standard edition if asked, choose *Production mode*, and pick a US location.
5. **Lock it down.** Open *Firestore Database > Rules*, replace everything with the contents of `firestore.rules` from this repo, and click *Publish*.
6. **Connect the site.** Click the gear icon, then *Project settings > Your apps > Web (</>)*. Register it as "GoonerGamble web" with Hosting unchecked. Copy the `firebaseConfig` object into `board/site/firebase-config.js` as `window.GG_FIREBASE = { ... };`.

## Is the config a secret?

No. Firebase's web config (including `apiKey`) identifies the project and is meant to sit in public web pages.
What protects the data is `firestore.rules`: only signed-in people can read, a group is visible only to its members
(and to someone holding its invite link), and each person can write only their own pick, only before that leg kicks off.
Optional extra: in Google Cloud console > APIs & Services > Credentials, restrict the browser key to the Render domain.

## What runs where

* `friends.py` / `scripts/friends_board.py` save each week's NFL board legs to `odds_log/friends/`, grade finished legs
  from free nflverse data, and write `board/site/group/*.json` plus the page. `.github/workflows/friends.yml` runs it
  after each NFL board push and Mon/Tue/Fri mornings. No Odds API credits, no secrets.
* The page's *Refresh results* button reads ESPN box scores on the phone for legs the grader hasn't reached yet.
* A pick only counts if Firebase's server time when it was saved is before that leg's kickoff in the site's own files.
