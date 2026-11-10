-- =====================================================================
-- Least-privilege database user for the web app (run as the admin user).
-- The app can READ everything but can only WRITE the application tables.
-- Even if an attacker found a SQL injection, they could not drop or alter
-- tables or change the match data.
--
-- Cloud SQL: the user is created by deploy/gcp_setup.sh with
--   gcloud sql users create ipl_app ...
-- which adds it to cloudsqlsuperuser by default, so we revoke that here.
-- Locally: create it first with  CREATE ROLE ipl_app LOGIN PASSWORD '...';
-- =====================================================================

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cloudsqlsuperuser') THEN
    EXECUTE 'REVOKE cloudsqlsuperuser FROM ipl_app';
  END IF;
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'Could not revoke cloudsqlsuperuser from ipl_app - check with: \du ipl_app';
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ipl_app;
GRANT USAGE ON SCHEMA public TO ipl_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ipl_app;               -- includes views and materialized views
GRANT INSERT, UPDATE, DELETE ON draft_pick, draft_board, app_user, board_member TO ipl_app;
GRANT USAGE, SELECT ON SEQUENCE draft_pick_pick_id_seq,
                                draft_board_board_id_seq,
                                app_user_user_id_seq TO ipl_app;
