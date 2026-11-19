# Task assignment & reassignment (US-04 / US-05)

Extends **متابعة الأعمال** (`makken_mail.WorkAssignment`):

- **Multi-employee assignments:** `WorkAssignment.assignees` (M2M, backfilled from `employee`) lets one task be assigned to one or more employees. All assignees can view the task, update progress, and receive email notifications (`work.created`, `work.reassigned`, `work.progress`, `work.edited`).
- **Agreement linking:** Registers `agreement_clauses.agreement` in `WORK_TARGETS` (`اتفاقية`), supporting search by ID, `AGR-XXXXXX`, title, or partnership name in `/my-work/targets/` and linking directly to US-17 (`partnerships:agreement`).
- **Authorized managers (RBAC & regional scope):** Registers `work_assignments` (`إسناد المهام`) in `access_control` (`view`, `create`, `edit`, `export_xlsx`, `export_pdf`). Super Admins and authorized managers can assign and reassign open tasks strictly within their regional and module scope.

## Migrations

- `access_control.0009_work_assignments_module` (registers `work_assignments` module and permissions).
- `makken_mail.0006_work_multi_assignees` (adds `WorkAssignment.assignees` and backfills existing rows).
