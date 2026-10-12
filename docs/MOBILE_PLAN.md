# Seeing the report on a phone and on a computer - plan (design only for the phone)

Status: the **Windows computer flow is built**. The phone flow is a plan only; no hosting code exists.

## The one flow, on every device

Phone and computer work the same way:

1. **View.** The person first looks at the report on screen: a simple "view the report" page, behind sign-in. Nothing has been emailed.
2. **Choose.** They then decide whether to email it. Two buttons on that page:
   - **Create the email in Microsoft 365** (on a computer, or any device signed in to Microsoft 365). This is a draft by default. If the person's administrator ticks **"send automatically"** (off by default, meant for admins using their own accounts later), the button sends instead.
   - **Open in my mail app** - the device's own mail app opens a new message with the text filled in. This is what a phone uses. It cannot attach the report page.

The figures never go anywhere unless the person presses one of those buttons (or an administrator turned on automatic sending for their own account).

## What exists today (first user: a single accountant on Windows)

- "DSS Report Run Now" makes yesterday's report and opens the **view page** on this computer. The page is served only to this computer, and only to a browser opened by the program (a one-time token); it is not reachable from the network.
- The scheduled morning run saves the report and, if email is on, creates a **draft** only. It does not send unless "send automatically" is ticked.
- Both buttons above are built and tested (Microsoft 365 against a mock only).

## What a phone needs (not built)

A phone cannot reach a page that lives only on the office computer, so "view first" on a phone needs the report to live somewhere the phone can reach, behind a real sign-in. That is a hosted service run by Jay and is the big decision below.

If it is built, it should be the **same page and the same two buttons**, with:
- **Authentication:** passkey or password plus a second factor, or a one-time sign-in link by email that expires in minutes. Short sessions; sign out everywhere.
- **Every request checks the login.** A long unguessable address is not security.
- **Isolation and storage:** each customer separate; encrypted in transit and at rest; access logged; delete after N days (suggest 30) or on request.
- **Upload only the finished report** (the same page and email text) with a per-customer key kept in the OS credential store; never raw R365 data or passwords.
- A breach plan, privacy notice and customer terms: Jay becomes custodian of the customer's financial data.

Until then, a traveller gets the report the way the flow above already allows: the office computer creates the Microsoft 365 draft (or sends, if the admin ticked it), and the phone's mail app shows it.

## Things to say plainly to users

- Keep figures out of the subject line and the first lines (lock-screen previews). The subject carries counts only, no dollar amounts.
- Forwarding the email forwards the figures.
- If the office computer is off at the scheduled time, the report runs once when it next starts and is marked **late**.

## Recommendation

1. **Now:** Windows computer, view first, then choose to email (built). A phone sees the report by email.
2. **Only when users ask for something email can't do** (history, an office computer that is often off): build the hosted view page described above as a separate, clearly labelled opt-in, after deciding hosting, sign-in method, retention and customer terms.

## Decisions for Jay

1. Agree to stay at step 1 until a customer needs more?
2. If step 2 later: hosting provider, sign-in method, retention period, customer terms, who answers if something goes wrong.
3. Does the office computer stay on overnight? If not, the late-run behaviour matters more.
