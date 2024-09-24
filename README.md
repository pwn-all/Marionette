# This project have WIP status. Use at your own risk.

![Main Screen, Empty](https://raw.githubusercontent.com/pwn-all/Marionette/main/images/1.png)
![Create Profile Screen](https://raw.githubusercontent.com/pwn-all/Marionette/main/images/2.png)
![Main Screen With Item](https://raw.githubusercontent.com/pwn-all/Marionette/main/images/3.png)

This is a basic project that provides the ability to spoof some browser data to prevent user identification. At this point, it supports the switch:

- [x] Time-Zone (`Date.getTimezoneOffset`)
- [x] Geolocation (`Geolocation.getCurrentPosition()`)
- [x] Locale
- [x] Accept-Lang
- [x] CPU Cores (`navigator.hardwareConcurrency`)
- [x] RAM Size (`navigator.deviceMemory`)

Not supported at moment:

- [ ] WebGL via `Runtime.evaluate`
- [ ] UserAgent via `Emulation.setUserAgentOverride`
- [ ] Screen (width&height, etc) via `Emulation.setDeviceMetricsOverride`
- [ ] Prevent local port discovery via `Fetch.failRequest`

## Briefly about the project
- It was created for research purposes only
- It is made fully asynchronous and built on `WebSocket`. No `/json` fetches
- It debugs all `Workers`
- It will not reveal techniques for bypassing current anti-fraud systems. Only basic.


## FAQ
1. Will your script help against surveillance?
- No. Better to blend in with the crowd and use fewer extensions.
2. Why is there no useragent change on Windows/MacOS/Linux/iPhone here?
- There is virtually no point in a programmatic substitution. This script is a basic program to help in not complicated tasks. The use of any similar browser can be easily disclosed. At least `Passive fingerprint` and `IP Scoring`.
3. What can you recommend for use?
- The best tool is a MacBook. It is hardest to find by the easiest anti-tracking methods. With the use of even this very basic script, you can bypass most defenses.

## Requirements
1. Installed `Chrome`
2. Installed `Python 3.11`+
3. `pip install asyncio aiohttp aiofiles timezonefinder shapely sanic python-socks`

## Warning
1. Using a proxy - can only give you a greater risk of being sent to a `shadow ban` or given a `red notice`. Virtually the most basic Passive fingerprint techniques can preclude the use of VPN/Proxy. You should choose a proxy server OS equal to the one you are spoofing. Otherwise it is useless
2. You can change default locations of Chrome in `chrome_settings.json`['location']
3. You can change default args for Chrome launch in `chrome_settings.json`['default_args']
