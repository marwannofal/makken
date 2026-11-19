# Agreement follow-up (US-17)

Open **بطاقة المتابعة** from a numbered agreement. This is the existing agreement route. The progress total and clause editors use the original assignments. Both teams and contact officers use the same records as **بيانات الاتفاقية**.

In **سجل المتابعة**, add a note, evidence, or both. A new entry can optionally refer to a clause in the current agreement. The timeline records the author and Riyadh timestamp. Removing a clause assignment keeps the historical entries and the clause name. The card header shows who last updated the agreement and when. For older records it uses the most recent agreement, profile or clause timestamp available.

Evidence allows up to five PDF, PNG or JPEG files per entry, with a 10 MiB limit per file. The existing private upload volume stores the files. Downloads require the partnership export permission and access to the record's region. Each download is logged. Editing uses the partnership edit permission and its existing full-region rule. An inactive partnership remains view-only.

## Release

Apply on top of the internal agreement record release. Migration `agreement_clauses.0004_agreement_followup` adds tables for the timeline, evidence and last update without changing existing agreements or clause assignments. The production web container applies migrations at startup. Continue backing up the private upload volume alongside the database.
