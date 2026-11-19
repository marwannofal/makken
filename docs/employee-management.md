# Employee management enhancements (US-01)

Extends **المستخدمون والصلاحيات** (`access_control`) and **الملف الشخصي** (`accounts`):

- **City & Department/Unit:** `UserProfile.city` and `UserProfile.department` reuse Makken's `AgreementOption` (`CITY` and `DEPARTMENT`) catalogs and are displayed on both the account editor and the user directory table.
- **Predefined Regions & RBAC:** Account creation/editing selects from `regions.Region` and saves directly to `UserAccess.region_scope` / `UserAccess.allowed_regions`, enforcing regional data access across the platform immediately.
- **Forced Password Change on First Login (Toggleable):** `UserProfile.must_change_password` defaults to **enabled** on account creation (and can be disabled by the Super Admin). When enabled, `AccessBoundaryMiddleware` redirects the employee to `/profile/` on every page (except logout) and displays a persistent RTL toaster until the password is updated.
- **Onboarding & Regional Assignment Emails:**
  - When enabled on account creation, sends an Arabic welcome email via `makken_mail` SMTP containing email, username, initial password, and forced-change instructions without ever storing the plaintext password in `SecurityAudit` or `Delivery`.
  - Queues a configurable `makken_mail` notification (`account.regions_assigned`) whenever an employee's regional scope is assigned or updated.
- **Employee Agreements Overview:** Displays every agreement where the employee is `responsible_employee` or `department_representative`, along with rounded progress (`mean_progress`), clause count, last follow-up timestamp/author, and links to US-17/US-16.

## Migrations

- `accounts.0002_employee_profile_and_password_policy` (additive fields on `UserProfile`; existing users default to `must_change_password=False`).
- `makken_mail.0005_account_regions_assigned` (registers `EventRule(code='account.regions_assigned', to_subject=True)`).
