from asyncio import new_event_loop, run_coroutine_threadsafe, to_thread
from datetime import datetime
from functools import wraps
from html import escape as html_escape
from json import dumps, loads
from os import getcwd
from re import findall as re_findall
from secrets import token_urlsafe
from shutil import rmtree
from threading import Thread
from uuid import uuid4

from aiofiles import open as aio_open
from chromedebugg import ChromeDebugg
from helpers.masking import MaskingTools
from sanic import HTTPResponse, Request, Sanic, html, redirect


app = Sanic("Marionette")
app.static(
    '/', 'templates/content/', stream_large_files=True, name='CSS/JS'
)

app.config['MM_PATH'] = getcwd()
app.config['MM_TOKEN'] = token_urlsafe(32)
app.config['MM_MASKING'] = MaskingTools()

with open('profiles.json', 'a+', encoding='utf-8') as file:
    app.config['MM_PROFILES'] = loads(file.read() or '{}')


def authorized(f):
    '''
        Simple wrapper for check if user has rights for do any action
        Using `request.cookies['token']` value

        Use always `True` if not need
    '''

    def decorator(f):
        @wraps(f)
        async def decorated_function(request: Request, *args, **kwargs):
            is_authorized = True  # _is_authorized(request)

            if is_authorized:
                response = await f(request, *args, **kwargs)
                return response
            else:
                return redirect('/login')
        return decorated_function
    return decorator


async def read_template(name: str) -> str:
    '''
        It can be static, but for testing purpouses in this way

        name: str - file name in `templates/*.html`

        Return `str`, file content
    '''

    async with aio_open(
        f"{app.config['MM_PATH']}/templates/{name}.html", 'r', encoding='utf-8'
    ) as file:
        return await file.read()


async def update_profiles() -> None:
    '''
        Save all changes in profiles to file
        
        Profiles data stored in `app.config['MM_PROFILES']`
    '''

    async with aio_open(
        f"{app.config['MM_PATH']}/profiles.json", 'w', encoding='utf-8'
    ) as conf_file:
        await conf_file.write(dumps(app.config['MM_PROFILES'], indent=4))


@authorized
@app.get("/")
async def index(request: Request) -> HTTPResponse:
    ''' Main page with DataTable (profiles) '''

    table_data = ''
    template = await read_template('index')

    for puuid, data in app.config['MM_PROFILES'].items():
        table_data += '''
                    <tr>
                        <td>{$NAME$}</td>
                        <td>{$DESC$}</td>
                        <td>{$DATE$}</td>
                        <td>
                            <a href="/run/{$UUID$}" title="Run Profile">▶️</a> | 
                            <a href="/edit/{$UUID$}" title="Edit Profile">✍️</a> | 
                            <a href="/delete/{$UUID$}" title="Delete Profile">🗑️</a>
                        </td>
                    </tr>

'''.replace('{$NAME$}', data['name']) \
               .replace('{$DESC$}', data['desc']) \
               .replace('{$UUID$}', puuid) \
               .replace('{$DATE$}', data['created'])

    template = template.replace('{$TABLE_DATA$}', table_data)

    return html(template)


@authorized
@app.get("/create")
async def create(request: Request) -> HTTPResponse:
    ''' Create profile page '''

    template = await read_template('new')

    for item in re_findall('{{PROFILE_.*}}', template):
        if item == '{{PROFILE_lat}}':
            template = template.replace(item, '33.13')
        elif item == '{{PROFILE_lon}}':
            template = template.replace(item, '22.5')
        else:
            template = template.replace(item, '')

    return html(template)


@authorized
@app.post("/create")
async def create_save(request: Request) -> HTTPResponse:
    ''' Create profile page '''

    if not request.form.get('name', None):
        return redirect('/create')
    if not request.form.get('lat', None):
        return redirect('/create')
    if not request.form.get('lon', None):
        return redirect('/create')

    uuid = str(uuid4())

    app.config['MM_PROFILES'][uuid] = {
        'created': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'desc': html_escape(request.form.get('desc', '')),
        'name': request.form.get('name', ''),
        'path': f'{app.config["MM_PATH"]}/profiles/{uuid}',
        'proxy': request.form.get('proxy', 'direct://'),
        'spoofing': {
            'geo': {
                'lat': float(request.form['lat'][0]),
                'lon': float(request.form['lon'][0]),
            },
            'hardware': {
                'cpu': int(request.form.get('cpu', 0)),
                'ram': int(request.form.get('ram', 0)),
            }
        }
    }

    await update_profiles()

    return redirect('/')


@authorized
@app.get("/delete/<uuid:uuid>")
async def delete(request: Request, uuid: str) -> HTTPResponse:
    '''
        Delete Profile by given UUID

        uuid: str - profile UUID
    '''

    uuid = str(uuid)

    if not app.config['MM_PROFILES'].get(uuid, None):
        return redirect('/')

    app.config['MM_PROFILES'].pop(uuid)
    await update_profiles()

    try:
        await to_thread(
            rmtree, f'profiles/{uuid}'
        )
    except FileNotFoundError:
        pass

    return redirect('/')


@authorized
@app.get("/run/<uuid:uuid>")
async def run(request: Request, uuid: str) -> HTTPResponse:
    '''
        Run Profile by given UUID

        uuid: str - profile UUID
    '''

    uuid = str(uuid)

    def _background_loop(profile_name: str):
            loop = new_event_loop()
            Thread(target=loop.run_forever, name=profile_name).start()
            return loop

    if not app.config['MM_PROFILES'].get(uuid, None):
        return redirect('/')

    run_coroutine_threadsafe(
        ChromeDebugg(
            app.config['MM_PROFILES'][uuid], app.config['MM_MASKING']
        ).main(),
        _background_loop(f'ChromeProfile_{uuid}')
    )

    return redirect('/')


@authorized
@app.get("/edit/<uuid:uuid>")
async def edit(request: Request, uuid: str) -> HTTPResponse:
    '''
        Edit Profile by given UUID

        uuid: str - profile UUID
    '''

    uuid = str(uuid)

    if not app.config['MM_PROFILES'].get(uuid, None):
        return redirect('/')

    profile = app.config['MM_PROFILES'][uuid]
    template = await read_template('new')

    for item in re_findall('{{PROFILE_.*}}', template):
        match item:
            case "{{PROFILE_name}}":
                template = template.replace(item, profile['name'])
            case "{{PROFILE_proxy}}":
                template = template.replace(item, profile['proxy'])
            case "{{PROFILE_desc}}":
                template = template.replace(item, profile['desc'])
            case "{{PROFILE_lat}}":
                template = template.replace(
                    item, str(profile['spoofing']['geo']['lat'])
                )
            case "{{PROFILE_lon}}":
                template = template.replace(
                    item, str(profile['spoofing']['geo']['lon'])
                )
            case "{{PROFILE_cpu}}":
                template = template.replace(
                    item, str(profile['spoofing']['hardware']['cpu'])
                )
            case "{{PROFILE_ram}}":
                template = template.replace(
                    item, str(profile['spoofing']['hardware']['ram'])
                )

    template = template.replace(
        'action="/create"', f'action="/edit/{uuid}"'
    )

    return html(template)

@authorized
@app.post("/edit/<uuid:uuid>")
async def edit_handle(request: Request, uuid: str) -> HTTPResponse:
    uuid = str(uuid)

    if not app.config['MM_PROFILES'].get(uuid, None):
        return redirect('/')

    app.config['MM_PROFILES'][uuid].update({
        'desc': html_escape(request.form.get('desc', '')),
        'name': request.form.get('name', ''),
        'proxy': request.form.get('proxy', 'direct://'),
        'spoofing': {
            'geo': {
                'lat': float(request.form['lat'][0]),
                'lon': float(request.form['lon'][0]),
            },
            'hardware': {
                'cpu': int(request.form.get('cpu', 0)),
                'ram': int(request.form.get('ram', 0)),
            }
        }
    })

    await update_profiles()

    return redirect('/')

if __name__ == '__main__':
    app.run('127.0.0.1', 8080)
