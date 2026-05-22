# Frappe App Standards Modernization Playbook

Use this document to audit an existing Frappe or ERPNext app and bring it closer to Frappe standards for code quality, maintainability, security, testing, migration safety, and documentation.

This is not a blind formatter pass. Frappe and ERPNext explicitly expect reviewed, intentional changes, server-side business rules, permission-safe APIs, migration patches for schema/data changes, and tests for even small behavior changes.

## Source Baseline

Checked on 2026-05-05 against:

- Frappe Framework repository: https://github.com/frappe/frappe
- ERPNext repository: https://github.com/frappe/erpnext
- ERPNext coding standards: https://github.com/frappe/erpnext/wiki/Coding-Standards
- ERPNext code security guidelines: https://github.com/frappe/erpnext/wiki/Code-Security-Guidelines
- ERPNext pull request checklist: https://github.com/frappe/erpnext/wiki/Pull-Request-Checklist
- Frappe testing docs: https://docs.frappe.io/framework/v15/user/en/testing
- Frappe UI integration testing docs: https://docs.frappe.io/framework/user/en/guides/automated-testing/integration-testing

Before applying this to a project, confirm the app's Frappe major version and align exact Python, Node, Ruff, Prettier, Cypress, and bench commands with that branch.

## The Standard

A Frappe-standard app should pass these expectations:

- DocTypes, controllers, hooks, fixtures, permissions, and patches are the source of truth for business behavior.
- Business rules and validations live on the server side, with client scripts used only for interaction help and immediate feedback.
- Whitelisted methods validate input types, enforce permissions, avoid arbitrary document access, and return predictable shapes.
- Database reads prefer `frappe.get_list`, `frappe.db.get_value`, `frappe.db.get_all` when permission bypass is intentional, or `frappe.qb` before raw SQL.
- Raw SQL uses parameter binding or explicit escaping, never string interpolation of request-controlled values.
- Schema and data changes ship with migration patches and are recorded in `patches.txt`.
- Tests exist for DocType logic, whitelisted APIs, permissions, migrations, and meaningful UI flows.
- Tooling is installed through `pre-commit` and CI, not left to personal editor settings.
- User-facing strings are translatable with `_()` in Python and `__()` in JavaScript.
- Docs explain behavior, setup, migrations, and operational concerns well enough for another team to maintain the app.

## Modernization Flow

Run this in phases. Do not start with a repo-wide formatting sweep; it creates churn before the risky parts are understood.

1. **Create an audit issue**
   - Link the app, branch, Frappe version, ERPNext dependency version, and production sites affected.
   - Record scope: whole app, module, release blocker, security pass, or test hardening pass.
   - Add a risk log for permission, accounting, stock, payroll, external API, and background job changes.

2. **Freeze a baseline**
   - Run the current test suite and record failures before touching code.
   - Export installed app versions with `bench version`.
   - Capture current migrations with `bench --site [site] migrate` on a disposable site.
   - Save current lint/type/check output.

3. **Inventory the app**
   - List DocTypes, hooks, patches, whitelisted methods, scheduled jobs, reports, print formats, fixtures, custom fields, web forms, and client scripts.
   - Mark each item as active, obsolete, unknown, or external-contract.
   - Identify modules that touch money, stock ledger, payroll, permissions, files, or external integrations.

4. **Fix blockers first**
   - Security and permission bypasses.
   - Broken migrations.
   - Data corruption risks.
   - Failing tests for shipped behavior.
   - API contracts used by other apps or integrations.

5. **Then improve maintainability**
   - Split long functions when they perform multiple jobs.
   - Move repeated DocType logic into controller methods or small helper modules.
   - Replace client-only validation with server validation.
   - Replace raw SQL with Frappe DB APIs or query builder where possible.
   - Add tests around the behavior before changing it.

6. **Adopt tooling last**
   - Add `pre-commit` with Frappe/ERPNext-shaped hooks.
   - Run formatting in small, reviewed batches.
   - Keep pure formatting commits separate from behavior commits.

## Severity Model

Use this model when converting audit notes into issues:

| Severity | Meaning                                                             | Examples                                                                                           | Action                                          |
| -------- | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| P0       | Active security, data loss, or migration failure risk               | SQL injection, permission bypass, destructive patch, accounting or stock corruption                | Stop release work and fix immediately           |
| P1       | Broken user workflow or unsafe maintainability debt in core modules | Client-only validation, failing tests, non-idempotent background job, raw SQL in financial logic   | Fix before the next release                     |
| P2       | Standards drift that raises future change risk                      | Long mixed-responsibility controller method, missing tests for a non-critical API, incomplete docs | Schedule in the modernization backlog           |
| P3       | Cosmetic or consistency cleanup                                     | Formatting drift, minor naming cleanup, old comments                                               | Batch only after higher-severity work is stable |

## Audit Commands

Run from the bench root unless noted.

```bash
bench version
bench --site [test_site] migrate
bench --site [test_site] run-tests --app [app_name]
bench --site [test_site] run-tests --app [app_name] --junit-xml-output test-results.xml
```

Run from the app directory:

```bash
python -m pip install pre-commit
pre-commit run --all-files
ruff check .
ruff format --check .
```

For UI flows in apps that use Cypress:

```bash
yarn install
yarn cypress:open
```

Use targeted searches to find risky patterns:

```bash
rg -n "@frappe.whitelist|ignore_permissions|frappe.db.sql|eval\\(|exec\\(|frappe.get_doc\\(|frappe.get_all\\(" [app_name]
rg -n "cur_frm|\\$c_obj|get_query|add_fetch" [app_name]
rg -n "_\\(|__\\(" [app_name]
rg -n "patches.txt|execute\\(" [app_name]
```

## Code Quality Checklist

### Python

- Use tabs for indentation in Frappe/ERPNext app code when matching existing app style.
- Keep functions small enough to read and review; split when one function mixes fetching, validation, mutation, and presentation.
- Place the calling function above helper functions in a file when practical.
- Prefer explicit names and simple conditionals over compressed boolean expressions.
- Keep comments focused on why the code exists or why a non-obvious decision was made.
- Avoid deprecated globals and APIs.
- Keep imports sorted by Ruff.
- Avoid broad exception handling unless the error is intentionally converted to a user-visible Frappe exception.

### JavaScript

- Keep client scripts thin: field reactions, UI affordances, and calls into server APIs.
- Do not rely on client scripts for business-critical validation.
- Use `__()` for all user-facing strings.
- Avoid deprecated globals such as `cur_frm` in new code; use the current `frm` APIs inside form handlers.
- Keep reports, list views, and form scripts close to their DocType or module.

### DocTypes And Controllers

- Put validations in controller hooks such as `validate`, `before_save`, `before_submit`, `on_submit`, `on_cancel`, and explicit helper methods.
- Use child tables for structured repeatable data instead of JSON blobs unless the payload is truly schemaless.
- Keep naming, autoname, permissions, indexes, and links deliberate.
- Add database indexes only for measured query paths.
- Keep fixtures small and intentional; avoid exporting unrelated site state.

## Security And Permissions Checklist

Treat these as release blockers.

- Whitelisted methods have type annotations or explicit type checks.
- Whitelisted methods call `doc.check_permission("read")`, `doc.check_permission("write")`, `frappe.has_permission`, or `frappe.only_for` where needed.
- APIs do not accept arbitrary `doctype`, `name`, method paths, field names, or filter structures without an allowlist.
- Code does not call `insert`, `save`, `submit`, or `delete` with `ignore_permissions=True` unless there is a documented server-side permission decision.
- `frappe.get_doc` results returned to users are permission checked.
- Use `frappe.get_list` when permissions should apply; use `frappe.get_all` only when bypassing permissions is intentional and safe.
- Prefer `frappe.qb` or Frappe DB APIs over raw SQL.
- Raw SQL binds parameters with `%s` or named parameters.
- No user-controlled value is inserted into SQL with `.format`, f-strings, or concatenation.
- No user-controlled file path is read or written directly; use the File DocType API or constrain paths to the site.
- Avoid `eval` and `exec`; if dynamic evaluation is unavoidable, use Frappe safe utilities with tightly controlled globals and locals.
- Background jobs and scheduled tasks are idempotent or protected against duplicate execution.

## Testing Checklist

Frappe tests can live anywhere, but test files should be named `test_*.py`. DocType tests usually live beside the DocType as `test_[doctype].py`.

Minimum useful coverage:

- Controller validations and lifecycle methods.
- Whitelisted methods, including permission failures.
- Query helpers and reports that implement business rules.
- Migration patches that transform existing data.
- Background jobs and scheduled tasks.
- Client or Cypress tests for cross-page Desk workflows.

Test design:

- Create required dependencies inside the test file or a small fixture helper.
- Use test sites, usually named with a `test_` prefix, to prevent accidental data loss.
- Avoid tests that depend on production data, mutable dates, or global user state.
- Use `frappe.set_user` deliberately and reset state when needed.
- For money, stock, payroll, and accounting flows, assert ledger or child-table side effects, not only return values.

Useful commands:

```bash
bench --site [test_site] run-tests --app [app_name]
bench --site [test_site] run-tests --doctype "Sales Invoice"
bench --site [test_site] run-tests --module [python.module.path]
bench --site [test_site] run-tests --module [python.module.path] --test [test_name]
```

## Migration And Data Safety Checklist

- Every schema or data change has a patch.
- Patch files are added to the correct module/version path and listed in `patches.txt`.
- Patches are idempotent or safely detect completed work.
- Patches handle missing optional apps, missing records, renamed fields, and partial prior runs.
- Patches avoid loading huge tables into memory.
- Patches use explicit commits only when there is a documented Frappe reason.
- Destructive migrations include a backup and rollback note in the release issue.
- Custom fields, property setters, roles, workflows, and fixtures are reviewed as deployable app state.

## Documentation Checklist

Each app should include:

- `README.md` with purpose, supported Frappe/ERPNext versions, install steps, setup, development commands, test commands, and deployment notes.
- Module-level docs for business workflows that are hard to infer from DocType names.
- API docs for whitelisted methods used by external clients.
- Migration notes for breaking changes, renamed fields, removed DocTypes, and manual operator steps.
- Security notes for roles, permission assumptions, scheduled jobs, webhooks, OAuth credentials, and file handling.
- Release notes or changelog entries for user-visible behavior.

For every PR:

- Explain the problem and why this solution was chosen.
- Link issue, migration patch, and docs.
- Include before/after screenshots or a short recording for UI changes.
- List tests run and any known gaps.

## Recommended Pre-Commit Shape

ERPNext uses pre-commit with hooks for whitespace, YAML/JSON/TOML checks, merge conflict detection, Python AST/debug statements, Prettier for JavaScript/Vue/SCSS, ESLint for JavaScript, and Ruff for Python import sorting, linting, and formatting.

Adopt this shape gradually:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.3.0
    hooks:
      - id: trailing-whitespace
      - id: check-yaml
      - id: check-json
      - id: check-toml
      - id: check-merge-conflict
      - id: check-ast
      - id: debug-statements
  - repo: https://github.com/pre-commit/mirrors-prettier
    rev: v2.7.1
    hooks:
      - id: prettier
        types_or: [javascript, vue, scss]
  - repo: https://github.com/pre-commit/mirrors-eslint
    rev: v8.44.0
    hooks:
      - id: eslint
        types_or: [javascript]
        args: ["--quiet"]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.2.0
    hooks:
      - id: ruff
        name: "Run ruff import sorter"
        args: ["--select=I", "--fix"]
      - id: ruff
        name: "Run ruff linter"
      - id: ruff-format
        name: "Run ruff formatter"
```

Pin versions to the Frappe/ERPNext branch your app targets before rolling this into CI.

## PR Readiness Gate

A modernization PR is ready only when:

- It has a linked issue and clear scope.
- Security and permission-sensitive changes are explained.
- Data migrations were run on a disposable copy of a real site when relevant.
- Tests were added or the reason for no tests is explicit.
- `bench --site [test_site] run-tests --app [app_name]` passes or known upstream failures are documented.
- `pre-commit run --all-files` passes for touched files or adoption gaps are logged.
- User-facing docs and screenshots are updated for UI/workflow changes.
- The change is not a purely automated bulk patch unless maintainers explicitly approved that strategy.

## Suggested Remediation Backlog

Use this ordering for existing apps:

1. Security and permission audit.
2. Migration safety audit.
3. Broken test and CI baseline.
4. Whitelisted API contract cleanup.
5. Server-side validation parity for client-side behavior.
6. Raw SQL replacement or parameterization.
7. DocType/controller maintainability cleanup.
8. Test coverage for money, stock, payroll, and external integrations.
9. Pre-commit and CI adoption.
10. Documentation and release-note cleanup.

This order keeps the work anchored in user and data safety before style. That is the spirit of Frappe quality: metadata-driven, server-enforced, permission-aware, tested behavior that another team can safely maintain.
