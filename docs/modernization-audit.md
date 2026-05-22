# Modernization audit (Frappe app)

This audit follows `docs/frappe-app-standards-modernization-playbook.md` as the operating brief.

## App / version assumptions

- **App name**: `prakash_steel`
- **Frappe / ERPNext** (from `bench version`):
  - `frappe 15.99.0`
  - `erpnext 15.96.0`
  - other installed apps present: `crm`, `hrms`, `india_compliance`, `lms`
- **Python**: `Python 3.10.12` available as `python3` (note: `python` was not available in this environment via `pyenv`)
- **Bench execution environment**: `bench` runs directly from the repo checkout here (no explicit venv activation was required for `bench version`)
- **Audit test site (for follow-up commands)**: `rd.com`

## Commands attempted and results

Run from `/home/beeta/ramlal-bench/apps/prakash_steel`:

```bash
python -V
```

- Result: `python: command not found` (pyenv suggests 3.14.0 exists but not active)

```bash
python3 -V
```

- Result: `Python 3.10.12`

```bash
bench --version
```

- Result: `5.22.6`

```bash
bench version
```

- Result:
  - `crm 2.0.0-dev`
  - `erpnext 15.96.0`
  - `frappe 15.99.0`
  - `hrms 15.57.0`
  - `india_compliance 15.25.3`
  - `lms 2.44.0`
  - `prakash_steel 0.0.1`

Not attempted (needs a disposable test site / bench context):

- `bench --site [test_site] migrate`
- `bench --site [test_site] run-tests --app prakash_steel`

## Dry prompt template (audit-first; no edits)

Use this as the “audit prompt” in Cursor/VS Code:

```md
Read docs/frappe-app-standards-modernization-playbook.md and audit this repo against it.

Do not edit files yet.

Assume Frappe/ERPNext v15 and use site: rd.com

Create docs/modernization-audit.md with:
- app/version assumptions
- commands attempted and results
- P0/P1/P2/P3 findings
- exact file references
- recommended fix order
- tests that currently exist
- tests missing for risky behavior

Prioritize Frappe security, permissions, migrations, server-side validation, raw SQL, whitelisted methods, and test coverage.
```

## Standards to enforce during fixes (policy notes)

- **Sensitive data access**: prefer “document methods” / permission-aware APIs (e.g. `frappe.get_doc(...).check_permission(...)`, `frappe.get_list`) for any endpoint that returns sales, purchase, pricing, inventory, or customer/supplier details.
- **`ignore_permissions=True`**: every usage must be either removed or explicitly justified (server-side permission decision) and covered by tests.
- **No `frappe.db.commit()` in app logic**: do not manually commit inside request handlers, whitelisted methods, scheduled jobs, reports, or DocType code unless there is a documented Frappe-specific reason and tests (default stance: remove).
- **Pre-commit**: install locally and run it before any commit/push:

```bash
python3 -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## Inventory (high-signal)

- **Hooks**: `prakash_steel/hooks.py`
  - `doc_events` for `Item`, `BOM`, `Purchase Receipt` (others commented out)
  - scheduler cron runs `save_daily_on_hand_colour` daily (`prakash_steel.prakash_steel.report.po_recomendation_for_psp.po_recomendation_for_psp.save_daily_on_hand_colour`)
  - fixtures export `Custom Field` filtered by module
- **Migration patches**: `prakash_steel/patches.txt` exists but contains no entries.
- **Whitelisted methods (sampled)**:
  - `prakash_steel/api/get_item_insight_data.py`
  - `prakash_steel/api/get_available_stock.py`
  - `prakash_steel/api/get_last_sales_invoice_rate.py`
  - `prakash_steel/api/get_last_sales_invoice_sold_qty.py`
  - `prakash_steel/api/get_last_purchase_invoice_rate.py`
  - `prakash_steel/api/get_decoupled_lead_time.py`
  - `prakash_steel/api/number_card_uom.py`
  - `prakash_steel/api/check_item_has_bom.py`
  - `prakash_steel/prakash_steel/report/po_recomendation/po_recomendation.py` (whitelisted helpers that create Material Requests)
  - `prakash_steel/prakash_steel/report/po_recomendation_for_psp/po_recomendation_for_psp.py` (has whitelisted functions; file is very large)

## Findings (P0 / P1 / P2 / P3)

### P0 (release blockers: security/permissions/data exposure)

#### P0-001: Whitelisted methods return sensitive business data without explicit permission checks

**Why it matters**

- Playbook expectation: whitelisted APIs must validate inputs and enforce permissions; do not expose arbitrary DocType data to users who shouldn’t see it.
- Several `@frappe.whitelist()` methods return pricing, sales, purchase, and stock signals using raw SQL and/or `frappe.get_all` (which bypasses permission checks).

**Evidence (exact files)**

- `prakash_steel/api/get_item_insight_data.py`
  - `get_item_insight_data()` iterates stock items and returns:
    - last sales party/qty/rate, last purchase party/qty/rate, pending SO/PO qty, warehouse stock
  - uses multiple `frappe.db.sql(...)` queries; no `frappe.has_permission(...)` or document-level checks are performed.
- `prakash_steel/api/get_available_stock.py`
  - `get_available_stock(...)` / `get_available_stock_for_warehouse(...)` returns Bin quantities; no permission checks.
- `prakash_steel/api/get_last_sales_invoice_rate.py`
  - `get_last_sales_invoice_rate(...)` returns invoice item rate; no permission checks.
- `prakash_steel/api/get_last_sales_invoice_sold_qty.py`
  - `get_last_sales_invoice_sold_qty(...)` returns last sold qty; no permission checks.
- `prakash_steel/api/get_last_purchase_invoice_rate.py`
  - `get_last_purchase_invoice_rate(...)` returns purchase invoice item rate; no permission checks.
- `prakash_steel/api/number_card_uom.py`
  - `get_all_uom_settings()` uses `frappe.get_all("Number Card UOM Setting", ...)` (permission bypass) and returns all settings.

**Recommended fix order**

- Fix this first, before formatting/refactors:
  - decide per-endpoint required roles / permissions (e.g., `Item`, `Sales Invoice`, `Purchase Invoice`, `Bin`, `Warehouse`, custom settings DocType)
  - enforce with `frappe.has_permission` / `frappe.only_for` / `frappe.get_list` as appropriate
  - add regression tests for:
    - unauthorized users receive permission errors or empty results
    - authorized users still receive expected data shape

**Tests missing for risky behavior**

- Permission regression tests around each whitelisted endpoint.

#### P0-002: Whitelisted report helper can create/submit purchasing documents without an explicit authorization model

**Why it matters**

- `@frappe.whitelist()` methods that create and submit documents are high-risk and must have a clear server-side authorization contract (roles/permissions), plus tests.

**Evidence**

- `prakash_steel/prakash_steel/report/po_recomendation/po_recomendation.py`
  - `@frappe.whitelist() create_material_request(item_code, qty)`
  - `@frappe.whitelist() create_material_requests_automatically(filters=None)`
  - These create and submit `Material Request` documents. The current code relies on whatever permissions the current session user happens to have, but does not explicitly enforce or document the intended permission model for this API surface.

**Recommended remediation**

- Make authorization explicit (roles / permission checks) and add tests.

### P1 (unsafe maintainability debt / broken workflows)

#### P1-001: SQL parameter binding bug in multiple whitelisted methods

**Why it matters**

- Incorrect parameter tuples can break queries or behave unpredictably.

**Evidence**

- `prakash_steel/api/get_last_sales_invoice_rate.py`: passes `(item_code)` instead of `(item_code,)`
- `prakash_steel/api/get_last_sales_invoice_sold_qty.py`: passes `(item_code)` instead of `(item_code,)`
- `prakash_steel/api/get_last_purchase_invoice_rate.py`: passes `(item_code)` instead of `(item_code,)`

**Recommended fix**

- Correct bindings and add small tests for these endpoints.

#### P1-002: Permission bypass via `ignore_permissions=True` without documented decision and tests

**Why it matters**

- Playbook explicitly flags `ignore_permissions=True` as high risk unless documented and tested.

**Evidence**

- `prakash_steel/utils/sales_invoice.py`
  - `stock_entry.insert(ignore_permissions=True)` in both `create_material_receipt(...)` and `create_material_issue(...)`
  - Note: hooks for Sales Invoice are currently commented out in `prakash_steel/hooks.py`, but this code can be enabled later and should be made safe.
- `prakash_steel/prakash_steel/report/po_recomendation/po_recomendation.py`
  - `doc.insert(ignore_permissions=True)` inside `save_daily_on_hand_colour()`
- `prakash_steel/prakash_steel/report/po_recomendation_for_psp/po_recomendation_for_psp.py`
  - `doc.insert(ignore_permissions=True)` inside `save_daily_on_hand_colour()`

**Recommended fix**

- Document/justify permission bypass (or remove it) and add targeted tests.

#### P1-003: Manual transaction commit in scheduled job code

**Why it matters**

- Explicit `frappe.db.commit()` inside app logic can create partial writes and makes behavior harder to reason about (especially inside scheduler / report codepaths).

**Evidence**

- `prakash_steel/prakash_steel/report/po_recomendation/po_recomendation.py`: `save_daily_on_hand_colour()` calls `frappe.db.commit()`
- `prakash_steel/prakash_steel/report/po_recomendation_for_psp/po_recomendation_for_psp.py`: `save_daily_on_hand_colour()` calls `frappe.db.commit()`

**Recommended fix**

- Ensure scheduler job is idempotent and rely on standard transaction handling unless there is a documented Frappe-specific need for manual commits.

#### P1-004: Patch baseline is empty

**Why it matters**

- Playbook expectation: schema/data changes ship with patches and are recorded in `patches.txt`.

**Evidence**

- `prakash_steel/patches.txt` contains only section headers; no patches are listed.

**Recommended fix**

- If this app has ever shipped schema/data changes, formalize them as patches; otherwise document that patch baseline is intentionally empty and ensure future changes use patches.

### P2 (standards drift, future change risk)

#### P2-001: Heavy reliance on raw SQL for read models / dashboards without tests

**Evidence**

- `prakash_steel/api/get_item_insight_data.py` uses many `frappe.db.sql` queries.
- Large report modules (e.g. `prakash_steel/prakash_steel/report/po_recomendation/po_recomendation.py`) contain many SQL queries and business rules.

**Recommended fix**

- Add tests around business semantics first, then consider query builder / safer APIs where it does not change accounting/stock semantics.

### P3 (cosmetic/consistency; defer)

- No repo-wide formatting work recommended until P0/P1 are resolved per playbook.

## Tests: current state

Found DocType-adjacent tests (examples; non-exhaustive list):

- `prakash_steel/prakash_steel/doctype/**/test_*.py` (24 files detected)

No top-level `tests/` tree was detected via `**/tests/**/test_*.py`.

## Recommended fix order (backlog)

1. **P0-001**: Secure whitelisted methods that expose sales/purchase/stock data (permissions + tests).
2. **P0-002**: Explicit authorization and tests for whitelisted document-creating APIs.
3. **P1-001**: Fix SQL parameter binding bugs (add tests).
4. **P1-002 / P1-003**: Remove/justify permission bypasses and manual commits in scheduled jobs (idempotency + tests).
5. **P1-004**: Patch baseline clarification and/or add required patches.
6. **P2 items**: Raw SQL hardening + refactors only after behavior is covered by tests.

## Status tracking

- P0-001: **open**
- P0-002: **open**
- P1-001: **open**
- P1-002: **open**
- P1-003: **open**
- P1-004: **open**

