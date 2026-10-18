-- Comoot database schema for OSM data + surface classification + scenic scoring
-- Run after osm2pgsql import (`make import-osm`). Idempotent: mehrfach ausfuehrbar.

-- 1. Surface classification enum
DO $$
BEGIN
    CREATE TYPE surface_class AS ENUM (
        'blocked',        -- motorway, trunk
        'road_good',      -- asphalt, excellent/good smoothness
        'road_ok',        -- asphalt intermediate, residential
        'road_poor',      -- asphalt bad smoothness
        'gravel_ideal',   -- fine_gravel, compacted, tracktype grade1-2
        'gravel_ok',      -- gravel, dirt, tracktype grade3
        'gravel_poor',    -- tracktype grade4-5
        'avoid',          -- sand, mud, cobblestone, sett
        'unknown'         -- paths without surface tag
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;  -- Enum existiert bereits
END $$;

-- 2. Extend osm_ways with surface_class
ALTER TABLE osm_ways ADD COLUMN IF NOT EXISTS surface_class surface_class;

-- 3. Update surface_class based on tags
UPDATE osm_ways SET surface_class = CASE
    WHEN highway IN ('motorway', 'trunk') THEN 'blocked'
    WHEN surface IN ('asphalt', 'paved', 'concrete', 'paving_stones')
         AND (smoothness IS NULL OR smoothness IN ('excellent', 'good')) THEN 'road_good'
    WHEN surface IN ('asphalt', 'paved', 'concrete', 'paving_stones')
         AND smoothness = 'intermediate' THEN 'road_ok'
    WHEN surface IN ('asphalt', 'paved', 'concrete', 'paving_stones')
         AND smoothness IN ('bad', 'very_bad', 'horrible', 'very_horrible', 'impassable') THEN 'road_poor'
    WHEN surface IN ('fine_gravel', 'compacted') THEN 'gravel_ideal'
    WHEN surface IN ('gravel', 'dirt', 'earth', 'unpaved') THEN 'gravel_ok'
    WHEN tracktype IN ('grade1', 'grade2') THEN 'gravel_ideal'
    WHEN tracktype = 'grade3' THEN 'gravel_ok'
    WHEN tracktype IN ('grade4', 'grade5') THEN 'gravel_poor'
    WHEN surface IN ('sand', 'mud', 'pebblestone', 'cobblestone', 'sett') THEN 'avoid'
    WHEN highway = 'cycleway' THEN 'road_good'
    WHEN highway IN ('residential', 'service', 'living_street') THEN 'road_ok'
    WHEN highway IN ('path', 'track') THEN 'unknown'
    ELSE 'unknown'
END::surface_class;

-- 4. Index for routing queries
CREATE INDEX IF NOT EXISTS idx_osm_ways_surface_class ON osm_ways (surface_class);
CREATE INDEX IF NOT EXISTS idx_osm_ways_highway ON osm_ways (highway);
CREATE INDEX IF NOT EXISTS idx_osm_ways_geom ON osm_ways USING GIST (geom);

-- 5. Scenic scoring table
CREATE TABLE IF NOT EXISTS scenic_features (
    id BIGSERIAL PRIMARY KEY,
    geom GEOMETRY(POINT, 4326),
    feature_type TEXT,  -- 'water', 'wood', 'viewpoint', 'historic', 'park'
    name TEXT,
    importance FLOAT DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_scenic_features_geom ON scenic_features USING GIST (geom);

-- 6. Scenic features aus OSM — derzeit deaktiviert.
-- Grund: osm2pgsql_flex.lua legt nur die Linientabelle `osm_ways` an; es gibt
-- weder `planet_osm_polygon`/`planet_osm_point` noch eine `tags`-HStore-Spalte.
-- Die folgenden Inserts liefen gegen das alte pgsql-Output und wuerden mit
-- ON_ERROR_STOP=1 den Import abbrechen. TODO: Polygon-/Punkt-Tabellen im
-- Flex-Config ergaenzen (Folge-Ticket), dann aktivieren.
--
-- INSERT INTO scenic_features (geom, feature_type, name, importance)
-- SELECT ST_Centroid(way.geom), 'water', way.tags->'name', 1.0
-- FROM planet_osm_polygon way
-- WHERE way.tags ? 'natural' AND way.tags->'natural' IN ('water', 'lake', 'river', 'stream');
--
-- INSERT INTO scenic_features (geom, feature_type, name, importance)
-- SELECT ST_Centroid(way.geom), 'wood', way.tags->'name', 0.8
-- FROM planet_osm_polygon way
-- WHERE way.tags ? 'landuse' AND way.tags->'landuse' = 'forest';
--
-- INSERT INTO scenic_features (geom, feature_type, name, importance)
-- SELECT node.geom, 'viewpoint', node.tags->'name', 1.2
-- FROM planet_osm_point node
-- WHERE node.tags ? 'tourism' AND node.tags->'tourism' = 'viewpoint';
--
-- INSERT INTO scenic_features (geom, feature_type, name, importance)
-- SELECT node.geom, 'historic', node.tags->'name', 1.0
-- FROM planet_osm_point node
-- WHERE node.tags ? 'historic' AND node.tags->'historic' IN ('castle', 'ruins', 'monument', 'memorial');
--
-- INSERT INTO scenic_features (geom, feature_type, name, importance)
-- SELECT ST_Centroid(way.geom), 'park', way.tags->'name', 0.9
-- FROM planet_osm_polygon way
-- WHERE way.tags ? 'leisure' AND way.tags->'leisure' IN ('park', 'nature_reserve');

-- 7. Segment scoring view for routing
CREATE OR REPLACE VIEW segment_scores AS
SELECT
    w.id,
    w.geom,
    w.highway,
    w.surface_class,
    w.name,
    -- Scenic score (0-1): proximity to scenic features
    LEAST(1.0, COALESCE((
        SELECT SUM(sf.importance / GREATEST(ST_Distance(w.geom::geography, sf.geom::geography), 100))
        FROM scenic_features sf
        WHERE ST_DWithin(w.geom::geography, sf.geom::geography, 5000)
    ), 0) * 10, 1.0) AS scenic_score,
    -- Traffic penalty (0=avoid, 1=prefer)
    CASE w.highway
        WHEN 'motorway' THEN 0.0
        WHEN 'trunk' THEN 0.0
        WHEN 'primary' THEN 0.3
        WHEN 'secondary' THEN 0.6
        WHEN 'tertiary' THEN 0.8
        WHEN 'residential' THEN 0.9
        WHEN 'service' THEN 0.9
        WHEN 'cycleway' THEN 1.0
        WHEN 'path' THEN 0.8
        WHEN 'track' THEN 0.7
        ELSE 0.5
    END AS traffic_score
FROM osm_ways w;