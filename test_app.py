"""
Unit and integration tests for the METAR Reader application.

Test strategy:
  - Unit tests cover each parsing function in isolation using mock METAR strings.
    No network calls are made; inputs and expected outputs are fully controlled.
  - Integration tests exercise the Flask routes via the test client.
    The external requests.get() call is patched so tests run without a network.

Run with:
    pytest test_app.py -v
"""

import pytest
from unittest.mock import patch, MagicMock

from app import app, degrees_to_compass, parse_visibility, decode_metar, generate_summary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Flask test client with testing mode enabled."""
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# degrees_to_compass
# ---------------------------------------------------------------------------

class TestDegreesToCompass:
    def test_north(self):
        assert degrees_to_compass(0) == 'North'

    def test_north_360(self):
        assert degrees_to_compass(360) == 'North'

    def test_east(self):
        assert degrees_to_compass(90) == 'East'

    def test_south(self):
        assert degrees_to_compass(180) == 'South'

    def test_west(self):
        assert degrees_to_compass(270) == 'West'

    def test_northeast(self):
        assert degrees_to_compass(45) == 'Northeast'

    def test_southwest(self):
        assert degrees_to_compass(225) == 'Southwest'

    def test_northwest(self):
        assert degrees_to_compass(315) == 'Northwest'

    def test_west_southwest(self):
        assert degrees_to_compass(250) == 'West-Southwest'

    def test_north_northeast(self):
        assert degrees_to_compass(22) == 'North-Northeast'


# ---------------------------------------------------------------------------
# parse_visibility
# ---------------------------------------------------------------------------

class TestParseVisibility:
    def _parse(self, *tokens):
        """Helper: pass tokens as a list and parse from index 0."""
        return parse_visibility(list(tokens), 0)

    def test_cavok(self):
        vis, idx = self._parse('CAVOK')
        assert 'Ceiling and Visibility OK' in vis
        assert idx == 1

    def test_10sm_excellent(self):
        vis, idx = self._parse('10SM')
        assert '10+' in vis
        assert 'excellent' in vis
        assert idx == 1

    def test_6sm(self):
        vis, idx = self._parse('6SM')
        assert '6 miles' in vis
        assert idx == 1

    def test_1sm_singular(self):
        vis, idx = self._parse('1SM')
        assert '1 mile' in vis
        assert 'miles' not in vis  # singular
        assert idx == 1

    def test_fraction_quarter(self):
        vis, idx = self._parse('1/4SM')
        assert '1/4' in vis
        assert idx == 1

    def test_fraction_three_quarters(self):
        vis, idx = self._parse('3/4SM')
        assert '3/4' in vis
        assert idx == 1

    def test_mixed_whole_and_fraction(self):
        """'1 1/2SM' is encoded as two separate tokens in a METAR."""
        vis, idx = self._parse('1', '1/2SM')
        assert '1 1/2' in vis
        assert idx == 2  # consumed both tokens

    def test_less_than_prefix(self):
        vis, idx = self._parse('M1/4SM')
        assert 'Less than' in vis
        assert '1/4' in vis
        assert idx == 1

    def test_meters_9999_excellent(self):
        vis, idx = self._parse('9999')
        assert '10+' in vis
        assert 'excellent' in vis
        assert idx == 1

    def test_meters_value(self):
        vis, idx = self._parse('4000')
        assert '4000 meters' in vis
        assert idx == 1

    def test_empty_tokens(self):
        vis, idx = parse_visibility([], 0)
        assert vis is None
        assert idx == 0


# ---------------------------------------------------------------------------
# decode_metar — field parsing
# ---------------------------------------------------------------------------

class TestDecodeMetar:

    def test_station_parsed(self):
        d = decode_metar('KHIO 031753Z 00000KT 10SM CLR 13/01 A3021')
        assert d['station'] == 'KHIO'

    def test_time_parsed(self):
        d = decode_metar('KHIO 031753Z 00000KT 10SM CLR 13/01 A3021')
        assert '17:53' in d['time']
        assert 'day 3' in d['time']

    def test_calm_wind(self):
        d = decode_metar('KHIO 031753Z 00000KT 10SM CLR 13/01 A3021')
        assert d['wind'] == 'Calm'

    def test_wind_direction_and_speed(self):
        d = decode_metar('KLAX 031753Z 18010KT 10SM CLR 22/08 A2995')
        assert 'South' in d['wind']
        assert '10 knots' in d['wind']

    def test_wind_with_gusts(self):
        d = decode_metar('EGLL 031820Z 25015G25KT 9999 FEW025 12/07 Q1010')
        assert 'gusting' in d['wind']
        assert '25 knots' in d['wind']

    def test_variable_wind(self):
        d = decode_metar('KLAX 031753Z VRB03KT 10SM CLR 22/08 A2995')
        assert 'Variable' in d['wind']

    def test_wind_variable_direction_range(self):
        d = decode_metar('KLAX 031753Z 18010KT 280V350 10SM CLR 22/08 A2995')
        assert 'wind_variable' in d
        assert 'West' in d['wind_variable']

    def test_visibility_10sm(self):
        d = decode_metar('KHIO 031753Z 00000KT 10SM CLR 13/01 A3021')
        assert '10+' in d['visibility']

    def test_visibility_fractional(self):
        d = decode_metar('KORD 031751Z 27008KT 1 1/4SM -SN BR OVC013 M03/M04 A2986')
        assert '1 1/4' in d['visibility']

    def test_visibility_metric(self):
        d = decode_metar('EGLL 031820Z 25015KT 9999 FEW025 12/07 Q1010')
        assert '10+' in d['visibility']

    def test_sky_clear(self):
        d = decode_metar('KLAX 031753Z 18005KT 10SM CLR 22/08 A2995')
        assert any('Clear' in s for s in d['sky'])

    def test_sky_single_layer(self):
        d = decode_metar('KHIO 031753Z 00000KT 10SM BKN060 13/01 A3021')
        assert any('6,000' in s for s in d['sky'])
        assert any('Broken' in s for s in d['sky'])

    def test_sky_multiple_layers(self):
        d = decode_metar('EGLL 031820Z 25015KT 9999 FEW026 BKN035 BKN044 12/07 Q1010')
        assert len(d['sky']) == 3

    def test_sky_cb_suffix(self):
        d = decode_metar('KORD 031751Z 18012KT 5SM TSRA BKN030CB 25/20 A2985')
        assert any('thunderstorm' in s for s in d['sky'])

    def test_present_weather_rain(self):
        d = decode_metar('KSEA 031753Z 18010KT 3SM RA OVC015 10/08 A2990')
        assert 'rain' in d['weather']

    def test_present_weather_light_snow(self):
        d = decode_metar('KORD 031751Z 27008KT 1 1/4SM -SN BR OVC013 M03/M04 A2986')
        assert 'light' in d['weather']
        assert 'snow' in d['weather']

    def test_present_weather_heavy_rain(self):
        d = decode_metar('KJFK 031753Z 21012KT 2SM +RA OVC010 15/13 A2985')
        assert 'heavy' in d['weather']
        assert 'rain' in d['weather']

    def test_present_weather_fog(self):
        d = decode_metar('KSFO 031753Z VRB02KT 1/4SM FG OVC002 12/12 A3010')
        assert 'fog' in d['weather']

    def test_present_weather_thunderstorm(self):
        d = decode_metar('KORD 031751Z 18012KT 5SM TSRA BKN030CB 25/20 A2985')
        assert 'thunderstorm' in d['weather']

    def test_temperature_positive(self):
        d = decode_metar('KLAX 031753Z 18005KT 10SM CLR 22/08 A2995')
        assert '22°C' in d['temperature']
        assert '72°F' in d['temperature']

    def test_temperature_negative(self):
        d = decode_metar('KORD 031751Z 27008KT 1 1/4SM -SN BR OVC013 M03/M04 A2986')
        assert '-3°C' in d['temperature']
        assert '27°F' in d['temperature']

    def test_dewpoint_parsed(self):
        d = decode_metar('KLAX 031753Z 18005KT 10SM CLR 22/08 A2995')
        assert '8°C' in d['dewpoint']

    def test_altimeter_inhg(self):
        d = decode_metar('KLAX 031753Z 18005KT 10SM CLR 22/08 A2995')
        assert '29.95 inHg' in d['altimeter']

    def test_altimeter_hpa(self):
        d = decode_metar('EGLL 031820Z 25015KT 9999 FEW025 12/07 Q1010')
        assert '1010 hPa' in d['altimeter']

    def test_remarks_stripped(self):
        """Everything after RMK should be ignored."""
        d = decode_metar('KHIO 031753Z 00000KT 10SM BKN060 13/01 A3021 RMK AO2 SLP229 T01330006')
        # RMK data (SLP, T-group) should not appear in any parsed field
        assert 'altimeter' in d  # A3021 is before RMK, should be parsed
        # 'raw' intentionally stores the full original string; check all other fields
        parsed_values = {k: v for k, v in d.items() if k != 'raw'}
        assert all('SLP' not in str(v) for v in parsed_values.values())

    def test_metar_type_prefix_ignored(self):
        """METAR/SPECI type indicator should be skipped, not treated as station."""
        d = decode_metar('METAR KHIO 031753Z 00000KT 10SM CLR 13/01 A3021')
        assert d['station'] == 'KHIO'

    def test_auto_flag(self):
        d = decode_metar('METAR EGLL 031620Z AUTO 25021KT 9999 FEW026 16/10 Q1009')
        assert d.get('is_auto') is True

    def test_cor_auto_both_modifiers(self):
        """COR and AUTO can appear together; both must be consumed."""
        d = decode_metar('METAR EGLL 031620Z COR AUTO 25021KT 9999 FEW026 BKN035 16/10 Q1009')
        assert d.get('is_auto') is True
        assert '25021KT' not in d.get('station', '')  # wind was parsed, not skipped
        assert 'wind' in d

    def test_raw_preserved(self):
        raw = 'KLAX 031753Z 18005KT 10SM CLR 22/08 A2995'
        d = decode_metar(raw)
        assert d['raw'] == raw

    def test_empty_string(self):
        d = decode_metar('')
        assert d == {}


# ---------------------------------------------------------------------------
# generate_summary
# ---------------------------------------------------------------------------

class TestGenerateSummary:

    def test_clear_sky_summary(self):
        d = decode_metar('KLAX 031753Z 18005KT 10SM CLR 22/08 A2995')
        summary = generate_summary(d)
        assert 'Clear' in summary
        assert summary.endswith('.')

    def test_overcast_summary(self):
        d = decode_metar('KSEA 031753Z 18010KT 3SM OVC015 10/08 A2990')
        summary = generate_summary(d)
        assert 'Overcast' in summary

    def test_mostly_cloudy_summary(self):
        d = decode_metar('KHIO 031753Z 00000KT 10SM BKN060 13/01 A3021')
        summary = generate_summary(d)
        assert 'cloudy' in summary.lower()

    def test_calm_wind_in_summary(self):
        d = decode_metar('KHIO 031753Z 00000KT 10SM CLR 13/01 A3021')
        summary = generate_summary(d)
        assert 'calm' in summary.lower()

    def test_temperature_in_summary(self):
        d = decode_metar('KLAX 031753Z 18005KT 10SM CLR 22/08 A2995')
        summary = generate_summary(d)
        assert '22°C' in summary

    def test_rainy_summary(self):
        d = decode_metar('KSEA 031753Z 18010KT 3SM RA OVC015 10/08 A2990')
        summary = generate_summary(d)
        assert 'rain' in summary.lower() or 'Rain' in summary

    def test_snow_summary(self):
        d = decode_metar('KORD 031751Z 27008KT 1 1/4SM -SN BR OVC013 M03/M04 A2986')
        summary = generate_summary(d)
        assert 'snow' in summary.lower() or 'Snow' in summary

    def test_thunderstorm_summary(self):
        d = decode_metar('KORD 031751Z 18012KT 5SM TSRA BKN030CB 25/20 A2985')
        summary = generate_summary(d)
        assert 'thunderstorm' in summary.lower() or 'Thunderstorm' in summary

    def test_excellent_visibility_summary(self):
        d = decode_metar('KLAX 031753Z 18005KT 10SM CLR 22/08 A2995')
        summary = generate_summary(d)
        assert 'excellent visibility' in summary.lower()

    def test_summary_ends_with_period(self):
        d = decode_metar('KLAX 031753Z 18005KT 10SM CLR 22/08 A2995')
        assert generate_summary(d).endswith('.')

    def test_summary_starts_uppercase(self):
        d = decode_metar('KLAX 031753Z 18005KT 10SM CLR 22/08 A2995')
        assert generate_summary(d)[0].isupper()

    def test_empty_decoded_fallback(self):
        summary = generate_summary({})
        assert 'Weather data is available' in summary


# ---------------------------------------------------------------------------
# Flask route — integration tests (requests.get is mocked)
# ---------------------------------------------------------------------------

class TestFlaskRoutes:

    def test_get_homepage_returns_200(self, client):
        resp = client.get('/')
        assert resp.status_code == 200

    def test_get_homepage_contains_form(self, client):
        resp = client.get('/')
        assert b'airport' in resp.data
        assert b'Get Weather' in resp.data

    def test_post_empty_airport_shows_error(self, client):
        resp = client.post('/', data={'airport': ''})
        assert resp.status_code == 200
        assert b'Please enter an airport code' in resp.data

    @patch('app.requests.get')
    def test_post_valid_airport_shows_result(self, mock_get, client):
        mock_get.return_value.text = 'KLAX 031753Z 18005KT 10SM CLR 22/08 A2995'
        mock_get.return_value.raise_for_status = lambda: None

        resp = client.post('/', data={'airport': 'KLAX'})
        assert resp.status_code == 200
        assert b'KLAX' in resp.data
        assert b'22' in resp.data  # temperature

    @patch('app.requests.get')
    def test_post_airport_code_uppercased(self, mock_get, client):
        """Lowercase input should be uppercased before the API call."""
        mock_get.return_value.text = 'KLAX 031753Z 18005KT 10SM CLR 22/08 A2995'
        mock_get.return_value.raise_for_status = lambda: None

        client.post('/', data={'airport': 'klax'})
        called_url = mock_get.call_args[0][0]
        assert 'KLAX' in called_url

    @patch('app.requests.get')
    def test_post_unknown_airport_shows_error(self, mock_get, client):
        """Empty API response means the airport code was not found."""
        mock_get.return_value.text = ''
        mock_get.return_value.raise_for_status = lambda: None

        resp = client.post('/', data={'airport': 'ZZZZ'})
        assert b'No METAR data found' in resp.data

    @patch('app.requests.get')
    def test_post_connection_error_shows_message(self, mock_get, client):
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError()

        resp = client.post('/', data={'airport': 'KLAX'})
        assert b'Could not connect' in resp.data

    @patch('app.requests.get')
    def test_post_timeout_shows_message(self, mock_get, client):
        import requests as req
        mock_get.side_effect = req.exceptions.Timeout()

        resp = client.post('/', data={'airport': 'KLAX'})
        assert b'timed out' in resp.data

    @patch('app.requests.get')
    def test_airport_code_repopulates_form(self, mock_get, client):
        """The search box should retain the entered code after submission."""
        mock_get.return_value.text = 'KLAX 031753Z 18005KT 10SM CLR 22/08 A2995'
        mock_get.return_value.raise_for_status = lambda: None

        resp = client.post('/', data={'airport': 'KLAX'})
        assert b'KLAX' in resp.data
