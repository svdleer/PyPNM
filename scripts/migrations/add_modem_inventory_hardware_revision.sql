-- Production migration for the large modem_inventory_current table.
-- ALGORITHM=INSTANT prevents a table copy; LOCK=NONE prevents a blocking DDL
-- fallback. The statement must fail if the server cannot honor both clauses.
-- Apply this migration explicitly before creating a CM-poller MySQL backfill.
ALTER TABLE modem_inventory_current
    ADD COLUMN hardware_revision VARCHAR(80) NULL,
    ALGORITHM=INSTANT,
    LOCK=NONE;
