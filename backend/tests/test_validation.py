import pytest
from pydantic import ValidationError

from app.models.metrics import MetricsSnapshotInput


@pytest.mark.parametrize("drivers, rides, accepted, cancelled, waiting", [
    (0, 0, 0, 0, 0), (20, 40, 25, 15, 20), (20, 40, 25, 5, 8),
    (2_147_483_647, 2_147_483_647, 0, 0, 0),
])
def test_valid_boundaries(drivers, rides, accepted, cancelled, waiting):
    MetricsSnapshotInput(zone_id="ZONE_1", online_drivers=drivers,
        ride_requests=rides, accepted_requests=accepted,
        cancelled_requests=cancelled, waiting_drivers=waiting)


@pytest.mark.parametrize("field", ["online_drivers", "ride_requests",
    "accepted_requests", "cancelled_requests", "waiting_drivers"])
@pytest.mark.parametrize("value", [-1, None, True, "0", 0.5, 2_147_483_648])
def test_each_metric_requires_supported_integer(field, value):
    payload = dict(zone_id="ZONE_1", online_drivers=0, ride_requests=0,
                   accepted_requests=0, cancelled_requests=0, waiting_drivers=0)
    payload[field] = value
    with pytest.raises(ValidationError):
        MetricsSnapshotInput(**payload)
