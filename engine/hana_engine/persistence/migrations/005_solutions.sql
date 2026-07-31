-- What fixed it.
--
-- `Error` and `Solution` have been in the domain since the first commit with
-- nothing ever producing them. The log analyzer produces the errors; this table
-- holds the other half, the half no analyzer can ever find: a person writing
-- down what made the failure stop.
--
-- Same reasoning as `annotations` (004): reanalysing the log that first showed
-- an error deletes and rebuilds its rows, so a solution stored on the error
-- itself would be erased by the next run. It is keyed by the error's
-- `identity_key` — code plus the object it names — which is derived from what
-- the failure *is* and therefore survives.
--
-- That key is also what makes this worth having. An error's identity is its
-- code and its object, so the same failure appearing in ten logs across two
-- years is one row here, and the solution written the first time is waiting the
-- tenth. The recurrence count is the number of evidence rows behind that error,
-- which the pipeline already writes without being asked.

CREATE TABLE solutions (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    -- identity_key of the Error entity this resolves.
    error_key    TEXT NOT NULL,
    -- What was done. Free text on purpose: the useful answer is a sentence,
    -- not a category from a list somebody guessed at in advance.
    description  TEXT NOT NULL,
    author       TEXT,
    -- Whether it actually worked. A remedy that did not is worth keeping: it
    -- stops the next person spending an afternoon on the same dead end.
    worked       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE(project_id, error_key, description),
    CHECK (worked IN (0, 1))
);

CREATE INDEX ix_solutions_project ON solutions(project_id, error_key);
