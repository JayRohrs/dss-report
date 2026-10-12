# Seeing the report while travelling - plan (design only, no code yet)

The owner travels and wants the morning report on a phone. The report page is already readable at phone
width (screenshots at 390 px). The question is how it gets to the phone **safely**, since it holds sales
figures. Two options.

## Option A - a private link to the saved report, behind a login

How it would work: after each run the program uploads the finished report page to a small service Jay
operates. The owner opens a link on their phone, signs in, and sees it.

What it needs:
- A hosted service (new infrastructure, run by Jay) that holds customers' sales figures. This is the big change: today nothing leaves the computer.
- **Authentication:** passkey or password **plus** a second factor; or a one-time sign-in link sent by email that expires in minutes. Sessions short-lived; sign-out everywhere.
- **Link safety:** long unguessable addresses are *not* security; every page request must check the login. Time-limited signed links as an extra, not a replacement.
- **Isolation:** each customer's reports kept apart, encrypted at rest and in transit, access logged.
- **Retention:** delete reports after N days (suggest 30), customer can delete on demand.
- Upload only the rendered report (the same page and email text), never raw R365 data or credentials; per-customer upload key kept in the OS credential store.
- Breach plan, privacy notice, and customer terms - Jay becomes a custodian of the customer's financial data.

Good: history in one place, works for people who don't use Microsoft 365, can later add push alerts.
Bad: most to build and secure; a real liability; contradicts "your data never leaves your computer" unless carefully presented as an option.

## Option B - email only

How it would work: the report already arrives as an email in the owner's own mailbox (Microsoft 365 draft or automatic send, built in this phase). The phone's mail app opens it; the HTML page is attached and the text body is readable on its own.

What it needs: nothing new to host. Protection comes from the mailbox's own login and phone lock.
- Keep figures out of the **subject line** and the first lines (lock-screen previews). Today the subject carries counts only, no dollar amounts.
- Warn that forwarding the email forwards the figures.
- "Send automatically" stays off by default; draft-first remains the safe path.
- If the computer is off at the scheduled time, the run happens on next start and is labelled late - so travel plus a sleeping office computer means a late email, not a missing one. Say this in the README.

Good: no new data custody, nothing to secure on Jay's side, already built, keeps the privacy promise.
Bad: no history page, depends on the office computer being on, attachments can be forwarded.

## Recommendation

**Start with Option B (email only).** It is built, it needs no hosting, and it keeps the promise that sales
data stays on the customer's side. Revisit Option A only if customers ask for something email can't do
(history, a computer that is often off), and only after deciding who hosts it, what customers sign, and
who answers if something goes wrong. If A is ever built, make it a separate, clearly labelled opt-in.

## Decisions for Jay

1. Agree Option B for now?
2. If A later: hosting provider, sign-in method, retention period, customer terms.
3. Does the office computer stay on overnight? If not, the "late run" behaviour matters more.
