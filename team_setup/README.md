# Team setup (optional)

CampusMail looks here when a computer has no sign-in setup of its own. Files placed here let
everyone with access to this repository sign in to Gmail or Outlook with one click, without the
one-time upload in the sidebar.

| file | what to put in it |
|---|---|
| `google_client.json` | the JSON downloaded for the team's **Desktop app** OAuth client in Google Cloud |
| `microsoft_client_id.txt` | the **Application (client) ID** of the team's Microsoft app registration, on one line |

Order of lookup: environment variables, then this computer's `secrets/` folder (written by the
sidebar), then this folder. A personal setup always wins over the team one.

## What committing these files exposes

- **Mail stays private.** These files identify the app, not a user. Nobody can read anyone's mail
  with them: each person still signs in with their own account and approves read-only access, and
  the access token stays in that person's CampusMail session.
- **Google treats Desktop app client secrets as not truly secret**, because installed apps ship
  them to every user. The Microsoft app ID is public by design (no secret is used).
- **The real risk is misuse of the app's name.** Someone holding the Google file could build a
  look-alike that asks people to sign in to "CampusMail". While the Google app is in *Testing*,
  only listed test users can sign in at all, which keeps this small.

So: commit these files **only while the repository is private**. If it becomes public, or a file
leaks, delete the OAuth client in Google Cloud (or the app registration in Microsoft Entra) and
create a new one. Never put API keys, passwords or tokens here.

## What still has to be done by a person

- Register the app once (README: *Optional: import from Outlook or Gmail*).
- Google: add each user's Gmail address under **Audience → Test users** (up to 100). Removing
  that limit needs Google's verification of the read-only Gmail scope, which includes a paid
  security assessment, so it is not practical for a course project.
- HKU Microsoft 365 accounts need IT approval; personal Outlook.com accounts do not.
