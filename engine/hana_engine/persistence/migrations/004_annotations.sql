-- Human judgement about what the analyzers found.
--
-- The schema has always allowed `verification_status = 'manual'` and nothing
-- ever wrote it. This is what writes it: a person confirming an inference HANA
-- guessed at, or rejecting one that is simply wrong.
--
-- Why a separate table rather than a column on `entities` and `relationships`:
-- reanalysing a file *deletes* its relationships and rebuilds them from the
-- source. A verdict living in the rebuilt row would be erased by the next run,
-- and it would be erased silently, which is the worst possible way to lose
-- somebody's work. Judgement outlives the analysis that prompted it, so it
-- lives somewhere the analysis does not touch, and is reapplied afterwards.
--
-- `identity_key` and not `id` for the same reason. Entity ids are ULIDs handed
-- out at insert time; an entity whose only supporting file changes is deleted
-- and recreated with a new one. Identity keys are derived from what the thing
-- *is*, so they survive.
--
-- For a relationship the key is deliberately *not* the one in `relationships`,
-- which embeds entity ids and the file that proved it. A person rejecting
-- "P117_NETWGT maps to UC_INSP_ENT.NETWGT" is ruling on the claim, not on which
-- file happened to demonstrate it. The key is therefore semantic:
--     <source identity_key>|<relation_type>|<target identity_key>

CREATE TABLE annotations (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    -- 'entity' | 'relationship'
    target_kind  TEXT NOT NULL,
    -- Semantic identity of what is being judged. Survives reanalysis.
    target_key   TEXT NOT NULL,
    -- 'confirmed' | 'rejected'
    verdict      TEXT NOT NULL,
    -- Why. The part that turns a click into knowledge somebody else can use.
    note         TEXT,
    author       TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE(project_id, target_kind, target_key),
    CHECK (target_kind IN ('entity', 'relationship')),
    CHECK (verdict IN ('confirmed', 'rejected'))
);

CREATE INDEX ix_annotations_project ON annotations(project_id, target_kind);
