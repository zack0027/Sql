-- Record which analyzer suite produced a file's knowledge.
--
-- Incremental analysis decides what to re-read by comparing content hashes. That
-- is right for files that change, but it silently leaves knowledge stale when
-- the *analyzers* change: adding band extraction to the JRXML analyzer did
-- nothing for the eighty-six reports already in the database, because none of
-- their bytes had moved. The user saw a report with no bands and no reason why.
--
-- Storing the suite version alongside the analysed hash lets the pipeline
-- re-read a file whose content is unchanged but whose knowledge was produced by
-- an older analyzer. NULL means "analysed before this column existed", which is
-- treated as stale.

ALTER TABLE files ADD COLUMN analyzed_by TEXT;

CREATE INDEX ix_files_analyzed_by ON files(project_id, analyzed_by);
