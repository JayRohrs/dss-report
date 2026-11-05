# Questions an owner asks

**Does my data leave my computer?**
No. The tool reads a file on the computer it runs on and writes its report on the same computer. Reading a DSS file makes no network call at all. It makes network calls only to places you set up: your email (if you turn email on), a language model on the same computer (if you turn that on), and an update address (only if you turn the optional update check on and press the button). There is no tracking and no analytics.

**Does it need my Restaurant365 password?**
No. With the DSS file route it never signs in to R365. You download the list yourself and give it the file. It keeps a copy of the file in its own folder on that computer and never changes the file you chose.

**Does it store any passwords?**
Not for the DSS file route. Only if you switch on optional email through Microsoft 365: you sign in on Microsoft's own page, the tool never sees your Microsoft password, and the sign-in is kept in Windows' own credential store, not in the tool's files. One command removes it: `python -m dssreport forget-secrets`.

**Can it change anything in Restaurant365?**
No. It cannot sign in, so it cannot change anything. It also cannot approve a day. Automatic approval does not exist in this tool.

**Who sees the report?**
Whoever can open the files on that computer, and whoever you email it to if you turn email on. Reports contain your figures, so treat the reports folder like the data it came from.

**What does it do when it is not sure?**
It says "Could not tell" and shows why: a blank or unclear status, no row for a day, a file older than today, a list that looks cut short, or two rows that disagree. It never counts those as approved.

**How do updates work?**
Only when Jay Rohrs sends you an update file (or, if you switch it on, you press a button to download one). You choose whether to install it. Nothing installs by itself. The tool checks on your computer that the file really is from Jay Rohrs and has not been changed, replaces only its own program files, and keeps your settings, licence and every earlier report. If you do not like the new version you can go back to the previous one. Whether updates are included in the price: **UNKNOWN**.

**What if Restaurant365 changes its file?**
The tool reads columns by name, not position, so a reordered file still works, and a new wording can be added by you without waiting for an update. If a column it needs is missing, it says exactly which one and which check could not run. If the file cannot be read at all, it says so and shows nothing.

**What does it cost, and what will it save me?**
Price: **UNKNOWN**. Savings and return on investment: **UNKNOWN**. No figure has been measured.

**Is it tested on real data?**
Not yet. It has been tested on invented files that follow the two layouts the owner has seen. A first check on a real download is still to be done, and some questions stay open until then (for example what the sign of the Over/Short number means in R365).

**Is it made or approved by Restaurant365?**
No. It is an independent tool for Restaurant365 users.

**Can I stop using it?**
Yes. Delete the program folder and its data folder, or run the uninstaller. The uninstaller is written but not yet run on a real Windows computer. R365 is unaffected either way, because nothing was ever changed there.

**What support do I get?**
Setup and support are available separately. Terms: **UNKNOWN**.
