from json import loads
from typing import List
from random import randint
from shapely.geometry import shape, Point
from timezonefinder import TimezoneFinder

from aiohttp import ClientSession, ClientTimeout
from aiohttp_socks import ProxyConnector as proxyC


class SpoofingTemplates:
    def __init__(self) -> None:
        pass

    def ram(self, value: int) -> str:  # value:
        return f'''if (navigator.__defineGetter__) {{
    navigator.__defineGetter__('deviceMemory', function () {{
        return {value};
    }});
}};'''


class MaskingTools:
    def __init__(
        self, proxy_timeout: int = 30, geo_file: str = 'helpers/WORLD.geojson'
    ) -> None:
        with open(geo_file, 'r', encoding='utf-8') as file:
            self._geo_loopup = loads(file.read())

        for item, value in self._geo_loopup.items():
            value['shape'] = shape(value['shape'])

        self._proxy_timeout: int = proxy_timeout
        self._spoffing: SpoofingTemplates = SpoofingTemplates()
        self._tz_finder: TimezoneFinder = TimezoneFinder()

    def find_country_specs(self, lat: float, lon: float) -> dict:
        '''
            Find country `locale` and `accept-lang` specs by GeoPoint.

            lat: float - latitude, like: 83.299111
            lon: float - longitude, like -4.23910

            Return `dict`, like:
            {
                'locale': 'en_US',
                'accept-lang': 'en-US,en'
            }
        '''

        geo_point = Point(lon, lat)

        for item, value in self._geo_loopup.items():
            if value['shape'].contains(geo_point):
                return {
                    'locale': value['locale'],
                    'accept-lang': value['accept-lang']
                }

        return {}

    def get_emulations(self, spoofing: dict) -> List[dict]:
        '''
            Creating emulations based on `spoofing` config in profile.

            spoofing: dict - spoofing config from profile, like: {'geo': ..., 'hardware': ...}

            Return List[dict], like:
            [
                {
                    'method': 'Emulation.setLocaleOverride',
                    'params': {
                        'locale': 'en_US'
                    }
                },
                ...
            ]
        '''

        emulations = []

        country_specs = self.find_country_specs(
            spoofing['geo']['lat'], spoofing['geo']['lon']
        )

        assert country_specs, "Can't get `country specs`. Fatal error."

        emulations.append({
            'method': 'Emulation.setGeolocationOverride',
            'params': {
                'latitude': spoofing['geo']['lat'],
                'longitude': spoofing['geo']['lon'],
                'accuracy': randint(6, 47)
            }
        })
        emulations.append({
            'method': 'Emulation.setTimezoneOverride',
            'params': {
                'timezoneId': self._tz_finder.timezone_at(
                    lng=spoofing['geo']['lon'],
                    lat=spoofing['geo']['lat']
                )
            }
        })
        emulations.append({
            'method': 'Emulation.setLocaleOverride',
            'params': {
                'locale': country_specs['locale']
            }
        })
        emulations.append({
            'method': 'Emulation.setUserAgentOverride',
            'params': {
                'userAgent': '',
                'acceptLanguage': country_specs['accept-lang']
            }
        })

        for param in spoofing['hardware']:
            match param:
                case "cpu":
                    if not spoofing['hardware'][param]:
                        continue
                    emulations.append({
                        'method': 'Emulation.setHardwareConcurrencyOverride',
                        'params': {
                            'hardwareConcurrency': spoofing['hardware'][param]
                        }
                    })
                case "ram":
                    if not spoofing['hardware'][param]:
                        continue
                    emulations.append({
                        'method': 'Runtime.evaluate',
                        'params': {
                            'expression': self._spoffing.ram(
                                spoofing['hardware'][param]
                            ),
                            'includeCommandLineAPI': True
                        }
                    })
                case "storage":
                    if not spoofing['hardware'][param]:
                        continue
                    emulations.append({
                        'method': 'Emulation.setHardwareConcurrencyOverride',
                        'params': {
                            'hardwareConcurrency': spoofing['hardware'][param]
                        }
                    })

        return emulations

    async def check_proxy(self, proxy: str) -> bool:
        '''
            Perform check if proxy is working

            proxy: str - proxy url, like: socks5://user:pass@127.0.0.1:9050

            Return `bool`, as logical result
        '''

        kwargs = {
            'connector': proxyC.from_url(proxy),
            'timeout': ClientTimeout(self._proxy_timeout)
        }

        async with ClientSession(**kwargs) as ses:
            try:
                async with ses.get('https://duckduckgo.com/', ssl=False) as _:
                    return True
            except Exception:
                return False
            finally:
                await ses.close()

        return False
