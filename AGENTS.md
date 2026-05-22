# Agent operating brief (Frappe modernization)

When modernizing this Frappe app:

- Read `docs/frappe-app-standards-modernization-playbook.md` first and follow it as the operating brief (not a summary).
- Follow its P0/P1/P2/P3 severity model.
- Do not do repo-wide formatting before security, migration, permission, and test-baseline issues are triaged.
- Keep each fix scoped to one issue or one audit finding.

Default workflow:

1. Playbook
2. Audit report
3. Prioritized backlog
4. One scoped fix PR (tests/docs)
5. Next fix

Additional safety constraints:

- Do not run automatic repo-wide formatting.
- Before committing or pushing, run pre-commit locally (and fix findings).
- Do not change generated DocType JSON unless required for the specific fix.
- Do not modify migration patches without explaining migration safety and idempotency.
- Do not use `ignore_permissions=True` unless the permission decision is documented and covered by tests.
- Do not replace raw SQL mechanically if the query has business/accounting semantics; add tests first.
