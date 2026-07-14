"""Sensor platform for Egypt Trains."""
import logging
import re
import json
from datetime import datetime
import aiohttp

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util
from datetime import timedelta

from .const import DOMAIN, CONF_DEPARTURE, CONF_ARRIVAL

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=30)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the sensor platform."""
    departure = entry.data.get(CONF_DEPARTURE)
    arrival = entry.data.get(CONF_ARRIVAL)

    async def async_update_data():
        """Fetch data from egytrains.com."""
        url = f"https://egytrains.com/trains/{departure}/{arrival}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    html = await response.text()
                    
                    match = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
                    if not match:
                        raise UpdateFailed("Could not find train data on the page.")
                    
                    data = json.loads(match.group(1))
                    trains_dict = data.get("props", {}).get("pageProps", {}).get("data", {})
                    
                    if not trains_dict:
                        raise UpdateFailed("No trains found for this route.")
                    
                    # Convert to list
                    trains = []
                    for t_id, t_info in trains_dict.items():
                        # skip meta keys like 'departure'
                        if isinstance(t_info, dict) and "startTime" in t_info:
                            t_info["train_number"] = t_id
                            trains.append(t_info)
                            
                    return trains
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="egypt_trains",
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()

    async_add_entities([
        EgyptTrainSensor(coordinator, departure, arrival, 0, "Next Train"),
        EgyptTrainSensor(coordinator, departure, arrival, 1, "Second Train"),
        EgyptTrainSensor(coordinator, departure, arrival, 2, "Third Train"),
    ])

class EgyptTrainSensor(SensorEntity):
    """Representation of a Train Sensor."""

    def __init__(self, coordinator, departure, arrival, index, name_suffix):
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._departure = departure
        self._arrival = arrival
        self._index = index
        self._name_suffix = name_suffix
        
        self._attr_name = f"{departure} to {arrival} {name_suffix}"
        self._attr_unique_id = f"egypt_trains_{departure}_{arrival}_{index}"
        self._attr_icon = "mdi:train"

    @property
    def state(self):
        """Return the state of the sensor (Departure Time)."""
        train = self._get_train()
        if train:
            return train.get("startTime", "Unknown")
        return "No Trains"

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        train = self._get_train()
        if train:
            return {
                "train_number": train.get("train_number"),
                "train_type": train.get("type"),
                "arrival_time": train.get("endTime"),
                "duration": train.get("duration"),
                "stops": train.get("stops")
            }
        return {}

    def _get_train(self):
        """Helper to get the specific train based on time and index."""
        if not self.coordinator.data:
            return None
            
        now = dt_util.now().time()
        
        # Parse time and sort
        def parse_time(time_str):
            try:
                return datetime.strptime(time_str, "%H:%M").time()
            except ValueError:
                return datetime.min.time()
                
        all_trains = sorted(self.coordinator.data, key=lambda x: parse_time(x.get("startTime", "00:00")))
        
        # Find upcoming trains (startTime >= now)
        upcoming = [t for t in all_trains if parse_time(t.get("startTime", "00:00")) >= now]
        
        # If we reach end of day, append tomorrow's early trains to the list
        past = [t for t in all_trains if parse_time(t.get("startTime", "00:00")) < now]
        circular_trains = upcoming + past
        
        if self._index < len(circular_trains):
            return circular_trains[self._index]
            
        return None

    @property
    def should_poll(self):
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    async def async_update(self):
        """Update the entity."""
        await self.coordinator.async_request_refresh()