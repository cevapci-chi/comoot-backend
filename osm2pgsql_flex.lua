-- osm2pgsql flex config for Comoot surface classification
-- Output: PostGIS tables with surface, smoothness, tracktype tags

local tables = {}

tables.ways = osm2pgsql.define_way_table('osm_ways', {
    {column = 'id', type = 'int8', not_null = true},
    {column = 'geom', type = 'linestring', projection = 4326, not_null = true},
    {column = 'highway', type = 'text'},
    {column = 'surface', type = 'text'},
    {column = 'smoothness', type = 'text'},
    {column = 'tracktype', type = 'text'},
    {column = 'name', type = 'text'},
    {column = 'maxspeed', type = 'text'},
    {column = 'lanes', type = 'int'},
    {column = 'width', type = 'text'},
    {column = 'bicycle', type = 'text'},
    {column = 'foot', type = 'text'},
    {column = 'horse', type = 'text'},
    {column = 'mtb_scale', type = 'text'},
    {column = 'sac_scale', type = 'text'},
    {column = 'trail_visibility', type = 'text'},
    {column = 'incline', type = 'text'},
    {column = 'layer', type = 'text'},
    {column = 'bridge', type = 'text'},
    {column = 'tunnel', type = 'text'},
    {column = 'natural', type = 'text'},
    {column = 'landuse', type = 'text'},
    {column = 'tourism', type = 'text'},
    {column = 'historic', type = 'text'},
})

-- Surface classification helper
local function classify_surface(tags)
    local surface = tags.surface or ''
    local smoothness = tags.smoothness or ''
    local tracktype = tags.tracktype or ''
    local highway = tags.highway or ''

    -- Blocked for bikes
    if highway == 'motorway' or highway == 'trunk' then
        return 'blocked'
    end

    -- Road bike (asphalt only)
    if surface:match('^asphalt$') or surface:match('^paved$') or surface:match('^concrete$') or surface:match('^paving_stones$') then
        if smoothness == 'excellent' or smoothness == 'good' or smoothness == '' then
            return 'road_good'
        elseif smoothness == 'intermediate' then
            return 'road_ok'
        else
            return 'road_poor'
        end
    end

    -- Gravel ideal
    if surface:match('^fine_gravel$') or surface:match('^compacted$') then
        return 'gravel_ideal'
    end

    -- Gravel ok
    if surface:match('^gravel$') or surface:match('^dirt$') or surface:match('^earth$') or surface:match('^unpaved$') then
        return 'gravel_ok'
    end

    -- Tracktype-based
    if tracktype == 'grade1' or tracktype == 'grade2' then
        return 'gravel_ideal'
    elseif tracktype == 'grade3' then
        return 'gravel_ok'
    elseif tracktype == 'grade4' or tracktype == 'grade5' then
        return 'gravel_poor'
    end

    -- Avoid
    if surface:match('^sand$') or surface:match('^mud$') or surface:match('^pebblestone$') or surface:match('^cobblestone$') or surface:match('^sett$') then
        return 'avoid'
    end

    -- Default for paths/tracks without surface tag
    if highway == 'path' or highway == 'track' then
        return 'unknown'
    end

    -- Default for residential/service/cycleway
    if highway == 'cycleway' then
        return 'road_good'
    elseif highway == 'residential' or highway == 'service' then
        return 'road_ok'
    end

    return 'unknown'
end

function osm2pgsql.process_way(object)
    local tags = object.tags

    -- Only process ways that are relevant for cycling
    local highway = tags.highway
    if not highway then return end

    local relevant_highways = {
        motorway = true, trunk = true, primary = true, secondary = true,
        tertiary = true, residential = true, service = true,
        cycleway = true, path = true, track = true,
        unclassified = true, living_street = true
    }

    if not relevant_highways[highway] then return end

    -- Classify surface
    local surface_class = classify_surface(tags)

    tables.ways:insert({
        id = object.id,
        geom = object:as_linestring(),
        highway = highway,
        surface = tags.surface,
        smoothness = tags.smoothness,
        tracktype = tags.tracktype,
        name = tags.name,
        maxspeed = tags.maxspeed,
        lanes = tags.lanes and tonumber(tags.lanes) or nil,
        width = tags.width,
        bicycle = tags.bicycle,
        foot = tags.foot,
        horse = tags.horse,
        mtb_scale = tags['mtb:scale'],
        sac_scale = tags.sac_scale,
        trail_visibility = tags.trail_visibility,
        incline = tags.incline,
        layer = tags.layer,
        bridge = tags.bridge,
        tunnel = tags.tunnel,
        natural = tags.natural,
        landuse = tags.landuse,
        tourism = tags.tourism,
        historic = tags.historic,
    })
end