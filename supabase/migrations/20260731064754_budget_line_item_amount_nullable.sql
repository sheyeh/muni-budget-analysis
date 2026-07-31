-- budget_line_item.amount is null for execution_pct rows by design
-- (docs/handshake-level3-postgres.md's "Resolutions of Prior Open
-- Questions": execution_pct columns have amount set to null to avoid
-- double-counting). Column must accept that.
alter table budget_line_item alter column amount drop not null;
