"""Sensor platform for Egypt Trains."""
import logging
import re
import json
import asyncio
from datetime import datetime
import aiohttp

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util
from datetime import timedelta

from .const import DOMAIN, CONF_DEPARTURE, CONF_ARRIVAL

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=30)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the sensor platform."""
    departure = entry.data.get(CONF_DEPARTURE)
    arrival = entry.data.get(CONF_ARRIVAL)
    
    # We will log the URL so the user can see what we're fetching
    _LOGGER.info(f"Setting up Egypt Trains for {departure} to {arrival}")

    async def fetch_train_details(session, train_number):
        """Fetch intermediate stations for a specific train."""
        url = f"https://egytrains.com/train/{train_number}"
        try:
            async with session.get(url, headers=HEADERS, timeout=10) as response:
                html = await response.text()
                match = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
                if match:
                    data = json.loads(match.group(1))
                    cities = data.get("props", {}).get("pageProps", {}).get("data", {}).get("cities", [])
                    return cities
        except Exception as e:
            _LOGGER.error(f"Error fetching train {train_number} details: {e}")
        return []

    async def async_update_data():
        """Fetch data from egytrains.com."""
        url = f"https://egytrains.com/trains/{departure}/{arrival}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=HEADERS, timeout=15) as response:
                    if response.status != 200:
                        raise UpdateFailed(f"Failed to fetch data, status code: {response.status}")
                        
                    html = await response.text()
                    
                    match = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
                    if not match:
                        raise UpdateFailed("Could not find train data on the page (Regex failed).")
                    
                    data = json.loads(match.group(1))
                    trains_dict = data.get("props", {}).get("pageProps", {}).get("data", {})
                    
                    if not trains_dict:
                        raise UpdateFailed("No trains found for this route in JSON.")
                    
                    all_trains = []
                    for t_id, t_info in trains_dict.items():
                        if isinstance(t_info, dict) and "startTime" in t_info:
                            t_info["train_number"] = t_id
                            all_trains.append(t_info)
                            
                    if not all_trains:
                        raise UpdateFailed("Parsed JSON but found 0 valid trains.")
                    
                    # Sort trains by time
                    def parse_time(t_str):
                        try:
                            return datetime.strptime(t_str, "%H:%M").time()
                        except ValueError:
                            return datetime.min.time()
                            
                    all_trains = sorted(all_trains, key=lambda x: parse_time(x.get("startTime", "00:00")))
                    
                    # Get next 3 trains
                    now = dt_util.now().time()
                    upcoming = [t for t in all_trains if parse_time(t.get("startTime", "00:00")) >= now]
                    past = [t for t in all_trains if parse_time(t.get("startTime", "00:00")) < now]
                    circular_trains = upcoming + past
                    next_3_trains = circular_trains[:3]
                    
                    # Fetch stations for the next 3 trains concurrently
                    tasks = [fetch_train_details(session, t["train_number"]) for t in next_3_trains]
                    stations_results = await asyncio.gather(*tasks)
                    
                    for i, t in enumerate(next_3_trains):
                        t["stations"] = stations_results[i]
                        
                    return {
                        "summary": [t["train_number"] for t in next_3_trains],
                        "trains": next_3_trains
                    }

        except Exception as err:
            _LOGGER.error(f"Egypt Trains Update Error: {err}")
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="egypt_trains",
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()

    entities = [
        EgyptTrainSummarySensor(coordinator, departure, arrival)
    ]
    
    for i in range(3):
        entities.append(EgyptTrainDetailsSensor(coordinator, departure, arrival, i))

    async_add_entities(entities)


class EgyptTrainSummarySensor(SensorEntity):
    """Sensor showing the summary of the next 3 trains."""

    def __init__(self, coordinator, departure, arrival):
        """Initialize."""
        self.coordinator = coordinator
        self._departure = departure
        self._arrival = arrival
        
        self._attr_name = f"{departure} to {arrival} Next Trains"
        self._attr_unique_id = f"egypt_trains_{departure}_{arrival}_summary"
        self._attr_icon = "mdi:timetable"

    @property
    def state(self):
        if self.coordinator.data and "summary" in self.coordinator.data:
            return ", ".join(self.coordinator.data["summary"])
        return "No Trains"

    @property
    def extra_state_attributes(self):
        if self.coordinator.data and "trains" in self.coordinator.data:
            return {"upcoming_trains": self.coordinator.data["trains"]}
        return {}
        
    @property
    def should_poll(self):
        return False
        
    async def async_update(self):
        await self.coordinator.async_request_refresh()


class EgyptTrainDetailsSensor(SensorEntity):
    """Sensor showing detailed stations for a specific upcoming train."""

    def __init__(self, coordinator, departure, arrival, index):
        """Initialize."""
        self.coordinator = coordinator
        self._departure = departure
        self._arrival = arrival
        self._index = index
        
        labels = ["Next Train", "Second Train", "Third Train"]
        
        self._attr_name = f"{departure} to {arrival} {labels[index]}"
        self._attr_unique_id = f"egypt_trains_{departure}_{arrival}_{index}"
        self._attr_icon = "mdi:train"

    @property
    def state(self):
        train = self._get_train()
        if train:
            return train.get("startTime", "Unknown")
        return "No Train"

    @property
    def extra_state_attributes(self):
        train = self._get_train()
        if train:
            attrs = {
                "train_number": train.get("train_number"),
                "train_type": train.get("type"),
                "arrival_time": train.get("endTime"),
                "duration": train.get("duration"),
                "total_stops": train.get("stops")
            }
            
            # Format the stations nicely
            stations_list = []
            for city in train.get("stations", []):
                name = city.get("name", "Unknown")
                arr = city.get("a", "-")
                dep = city.get("d", "-")
                stations_list.append(f"{name} (Arr: {arr}, Dep: {dep})")
                
            attrs["route_stations"] = stations_list
            return attrs
        return {}

    def _get_train(self):
        if self.coordinator.data and "trains" in self.coordinator.data:
            trains = self.coordinator.data["trains"]
            if self._index < len(trains):
                return trains[self._index]
        return None

    @property
    def should_poll(self):
        return False
        
    async def async_update(self):
        await self.coordinator.async_request_refresh()