-- PostGIS in der Comoot-Datenbank aktivieren.
-- Laeuft einmalig beim ersten Start des db-Containers (leeres Daten-Volume).
-- Hinweis: postgis/postgis:16-3.4 laedt die Extensions bereits selbst in
-- $POSTGRES_DB (10_postgis.sh). Diese Datei ist damit ein Sicherheitsnetz
-- (z.B. bei Wechsel auf ein Basis-Image) und idempotent durch IF NOT EXISTS.
CREATE EXTENSION IF NOT EXISTS postgis;
