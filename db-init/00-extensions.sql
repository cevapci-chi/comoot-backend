-- PostGIS in der Comoot-Datenbank aktivieren.
-- Laeuft einmalig beim ersten Start des db-Containers (leeres Daten-Volume).
-- osm2pgsql (flex/linestring) und schema.sql setzen PostGIS voraus.
CREATE EXTENSION IF NOT EXISTS postgis;
