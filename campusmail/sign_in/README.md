# Built-in sign-in registration

Files in this folder let every copy of CampusMail sign in to Gmail or Outlook with one click:
the user presses **Sign in**, a browser window from Google or Microsoft opens, they approve
read-only access, and the mail appears. Users never download or upload anything.

| file | what it is |
|---|---|
| `google_client.json` | the JSON of the project's **Desktop app** OAuth client in Google Cloud |
| `microsoft_client_id.txt` | the **Application (client) ID** of the project's Microsoft app registration |

The developer creates them once (README: *Optional: import from Outlook or Gmail*) and either
adds them in **Settings → Sign-in setup → Build into this copy**, or commits them here.

## What shipping these files exposes

- **Mail stays private.** These files identify the app, not a person. Nobody can read anyone's
  mail with them: each person signs in with their own account and approves read-only access,
  and the access token stays in that person's CampusMail session, in memory only.
- Google treats Desktop app client secrets as **not secret**, because installed apps ship them
  to every user. The Microsoft app ID is public by design; no secret is used.
- The real risk is someone reusing the app's name in a look-alike. Keep the repository private
  while these files are in it. If a file leaks, delete the OAuth client in Google Cloud (or the
  app registration in Microsoft Entra) and create a new one.
- Never put API keys, passwords or tokens here.

## Limits that remain

- While the Google app is in **Testing**, only Gmail addresses listed under **Audience → Test
  users** can sign in (up to 100). Google shows an "unverified app" notice; users press
  **Continue**. Removing both needs Google's verification of the Gmail read-only scope, which
  includes a paid security assessment and is not practical for a course project.
- HKU Microsoft 365 accounts need approval from HKU IT; personal Outlook.com accounts do not.
