# Agreement inquiries (US-18)

Open **الشراكات ← الاستعلامات** (`/partnerships/agreements/inquiries/`) to search agreements across all authorized partnerships.

## Filters

All active filters combine with **AND** semantics on top of the user's regional scope:

1. **سنة الاتفاقية (`year`)**: Matches `AgreementDetails.signed_on` year (supports Western and Arabic numerals, `1900–2100`).
2. **المنطقة (`region`)**: Matches partnerships assigned to the region (`PartnershipRegion`) or agreements whose `signing_region` matches. Region dropdown choices are scoped to the user's allowed regions.
3. **الموقّع (`signatory`)**: Searches `institution_signatory`, `partner_signatory`, and their titles.
4. **الإدارة المعنية (`department`)**: Matches `AgreementDetails.departments` using an `EXISTS` subquery (no join duplication).
5. **فريق العمل (`team`)**: Searches `AgreementMember` name, organization, email, and phone (with Arabic digit normalization).
6. **ضابط الاتصال (`contact`)**: Searches `AgreementMember` records strictly with `role=TeamRole.CONTACT`, keeping contact officers distinct from `AgreementDetails.department_representative` and other team roles.
7. **الموظف (`employee`)**: Matches `AgreementDetails.responsible_employee` or `AgreementDetails.department_representative`. Employee dropdown choices are scoped to the user's regional boundary.
8. **نسبة إنجاز الاتفاقية (`progress_min`, `progress_max`)**: Filters agreements by their rounded mean clause progress (`ROUND_HALF_UP` to 2 decimal places, matching `agreement_clauses.models.mean_progress`). Agreements without clause assignments have no percentage and are excluded when a numeric range is set.

## Security & Release

- Protected by `AccessBoundaryMiddleware` and `@module_view('partnerships')` (`GET`/`HEAD` requires `partnerships.view`; exports require `export_xlsx`/`export_pdf`; mutations are denied).
- Regional scoping (`access_control.regions.scoped`) is applied to `Partnership` before any user filter, preventing cross-region leakage via direct URLs or crafted query parameters.
- No database migrations are required.
