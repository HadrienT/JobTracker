"""`GET /map/pins` — one pin per located city, under the same filters as `/postings`.

The store counts postings per `(country, city)`; this route only attaches the coordinates
from the geo referential. Clicking a pin then lists its postings with the ordinary
`/postings` route and `place_country` + `place_city`, so the list and the pin can never
disagree about what "this pin" means.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from jobtracker.api.deps import Conn, get_posting_filter
from jobtracker.api.schemas import MapPin, MapPins
from jobtracker.core.geo import GeoIndex, city_coordinates
from jobtracker.core.logging import get_logger
from jobtracker.store.map import location_counts
from jobtracker.store.postings import PostingFilter

router = APIRouter(tags=["map"])
_logger = get_logger(__name__)


@router.get("/map/pins")
def get_map_pins(
    flt: Annotated[PostingFilter, Depends(get_posting_filter)], conn: Conn, request: Request
) -> MapPins:
    geo: GeoIndex = request.app.state.geo
    counts = location_counts(conn, flt)
    pins: list[MapPin] = []
    for location in counts.locations:
        coordinates = city_coordinates(geo, location.city, location.country)
        if coordinates is None:
            # A city stored by an older referential. Say so: a pin that silently vanishes
            # looks exactly like "nobody hires there".
            _logger.warning(
                "map_pin_without_coordinates", city=location.city, country=location.country
            )
            continue
        pins.append(
            MapPin(
                city=location.city,
                country=location.country,
                lat=coordinates[0],
                lon=coordinates[1],
                count=location.count,
                posting_id=location.sample_posting_id if location.count == 1 else None,
            )
        )
    return MapPins(pins=tuple(pins), total=counts.total, unplaced=counts.total - counts.placed)
