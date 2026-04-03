"""
METAR Reader — Flask web application.

Fetches live METAR weather reports from aviationweather.gov and decodes
the raw encoded string into plain-English descriptions that anyone can
understand.

Data source: https://aviationweather.gov/api/data/metar
"""

import re
import requests
from flask import Flask, render_template, request

app = Flask(__name__)


def degrees_to_compass(degrees: int) -> str:
    """Convert a wind direction in degrees to a full compass direction name.

    Args:
        degrees: Wind direction in degrees (0–360).

    Returns:
        A human-readable compass direction, e.g. "North-Northwest".
    """
    directions = [
        'North', 'North-Northeast', 'Northeast', 'East-Northeast',
        'East', 'East-Southeast', 'Southeast', 'South-Southeast',
        'South', 'South-Southwest', 'Southwest', 'West-Southwest',
        'West', 'West-Northwest', 'Northwest', 'North-Northwest'
    ]
    index = round(degrees / 22.5) % 16
    return directions[index]


def parse_visibility(tokens: list[str], idx: int) -> tuple[str | None, int]:
    """Parse the visibility field from a METAR token list.

    Visibility in METARs can be expressed in several formats:
      - Statute miles: "10SM", "6SM"
      - Fractional miles: "1/4SM", "3/4SM"
      - Mixed whole + fraction spanning two tokens: "1" then "1/2SM"
      - Metric meters: "4000", "9999" (9999 means 10+ km)
      - Metric km: "10KM"
      - CAVOK (Ceiling And Visibility OK — best conditions)
      - M prefix meaning "less than", e.g. "M1/4SM"

    Args:
        tokens: The full list of METAR tokens (remarks already stripped).
        idx: The index of the token to start parsing from.

    Returns:
        A tuple of (human-readable visibility string or None, updated index).
    """
    if idx >= len(tokens):
        return None, idx

    token = tokens[idx]

    if token == 'CAVOK':
        return "Ceiling and Visibility OK (>10 km, no significant weather)", idx + 1

    # The "M" prefix means "less than" (e.g. M1/4SM = less than 1/4 mile)
    less_than = token.startswith('M')
    if less_than:
        token = token[1:]
    prefix = "Less than " if less_than else ""

    # Integer statute or metric value: "10SM", "6SM", "10KM"
    m = re.match(r'^(\d+)(SM|KM)$', token)
    if m:
        val = int(m.group(1))
        unit = m.group(2)
        if unit == 'SM':
            if val >= 10:
                return f"{prefix}10+ miles (excellent)", idx + 1
            return f"{prefix}{val} mile{'s' if val != 1 else ''}", idx + 1
        else:
            if val >= 10:
                return f"{prefix}10+ km (excellent)", idx + 1
            return f"{prefix}{val} km", idx + 1

    # Pure fractional statute miles: "1/4SM", "3/4SM"
    m = re.match(r'^(\d+)/(\d+)(SM)$', token)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        return f"{prefix}{num}/{den} mile", idx + 1

    # Visibility in whole meters: "9999", "4000", "0600"
    m = re.match(r'^(\d{4})$', token)
    if m:
        val = int(m.group(1))
        if val == 9999:
            return "10+ km (excellent)", idx + 1
        return f"{prefix}{val} meters", idx + 1

    # Mixed whole number + fractional token, e.g. "1" followed by "1/2SM" = 1.5 miles
    m_whole = re.match(r'^(\d+)$', token)
    if m_whole and idx + 1 < len(tokens):
        next_token = tokens[idx + 1]
        m_frac = re.match(r'^(\d+)/(\d+)(SM)$', next_token)
        if m_frac:
            whole = int(m_whole.group(1))
            num, den = int(m_frac.group(1)), int(m_frac.group(2))
            return f"{prefix}{whole} {num}/{den} miles", idx + 2

    return None, idx


def decode_metar(raw: str) -> dict:
    """Decode a raw METAR string into a dictionary of human-readable fields.

    Parses the METAR left-to-right in the standard field order defined by
    ICAO Annex 3 / WMO No. 49:
      type → station → time → modifier → wind → wind variability →
      visibility → RVR → present weather → sky condition →
      temperature/dewpoint → altimeter

    The "RMK" (remarks) section is stripped before parsing because it
    contains coded supplementary data not intended for general audiences.

    Args:
        raw: The raw METAR string as returned by the API.

    Returns:
        A dict with string values for any fields that were successfully
        parsed. Keys: station, time, is_auto, wind, wind_variable,
        visibility, weather, sky, temperature, dewpoint, altimeter, raw.
    """
    # Strip the remarks section — everything after "RMK" is supplementary
    raw_clean = re.split(r'\bRMK\b', raw)[0]
    tokens = raw_clean.strip().split()

    if not tokens:
        return {}

    result = {'raw': raw.strip()}
    idx = 0

    # Optional type indicator: METAR (routine) or SPECI (special/unscheduled)
    if tokens[idx] in ('METAR', 'SPECI'):
        idx += 1

    if idx >= len(tokens):
        return result

    # ICAO station identifier, e.g. "KHIO", "EGLL"
    result['station'] = tokens[idx]
    idx += 1

    if idx >= len(tokens):
        return result

    # Observation date/time in DDHHmmZ format (UTC)
    m = re.match(r'^(\d{2})(\d{2})(\d{2})Z$', tokens[idx])
    if m:
        day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result['time'] = f"{hour:02d}:{minute:02d} UTC (day {day} of the month)"
        idx += 1

    if idx >= len(tokens):
        return result

    # Optional modifier(s): AUTO = fully automated station, COR = corrected report
    # Both can appear together (e.g. "COR AUTO"), so consume all modifier tokens
    while tokens[idx] in ('AUTO', 'COR', 'RTD'):
        if tokens[idx] == 'AUTO':
            result['is_auto'] = True
        idx += 1
        if idx >= len(tokens):
            break

    if idx >= len(tokens):
        return result

    # Wind: dddssKT, dddssGggKT, or VRBssKT (variable direction)
    # Units may be KT (knots), MPS (metres per second), or KMH
    m = re.match(r'^(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?(KT|MPS|KMH)$', tokens[idx])
    if m:
        direction = m.group(1)
        speed = int(m.group(2))
        gust_raw = m.group(4)
        unit = m.group(5)

        def to_mph(val: int, u: str) -> int:
            """Convert wind speed to mph for display alongside the native unit."""
            if u == 'KT':
                return round(val * 1.15078)
            elif u == 'MPS':
                return round(val * 2.23694)
            else:  # KMH
                return round(val * 0.621371)

        unit_label = {'KT': 'knots', 'MPS': 'm/s', 'KMH': 'km/h'}[unit]

        if speed == 0:
            result['wind'] = "Calm"
        elif direction == 'VRB':
            mph = to_mph(speed, unit)
            result['wind'] = f"Variable at {speed} {unit_label} ({mph} mph)"
        else:
            deg = int(direction)
            compass = degrees_to_compass(deg)
            mph = to_mph(speed, unit)
            result['wind'] = f"From the {compass} ({deg}°) at {speed} {unit_label} ({mph} mph)"

        if gust_raw:
            g = int(gust_raw)
            g_mph = to_mph(g, unit)
            result['wind'] += f", gusting to {g} {unit_label} ({g_mph} mph)"

        idx += 1

    if idx >= len(tokens):
        return result

    # Optional wind direction variability when direction fluctuates > 60°
    # Format: dddVddd, e.g. "280V350"
    m = re.match(r'^(\d{3})V(\d{3})$', tokens[idx])
    if m:
        d1 = degrees_to_compass(int(m.group(1)))
        d2 = degrees_to_compass(int(m.group(2)))
        result['wind_variable'] = f"Varying between {d1} and {d2}"
        idx += 1

    if idx >= len(tokens):
        return result

    # Prevailing visibility (delegates to parse_visibility for format variants)
    vis, idx = parse_visibility(tokens, idx)
    if vis:
        result['visibility'] = vis

    if idx >= len(tokens):
        return result

    # Skip Runway Visual Range entries (e.g. "R28L/2400FT") — pilot-specific data
    while idx < len(tokens) and re.match(r'^R\d+[LCR]?/', tokens[idx]):
        idx += 1

    # Present weather — one or more coded groups, each optionally prefixed with
    # intensity (+/-/VC), a descriptor (SH, TS, FZ, etc.), and a phenomenon code
    wx_intensities = {'-': 'light', '+': 'heavy', 'VC': 'in the vicinity'}
    wx_descriptors = {
        'MI': 'shallow', 'PR': 'partial', 'BC': 'patches of',
        'DR': 'low drifting', 'BL': 'blowing', 'SH': 'shower',
        'TS': 'thunderstorm', 'FZ': 'freezing'
    }
    wx_phenomena = {
        'DZ': 'drizzle', 'RA': 'rain', 'SN': 'snow', 'SG': 'snow grains',
        'IC': 'ice crystals', 'PL': 'ice pellets', 'GR': 'hail',
        'GS': 'small hail', 'UP': 'unknown precipitation',
        'BR': 'mist', 'FG': 'fog', 'FU': 'smoke', 'VA': 'volcanic ash',
        'DU': 'dust', 'SA': 'sand', 'HZ': 'haze', 'PY': 'spray',
        'PO': 'dust/sand whirls', 'SQ': 'squalls', 'FC': 'funnel cloud',
        'SS': 'sandstorm', 'DS': 'duststorm'
    }

    wx_pattern = re.compile(
        r'^(\+|-|VC)?(MI|PR|BC|DR|BL|SH|TS|FZ)?(DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)$'
    )

    weather_list = []
    while idx < len(tokens):
        token = tokens[idx]
        if token == 'NSW':
            # NSW = No Significant Weather (used after TEMPO/BECMG in TAFs)
            weather_list.append('no significant weather')
            idx += 1
            continue
        m = wx_pattern.match(token)
        if m:
            parts = []
            if m.group(1):
                parts.append(wx_intensities.get(m.group(1), ''))
            if m.group(2):
                parts.append(wx_descriptors.get(m.group(2), ''))
            parts.append(wx_phenomena.get(m.group(3), m.group(3)))
            weather_list.append(' '.join(p for p in parts if p))
            idx += 1
        else:
            break

    if weather_list:
        result['weather'] = ', '.join(weather_list)

    if idx >= len(tokens):
        return result

    # Sky condition — zero or more layers, lowest first
    # Coverage codes: CLR/SKC = clear, FEW = 1–2 oktas, SCT = 3–4, BKN = 5–7, OVC = 8
    # Height is encoded in hundreds of feet, e.g. "BKN060" = broken at 6,000 ft
    # CB suffix = cumulonimbus (thunderstorm), TCU = towering cumulus
    sky_codes = {
        'FEW': 'Few clouds', 'SCT': 'Scattered clouds',
        'BKN': 'Broken cloud layer', 'OVC': 'Overcast'
    }
    sky_list = []

    while idx < len(tokens):
        token = tokens[idx]
        if token in ('CLR', 'SKC', 'NCD', 'NSC'):
            sky_list.append('Clear skies')
            idx += 1
        elif token == 'CAVOK':
            sky_list.append('Ceiling and Visibility OK')
            idx += 1
        else:
            m = re.match(r'^(FEW|SCT|BKN|OVC)(\d{3})(CB|TCU)?$', token)
            if m:
                coverage = sky_codes[m.group(1)]
                height = int(m.group(2)) * 100
                extra = ''
                if m.group(3) == 'CB':
                    extra = ' — thunderstorm potential'
                elif m.group(3) == 'TCU':
                    extra = ' — towering cumulus'
                sky_list.append(f"{coverage} at {height:,} ft{extra}")
                idx += 1
            else:
                break

    if sky_list:
        result['sky'] = sky_list

    if idx >= len(tokens):
        return result

    # Temperature and dewpoint in Celsius, separated by "/"
    # Negative values are prefixed with "M" (e.g. "M03/M07")
    m = re.match(r'^(M?\d+)/(M?\d*)$', tokens[idx])
    if m:
        temp_str = m.group(1).replace('M', '-')
        dew_str = m.group(2).replace('M', '-')
        temp_c = int(temp_str)
        temp_f = round(temp_c * 9 / 5 + 32)
        result['temperature'] = f"{temp_c}°C ({temp_f}°F)"
        if dew_str and dew_str != '-':
            dew_c = int(dew_str)
            dew_f = round(dew_c * 9 / 5 + 32)
            result['dewpoint'] = f"{dew_c}°C ({dew_f}°F)"
        idx += 1

    if idx >= len(tokens):
        return result

    # Altimeter setting
    # "A" prefix = inches of mercury (USA), e.g. A2992 → 29.92 inHg
    # "Q" prefix = hectopascals/millibars (international), e.g. Q1013
    m = re.match(r'^A(\d{4})$', tokens[idx])
    if m:
        alt = int(m.group(1)) / 100
        result['altimeter'] = f"{alt:.2f} inHg"
        idx += 1
    else:
        m = re.match(r'^Q(\d{4})$', tokens[idx])
        if m:
            result['altimeter'] = f"{int(m.group(1))} hPa"

    return result


def generate_summary(decoded: dict) -> str:
    """Build a friendly one-sentence weather description from decoded fields.

    Combines the most human-relevant elements — sky condition or present
    weather, temperature, wind, and visibility — into a single readable
    sentence suitable for a non-aviation audience.

    Args:
        decoded: The dict returned by decode_metar().

    Returns:
        A plain-English summary string ending with a period.
    """
    parts = []

    # Lead with sky condition or present weather (most impactful for the reader)
    if 'weather' in decoded:
        wx = decoded['weather'].lower()
        if 'thunderstorm' in wx:
            parts.append("Thunderstorms in the area")
        elif 'heavy rain' in wx:
            parts.append("Heavy rain")
        elif 'rain' in wx or 'drizzle' in wx:
            parts.append("Rainy")
        elif 'snow' in wx:
            parts.append("Snowy")
        elif 'fog' in wx:
            parts.append("Foggy")
        elif 'haze' in wx:
            parts.append("Hazy")
        elif 'mist' in wx:
            parts.append("Misty")
        else:
            parts.append(decoded['weather'].capitalize())
    elif 'sky' in decoded:
        sky_text = ' '.join(decoded['sky']).lower()
        if 'clear' in sky_text:
            parts.append("Clear skies")
        elif 'overcast' in sky_text:
            parts.append("Overcast")
        elif 'broken' in sky_text:
            parts.append("Mostly cloudy")
        elif 'scattered' in sky_text:
            parts.append("Partly cloudy")
        elif 'few' in sky_text:
            parts.append("Mostly clear")
        else:
            parts.append("Cloudy")

    if 'temperature' in decoded:
        parts.append(f"temperature {decoded['temperature']}")

    if 'wind' in decoded:
        wind = decoded['wind']
        if wind == 'Calm':
            parts.append("calm winds")
        else:
            parts.append(f"wind {wind[0].lower()}{wind[1:]}")

    if 'visibility' in decoded:
        vis = decoded['visibility'].lower()
        if 'excellent' in vis or '10+' in vis:
            parts.append("excellent visibility")
        else:
            parts.append(f"visibility {decoded['visibility'].lower()}")

    if not parts:
        return "Weather data is available — see the details below."

    sentence = '. '.join(parts)
    return sentence[0].upper() + sentence[1:] + '.'


@app.route('/', methods=['GET', 'POST'])
def index():
    """Render the main page and handle airport code form submissions.

    GET:  Display the search form (empty or pre-filled from a prior search).
    POST: Fetch the METAR for the submitted airport code, decode it, and
          render the result. Errors (bad code, network failure, etc.) are
          passed to the template for display.
    """
    result = None
    error = None
    airport = ''

    if request.method == 'POST':
        airport = request.form.get('airport', '').strip().upper()
        if not airport:
            error = "Please enter an airport code."
        else:
            try:
                url = f"https://aviationweather.gov/api/data/metar?ids={airport}"
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                raw = resp.text.strip()
                if not raw:
                    error = f"No METAR data found for '{airport}'. Please verify the airport code."
                else:
                    decoded = decode_metar(raw)
                    summary = generate_summary(decoded)
                    result = {'decoded': decoded, 'summary': summary}
            except requests.exceptions.ConnectionError:
                error = "Could not connect to the weather service. Check your internet connection."
            except requests.exceptions.Timeout:
                error = "The weather service timed out. Please try again."
            except Exception as e:
                error = f"Unexpected error: {e}"

    return render_template('index.html', result=result, error=error, airport=airport)


if __name__ == '__main__':
    app.run(debug=True)
