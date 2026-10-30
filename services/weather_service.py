"""Optional live weather using Open-Meteo (https://open-meteo.com).

* No API key is required.
* Geocoding API: https://geocoding-api.open-meteo.com/v1/search
* Forecast API:  https://api.open-meteo.com/v1/forecast
* Forecasts only cover about the next 16 days. For later trips we show the
  current forecast and label it clearly as "not for your travel dates".

If anything fails, WeatherError is raised and the app simply continues
without weather. Weather is never required.
"""

from datetime import date, timedelta
from typing import Any, Dict, Optional

import requests

import config

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_FORECAST_DAYS_AHEAD = 15  # today + 15 = 16 days of forecast

# WMO weather interpretation codes used by Open-Meteo.
WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Heavy freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Violent showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm with hail",
}


class WeatherError(Exception):
    """Raised when weather data cannot be fetched. Message is user-friendly."""


def _get_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        response = requests.get(url, params=params, timeout=config.WEATHER_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        raise WeatherError("The weather service took too long to respond.")
    except requests.ConnectionError:
        raise WeatherError("Could not reach the weather service (check your internet).")
    except requests.HTTPError as exc:
        raise WeatherError(f"Weather service returned an error ({exc.response.status_code}).")
    except ValueError:
        raise WeatherError("Weather service returned an unreadable response.")
    except requests.RequestException:
        raise WeatherError("Weather request failed.")


def get_weather(destination: str, start_date: Optional[date], days: int) -> Dict[str, Any]:
    """Return a forecast dictionary for the destination.

    Result keys: place, is_for_trip_dates (bool), note, days (list of dicts).
    """
    # 1) Find coordinates of the destination.
    geo = _get_json(GEOCODE_URL, {"name": destination.split(",")[0].strip(), "count": 1})
    results = geo.get("results") or []
    if not results:
        raise WeatherError(f"Weather location '{destination}' was not found.")
    place = results[0]
    place_name = ", ".join(
        part for part in (place.get("name"), place.get("admin1"), place.get("country")) if part
    )

    # 2) Ask for the daily forecast.
    params: Dict[str, Any] = {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
    }
    today = date.today()
    for_trip_dates = False
    if start_date and 0 <= (start_date - today).days <= MAX_FORECAST_DAYS_AHEAD:
        end_date = min(start_date + timedelta(days=days - 1), today + timedelta(days=MAX_FORECAST_DAYS_AHEAD))
        params["start_date"] = start_date.isoformat()
        params["end_date"] = end_date.isoformat()
        for_trip_dates = True
        note = "Forecast for your travel dates (forecasts are less reliable further ahead)."
    else:
        params["forecast_days"] = 7
        note = (
            "Your trip is beyond the forecast range (or no exact date was given), "
            "so this is the CURRENT 7-day forecast, shown only as a rough idea."
        )

    data = _get_json(FORECAST_URL, params)
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    if not dates:
        raise WeatherError("No forecast data was returned for this location.")

    rows = []
    for index, day_str in enumerate(dates):
        def pick(key: str):
            values = daily.get(key) or []
            return values[index] if index < len(values) else None

        code = pick("weather_code")
        rows.append(
            {
                "date": day_str,
                "summary": WEATHER_CODES.get(code, "Unknown"),
                "temp_max": pick("temperature_2m_max"),
                "temp_min": pick("temperature_2m_min"),
                "rain_chance": pick("precipitation_probability_max"),
            }
        )

    return {"place": place_name, "is_for_trip_dates": for_trip_dates, "note": note, "days": rows}


def weather_to_prompt_text(weather: Dict[str, Any]) -> str:
    """Compact text version of the forecast for the AI prompt."""
    lines = [f"Weather forecast for {weather['place']} ({weather['note']})"]
    for row in weather["days"]:
        lines.append(
            f"- {row['date']}: {row['summary']}, {row['temp_min']}–{row['temp_max']} °C, "
            f"rain chance {row['rain_chance']}%"
        )
    return "\n".join(lines)
