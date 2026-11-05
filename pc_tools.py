"""Jarvis's hands: things it can do on this Windows PC. The AI picks which to call.

Each tool is a plain function; its docstring tells the AI what it does and what the
arguments mean, so keep them clear.
"""

import ctypes
import difflib
import json
import subprocess
import threading
import webbrowser
from urllib.parse import urlencode
from urllib.request import urlopen

import psutil
from ddgs import DDGS

# main.py points this at Voice.say so timers can speak.
announce = print

VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP = 0xAD, 0xAE, 0xAF
VK_MEDIA = {"next": 0xB0, "previous": 0xB1, "play_pause": 0xB3, "mute": VK_VOLUME_MUTE}
KEYEVENTF_KEYUP = 0x0002

# Open-Meteo weather codes -> words.
WEATHER_CODES = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail",
}

_start_apps: dict[str, tuple[str, str]] | None = None
MEDIA_REPLIES = {"next": "Skipping ahead.", "previous": "Going back a track.", "play_pause": "Done.", "mute": "Sound toggled."}


def _press(vk: int, times: int = 1):
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def _get_json(url: str, **params) -> dict:
    with urlopen(f"{url}?{urlencode(params)}", timeout=15) as response:
        return json.load(response)


def _installed_apps() -> dict[str, tuple[str, str]]:
    """Every app in the Start menu (including Store apps), as {lowercase name: (name, AppID)}."""
    global _start_apps
    if _start_apps is None:
        # Force UTF-8 so non-English app names (e.g. Korean) come through intact.
        command = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        ).stdout
        apps = json.loads(out) if out.strip() else []
        if isinstance(apps, dict):
            apps = [apps]
        _start_apps = {a["Name"].lower(): (a["Name"], a["AppID"]) for a in apps}
    return _start_apps


def _find_app(name: str) -> str | None:
    apps = _installed_apps()
    name = name.lower().strip()
    if name in apps:
        return name
    for pick in (lambda a: a.startswith(name), lambda a: name in a):
        matches = sorted((a for a in apps if pick(a)), key=len)
        if matches:
            return matches[0]
    close = difflib.get_close_matches(name, apps, n=1, cutoff=0.6)
    return close[0] if close else None


def open_app(name: str) -> str:
    """Open an application installed on this Windows PC.

    Args:
        name: The app's name, e.g. "Spotify", "Chrome", "Notepad", "Calculator", "Settings".
    """
    match = _find_app(name)
    if match is None:
        return f"I couldn't find an app called {name}."
    app_name, app_id = _installed_apps()[match]
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
    return f"Opening {app_name}."


def open_website(url: str) -> str:
    """Open a web page in the browser so the user can see it. To play or find a video, use
    https://www.youtube.com/results?search_query=... with the search words.

    Args:
        url: The full web address.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return "It's open in your browser."


def web_search(query: str) -> str:
    """Search the internet for up-to-date information: news, facts, people, prices,
    sports results, or anything you are not sure about.

    Args:
        query: What to search for.
    """
    results = DDGS().text(query, max_results=5)
    if not results:
        return "No results found."
    return "\n".join(f"- {r['title']}: {r['body']}" for r in results)


def get_weather(city: str) -> str:
    """Get the current weather and today's forecast for a city.

    Args:
        city: City name, e.g. "Seoul" or "London".
    """
    places = _get_json("https://geocoding-api.open-meteo.com/v1/search", name=city, count=1).get("results")
    if not places:
        return f"I couldn't find a place called {city}."
    place = places[0]
    data = _get_json(
        "https://api.open-meteo.com/v1/forecast",
        latitude=place["latitude"], longitude=place["longitude"], timezone="auto", forecast_days=1,
        current="temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        daily="temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    )
    now, today = data["current"], data["daily"]
    sky = WEATHER_CODES.get(now["weather_code"], "unknown conditions")
    return (
        f"{place['name']}, {place.get('country', '')}: {sky}, {now['temperature_2m']:.0f}°C "
        f"(feels like {now['apparent_temperature']:.0f}°C), humidity {now['relative_humidity_2m']}%, "
        f"wind {now['wind_speed_10m']:.0f} km/h. Today: low {today['temperature_2m_min'][0]:.0f}°C, "
        f"high {today['temperature_2m_max'][0]:.0f}°C, {today['precipitation_probability_max'][0]}% chance of rain."
    )


def set_volume(level: int) -> str:
    """Set the PC's speaker volume.

    Args:
        level: Volume from 0 (silent) to 100 (loudest).
    """
    level = max(0, min(100, int(level)))
    # Each key press moves the volume by 2, so go to 0 first, then up to the target.
    _press(VK_VOLUME_DOWN, 50)
    _press(VK_VOLUME_UP, round(level / 2))
    return f"Volume set to {level}."


def media_control(action: str) -> str:
    """Control whatever music or video is playing (Spotify, YouTube, and so on), or mute the PC.

    Args:
        action: One of: play_pause, next, previous, mute.
    """
    action = action.strip().lower().replace(" ", "_").replace("/", "_")
    if action not in VK_MEDIA:
        return f"I can't do '{action}' with the music; I can play or pause, skip, go back, or mute."
    _press(VK_MEDIA[action])
    return MEDIA_REPLIES[action]


def system_status() -> str:
    """Report the PC's battery level, CPU load, memory use and free disk space."""
    parts = []
    battery = psutil.sensors_battery()
    if battery:
        plugged = "charging" if battery.power_plugged else "on battery"
        parts.append(f"battery {battery.percent:.0f}% ({plugged})")
    parts.append(f"CPU {psutil.cpu_percent(interval=0.5):.0f}%")
    parts.append(f"memory {psutil.virtual_memory().percent:.0f}% used")
    disk = psutil.disk_usage("C:\\")
    parts.append(f"{disk.free / 1e9:.0f} GB free on C:")
    return ", ".join(parts)


def set_timer(minutes: float, label: str | None = None) -> str:
    """Start a countdown timer. Jarvis says out loud when it finishes.

    Args:
        minutes: Length in minutes; use decimals for seconds (0.5 = 30 seconds).
        label: What the timer is for, e.g. "pasta". Optional.
    """
    minutes = float(minutes)
    message = f"Your {label} timer is done." if label else "Your timer is done."
    timer = threading.Timer(minutes * 60, announce, args=[message])
    timer.daemon = True
    timer.start()
    return f"Timer set for {minutes:g} minutes{f' for your {label}' if label else ''}."


def lock_computer() -> str:
    """Lock the Windows screen."""
    ctypes.windll.user32.LockWorkStation()
    return "Screen locked."


ALL_TOOLS = [
    web_search, get_weather, open_app, open_website, set_volume,
    media_control, system_status, set_timer, lock_computer,
]
