from .entities import SENSORS
from .entities import async_setup_sensor_entry as async_setup_entry

PARALLEL_UPDATES = 0

__all__ = ["SENSORS", "async_setup_entry"]
