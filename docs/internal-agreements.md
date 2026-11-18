# Internal agreement record (US-16)

Open a partnership, select its numbered agreement, then choose **بيانات الاتفاقية**. Existing agreement identifiers, clauses and progress stay in place. Legacy records can be completed when the information becomes available.

- **التصنيف والتوقيع**: agreement status and classification, partnership and organization types, signing location, headquarters city, departments, signature and term.
- **الموقّعون وجهات الاتصال**: both signatories and positions, organization contact details, the responsible employee and the department representative. Each side has its own roster of representatives, leads, members and contact officers.
- **هدف الشراكة والنتائج**: the objective, announcement, audience and expected results.

Local edits follow the partnership's view/edit permissions and administrative regions. The signing region documents the signing location and cannot change access. Selecting an employee records their responsibility; it does not grant permissions or assign tasks.

Open **بنود الاتفاقية → القوائم المرجعية للاتفاقيات** to maintain the available types, statuses, classifications, departments and Saudi cities. Administrators can distinguish units from departments. Deactivated options remain attached to existing records; they cannot be newly selected. The migration seeds starter values and does not copy or change the partnership's existing data.

## Dates and renewal

Use a signing date and a duration in calendar months. The server adds the requested months and uses the final day of the target month if necessary (31 January plus one month is 28 February, or 29 in a leap year). Agreement dates are separate from partnership dates and partnership expiry reminders.

Once a term and renewal rule are saved, use **تسجيل تجديد**. The next period starts at the current expiry. For prior approval the operator must enter the approval reference. The automatic rule records the contract's renewal terms; the system records a new period when staff confirm it. It does not extend agreements in the background. Previous periods and the original signing date are preserved. After the first renewal the original signing date and duration are locked.

## Release

Apply on top of the existing agreement clauses release. The additive migrations create dedicated detail, team, reference and renewal tables. Existing records keep their agreement numbers and clause assignments. The production web container applies migrations during its normal startup.
