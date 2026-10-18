"""Comoot Backend — BRouter integration.

FastAPI + BRouter (RouteServer) for real routing.
"""

import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
import httpx
import xml.etree.ElementTree as ET
import math
import asyncpg

# Database config
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///comoot")

app = FastAPI(
    title="Comoot API",
    description="Routenplanung für Rennrad, Gravel & Bikepacking",
    version="0.1.0",
)

CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# BRouter config
BROUTER_URL = os.environ.get("BROUTER_URL", "http://localhost:17777")
PROFILE_MAP = {
    "road": "fastbike",
    "gravel": "gravel",
    "bikepacking": "trekking",
}


# ---------- Schemas ----------

class Waypoint(BaseModel):
    lat: float = Field(..., example=51.3397)
    lng: float = Field(..., example=12.3731)


class RoutingPreferences(BaseModel):
    scenic: float = Field(0.5, ge=0.0, le=1.0)
    avoid_traffic: float = Field(0.5, ge=0.0, le=1.0)
    wind_optimize: bool = False
    max_gradient: float = Field(15.0, ge=1.0)


class PlanRequest(BaseModel):
    waypoints: List[Waypoint]
    profile: Literal["road", "gravel", "bikepacking"] = "gravel"
    preferences: RoutingPreferences = RoutingPreferences()


class Segment(BaseModel):
    distance_m: int
    surface: str
    surface_quality: str
    traffic_level: str
    scenic_score: float
    gradient_avg: float
    tire_width_mm: int


class Climb(BaseModel):
    name: str
    category: int
    length_km: float
    avg_gradient: float
    max_gradient: float


class PlanResponse(BaseModel):
    geometry: dict
    distance_km: float
    elevation_gain: int
    surface_breakdown: dict
    segments: List[Segment]
    climbs: List[Climb]


# ---------- Helpers ----------

def parse_gpx_distance_and_elevation(gpx_xml: str) -> tuple[float, int]:
    """Parse GPX XML, return (distance_m, elevation_gain_m)."""
    try:
        root = ET.fromstring(gpx_xml)
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        trkseg = root.find(".//gpx:trkseg", ns)
        if trkseg is None:
            return 0.0, 0

        points = trkseg.findall("gpx:trkpt", ns)
        if len(points) < 2:
            return 0.0, 0

        def haversine(lat1, lon1, lat2, lon2):
            R = 6371000
            phi1, phi2 = math.radians(lat1), math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
            return 2 * R * math.asin(math.sqrt(a))

        total_dist = 0.0
        total_elev_gain = 0
        prev = None
        for pt in points:
            lat = float(pt.get("lat"))
            lon = float(pt.get("lon"))
            ele_elem = pt.find("gpx:ele", ns)
            ele = float(ele_elem.text) if ele_elem is not None else 0
            if prev:
                total_dist += haversine(prev[0], prev[1], lat, lon)
                if ele > prev[2]:
                    total_elev_gain += ele - prev[2]
            prev = (lat, lon, ele)

        return total_dist, int(total_elev_gain)
    except Exception:
        return 0.0, 0


def estimate_surface_breakdown(profile: str, distance_km: float) -> dict:
    """Estimate surface breakdown based on profile and BRouter's typical behavior."""
    if profile == "road":
        return {"asphalt": 95, "gravel": 5, "trail": 0}
    elif profile == "gravel":
        return {"asphalt": 30, "gravel": 60, "trail": 10}
    else:  # bikepacking
        return {"asphalt": 40, "gravel": 45, "trail": 15}


def build_segments_from_profile(profile: str, distance_km: float, elev_gain: int) -> List[Segment]:
    """Build segment list matching the response schema."""
    if profile == "road":
        return [
            Segment(
                distance_m=int(distance_km * 1000 * 0.95),
                surface="asphalt",
                surface_quality="good",
                traffic_level="low",
                scenic_score=0.6,
                gradient_avg=round(elev_gain / (distance_km * 10) if distance_km > 0 else 0, 1),
                tire_width_mm=25,
            ),
            Segment(
                distance_m=int(distance_km * 1000 * 0.05),
                surface="gravel",
                surface_quality="compacted",
                traffic_level="none",
                scenic_score=0.7,
                gradient_avg=round(elev_gain / (distance_km * 10) if distance_km > 0 else 0, 1),
                tire_width_mm=28,
            ),
        ]
    elif profile == "gravel":
        return [
            Segment(
                distance_m=int(distance_km * 1000 * 0.3),
                surface="asphalt",
                surface_quality="good",
                traffic_level="low",
                scenic_score=0.5,
                gradient_avg=round(elev_gain / (distance_km * 10) if distance_km > 0 else 0, 1),
                tire_width_mm=32,
            ),
            Segment(
                distance_m=int(distance_km * 1000 * 0.6),
                surface="gravel",
                surface_quality="compacted",
                traffic_level="none",
                scenic_score=0.8,
                gradient_avg=round(elev_gain / (distance_km * 10) if distance_km > 0 else 0, 1),
                tire_width_mm=40,
            ),
            Segment(
                distance_m=int(distance_km * 1000 * 0.1),
                surface="trail",
                surface_quality="rough",
                traffic_level="none",
                scenic_score=0.9,
                gradient_avg=round(elev_gain / (distance_km * 10) if distance_km > 0 else 0, 1),
                tire_width_mm=45,
            ),
        ]
    else:  # bikepacking
        return [
            Segment(
                distance_m=int(distance_km * 1000 * 0.4),
                surface="asphalt",
                surface_quality="good",
                traffic_level="low",
                scenic_score=0.6,
                gradient_avg=round(elev_gain / (distance_km * 10) if distance_km > 0 else 0, 1),
                tire_width_mm=35,
            ),
            Segment(
                distance_m=int(distance_km * 1000 * 0.45),
                surface="gravel",
                surface_quality="compacted",
                traffic_level="none",
                scenic_score=0.8,
                gradient_avg=round(elev_gain / (distance_km * 10) if distance_km > 0 else 0, 1),
                tire_width_mm=42,
            ),
            Segment(
                distance_m=int(distance_km * 1000 * 0.15),
                surface="trail",
                surface_quality="rough",
                traffic_level="none",
                scenic_score=0.9,
                gradient_avg=round(elev_gain / (distance_km * 10) if distance_km > 0 else 0, 1),
                tire_width_mm=45,
            ),
        ]


def extract_climbs_from_gpx(gpx_xml: str) -> List[Climb]:
    """Extract notable climbs from GPX elevation data."""
    try:
        root = ET.fromstring(gpx_xml)
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        trkseg = root.find(".//gpx:trkseg", ns)
        if trkseg is None:
            return []

        points = trkseg.findall("gpx:trkpt", ns)
        if len(points) < 3:
            return []

        climbs = []
        current_climb = None
        min_climb_gain = 50  # minimum 50m elevation gain to count as climb

        for i, pt in enumerate(points):
            ele_elem = pt.find("gpx:ele", ns)
            if ele_elem is None:
                continue
            ele = float(ele_elem.text)

            if current_climb is None:
                current_climb = {"start_idx": i, "start_ele": ele, "max_ele": ele, "gain": 0}
            else:
                if ele > current_climb["max_ele"]:
                    current_climb["max_ele"] = ele
                current_climb["gain"] = current_climb["max_ele"] - current_climb["start_ele"]

                # Check if descent starts or end of track
                if i == len(points) - 1 or float(points[i + 1].find("gpx:ele", ns).text if points[i + 1].find("gpx:ele", ns) is not None else ele) < ele:
                    if current_climb["gain"] >= min_climb_gain:
                        climbs.append(Climb(
                            name=f"Anstieg {len(climbs)+1}",
                            category=max(1, min(4, int(current_climb["gain"] / 150))),  # rough HC-4
                            length_km=round(current_climb["gain"] / 100, 1),  # rough
                            avg_gradient=round(current_climb["gain"] / 500, 1),  # rough
                            max_gradient=round(current_climb["gain"] / 200, 1),
                        ))
                    current_climb = None

        return climbs[:5]  # max 5 climbs
    except Exception:
        return []


async def get_surface_breakdown_from_route(gpx_xml: str) -> dict:
    """Extract surface breakdown from PostGIS by finding ways near the route."""
    try:
        root = ET.fromstring(gpx_xml)
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        coords = []
        for pt in root.findall(".//gpx:trkpt", ns):
            coords.append((float(pt.get("lon")), float(pt.get("lat"))))

        if len(coords) < 2:
            return {"asphalt": 50, "gravel": 50, "trail": 0}

        # Build linestring for the route
        route_wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in coords) + ")"

        conn = await asyncpg.connect(DATABASE_URL)
        try:
            # Use bounding box pre-filter + ST_DWithin for performance
            # Get bbox from coordinates
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            bbox = f"{min(lons) - 0.005} {min(lats) - 0.005}, {max(lons) + 0.005} {max(lats) + 0.005}"

            rows = await conn.fetch("""
                SELECT surface_class, SUM(ST_Length(geom::geography)) as total_length
                FROM osm_ways
                WHERE geom && ST_MakeEnvelope($2, $3, $4, $5, 4326)
                AND ST_DWithin(
                    geom::geography,
                    ST_GeomFromText($1, 4326)::geography,
                    25
                )
                AND surface_class IS NOT NULL
                GROUP BY surface_class
                ORDER BY total_length DESC
                LIMIT 10
            """, route_wkt, min(lons), min(lats), max(lons), max(lats))
        finally:
            await conn.close()

        if not rows:
            return {"asphalt": 50, "gravel": 50, "trail": 0}

        # Map surface_class to display categories
        total = sum(r["total_length"] for r in rows) or 1
        breakdown = {"asphalt": 0, "gravel": 0, "trail": 0}
        for row in rows:
            sc = row["surface_class"]
            pct = round(row["total_length"] / total * 100)
            if sc in ("road_good", "road_ok", "road_poor"):
                breakdown["asphalt"] += pct
            elif sc in ("gravel_ideal", "gravel_ok", "gravel_poor"):
                breakdown["gravel"] += pct
            else:
                breakdown["trail"] += pct

        # Normalize to 100%
        s = sum(breakdown.values()) or 1
        for k in breakdown:
            breakdown[k] = round(breakdown[k] / s * 100)

        return breakdown
    except Exception:
        return {"asphalt": 50, "gravel": 50, "trail": 0}


# ---------- Endpoints ----------

@app.get("/health", tags=["meta"])
def health():
    # Also check BRouter (use a point within our segment coverage)
    brouter_ok = False
    try:
        r = httpx.get(
            f"{BROUTER_URL}/brouter",
            params={"lonlats": "11.5756,48.1374|11.5820,48.1410", "profile": "fastbike", "format": "gpx"},
            timeout=2.0
        )
        brouter_ok = r.status_code == 200 and "datafile" not in r.text
    except Exception:
        pass

    return {
        "status": "ok",
        "service": "comoot-backend",
        "version": "0.1.0",
        "brouter_connected": brouter_ok,
    }


@app.post("/api/routing/plan", response_model=PlanResponse, tags=["routing"])
async def plan_route(req: PlanRequest):
    """Route zwischen Waypoints berechnen via BRouter."""
    if len(req.waypoints) < 2:
        raise HTTPException(status_code=400, detail="Mindestens 2 Waypoints nötig")

    brouter_profile = PROFILE_MAP.get(req.profile, "trekking")

    # Build lonlats string
    lonlats = "|".join(f"{wp.lng},{wp.lat}" for wp in req.waypoints)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{BROUTER_URL}/brouter",
                params={"lonlats": lonlats, "profile": brouter_profile, "format": "gpx"}
            )
            r.raise_for_status()
            gpx_xml = r.text
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="BRouter timeout")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"BRouter error: {e}")

    # Parse GPX for distance & elevation
    distance_m, elev_gain = parse_gpx_distance_and_elevation(gpx_xml)
    distance_km = round(distance_m / 1000, 1)

    # Parse geometry from GPX
    try:
        root = ET.fromstring(gpx_xml)
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        coords = []
        for pt in root.findall(".//gpx:trkpt", ns):
            coords.append([float(pt.get("lon")), float(pt.get("lat"))])
        geometry = {"type": "LineString", "coordinates": coords}
    except Exception:
        geometry = {"type": "LineString", "coordinates": []}

    # Get real surface breakdown from PostGIS
    surface_breakdown = await get_surface_breakdown_from_route(gpx_xml)
    segments = build_segments_from_profile(req.profile, distance_km, elev_gain)
    climbs = extract_climbs_from_gpx(gpx_xml)

    return PlanResponse(
        geometry=geometry,
        distance_km=distance_km,
        elevation_gain=elev_gain,
        surface_breakdown=surface_breakdown,
        segments=segments,
        climbs=climbs,
    )