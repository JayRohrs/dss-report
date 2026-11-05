# Microsoft 365 draft email: permissions

The optional draft step puts the report in the owner's **Drafts folder** with the report page attached.
**This program never sends it.** The owner opens Outlook, reads it, and sends it (or deletes it).
It is **off by default** (`dss-report.exe draft on` to switch it on).

## Permissions asked for (delegated, signed in as the owner)

| Scope | Why | Asked? |
|---|---|---|
| `Mail.ReadWrite` | The least-privileged delegated permission Microsoft lists for creating a message (`POST /me/messages`) and adding an attachment. | Yes |
| `offline_access` | Lets the saved sign-in refresh so the 7 a.m. run needs no one at the keyboard. | Yes |
| `Mail.Send` | Would allow sending. | **Never requested.** Microsoft would refuse a send even if code tried. |
| Anything else (calendar, files, contacts, Teams, user profile) | - | No |

No admin consent is needed for these scopes in a typical tenant, but a tenant policy may require it.
Application (app-only) permissions are not used.

## The only Graph calls the program can make

1. `POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` (refresh the sign-in)
2. `POST https://graph.microsoft.com/v1.0/me/messages` (create the draft)
3. `POST https://graph.microsoft.com/v1.0/me/messages/{id}/attachments` (attach the report; up to 3 MB)

Anything else is refused by an allow-list in `dssreport/desktop/draftmail.py` before it reaches the network.
`tests/test_desktop_draft_only.py` fails if any send-like call, word or permission appears in that code path.

## Setting it up (once)

1. In the Microsoft Entra admin centre register an app: *Public client / mobile & desktop*, redirect URI not needed
   for the device-code sign-in, "Allow public client flows" = Yes. Add delegated permission **Mail.ReadWrite** only.
2. `dss-report.exe set graph_client_id <Application (client) ID>` (this ID is not a secret).
3. `dss-report.exe set draft_to someone@yourcompany.example`
4. `dss-report.exe draft-signin` and follow the on-screen code. The sign-in is kept in Windows Credential Manager;
   no password is typed into or stored by this program.
5. `dss-report.exe draft on`

To remove the saved sign-in, use the existing command `python -m dssreport forget-secrets` (source install) or delete the "DssReport" entries in Windows Credential Manager.

## Not yet proven

Tested only against a pretend Microsoft server with made-up IDs. It has not been tried on a real Microsoft 365 account.
