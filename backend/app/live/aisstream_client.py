"""Live vessel data via the aisstream.io AIS websocket feed.

DP World / Jebel Ali do not expose a public API for berth occupancy or
internal queue data — those stay estimated/manual. What IS available is
live AIS vessel positions, geofenced around a port area, as a proxy for
"vessels currently anchored/waiting nearby."

Caveat (confirmed by testing): aisstream.io is a free, volunteer-receiver
network — coverage depends on people running their own AIS antennas, not
satellite AIS. The Persian Gulf / Jebel Ali currently has little to no
volunteer receiver coverage on this free tier, so the Jebel Ali feed will
usually show 0 vessels. Rotterdam (dense European receiver coverage) is
included as a live "proof of capability" panel — the same pipeline, same
code path, just pointed at a port that actually has free data flowing.

Anchored vessels only broadcast an AIS position update roughly every
2-3 minutes (vs. every few seconds while underway), so a short blocking
request per API call would almost always see nothing. Instead this module
runs a persistent background listener (started at app startup) that keeps
an in-memory cache of the most recently seen vessels per port, and API
requests just read that cache.
"""

import asyncio
import json
import logging
import os
import time

import websockets

from app.geo import haversine_m

logger = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

# A vessel under this speed (knots) is treated as anchored/waiting rather than transiting.
# Only used as a fallback when a vessel's AIS navigational-status code isn't reported.
WAITING_SPEED_KNOTS = 1.0

# AIS "Navigational Status" enum (ITU-R M.1371) values relevant here — a vessel reports
# this itself, so where present it's a direct signal rather than a speed-based guess.
NAV_STATUS_UNDER_WAY_ENGINE = 0
NAV_STATUS_AT_ANCHOR = 1
NAV_STATUS_MOORED = 5
NAV_STATUS_NOT_DEFINED = 15

# Above this speed, an "at anchor" status is stale: the ship is under way (see upsert).
STALE_ANCHOR_STATUS_KNOTS = 3.0

# Anchored vessels report infrequently; a vessel not heard from in this long is dropped from the cache.
STALE_AFTER_SECONDS = 8 * 60

RECONNECT_DELAY_SECONDS = 5

# Where the vessel cache is persisted between restarts, so `waiting_since` timestamps
# (and thus avg_waiting_time_hours) survive a redeploy instead of resetting to "just
# arrived" for every currently-anchored vessel.
CACHE_FILE = os.path.join(os.path.dirname(__file__), ".vessel_cache.json")
CACHE_SAVE_INTERVAL_SECONDS = 30

EN_LIVE_NOTE = "We are tracking real ship movements near this port right now."
AR_LIVE_NOTE = "نتابع حركة السفن الحقيقية قرب هذا الميناء الآن."

PORTS = {
    "rotterdam": {
        "name": {"en": "Rotterdam", "ar": "روتردام"},
        "country": {"en": "Netherlands", "ar": "هولندا"},
        "bbox": [[51.85, 3.95], [52.00, 4.15]],
        "live_coverage": True,
        "note": {"en": EN_LIVE_NOTE, "ar": AR_LIVE_NOTE},
        # Deep-sea container berths across Maasvlakte I/II (APMT, ECT, RWG) — publicly
        # published terminal counts, not measured live. Update if a terminal is added/closed.
        "berth_count": 20,
    },
    "singapore": {
        "name": {"en": "Singapore", "ar": "سنغافورة"},
        "country": {"en": "Singapore", "ar": "سنغافورة"},
        "bbox": [[1.20, 103.60], [1.30, 103.90]],
        "live_coverage": True,
        "note": {"en": EN_LIVE_NOTE, "ar": AR_LIVE_NOTE},
        # PSA Singapore's Pasir Panjang + Tanjong Pagar/Keppel container berths, published count.
        "berth_count": 57,
    },
    "hong_kong": {
        "name": {"en": "Hong Kong", "ar": "هونغ كونغ"},
        "country": {"en": "Hong Kong, China", "ar": "هونغ كونغ، الصين"},
        # Kwai Tsing container terminals (~22.34N 114.11E) and the western harbour
        # anchorages where ocean-going ships wait.
        "bbox": [[22.25, 113.95], [22.40, 114.15]],
        "live_coverage": True,
        "note": {"en": EN_LIVE_NOTE, "ar": AR_LIVE_NOTE},
        # Official: Hong Kong Marine Department, "Port of Hong Kong in Figures" —
        # Kwai Tsing: 9 terminals, 24 berths, ~7,794 m of deep-water frontage.
        "berth_count": 24,
    },
    "los_angeles": {
        "name": {"en": "Los Angeles / Long Beach", "ar": "لوس أنجلوس / لونغ بيتش"},
        "country": {"en": "United States", "ar": "الولايات المتحدة"},
        "bbox": [[33.70, -118.30], [33.79, -118.19]],
        "live_coverage": True,
        "note": {"en": EN_LIVE_NOTE, "ar": AR_LIVE_NOTE},
        # Combined container berths across both ports' terminals, published counts.
        "berth_count": 32,
    },
    "new_york_nj": {
        "name": {"en": "New York / New Jersey", "ar": "نيويورك / نيوجيرسي"},
        "country": {"en": "United States", "ar": "الولايات المتحدة"},
        # Port Newark/Elizabeth (~40.68N 74.15W), Bayonne, Howland Hook and Red Hook
        # terminals, the harbour anchorages (Stapleton, Bay Ridge, Gravesend) and the
        # Ambrose anchorage offshore, where container ships queue at busy times.
        "bbox": [[40.38, -74.20], [40.72, -73.70]],
        "live_coverage": True,
        "note": {"en": EN_LIVE_NOTE, "ar": AR_LIVE_NOTE},
        # Derived: ~27,820 ft (8.5 km) of container berth length across Maher 10,128,
        # APM 6,000, PNCT 4,800, GCT New York 3,012, GCT Bayonne 1,800 and Red Hook
        # 2,080 ft (NAIOP port report) ÷ 350 m. PANYNJ publishes no berth count.
        "berth_count": 24,
    },
    "antwerp": {
        "name": {"en": "Antwerp", "ar": "أنتويرب"},
        "country": {"en": "Belgium", "ar": "بلجيكا"},
        "bbox": [[51.20, 4.20], [51.35, 4.45]],
        "live_coverage": True,
        "note": {"en": EN_LIVE_NOTE, "ar": AR_LIVE_NOTE},
        # Container berths at Antwerp Gateway, MPET and DP World Antwerp, published counts.
        "berth_count": 24,
    },
    # ------------------------------------------------------------------------------
    # Ports added Nov 2026. Each was checked two ways before being added:
    #   1. Live coverage: a 4-minute aisstream.io capture with these exact boxes
    #      (ships seen / at anchor): Felixstowe 15/1, Valencia 28/0, NY/NJ 51/3,
    #      Le Havre 45/3, Hong Kong 78/7. Busan and Port Klang were also tested and
    #      returned 0 ships (no free receiver coverage), so they were not added;
    #      Hamburg was left out because its waiting ships anchor ~100 km away in the
    #      German Bight, and Piraeus because published berth figures conflict.
    #   2. Boxes cover both the container terminals and the anchorages where ships
    #      actually wait, per the sources cited on each entry.
    # Berth counts only feed the rough occupancy estimate, which doesn't drive tiers.
    # Where no official count is published, it's derived as container quay length
    # ÷ 350 m (a typical large-container-ship berth) and marked "derived".
    # ------------------------------------------------------------------------------
    "felixstowe": {
        "name": {"en": "Felixstowe", "ar": "فيليكستو"},
        "country": {"en": "United Kingdom", "ar": "المملكة المتحدة"},
        # Port of Felixstowe (51.95N 1.31E), Harwich anchorage (~51.94N 1.49E, Harwich
        # Haven Authority area) and the Sunk area to the east, where deep-sea ships wait
        # for pilots (Sunk pilot boarding ~3.4 nm E of Sunk Inner, 51°51.5'N 1°40.5'E).
        "bbox": [[51.80, 1.20], [51.98, 1.95]],
        "live_coverage": True,
        "note": {"en": EN_LIVE_NOTE, "ar": AR_LIVE_NOTE},
        # 10 container berths, 9 active (Port of Felixstowe; ~3,773 m of container quay
        # per the port's 2023 brochure).
        "berth_count": 9,
    },
    "le_havre": {
        "name": {"en": "Le Havre", "ar": "لوهافر"},
        "country": {"en": "France", "ar": "فرنسا"},
        # Port 2000 / HAROPA container terminals (~49.47N 0.15E) and the outer anchorage
        # off the port entrance.
        "bbox": [[49.40, -0.20], [49.60, 0.25]],
        "live_coverage": True,
        "note": {"en": EN_LIVE_NOTE, "ar": AR_LIVE_NOTE},
        # HAROPA 2026 container-terminal catalogue: Terminal de France 4 berths +
        # Terminaux de Normandie 6 berths (Terminal de l'Atlantique's count isn't published).
        "berth_count": 10,
    },
    "valencia": {
        "name": {"en": "Valencia", "ar": "فالنسيا"},
        "country": {"en": "Spain", "ar": "إسبانيا"},
        # Container terminals plus both official anchorages (Valenciaport port guide):
        #   North: 39°26.170'–39°27.251'N, 0°12.714'–0°14.804'W
        #   South: 39°23.000'–39°24.297'N, 0°12.714'–0°17.029'W
        "bbox": [[39.375, -0.345], [39.465, -0.205]],
        "live_coverage": True,
        "note": {"en": EN_LIVE_NOTE, "ar": AR_LIVE_NOTE},
        # Derived: 4,767 m of container quay per the same Valenciaport guide —
        # CSP 2,310 m (Costa 538 + Príncipe Felipe 1,440 + Este 332), MSC 776 m
        # (Transversal Costa), APM 1,681 m (Llovera 488 + Levante 1–3 1,193) — ÷ 350 m.
        "berth_count": 14,
    },
    "jebel_ali": {
        "name": {"en": "Jebel Ali", "ar": "جبل علي"},
        "country": {"en": "United Arab Emirates", "ar": "الإمارات العربية المتحدة"},
        "bbox": [[24.90, 54.95], [25.05, 55.10]],
        "live_coverage": False,
        "note": {
            "en": "We don't have live ship-tracking data for this port yet, so this will show 0.",
            "ar": "لا تتوفر لدينا بيانات تتبع مباشرة لهذا الميناء بعد، لذا ستظهر القيمة 0.",
        },
        # DP World Jebel Ali's published container berth count.
        "berth_count": 24,
    },
}


def _localized(field: dict, lang: str) -> str:
    return field.get(lang, field["en"])


class AISStreamError(Exception):
    pass


def _port_for_coords(lat: float, lon: float) -> str | None:
    for port_id, info in PORTS.items():
        (lat_min, lon_min), (lat_max, lon_max) = info["bbox"]
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return port_id
    return None


class VesselCache:
    def __init__(self):
        self._vessels: dict[str, dict[str, dict]] = {port_id: {} for port_id in PORTS}
        self.connected = False
        self.last_error: str | None = None
        self.started_at = time.time()

    def upsert(
        self, port_id: str, mmsi: str, sog_knots: float, lat: float, lon: float,
        nav_status: int | None = None,
    ):
        now = time.time()
        existing = self._vessels[port_id].get(mmsi)

        # Prefer the vessel's own reported navigational status over a speed guess: a
        # vessel moored at berth and one anchored offshore waiting can both show ~0
        # knots, but only nav_status tells them apart. Fall back to the speed
        # threshold when status is missing/unreported (15, or absent from the message).
        has_status = nav_status is not None and nav_status != NAV_STATUS_NOT_DEFINED
        if has_status:
            at_berth = nav_status == NAV_STATUS_MOORED
            # Stale 'at anchor' on a ship under way isn't a ship waiting (see below).
            is_waiting = nav_status == NAV_STATUS_AT_ANCHOR and sog_knots <= STALE_ANCHOR_STATUS_KNOTS
        else:
            at_berth = False
            is_waiting = sog_knots < WAITING_SPEED_KNOTS

        # Track when each vessel first started waiting, so we can measure its actual
        # elapsed anchor time instead of guessing at one.
        if is_waiting and existing and existing.get("waiting_since") is not None:
            waiting_since = existing["waiting_since"]
        elif is_waiting:
            waiting_since = now
        else:
            waiting_since = None

        # Remember where an anchored vessel first reported "at anchor", so the monitor
        # can spot one that keeps moving away from that point (possible anchor drag).
        # Only the explicit AIS status counts here — a slow-moving ship with no status
        # isn't necessarily anchored.
        # A ship doing more than a few knots isn't anchored, whatever its status says:
        # it has weighed anchor without updating AIS. Drop its anchor point, so when it
        # anchors again somewhere else the new spot becomes the reference instead of the
        # old one (which would look like kilometres of drift).
        at_anchor = has_status and nav_status == NAV_STATUS_AT_ANCHOR and sog_knots <= STALE_ANCHOR_STATUS_KNOTS
        if at_anchor and existing and existing.get("anchor_lat") is not None:
            anchor_lat, anchor_lon = existing["anchor_lat"], existing["anchor_lon"]
        elif at_anchor:
            anchor_lat, anchor_lon = lat, lon
        else:
            anchor_lat = anchor_lon = None

        self._vessels[port_id][mmsi] = {
            "sog_knots": sog_knots,
            "lat": lat,
            "lon": lon,
            "last_seen": now,
            "waiting_since": waiting_since,
            "at_berth": at_berth,
            "is_waiting": is_waiting,
            "anchor_lat": anchor_lat,
            "anchor_lon": anchor_lon,
        }

    def anchored_vessels(self, port_id: str) -> list[dict]:
        """Fresh vessels reporting 'at anchor', with how far each has moved from its anchor point."""
        now = time.time()
        result = []
        for mmsi, v in self._vessels.get(port_id, {}).items():
            if v.get("anchor_lat") is None or now - v["last_seen"] > STALE_AFTER_SECONDS:
                continue
            result.append({
                "mmsi": mmsi,
                "lat": v["lat"],
                "lon": v["lon"],
                "anchor_lat": v["anchor_lat"],
                "anchor_lon": v["anchor_lon"],
                "drift_m": round(haversine_m(v["anchor_lat"], v["anchor_lon"], v["lat"], v["lon"])),
                "speed_knots": v["sog_knots"],
            })
        return result

    def snapshot(self, port_id: str, include_positions: bool = False, lang: str = "en") -> dict:
        now = time.time()
        fresh = {
            mmsi: v for mmsi, v in self._vessels.get(port_id, {}).items()
            if now - v["last_seen"] <= STALE_AFTER_SECONDS
        }
        self._vessels[port_id] = fresh

        # .get() fallbacks cover vessel entries persisted before at_berth/is_waiting
        # were tracked (see VesselCache.save/load).
        waiting = [v for v in fresh.values() if v.get("is_waiting", v["sog_knots"] < WAITING_SPEED_KNOTS)]
        at_berth = [v for v in fresh.values() if v.get("at_berth", False)]

        # Average of each currently-waiting vessel's own observed anchor time. Vessels
        # that were already anchored before this process started listening will read
        # as waiting-since-first-seen, understating their true wait — a live-observed
        # floor, not an exact figure.
        wait_hours = [(now - v["waiting_since"]) / 3600 for v in waiting if v.get("waiting_since") is not None]
        avg_waiting_time_hours = sum(wait_hours) / len(wait_hours) if wait_hours else 0.0

        port_info = PORTS[port_id]
        (lat_min, lon_min), (lat_max, lon_max) = port_info["bbox"]

        result = {
            "port_id": port_id,
            "port_name": _localized(port_info["name"], lang),
            "country": _localized(port_info["country"], lang),
            "live_coverage": port_info["live_coverage"],
            "vessel_queue_length": len(waiting),
            "vessels_at_berth": len(at_berth),
            "vessels_observed": len(fresh),
            "avg_waiting_time_hours": round(avg_waiting_time_hours, 1),
            "source": "aisstream.io",
            "bounding_box": port_info["bbox"],
            "center": [(lat_min + lat_max) / 2, (lon_min + lon_max) / 2],
            "coverage_note": _localized(port_info["note"], lang),
            "connected": self.connected,
            "warming_up": self.connected and (now - self.started_at) < STALE_AFTER_SECONDS,
            "last_error": self.last_error,
        }

        if include_positions:
            result["ships"] = [
                {
                    "id": mmsi,
                    "lat": v["lat"],
                    "lon": v["lon"],
                    "speed_knots": round(v["sog_knots"], 1),
                    "waiting": v.get("is_waiting", v["sog_knots"] < WAITING_SPEED_KNOTS),
                    "at_berth": v.get("at_berth", False),
                }
                for mmsi, v in fresh.items()
            ]

        return result

    def all_snapshots(self, lang: str = "en") -> list[dict]:
        return [self.snapshot(port_id, lang=lang) for port_id in PORTS]

    def save(self, path: str = CACHE_FILE):
        try:
            with open(path, "w") as f:
                json.dump(self._vessels, f)
        except OSError as exc:
            logger.warning("Could not persist vessel cache to %s: %s", path, exc)

    def load(self, path: str = CACHE_FILE):
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load persisted vessel cache from %s: %s", path, exc)
            return

        now = time.time()
        for port_id, vessels in loaded.items():
            if port_id not in self._vessels:
                continue
            fresh = {
                mmsi: v for mmsi, v in vessels.items()
                if now - v.get("last_seen", 0) <= STALE_AFTER_SECONDS
            }
            self._vessels[port_id] = fresh
        logger.info("Loaded persisted vessel cache from %s", path)


cache = VesselCache()


async def _listen_forever():
    api_key = os.environ.get("AISSTREAM_API_KEY")
    if not api_key:
        cache.last_error = "AISSTREAM_API_KEY is not set"
        return

    bounding_boxes = [info["bbox"] for info in PORTS.values()]

    while True:
        try:
            async with websockets.connect(AISSTREAM_URL) as ws:
                subscribe = {
                    "APIKey": api_key,
                    "BoundingBoxes": bounding_boxes,
                    "FilterMessageTypes": ["PositionReport"],
                }
                await ws.send(json.dumps(subscribe))
                cache.connected = True
                cache.last_error = None
                logger.info("AIS stream connected, watching %d port bounding boxes", len(bounding_boxes))

                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("MessageType") != "PositionReport":
                        continue
                    report = msg["Message"]["PositionReport"]
                    lat, lon = report.get("Latitude"), report.get("Longitude")
                    port_id = _port_for_coords(lat, lon)
                    if port_id is None:
                        continue
                    mmsi = str(report.get("UserID"))
                    cache.upsert(
                        port_id, mmsi, sog_knots=report.get("Sog", 0.0), lat=lat, lon=lon,
                        nav_status=report.get("NavigationalStatus"),
                    )
        except (websockets.exceptions.WebSocketException, OSError) as exc:
            cache.connected = False
            cache.last_error = str(exc)
            logger.warning("AIS stream disconnected: %s — retrying in %ss", exc, RECONNECT_DELAY_SECONDS)
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


async def _save_periodically():
    while True:
        await asyncio.sleep(CACHE_SAVE_INTERVAL_SECONDS)
        cache.save()


_collector_task: asyncio.Task | None = None
_save_task: asyncio.Task | None = None


def start_collector():
    global _collector_task, _save_task
    cache.load()
    if _collector_task is None:
        _collector_task = asyncio.create_task(_listen_forever())
    if _save_task is None:
        _save_task = asyncio.create_task(_save_periodically())


def stop_collector():
    global _collector_task, _save_task
    cache.save()
    if _collector_task is not None:
        _collector_task.cancel()
        _collector_task = None
    if _save_task is not None:
        _save_task.cancel()
        _save_task = None


def get_live_vessel_queue(port_id: str, include_positions: bool = False, lang: str = "en") -> dict:
    if port_id not in PORTS:
        raise AISStreamError(f"Unknown port_id '{port_id}'. Known ports: {list(PORTS)}")
    return cache.snapshot(port_id, include_positions=include_positions, lang=lang)


def build_port_snapshot(port_id: str, lang: str = "en") -> dict:
    """Map a live AIS vessel-queue reading into a PortSnapshot for the agent pipeline.

    `vessel_queue_length` and `avg_waiting_time_hours` come from the live AIS cache:
    queue length is a direct count of anchored vessels, and waiting time is the
    observed average of each of those vessels' own elapsed anchor time (see
    `VesselCache.upsert`/`snapshot`) rather than a guessed constant.

    `berth_occupancy_rate` is now also a real count — `vessels_at_berth` (vessels
    whose AIS navigational status reports "moored") against that port's published
    container-berth count (`berth_count` in `PORTS`) — rather than proxying it off
    the queue length. It's still flagged as estimated because `berth_count` is a
    hand-sourced published figure, not a live capacity feed, and a moored vessel
    isn't necessarily occupying one of the container berths counted (it could be
    at a bulk/tanker berth in the same bounding box).
    """
    if port_id not in PORTS:
        raise AISStreamError(f"Unknown port_id '{port_id}'. Known ports: {list(PORTS)}")

    live = cache.snapshot(port_id, lang=lang)
    queue_length = live["vessel_queue_length"]
    berth_count = PORTS[port_id]["berth_count"]

    berth_occupancy_rate = min(1.0, live["vessels_at_berth"] / berth_count)

    return {
        "port_name": live["port_name"],
        "berth_occupancy_rate": round(berth_occupancy_rate, 2),
        "vessel_queue_length": queue_length,
        "avg_waiting_time_hours": live["avg_waiting_time_hours"],
        "language": lang,
        "estimated_fields": ["berth_occupancy_rate"],
        "live_coverage": live["live_coverage"],
        "warming_up": live["warming_up"],
    }


def get_all_live_vessel_queues(lang: str = "en") -> list[dict]:
    return cache.all_snapshots(lang=lang)


def list_ports(lang: str = "en") -> list[dict]:
    return [
        {
            "port_id": port_id,
            "name": _localized(info["name"], lang),
            "country": _localized(info["country"], lang),
            "live_coverage": info["live_coverage"],
        }
        for port_id, info in PORTS.items()
    ]
