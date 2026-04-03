# METAR Reader

A Flask web application that turns cryptic aviation weather reports (METARs) into plain-English descriptions anyone can understand.

Type in any ICAO airport code and get a friendly summary like:

> *Mostly cloudy. Temperature 13°C (55°F). Wind from the West at 11 knots (13 mph). Excellent visibility.*

## What is a METAR?

A METAR is a standardized weather observation used by pilots and air traffic control worldwide. They look like this:

```
KHIO 022353Z 26011KT 10SM BKN060 13/01 A3021
```

This app decodes every field — wind direction and speed, visibility, cloud layers, temperature, dewpoint, and altimeter setting — and presents them in a format that requires no aviation knowledge to read.

## Features

- Live data fetched directly from [aviationweather.gov](https://aviationweather.gov)
- Supports any ICAO airport code worldwide (e.g. `KLAX`, `EGLL`, `RJTT`)
- Converts units to mph and °F alongside native aviation units
- Handles complex visibility formats, gusting winds, multiple cloud layers, and present weather (rain, snow, fog, thunderstorms, etc.)
- Collapsible raw METAR display for the curious
- Clean, mobile-friendly interface

## Installation

**Requirements:** Python 3.10 or later

1. **Clone the repository**

   ```bash
   git clone https://github.com/your-username/metar-reader.git
   cd metar-reader
   ```

2. **Create and activate a virtual environment** (recommended)

   ```bash
   python3 -m venv venv
   source venv/bin/activate      # macOS / Linux
   venv\Scripts\activate         # Windows
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**

   ```bash
   python app.py
   ```

5. Open your browser and go to `http://127.0.0.1:5000`

## Usage

Enter a four-letter ICAO airport code in the search box and press **Get Weather**.

| Example code | Airport |
|---|---|
| `KLAX` | Los Angeles International |
| `KJFK` | John F. Kennedy International (New York) |
| `KORD` | O'Hare International (Chicago) |
| `EGLL` | London Heathrow |
| `RJTT` | Tokyo Haneda |

> **Tip:** ICAO codes are not the same as the shorter IATA codes used on flight tickets (e.g. LAX, JFK). In the US, most codes start with `K` followed by the three-letter IATA code.

## Data Source

Weather data is retrieved in real time from the [Aviation Weather Center API](https://aviationweather.gov/api/data/metar), operated by NOAA. No API key is required.

## Project Structure

```
metar-reader/
├── app.py              # Flask application and METAR parser
├── requirements.txt    # Python dependencies
└── templates/
    └── index.html      # Front-end template
```

## License

MIT
